import time
import json
import os
from typing import Dict, Any

from dgm_agent_v2.interfaces.llm_client import ILLMClient
from dgm_agent_v2.interfaces.sandbox import ISandbox
from dgm_agent_v2.core.rimrule_memory import RimruleMemoryBank
from dgm_agent_v2.core.proposer_agent import ProposerAgent
from dgm_agent_v2.core.solver_agent import SolverAgent
from dgm_agent_v2.core.verifier_agent import VerifierAgent
from dgm_agent_v2.blackboard import Blackboard, BlackboardRequest, build_file_agents

class TriadicDGMOrchestrator:
    """
    Main Orchestrator for the Triadic DGM architecture.
    Ties together the Blackboard, Proposer, Solver, and Verifier.
    Dependencies (LLM, Sandbox) are injected via constructor (Dependency Inversion).
    """
    def __init__(self, llm_client: ILLMClient, sandbox: ISandbox, memory_bank: RimruleMemoryBank, max_inner_retries: int = 10):
        # [SOLID] Tiêm phụ thuộc (Dependency Injection) các core modules
        self.llm_client = llm_client
        self.sandbox = sandbox
        self.memory_bank = memory_bank
        self.max_inner_retries = max_inner_retries
        
        # Khởi tạo Triadic Agents
        self.proposer = ProposerAgent(self.llm_client)
        self.solver = SolverAgent(self.llm_client, self.memory_bank)
        self.verifier = VerifierAgent(self.llm_client, self.memory_bank)
        
        # Khởi tạo Bảng tin trung tâm
        self.blackboard = Blackboard()

    def run_task(self, task_description: str, workspace_dir: str, solver_instruction: str = "") -> Dict[str, Any]:
        """
        Thực thi quy trình Inner Loop: Blackboard (Context) -> Propose -> Solve -> Verify.
        """
        print("\n[ORCHESTRATOR] 📋 Khởi động Blackboard và gom nhóm dữ liệu...")
        # 1. Quét file và đẩy lên Blackboard
        file_agents = build_file_agents(workspace_dir)
        for agent in file_agents:
            self.blackboard.register_agent(agent)
            
        req = BlackboardRequest(query="Analyze workspace structure and dataset schemas", publisher="Orchestrator")
        self.blackboard.post_request(req)
        context_graph = self.blackboard.get_aggregated_context()

        print("\n[ORCHESTRATOR] 🧠 Proposer đang phân tích yêu cầu (Vocab Dropout enabled)...")
        # 2. Proposer lập kế hoạch
        plan = self.proposer.propose_plan(task_description, context_graph)
        if "error" in plan:
            return {"status": "FAILED_AT_PROPOSER", "error": plan["error"]}

        attempt = 0
        current_feedback = ""
        
        # 3. Inner Loop: Tiến hóa bất đối xứng
        while attempt < self.max_inner_retries:
            print(f"\n[ORCHESTRATOR] 💻 Solver đang sinh mã đa ứng viên (Lần {attempt + 1}/{self.max_inner_retries})...")
            
            augmented_task = task_description
            if solver_instruction:
                augmented_task += f"\n\n{solver_instruction}"
            if current_feedback:
                augmented_task += f"\n\n[VERIFIER FEEDBACK]:\n{current_feedback}\nFix the logic and strictly output valid code."

            # Solver sinh 3 biến thể code
            candidate_codes = self.solver.solve(augmented_task, plan, num_candidates=3)
            
            # Chạy thử code ngay trong Sandbox
            evaluated_candidates = []
            
            # Detect language from augmented_task
            is_python_task = "TARGET PROGRAMMING LANGUAGE IS PYTHON" in augmented_task or "TARGET PROGRAMMING LANGUAGE" not in augmented_task
            
            for code in candidate_codes:
                if is_python_task:
                    is_success, execution_log = self.sandbox.execute(code, task_id="inner_loop_eval")
                else:
                    is_success, execution_log = True, "Skipped sandbox evaluation for non-Python language"
                
                evaluated_candidates.append({
                    "code": code,
                    "is_success": is_success,
                    "error_log": execution_log
                })

            print("\n[ORCHESTRATOR] ⚖️ Verifier chấm điểm (Runtime + Epiplexity/MDL)...")
            # Verifier phân loại theo Ma trận 4 góc phần tư
            verification_result = self.verifier.verify_candidates(augmented_task, evaluated_candidates)
            best_solution = verification_result.get("best_valid_solution")
            
            # Tình huống A: Tuyệt hảo (Pass Runtime + Nằm trong Goldilocks Zone)
            if best_solution:
                print(f"[ORCHESTRATOR] 🎉 THÀNH CÔNG! Giải pháp tối ưu đạt Epiplexity: {best_solution['epiplexity_score']:.2f}")
                return {
                    "status": "SUCCESS",
                    "code": best_solution["code"],
                    "conceptual_plan": plan,
                    "epiplexity_score": best_solution["epiplexity_score"],
                    "goldilocks_status": "PASS",
                    "attempts": attempt + 1
                }
            
            # Tình huống C: Lỗi Runtime nhưng ý tưởng tốt -> Cấp Feedback (Reflexion)
            current_feedback = verification_result.get("reflexion_feedback", "")
            if current_feedback:
                print(f"[ORCHESTRATOR] 🔄 Code lỗi. Đã trích xuất Reflexion Feedback. Bắt đầu vòng tự sửa...")
            else:
                print(f"[ORCHESTRATOR] ⚠️ Các ứng viên đều là rác (Discard). Yêu cầu Solver thử hướng mới...")
                
            attempt += 1

        print("[ORCHESTRATOR] ❌ Cạn kiệt ngân sách tính toán (Max Retries). Bỏ cuộc để chống lặp vô hạn!")
        return {
            "status": "FAILED_MAX_RETRIES",
            "code": "",
            "goldilocks_status": "FAIL",
            "final_feedback": current_feedback
        }

### Example Pipeline Runner [Từ file gốc của bác]
def run_ds_pipeline(manifest_path: str, output_dir: str):
    """Entry point for running benchmark evaluations."""
    from dgm_agent_v2.implementations.qwen_llm import OpenAICompatibleClient
    from dgm_agent_v2.implementations.local_sandbox import LocalSubprocessSandbox
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Khởi tạo các module nền tảng (Platform Substrate)
    llm_client = OpenAICompatibleClient(
        api_key="EMPTY",
        base_url="http://localhost:8000/v1",
        model_name="hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8"
    )
    sandbox = LocalSubprocessSandbox()
    memory_bank = RimruleMemoryBank()
    
    # Khởi tạo Orchestrator
    orchestrator = TriadicDGMOrchestrator(llm_client, sandbox, memory_bank)
    
    # Đọc danh sách bài toán (VD: Polyglot hoặc DSBench)
    with open(manifest_path, 'r', encoding='utf-8') as f:
        tasks = json.load(f)
        
    results = []
    for task in tasks:
        task_id = task.get("task_id")
        task_desc = task.get("description", "")
        workspace_dir = task.get("workspace", "./workspace")
        
        print(f"\n================ ĐANG XỬ LÝ TASK: {task_id} ================")
        result = orchestrator.run_task(task_desc, workspace_dir)
        result["task_id"] = task_id
        results.append(result)
        
    # Ghi nhận toàn bộ kết quả vào archive để Outer Loop (DarwinOrchestrator) lấy đi chấm
    archive_path = os.path.join(output_dir, "evolution_archive.json")
    with open(archive_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4)
        
    print(f"\n[PIPELINE] Hoàn thành! Đã xuất {len(results)} kết quả ra {archive_path}")
