import os
import subprocess
import sys
from typing import Tuple

from triadic_dgm.benchmark.interfaces.sandbox import ISandbox


class LocalSubprocessSandbox(ISandbox):
    """
    Local sandbox implementation using Python's subprocess module.
    """

    def __init__(self, sandbox_dir: str = "./triadic_dgm.benchmark/lcb_sandbox"):
        self.sandbox_dir = sandbox_dir
        os.makedirs(self.sandbox_dir, exist_ok=True)

    def execute(self, code: str, task_id: str, timeout: int = 30) -> Tuple[bool, str]:
        """
        Executes code in a local subprocess and returns the result.
        """
        # Heuristic nhận diện ngôn ngữ non-Python
        if any(keyword in code for keyword in ["#include", "package ", "func ", "public class", "std::", "console.log", "function ", "let ", "const "]):
            # Bỏ qua kiểm tra cú pháp Python, auto-pass Inner Loop 
            # để nhường việc biên dịch thật cho WSL Docker ở Vòng Ngoài (Phase 2)
            return True, "Syntax check bypassed for compiled/non-Python languages. Deferring to Docker."

        script_path = os.path.join(self.sandbox_dir, f"ds_{task_id}.py")
        
        # Save the code to a temporary file
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
            
        try:
            # Run the script using the current Python executable
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace"
            )
            
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, (result.stderr + "\n" + result.stdout).strip()
                
        except subprocess.TimeoutExpired:
            return False, f"TimeoutError: Code execution exceeded {timeout}s limit."
        except Exception as e:
            return False, str(e)
