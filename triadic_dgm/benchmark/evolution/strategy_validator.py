import ast
import tempfile
import os
import importlib.util
import time
import multiprocessing
import traceback
from typing import Tuple

class StrategyValidator:
    """
    [SOTA] Meta-Evolution Strategy Validator.
    Implements Layer 2a (AST Static Check) and Layer 2b (Runtime Sandbox with Timeout)
    to prevent Objective Hacking and Infinite Loops in self-modifying code.
    """
    
    # Danh sách các thư viện bị cấm tuyệt đối theo chuẩn của Khóa luận
    DANGEROUS_MODULES = {'os', 'sys', 'subprocess', 'shutil', 'pathlib'}

    @staticmethod
    def validate_ast(code: str) -> Tuple[bool, str]:
        """
        [Lớp 2a] Kiểm tra AST tĩnh: Bắt syntax error, interface, và module độc hại.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Lỗi cú pháp (SyntaxError) dòng {e.lineno}: {e.msg}"

        has_class = False
        has_method = False

        for node in ast.walk(tree):
            # 1. Chặn các import độc hại (Objective Hacking Prevention)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] in StrategyValidator.DANGEROUS_MODULES:
                        return False, f"Security Violation: Import '{alias.name}' bị cấm."
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split('.')[0] in StrategyValidator.DANGEROUS_MODULES:
                    return False, f"Security Violation: Import from '{node.module}' bị cấm."

            # 2. Kiểm tra Interface bắt buộc
            if isinstance(node, ast.ClassDef) and node.name == 'EvolutionStrategy':
                has_class = True
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == 'select_parent':
                        has_method = True

        if not has_class:
            return False, "Thiếu class bắt buộc: 'EvolutionStrategy'."
        if not has_method:
            return False, "Thiếu method bắt buộc: 'select_parent' trong 'EvolutionStrategy'."

        return True, "AST Validation Passed."

    @staticmethod
    def _sandbox_worker(code: str, return_dict: dict):
        """Hàm công nhân chạy bên trong process cách ly."""
        tmp_path = ""
        try:
            # Ghi code ra file tạm
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            # Load module động từ file tạm
            spec = importlib.util.spec_from_file_location("mock_strategy", tmp_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Mock archive để test thử logic chọn cha mẹ
            mock_archive = [
                {"id": 1, "fitness_score": 0.5, "goldilocks_status": "PASS"},
                {"id": 2, "fitness_score": 0.8, "goldilocks_status": "PASS"},
                {"id": 3, "fitness_score": 0.2, "goldilocks_status": "FAIL"}
            ]

            # Khởi tạo và chạy thử
            strategy_instance = module.EvolutionStrategy()
            selected = strategy_instance.select_parent(mock_archive)

            # Kiểm tra kiểu trả về
            if selected and isinstance(selected, dict):
                return_dict['success'] = True
                return_dict['msg'] = "Sandbox execution successful."
            else:
                return_dict['success'] = False
                return_dict['msg'] = "Lỗi: select_parent không trả về một dictionary hợp lệ."

        except Exception as e:
            return_dict['success'] = False
            return_dict['msg'] = f"Runtime Exception: {str(e)}"
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    @staticmethod
    def validate_strategy(code: str) -> Tuple[bool, str]:
        """
        [Lớp 2b] Runtime Sandbox: Chạy thử chiến lược với Timeout để bắt Infinite Loops.
        """
        # Bước 1: Vượt qua AST Check tĩnh trước
        ast_ok, ast_msg = StrategyValidator.validate_ast(code)
        if not ast_ok:
            return False, ast_msg

        # Bước 2: Chạy Runtime Sandbox bằng multiprocessing
        manager = multiprocessing.Manager()
        return_dict = manager.dict()
        return_dict['success'] = False
        return_dict['msg'] = "Unknown Sandbox Error."

        p = multiprocessing.Process(target=StrategyValidator._sandbox_worker, args=(code, return_dict))
        p.start()
        
        # Đợi tối đa 3 giây theo chuẩn của Khóa luận
        p.join(timeout=3.0) 

        # Nếu sau 3 giây process vẫn chạy -> LLM đã viết Infinite Loop
        if p.is_alive():
            p.terminate()
            p.join()
            return False, "Runtime Timeout: Execution vượt quá 3 giây (Phát hiện Infinite Loop)."

        return return_dict['success'], return_dict['msg']
