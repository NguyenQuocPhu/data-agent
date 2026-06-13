import os
import json
import tempfile
import traceback
from typing import Dict, Any

from triadic_dgm.benchmark.harness.polyglot.harness import harness as polyglot_harness
from triadic_dgm.benchmark.utils.evo_utils import get_all_performance

class FitnessEvaluator:
    """
    [SOTA] Outer Loop Evaluator for the Darwin Gödel Machine.
    Evaluates a mutant DGM version against the Polyglot benchmark using Docker Sandbox.
    Implements the "Staged Evaluation Strategy" to optimize compute budget.
    """
    
    def __init__(self, base_dir: str = "./triadic_dgm.benchmark"):
        self.base_dir = os.path.abspath(base_dir)
        # Tải sẵn danh sách các bài toán (60 tasks Polyglot)
        metadata_path = os.path.join(self.base_dir, "harness/polyglot/polyglot_benchmark_metadata.json")
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                self.dataset = json.load(f)
            self.all_tasks = list(self.dataset.keys())
        except FileNotFoundError:
            print(f"⚠️ [FitnessEvaluator] Không tìm thấy file metadata tại {metadata_path}. Sẽ dùng mảng mặc định.")
            self.all_tasks = [f"task_{i}" for i in range(60)] # Dummy cho trường hợp không có dữ liệu

    def evaluate(self, code_string: str, output_dir: str = "./output_eval") -> Dict[str, Any]:
        """
        Nhận mã nguồn đã đột biến từ DGM Outer, chạy đánh giá và trả về Pass Rate.
        """
        print("🐳 [Evaluator] Khởi động Real Compiler (Docker Sandbox)...")
        
        # 1. Tạo file patch tạm thời từ chuỗi code LLM sinh ra
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_file:
            temp_file.write(code_string)
            mutant_patch_path = temp_file.name

        try:
            os.makedirs(output_dir, exist_ok=True)
            
            # =================================================================
            # [SOTA] STAGED EVALUATION STRATEGY (Theo chuẩn Section 4.2 DGM)
            # =================================================================
            
            # Giai đoạn 1: Chạy 10 tasks để kiểm tra chức năng cơ bản
            stage1_tasks = self.all_tasks[:10]
            print(f"▶ [Stage 1] Đang đánh giá {len(stage1_tasks)} tasks cơ bản...")
            stage1_score, stage1_log = self._run_harness(mutant_patch_path, stage1_tasks, output_dir)
            
            # Ngưỡng 40% (0.4) quy định bởi bài báo
            if stage1_score < 0.4:
                print(f"⚠️ [Evaluator] Đột biến bị HỎNG chức năng (Score {stage1_score:.2f} < 0.4). Loại bỏ sớm!")
                return {
                    "pass_rate": stage1_score, 
                    "log": stage1_log, 
                    "status": "pruned_at_stage1"
                }
            
            # Giai đoạn 2: Agent khỏe! Cho chạy nốt 50 bài mở rộng
            print(f"✅ [Stage 1] Pass! (Score {stage1_score:.2f}). Mở khóa đánh giá toàn diện Stage 2...")
            stage2_tasks = self.all_tasks[10:60] if len(self.all_tasks) > 10 else []
            if stage2_tasks:
                stage2_score, stage2_log = self._run_harness(mutant_patch_path, stage2_tasks, output_dir)
                # Tính điểm trung bình trọng số (Weighted Pass Rate)
                final_score = (stage1_score * len(stage1_tasks) + stage2_score * len(stage2_tasks)) / max(1, len(self.all_tasks[:60]))
            else:
                final_score = stage1_score
                stage2_log = "No stage 2 tasks available."
            
            return {
                "pass_rate": final_score,
                "log": f"=== STAGE 1 ===\n{stage1_log}\n=== STAGE 2 ===\n{stage2_log}",
                "status": "completed_successfully"
            }

        except Exception as e:
            trace = traceback.format_exc()
            print(f"❌ [Evaluator] Docker Sandbox Crash: {e}")
            return {
                "pass_rate": 0.0,
                "log": trace,
                "status": "error"
            }
        finally:
            # 2. Dọn dẹp file tạm để bảo vệ bộ nhớ máy chủ
            if os.path.exists(mutant_patch_path):
                os.remove(mutant_patch_path)

    def _run_harness(self, patch_path: str, task_list: list, output_dir: str):
        """Hàm private bọc logic gọi Polyglot Harness."""
        try:
            polyglot_harness(
                test_task_list=task_list,
                num_samples=-1,
                max_workers=min(10, max(1, len(task_list))),
                model_name_or_path="mutant_agent",
                model_patch_paths=[patch_path],
                num_evals=1,
                num_evals_parallel=min(5, max(1, len(task_list))),
                pred_dname=os.path.join(output_dir, "predictions"),
                output_dir=output_dir
            )
            
            # Parse kết quả
            performances, overall_performance = get_all_performance("mutant_agent", results_dir=output_dir)
            score = overall_performance.get("accuracy_score", 0.0) if overall_performance else 0.0
            
            # Nén log thành JSON text để Diagnoser dễ đọc
            log_str = json.dumps(overall_performance, indent=2) if overall_performance else "Evaluation completed but no metrics found."
            return score, log_str
        except Exception as e:
            print(f"Harness error: {e}")
            return 0.0, f"Harness crashed: {str(e)}"
