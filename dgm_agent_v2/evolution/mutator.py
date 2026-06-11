import ast
import os
import re
import json
from typing import Tuple, Dict
from dgm_agent_v2.interfaces.llm_client import ILLMClient

class TPGONodeTransformer(ast.NodeTransformer):
    """
    [SOTA] AST Transformer để cấy ghép Node (Function/Class) trên Đồ thị TPG.
    Đảm bảo an toàn cấu trúc tuyệt đối, không gây lỗi thụt lề (IndentationError).
    """
    def __init__(self, target_node_name: str, new_node_ast: ast.stmt):
        self.target_node_name = target_node_name
        self.new_node_ast = new_node_ast
        self.mutation_applied = False

    def visit_FunctionDef(self, node):
        if node.name == self.target_node_name:
            self.mutation_applied = True
            return self.new_node_ast
        return self.generic_visit(node)

    def visit_ClassDef(self, node):
        if node.name == self.target_node_name:
            self.mutation_applied = True
            return self.new_node_ast
        return self.generic_visit(node)

class SourceCodeMutator:
    """
    Handles self-modification combining Hyper Evolution (HE) and TPGO.
    """
    def __init__(self, llm_client: ILLMClient, project_root: str = "./dgm_agent_v2"):
        self.llm_client = llm_client
        self.project_root = os.path.abspath(project_root)
        
        self.FROZEN_FILES = [
            "interfaces", "evolution/evaluator.py", "evolution/strategy_validator.py", 
            "evolution/dgm_outer.py", "harness", "blackboard.py", "DGM_orchestrator.py"
        ]

        # [Tầng 2 - HE] Biến trạng thái lưu trữ System Prompt linh hoạt
        self.current_mutation_prompt = (
            "You are a TPGO (Textual Parameter Graph Optimization) Mutator. "
            "Your task is to rewrite ONLY the specific function/class that needs improvement. "
            "Do NOT output the entire file."
        )

    def hyper_evolve_prompt(self) -> str:
        """
        [Tầng 2 - HE] Tiến hóa Siêu việt: LLM tự viết lại lệnh đột biến của chính nó.
        """
        print("[HYPER EVOLUTION] Dang tu nang cap DNA cua Mutation Prompt...")
        hyper_prompt = (
            "You are a Meta-Prompt Engineer. Improve the following Mutation Prompt. "
            "Make it more explicit, strict on JSON outputs for TPGO, and encourage highly optimized Python code. "
            "Output ONLY the new prompt text."
        )
        
        new_prompt = self.llm_client.generate(
            prompt=f"Current Prompt:\n{self.current_mutation_prompt}",
            system_prompt=hyper_prompt,
            temperature=0.8
        )
        
        if len(new_prompt) > 50:
            self.current_mutation_prompt = new_prompt.strip()
            print("[HYPER EVOLUTION] Da nang cap Mutation Prompt thanh cong!")
            
        return self.current_mutation_prompt

    def _is_safe_target(self, target_file: str) -> bool:
        """Lớp bảo vệ 1 (Frozen Evaluation Boundary)."""
        target_abs = os.path.abspath(target_file)
        if not target_abs.startswith(self.project_root): return False
        rel_path = os.path.relpath(target_abs, self.project_root).replace("\\", "/")
        for frozen in self.FROZEN_FILES:
            if rel_path.startswith(frozen) or frozen in rel_path: return False
        return True

    def _apply_tpgo_ast(self, original_code: str, target_node_name: str, new_node_code: str) -> str:
        """Thực thi cấy ghép Node bằng AST."""
        original_tree = ast.parse(original_code)
        
        try:
            # Parse code mới của LLM để lấy Node thay thế
            new_tree = ast.parse(new_node_code)
            new_node_ast = new_tree.body[0]  # Get the first statement (the function/class def)
        except Exception as e:
            raise ValueError(f"LLM generated invalid syntax for new node: {e}")

        # Cấy ghép
        transformer = TPGONodeTransformer(target_node_name, new_node_ast)
        modified_tree = transformer.visit(original_tree)
        
        if not transformer.mutation_applied:
            raise ValueError(f"Target node '{target_node_name}' not found in the original AST.")
            
        ast.fix_missing_locations(modified_tree)
        # Xuất ngược lại thành Code (yêu cầu Python 3.9+)
        return ast.unparse(modified_tree)

    def mutate_file_tpgo(self, target_file: str, diagnosis_json: Dict) -> Tuple[bool, str]:
        """
        [Tầng 3 - TPGO] Đột biến cục bộ dựa trên Đạo hàm văn bản (Textual Gradients).
        """
        if not self._is_safe_target(target_file):
            return False, f"🚨 SECURITY BLOCKED: {target_file} is a frozen file."
            
        with open(target_file, "r", encoding="utf-8") as f:
            current_code = f.read()

        textual_gradient_neg = diagnosis_json.get("textual_gradient", "Unknown error")
        improvement_proposal = diagnosis_json.get("improvement_proposal", "Optimize code")

        # Ép LLM trả về chuẩn TPGO JSON Format
        tpgo_system_prompt = (
            f"{self.current_mutation_prompt}\n\n"
            "CRITICAL RULES:\n"
            "1. Identify the EXACT name of the function or class (target_function) that needs fixing.\n"
            "2. Output a strictly valid JSON block with NO wrapping text.\n"
            "Schema:\n"
            "{\n"
            "  \"action\": \"REWRITE_NODE\",\n"
            "  \"target_function\": \"name_of_function_or_class\",\n"
            "  \"new_code\": \"def name_of_function(...): ...\"\n"
            "}"
        )
        
        user_prompt = (
            f"FILE: {target_file}\n"
            f"NEGATIVE GRADIENT (δ-): {textual_gradient_neg}\n"
            f"POSITIVE PROPOSAL (δ+): {improvement_proposal}\n\n"
            f"CURRENT FILE CONTENT:\n```python\n{current_code}\n```\n"
        )
        
        print(f"[Mutator-TPGO] Dang tien hanh ghep tang (dot bien cuc bo) cho {target_file}...")
        response = self.llm_client.generate(prompt=user_prompt, system_prompt=tpgo_system_prompt, temperature=0.5)
        
        try:
            # 1. Bóc tách JSON
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                return False, "LLM failed to output valid JSON."
            json_str = json_match.group(0)
            mutation_data = json.loads(json_str)
            
            target_node = mutation_data["target_function"]
            new_code = mutation_data["new_code"]
            
            # 2. Cấy ghép bằng AST
            final_code = self._apply_tpgo_ast(current_code, target_node, new_code)
            
            # 3. Ghi đè file an toàn
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(final_code)
                
            return True, f"TPGO Mutation successful on node: {target_node}"
            
        except Exception as e:
            return False, f"TPGO Mutation failed: {str(e)}"
