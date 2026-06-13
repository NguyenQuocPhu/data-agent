import sys
import os

# Add root and triadic_dgm.benchmark to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, "triadic_dgm.benchmark"))

from triadic_dgm.benchmark.evolution.mutator import SourceCodeMutator
from triadic_dgm.benchmark.interfaces.llm_client import ILLMClient

class MockLLM(ILLMClient):
    def generate(self, prompt: str, system_prompt: str, temperature: float = 0.7) -> str:
        # Giả lập LLM nhả ra TPGO format
        return '''
        Here is the JSON for TPGO:
        {
          "action": "REWRITE_NODE",
          "target_function": "compute_fitness",
          "new_code": "def compute_fitness(self):\\n    # LLM MUTATED THIS FUNCTION SAFELY!\\n    return self.score * 1.5"
        }
        '''
        
    def generate_with_tools(self, prompt: str, system_prompt: str, tools: list, temperature: float = 0.7) -> str:
        pass

def test_tpgo_ast_transplant():
    print("Khoi chay bai test TPGONodeTransformer (Dot bien cau truc)...")
    
    dummy_file_path = "triadic_dgm.benchmark/tests/dummy_agent.py"
    dummy_code = '''class DummyAgent:
    def __init__(self):
        self.score = 10
        
    def compute_fitness(self):
        # BUGGY FUNCTION
        return self.score
        
    def do_not_touch_this(self):
        print("I should remain untouched!")
'''
    with open(dummy_file_path, "w", encoding="utf-8") as f:
        f.write(dummy_code)
        
    mutator = SourceCodeMutator(MockLLM(), project_root="triadic_dgm.benchmark")
    
    # Bỏ qua kiểm tra is_safe_target cho bài test bằng cách nới lỏng frozen files hoặc test file ở thư mục con
    
    diagnosis = {
        "textual_gradient": "Function compute_fitness does not scale the score.",
        "improvement_proposal": "Multiply self.score by 1.5 in compute_fitness."
    }
    
    success, msg = mutator.mutate_file_tpgo(dummy_file_path, diagnosis)
    
    print(f"Result: {success} - {msg}")
    
    with open(dummy_file_path, "r", encoding="utf-8") as f:
        new_content = f.read()
        
    print("\n--- FILE SAU KHI DOT BIEN ---")
    print(new_content)
    
    if "return self.score * 1.5" in new_content and "do_not_touch_this" in new_content:
        print("\nKIEM THU THANH CONG: AST ghep tang chuan xac, khong sut me cac ham khac!")
    else:
        print("\nLOI: Ghep tang that bai hoac pha hong cau truc!")

if __name__ == "__main__":
    test_tpgo_ast_transplant()
