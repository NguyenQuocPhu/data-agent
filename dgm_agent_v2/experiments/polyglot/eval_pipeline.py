import os
import json
import sys

# Thêm root vào sys.path để tránh lỗi ModuleNotFoundError
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, root_dir)

from dgm_agent_v2.DGM_orchestrator import TriadicDGMOrchestrator
from dgm_agent_v2.implementations.qwen_llm import OpenAICompatibleClient
from dgm_agent_v2.implementations.local_sandbox import LocalSubprocessSandbox
from dgm_agent_v2.core.rimrule_memory import RimruleMemoryBank
from dgm_agent.outer_eval import get_task_meta_dynamically

def run_full_eval():
    print("🚀 [PHASE 1 - FULL] Khởi động Polyglot Full 60 Tasks...")
    
    # 1. Nạp cơ sở hạ tầng
    llm_client = OpenAICompatibleClient(
        api_key="EMPTY",
        base_url="http://localhost:8000/v1",
        model_name="hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8"
    )
    sandbox = LocalSubprocessSandbox()
    
    # Đổi sang thư mục data_60/
    output_dir = "dgm_agent_v2/experiments/polyglot/data_60"
    os.makedirs(output_dir, exist_ok=True)
    memory_bank = RimruleMemoryBank(archive_path=f"{output_dir}/rimrule_memory.json")
    
    orchestrator = TriadicDGMOrchestrator(llm_client, sandbox, memory_bank, max_inner_retries=3)
    
    # 2. Đọc danh sách 60 bài toán chuẩn DGM
    subset_path = "dgm_agent_v2/harness/polyglot/subsets/polyglot_60.json"
    with open(subset_path, 'r', encoding='utf-8') as f:
        tasks = json.load(f)
    
    predictions = []
    pred_file = os.path.join(output_dir, "predictions.jsonl")
    
    # Nếu file đã tồn tại, có thể đọc lên để skip những bài đã làm (tuỳ chọn nâng cao)
    # Tạm thời ta cứ ghi đè hoặc tạo mới
    
    # 3. Vòng lặp Orchestrator với tính năng Checkpointing
    for i, task_id in enumerate(tasks):
        print(f"\n================ ĐANG GIẢI QUYẾT: {task_id} ({i+1}/{len(tasks)}) ================")
        
        try:
            task_info = get_task_meta_dynamically(task_id)
            task_description = task_info.get("problem_statement", "")
            
            language_prefix = task_id.split('__')[0].upper()
            workspace_path = os.path.abspath(f"{output_dir}/workspace_polyglot/{task_id}")
            os.makedirs(workspace_path, exist_ok=True)
            
            # Download files to get the solution stub
            from dgm_agent.outer_eval import download_task_files
            downloaded = download_task_files(task_id, workspace_path)
            target_file = task_info.get("files", {}).get("solution_stub", "solution.txt")
            
            stub_content = ""
            if "solution_stub" in downloaded and downloaded["solution_stub"]:
                try:
                    with open(downloaded["solution_stub"], "r", encoding="utf-8") as f:
                        stub_content = f.read().strip()
                except Exception:
                    pass
            
            stub_prompt = f"\n\n=== STARTING CODE STUB ===\n{stub_content}\n==========================\n" if stub_content else ""

            # 1. Ép LLM trả về tên file và code
            solver_instruction = (
                f"[CRITICAL INSTRUCTION: TARGET PROGRAMMING LANGUAGE IS {language_prefix}]\n"
                f"You MUST write the solution strictly in {language_prefix}.\n"
            )
            
            if language_prefix != "PYTHON" and stub_prompt:
                solver_instruction += stub_prompt
        except Exception as e:
            print(f"Lỗi khi lấy thông tin bài {task_id}: {e}")
            task_description = f"Solve the {task_id} problem."
            solver_instruction = ""
            workspace_path = os.path.abspath(f"{output_dir}/workspace_polyglot/{task_id}")
            os.makedirs(workspace_path, exist_ok=True)
            target_file = "solution.txt"
        
        result = orchestrator.run_task(
            task_description=task_description, 
            workspace_dir=workspace_path,
            solver_instruction=solver_instruction
        )
        raw_response = result.get("code", "")
        
        # 2. Bóc tách Tên file và Code
        import subprocess
        git_diff_patch = ""
        new_code = raw_response
        
        if new_code and result.get("status") in ["SUCCESS", "FAILED_MAX_RETRIES"] and new_code != "# Failed to generate valid code":
            file_abs_path = os.path.join(workspace_path, target_file)
            
            # 3. Ghi đè file và dùng Git để tính Diff
            try:
                # Setup dummy git repo so diff works
                if not os.path.exists(os.path.join(workspace_path, ".git")):
                    subprocess.run(["git", "init"], cwd=workspace_path, capture_output=True)
                    open(file_abs_path, 'a').close() # touch file
                    subprocess.run(["git", "add", target_file], cwd=workspace_path, capture_output=True)
                    subprocess.run(["git", "commit", "-m", "init"], cwd=workspace_path, capture_output=True)
                
                with open(file_abs_path, 'w', encoding='utf-8') as f:
                    f.write(new_code + "\n")
                
                # Chạy lệnh git diff trong thư mục workspace
                diff_cmd = ["git", "diff", target_file]
                diff_output = subprocess.check_output(diff_cmd, cwd=workspace_path, text=True, stderr=subprocess.STDOUT)
                
                # Nếu có thay đổi, lưu diff
                if diff_output:
                    git_diff_patch = diff_output
                else:
                    git_diff_patch = raw_response 
                    
            except Exception as e:
                print(f"⚠️ Lỗi tạo Git Diff: {e}")
                git_diff_patch = raw_response
        else:
            git_diff_patch = raw_response if raw_response else "# Failed to generate"
            
        # 4. Lưu Record chuẩn SWE-bench
        pred_record = {
            "model_name_or_path": "triadic_dgm_v2",
            "instance_id": task_id,
            "model_patch": git_diff_patch,
            "epiplexity": result.get("epiplexity_score", 0.0)
        }
        predictions.append(pred_record)
        
        # Ghi trực tiếp ra file sau mỗi lượt để bảo toàn dữ liệu (Checkpointing)
        with open(pred_file, 'w', encoding='utf-8') as f:
            for p in predictions:
                f.write(json.dumps(p) + "\n")
            
    print(f"\n✅ [PHASE 1 HOÀN TẤT] Đã xuất {len(predictions)} giải pháp ra {pred_file}")

if __name__ == "__main__":
    run_full_eval()
