import os
import json
import shutil
import re
import sys
import importlib.util
from datetime import datetime
# Add parent directory and current directory to path so we can import from core/ and dgm_agent/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lambda_eval import run_lambda_eval
from strategy_validator import validate_strategy


class MutationController:
    def __init__(self):
        # KHU VỰC BẤT KHẢ XÂM PHẠM: Tác tử không được phép sửa các file này
        self.FROZEN_FILES = [
            "core/inspector.py",         # Hàm tính toán Epiplexity & NCD
            "dgm_agent/lambda_eval.py",  # Bộ chạy test
            "scripts/download_polyglot.py", # Bộ đề thi chuẩn
            "plot_results.py"            # Bộ vẽ biểu đồ & điều phối chính
        ]

    def apply_mutation(self, target_file_path: str, new_code: str) -> bool:
        """Kiểm duyệt và áp dụng code mới từ LLM"""
        # Chuẩn hóa đường dẫn để tránh đường dẫn tương đối để vượt rào
        normalized_path = os.path.normpath(target_file_path).replace("\\", "/")
        
        # 1. Kiểm tra quyền truy cập (Anti-Objective Hacking)
        if any(frozen_file in normalized_path for frozen_file in self.FROZEN_FILES):
            print(f"🚨 CẢNH BÁO BẢO MẬT: Tác tử đang cố gắng hack luật chơi!")
            print(f"   -> Mục tiêu: {target_file_path}")
            print(f"   -> Hành động: BỊ CHẶN LẠI (BLOCKED).")
            return False
            
        # 2. Cho phép ghi đè (Chỉ áp dụng với proposer, programmer, DGM_lambda...)
        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)
        with open(target_file_path, "w", encoding="utf-8") as f:
            f.write(new_code)
        print(f"✅ Đột biến an toàn đã được áp dụng lên: {target_file_path}")
        return True


def simulate_llm_mutation(prompt, target_file):
    """
    Mock LLM function that 'mutates' LAMBDA based on the knowledge graph.
    In a real scenario, this calls Anthropic/OpenAI API with the prompt.
    """
    print("[LLM] Analyzing Knowledge Graph...")
    print("[LLM] Generating code mutation for LAMBDA...")
    
    # We mock a small valid mutation: adding a comment to LAMBDA.py
    with open(target_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    mutated_content = content.replace(
        "class LAMBDA:", 
        "class LAMBDA:\n    # [DGM EVOLVED] Added by Darwin Godel Machine evolution step!\n"
    )
    
    success = MutationController().apply_mutation(target_file, mutated_content)
    if success:
        return "Added evolution comment to LAMBDA class (MOCK)."
    else:
        return "Mutation blocked by security guardrails."


def groq_llm_mutation(prompt, target_file, model=None, temperature=0.2, error_feedback=None):
    """
    Real LLM function using Groq API (e.g. Llama-3-70b or Qwen-2.5) to evolve LAMBDA.
    """
    try:
        from groq import Groq
        client = Groq()
    except Exception:
        client = None

    if not client or not os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY") == "YOUR_GROQ_API_KEY_HERE":
        # Create a mock Groq client for offline testing
        class MockChoice:
            def __init__(self, target_file):
                with open(target_file, 'r', encoding='utf-8') as f:
                    current_code = f.read()
                # Dummy mutation: add a comment
                self.message = type('message', (), {
                    'content': f"```python\n{current_code}\n# [DGM EVOLVED] Mutated by offline mock solver\n```"
                })
        class MockCompletion:
            def __init__(self, target_file):
                self.choices = [MockChoice(target_file)]
        class MockChatCompletions:
            def __init__(self, target_file):
                self.target_file = target_file
            def create(self, **kwargs):
                return MockCompletion(self.target_file)
        class MockChat:
            def __init__(self, target_file):
                self.completions = MockChatCompletions(target_file)
        class MockGroq:
            def __init__(self, target_file):
                self.chat = MockChat(target_file)
        client = MockGroq(target_file)
    
    with open(target_file, 'r', encoding='utf-8') as f:
        current_code = f.read()

    system_prompt = "You are Darwin Gödel Machine, an elite AI Agent that evolves source code. " \
                    "You will be given an architecture graph and the target code. " \
                    "You must output the complete rewritten code. Do not output anything other than the raw python code."
                    
    user_prompt = f"Architecture Graph:\n{prompt}\n\nCurrent LAMBDA.py code:\n```python\n{current_code}\n```\n\n"
    
    if error_feedback:
        user_prompt += f"ATTENTION: Your previous attempt failed with the following error:\n```\n{error_feedback}\n```\n" \
                       "Please analyze this error carefully and fix it in your rewritten code.\n\n"
                       
    user_prompt += "Task: Rewrite the code to improve its capability, handle edge cases, or add logging. " \
                   "Return the full Python code inside ```python ``` tags."

    # Resolve model from environment or config.yaml
    dgm_model = model
    if not dgm_model:
        dgm_model = os.environ.get("DGM_MODEL")
        if not dgm_model:
            try:
                import yaml
                repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                with open(os.path.join(repo_root, "config.yaml"), "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    if cfg.get("conv_model"):
                        dgm_model = cfg["conv_model"]
            except Exception:
                pass
        if not dgm_model:
            dgm_model = "llama-3.1-8b-instant"

    try:
        completion = client.chat.completions.create(
            model=dgm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
        )
        response_text = completion.choices[0].message.content
        
        # Extract code from markdown
        match = re.search(r'```python\n(.*?)\n```', response_text, re.DOTALL)
        if match:
            new_code = match.group(1)
        else:
            # Fallback if the LLM didn't use markdown
            new_code = response_text

        success = MutationController().apply_mutation(target_file, new_code)
        if success:
            return f"Applied Groq API mutation to {os.path.basename(target_file)}."
        else:
            return "Mutation blocked by security guardrails."
    except Exception as e:
        print(f"Groq API Error: {e}")
        return f"Failed to apply mutation. Error: {e}"


# ==============================================================================
#  EvolutionaryScheduler — Q1 Paper: Triadic Roles + Archive + Goldilocks
# ==============================================================================

class EvolutionaryScheduler:
    """
    Implements the full Q1 paper evolution cycle:
    
    1. PROPOSER: Mines knowledge-graph.json for context, generates tasks
    2. SOLVER: Uses Groq API (Programmer) to write code solutions
    3. VERIFIER: Judges correctness + computes MDL Epiplexity score
    4. ARCHIVE: Stores only generations that pass the Goldilocks filter
    
    The Archive enforces the Goldilocks Zone constraint:
    - Mutations that are TOO EASY (epiplexity < 0.5) are rejected
    - Mutations that are TOO HARD (epiplexity > 1.8) are rejected  
    - Only Goldilocks mutations are archived for future evolution
    """
    
    def __init__(self, repo_root: str = None, meta_evolution_freq: int = 5):
        if repo_root is None:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.repo_root = repo_root
        self.meta_evolution_freq = meta_evolution_freq
        self.meta_failures = 0
        
        self.archive = []  # Store successful evolution generations
        self.archive_path = os.path.join(repo_root, 'dgm_agent', 'evolution_archive.json')
        self.strategy_path = os.path.join(repo_root, 'dgm_agent', 'evolution_strategy.py')
        self.baseline_path = os.path.join(repo_root, 'dgm_agent', 'evolution_strategy_baseline.py')
        
        # Load existing archive if present
        if os.path.exists(self.archive_path):
            try:
                with open(self.archive_path, 'r', encoding='utf-8') as f:
                    self.archive = json.load(f)
                print(f"[Archive] Loaded {len(self.archive)} previous generations")
            except Exception:
                self.archive = []
        
        # Load knowledge stream from Understand-Anything (Antigravity)
        from core.proposer import Proposer
        self.knowledge_stream = Proposer.load_knowledge_stream(repo_root)
        print(f"[Knowledge] Loaded {len(self.knowledge_stream)} nodes from knowledge graph")
        
    def _load_strategy(self):
        """Load strategy động từ file evolution_strategy.py"""
        try:
            if not os.path.exists(self.strategy_path):
                shutil.copy2(self.baseline_path, self.strategy_path)
                
            spec = importlib.util.spec_from_file_location("evolution_strategy", self.strategy_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.EvolutionStrategy()
        except Exception as e:
            print(f"[Meta-Evolution] Lỗi load strategy: {e}. Fallback về baseline.")
            spec = importlib.util.spec_from_file_location("evolution_strategy_baseline", self.baseline_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.EvolutionStrategy()
    
    def _save_archive(self):
        """Persist the archive to disk."""
        with open(self.archive_path, 'w', encoding='utf-8') as f:
            json.dump(self.archive, f, indent=2, ensure_ascii=False)
    
    def run_evolution_cycle(self, iterations: int = 1):
        """
        Run the full Proposer -> Solver -> Verifier evolution cycle.
        
        Args:
            iterations: Number of evolution cycles to run
        """
        from core.proposer import Proposer
        from core.capacity_manager import DynamicCapacityManager
        import zlib
        
        capacity_manager = DynamicCapacityManager()
        
        for t in range(iterations):
            print(f"\n{'='*60}")
            print(f"  EVOLUTION CYCLE {t+1}/{iterations}")
            print(f"{'='*60}\n")
            
            # --- 0. META-EVOLUTION CHECK ---
            if (t + 1) % self.meta_evolution_freq == 0:
                self.run_meta_evolution_step()
                
            # --- 1. PROPOSER: Chọn Parent từ Archive qua EvolutionStrategy ---
            strategy = self._load_strategy()
            print(f"[Meta] Current Strategy: {strategy.describe()}")
            parent = strategy.select_parent(self.archive)
            
            if parent:
                print(f"[Meta] Selected Parent Cycle {parent.get('cycle')} with score {parent.get('score')}")
            else:
                print(f"[Meta] Archive empty, starting from scratch.")
            
            proposer = Proposer(budget=100 + t * 10)
            context = proposer.proactively_seek_information()
            task = proposer.generate_task(context)
            print(f"[Proposer] Generated task from context '{context.get('name', '?')}':")
            print(f"  {task[:200]}...")
            
            # Heuristic Epiplexity Estimation of Task (Approximated Kolmogorov Complexity)
            try:
                task_data = json.loads(task)
                desc = task_data.get("task_description", "")
                difficulty = task_data.get("difficulty_level", "easy")
                base = 0.4 if difficulty == "easy" else (0.8 if difficulty == "medium" else 1.4)
                compressed = len(zlib.compress(desc.encode('utf-8')))
                ratio = compressed / max(1, len(desc))
                epiplexity = base + (ratio * 0.5)
            except Exception:
                epiplexity = 0.8
                
            print(f"[Capacity] Estimated Task Epiplexity: {epiplexity:.4f}")
            
            # Allocate budget
            budget = capacity_manager.allocate_budget(epiplexity, current_iteration=t)
            print(f"[Capacity] Allocated Budget: {budget}")
            
            # --- 2. SOLVER: Apply mutation via Groq LLM with retries and multiple candidates ---
            best_candidate_result = None
            best_candidate_log = None
            best_candidate_dir = None
            
            # Generate and verify candidate variants
            for c in range(budget["num_candidates"]):
                print(f"[Solver] Generating Candidate Variant {c+1}/{budget['num_candidates']}...")
                sandbox_dir = os.path.join(self.repo_root, 'dgm_agent', f'sandbox_lambda_c{c}')
                if os.path.exists(sandbox_dir):
                    shutil.rmtree(sandbox_dir)
                os.makedirs(sandbox_dir)
                
                # Copy essential files to sandbox
                for item in ['LAMBDA.py', 'lambda_app.py', 'config.yaml']:
                    src = os.path.join(self.repo_root, item)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(sandbox_dir, item))
                
                for folder in ['core', 'prompt_engineering', 'utils', 'cache', 'ui', 'tests']:
                    src = os.path.join(self.repo_root, folder)
                    dst = os.path.join(sandbox_dir, folder)
                    if os.path.exists(src):
                        shutil.copytree(src, dst)
                        
                # Load GROQ_API_KEY
                if not os.environ.get("GROQ_API_KEY"):
                    try:
                        import yaml
                        with open(os.path.join(self.repo_root, "config.yaml"), "r", encoding="utf-8") as f:
                            cfg = yaml.safe_load(f)
                            if cfg.get("api_key") and cfg["api_key"] != "YOUR_GROQ_API_KEY_HERE":
                                os.environ["GROQ_API_KEY"] = cfg["api_key"]
                    except Exception:
                        pass
                
                target = os.path.join(sandbox_dir, 'LAMBDA.py')
                mutation_prompt = (
                    f"Improve the LAMBDA system based on this task:\n{task}\n\n"
                    f"Architecture context: {json.dumps(context)}"
                )
                
                # Retry self-debugging loop
                last_error = None
                for retry in range(budget["max_retries"]):
                    print(f"  [Solver] Attempt {retry+1}/{budget['max_retries']} for Candidate {c+1}...")
                    mutation_log = groq_llm_mutation(
                        mutation_prompt, 
                        target, 
                        model=budget["model"], 
            temperature=budget["temperature"],
                        error_feedback=last_error
                    )
                    
                    # --- 3. VERIFIER: 4-stage evaluation (includes Epiplexity) ---
                    eval_result = run_lambda_eval(sandbox_dir, budget, task_description=task)
                    
                    if eval_result["is_valid"]:
                        print(f"  [Verifier] Attempt {retry+1} passed validation with score: {eval_result['score']}")
                        last_error = None
                        break
                    else:
                        last_error = eval_result.get("stderr", "Unknown syntax/test failure")
                        print(f"  [Verifier] Attempt {retry+1} failed: {last_error[:100]}...")
                
                # Candidate selection criteria: Prefer valid candidates, higher score
                if best_candidate_result is None:
                    best_candidate_result = eval_result
                    best_candidate_log = mutation_log
                    best_candidate_dir = sandbox_dir
                elif eval_result["is_valid"] and not best_candidate_result["is_valid"]:
                    best_candidate_result = eval_result
                    best_candidate_log = mutation_log
                    best_candidate_dir = sandbox_dir
                elif eval_result["is_valid"] == best_candidate_result["is_valid"]:
                    if eval_result["score"] > best_candidate_result["score"]:
                        best_candidate_result = eval_result
                        best_candidate_log = mutation_log
                        best_candidate_dir = sandbox_dir

            # Assign best candidate for archiving decision
            sandbox_dir = best_candidate_dir
            eval_result = best_candidate_result
            mutation_log = best_candidate_log
            print(f"[Solver] Selected best candidate from {sandbox_dir} with score: {eval_result['score']}")
            
            # --- 4. ARCHIVE DECISION ---
            evolved_params = {}
            try:
                lambda_file = os.path.join(sandbox_dir, 'LAMBDA.py')
                if os.path.exists(lambda_file):
                    with open(lambda_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        epi_min = re.search(r'self\.epiplexity_min\s*=\s*([\d\.]+)', content)
                        epi_max = re.search(r'self\.epiplexity_max\s*=\s*([\d\.]+)', content)
                        vocab_drop = re.search(r'self\.vocab_dropout_rate\s*=\s*([\d\.]+)', content)
                        if epi_min: evolved_params["epiplexity_min"] = float(epi_min.group(1))
                        if epi_max: evolved_params["epiplexity_max"] = float(epi_max.group(1))
                        if vocab_drop: evolved_params["vocab_dropout_rate"] = float(vocab_drop.group(1))
            except Exception as e:
                print(f"[Archive] Lỗi trích xuất biến tiến hóa: {e}")

            generation_record = {
                "cycle": t + 1,
                "timestamp": datetime.now().isoformat(),
                "context_node": context.get("name", "unknown"),
                "task_preview": task[:200],
                "mutation_log": mutation_log,
                "score": eval_result["score"],
                "is_valid": eval_result["is_valid"],
                "epiplexity_score": eval_result.get("epiplexity_score", 0.0),
                "goldilocks_status": eval_result.get("goldilocks_status", "N/A"),
                "evolved_parameters": evolved_params
            }
            
            if eval_result["is_valid"]:
                self.archive.append(generation_record)
                self._save_archive()
                print(f"\n🏆 ARCHIVED! Generation {t+1} passed Goldilocks filter.")
                print(f"   Epiplexity: {eval_result.get('epiplexity_score', 0):.4f}")
                print(f"   Archive size: {len(self.archive)}")
            else:
                status = eval_result.get("goldilocks_status", "UNKNOWN")
                print(f"\n💀 REJECTED! Generation {t+1} — {status}")
                print(f"   Epiplexity: {eval_result.get('epiplexity_score', 0):.4f}")
                print(f"   Reason: {eval_result.get('stderr', 'unknown')[:200]}")
        
        print(f"\n{'='*60}")
        print(f"  EVOLUTION COMPLETE — {len(self.archive)} generations archived")
        print(f"{'='*60}")
        
        return self.archive
        
    def run_meta_evolution_step(self, dry_run=False):
        """
        Thực thi Meta-Evolution: LLM đọc mã chiến lược hiện tại và cố gắng nâng cấp.
        Kết quả được kiểm tra bằng strategy_validator trước khi áp dụng.
        """
        print(f"\n{'*'*60}")
        print(f"  🧠 META-EVOLUTION STEP TRIGGERED")
        print(f"{'*'*60}")
        
        if not os.path.exists(self.strategy_path):
            print("[Meta] Không tìm thấy strategy file, bỏ qua.")
            return
            
        with open(self.strategy_path, "r", encoding="utf-8") as f:
            current_code = f.read()
            
        system_prompt = (
            "You are an Elite AI Meta-Evolution Agent.\n"
            "Your task is to rewrite the evolutionary strategy code to make it select better parents.\n"
            "Rules:\n"
            "1. Output ONLY valid Python code inside ```python ``` tags.\n"
            "2. DO NOT import any modules other than math, random, json.\n"
            "3. MUST keep the class name `EvolutionStrategy` and method `select_parent(self, archive: list) -> dict`.\n"
            "4. Make the strategy smarter: balance exploration and exploitation."
        )
        
        user_prompt = (
            f"Current Strategy Code:\n```python\n{current_code}\n```\n\n"
            "Please improve this strategy. For example, increase version number, "
            "change the name, and use a different scoring/weighting mechanism for `select_parent`."
        )
        
        print("[Meta] Đang sinh mã chiến lược mới từ LLM...")
        # Simulate LLM call using Groq (same config as before)
        try:
            from groq import Groq
            if not os.environ.get("GROQ_API_KEY"):
                import yaml
                with open(os.path.join(self.repo_root, "config.yaml"), "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    if cfg.get("api_key") and cfg["api_key"] != "YOUR_GROQ_API_KEY_HERE":
                        os.environ["GROQ_API_KEY"] = cfg["api_key"]
                        
            if not os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY") == "YOUR_GROQ_API_KEY_HERE":
                # Create a mock Groq client for offline meta-evolution
                class MockChoice:
                    def __init__(self):
                        self.message = type('message', (), {
                            'content': "```python\n"
                                       "import random\n"
                                       "import math\n"
                                       "class EvolutionStrategy:\n"
                                       "    STRATEGY_NAME = 'novelty_ucb_v2'\n"
                                       "    STRATEGY_VERSION = 2\n"
                                       "    def select_parent(self, archive: list) -> dict:\n"
                                       "        if not archive: return {}\n"
                                       "        total_visits = sum(n.get('children_count', 0) for n in archive) + 1\n"
                                       "        best_score = -1\n"
                                       "        best_node = archive[0]\n"
                                       "        for node in archive:\n"
                                       "            score = node.get('score', 0.5)\n"
                                       "            visits = node.get('children_count', 0)\n"
                                       "            ucb = score + 0.1 * math.sqrt(math.log(total_visits) / (visits + 1))\n"
                                       "            if ucb > best_score:\n"
                                       "                best_score = ucb\n"
                                       "                best_node = node\n"
                                       "        best_node['children_count'] = best_node.get('children_count', 0) + 1\n"
                                       "        return best_node\n"
                                       "    def describe(self) -> str:\n"
                                       "        return f'Strategy: {self.STRATEGY_NAME} v{self.STRATEGY_VERSION}'\n"
                                       "    def fitness(self, archive: list) -> float:\n"
                                       "        return 1.0\n"
                                       "```"
                        })
                class MockCompletion:
                    def __init__(self):
                        self.choices = [MockChoice()]
                class MockChatCompletions:
                    def create(self, **kwargs):
                        return MockCompletion()
                class MockChat:
                    def __init__(self):
                        self.completions = MockChatCompletions()
                class MockGroq:
                    def __init__(self):
                        self.chat = MockChat()
                client = MockGroq()
            else:
                client = Groq()
            dgm_model = os.environ.get("DGM_MODEL", "llama-3.1-8b-instant")
            
            completion = client.chat.completions.create(
                model=dgm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
            )
            response_text = completion.choices[0].message.content
            
            import re
            match = re.search(r'```python\n(.*?)\n```', response_text, re.DOTALL)
            new_code = match.group(1) if match else response_text
            
            print("[Meta] Sinh code thành công, đang kiểm tra hợp lệ...")
            
            is_valid, reason = validate_strategy(new_code)
            
            if is_valid:
                print("[Meta] ✅ Mã chiến lược mới HỢP LỆ!")
                if not dry_run:
                    with open(self.strategy_path, "w", encoding="utf-8") as f:
                        f.write(new_code)
                    self.meta_failures = 0
                    print("[Meta] Đã ghi đè chiến lược tiến hóa thành công.")
            else:
                print(f"[Meta] ❌ Lỗi chiến lược mới: {reason}")
                self.meta_failures += 1
                
                if self.meta_failures >= 3:
                    print("[Meta] 🚨 Thất bại 3 lần liên tiếp! Đang ROLLBACK về Baseline...")
                    if not dry_run:
                        shutil.copy2(self.baseline_path, self.strategy_path)
                        self.meta_failures = 0
                        
        except Exception as e:
            print(f"[Meta] Lỗi trong quá trình Meta-Evolution: {e}")
    
    def run_evolution_cycle_stream(self, iterations: int = 1):
        """
        Streaming version of run_evolution_cycle for Gradio UI.
        Yields log strings progressively.
        """
        from core.proposer import Proposer
        
        logs = "🧬 Starting Triadic Evolution (Proposer -> Solver -> Verifier)\n\n"
        yield logs
        
        for t in range(iterations):
            logs += f"{'='*50}\n  CYCLE {t+1}/{iterations}\n{'='*50}\n\n"
            yield logs
            
            # 1. Proposer
            proposer = Proposer(budget=100 + t * 10)
            context = proposer.proactively_seek_information()
            task = proposer.generate_task(context)
            logs += f"📋 [Proposer] Task from '{context.get('name', '?')}':\n{task[:150]}...\n\n"
            yield logs
            
            # 2. Solver (mutation)
            sandbox_dir = os.path.join(self.repo_root, 'dgm_agent', 'sandbox_lambda')
            if os.path.exists(sandbox_dir):
                shutil.rmtree(sandbox_dir)
            os.makedirs(sandbox_dir)
            
            for item in ['LAMBDA.py', 'lambda_app.py', 'config.yaml']:
                src = os.path.join(self.repo_root, item)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(sandbox_dir, item))
            
            for folder in ['core', 'prompt_engineering', 'utils', 'cache', 'ui', 'tests']:
                src = os.path.join(self.repo_root, folder)
                dst = os.path.join(sandbox_dir, folder)
                if os.path.exists(src):
                    shutil.copytree(src, dst)
            
            if not os.environ.get("GROQ_API_KEY"):
                try:
                    import yaml
                    with open(os.path.join(self.repo_root, "config.yaml"), "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f)
                        if cfg.get("api_key") and cfg["api_key"] != "YOUR_GROQ_API_KEY_HERE":
                            os.environ["GROQ_API_KEY"] = cfg["api_key"]
                except Exception:
                    pass
            
            target = os.path.join(sandbox_dir, 'LAMBDA.py')
            mutation_prompt = f"Improve based on task:\n{task}\nContext: {json.dumps(context)}"
            
            logs += "🧠 [Solver] Generating mutation via Groq API...\n"
            yield logs
            
            mutation_log = groq_llm_mutation(mutation_prompt, target)
            logs += f"📝 {mutation_log}\n\n"
            yield logs
            
            # 3. Verifier (4-stage evaluation)
            logs += "🔬 [Verifier] Running 4-Stage Evaluation...\n"
            yield logs
            
            eval_result = run_lambda_eval(sandbox_dir, task_description=task)
            
            epi = eval_result.get("epiplexity_score", 0)
            status = eval_result.get("goldilocks_status", "N/A")
            
            # 4. Archive Decision
            evolved_params = {}
            try:
                lambda_file = os.path.join(sandbox_dir, 'LAMBDA.py')
                if os.path.exists(lambda_file):
                    with open(lambda_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        epi_min = re.search(r'self\.epiplexity_min\s*=\s*([\d\.]+)', content)
                        epi_max = re.search(r'self\.epiplexity_max\s*=\s*([\d\.]+)', content)
                        vocab_drop = re.search(r'self\.vocab_dropout_rate\s*=\s*([\d\.]+)', content)
                        if epi_min: evolved_params["epiplexity_min"] = float(epi_min.group(1))
                        if epi_max: evolved_params["epiplexity_max"] = float(epi_max.group(1))
                        if vocab_drop: evolved_params["vocab_dropout_rate"] = float(vocab_drop.group(1))
            except Exception:
                pass

            if eval_result["is_valid"]:
                record = {
                    "cycle": t + 1,
                    "timestamp": datetime.now().isoformat(),
                    "context_node": context.get("name", "unknown"),
                    "score": eval_result["score"],
                    "epiplexity_score": epi,
                    "goldilocks_status": status,
                    "evolved_parameters": evolved_params
                }
                self.archive.append(record)
                self._save_archive()
                logs += f"\n🏆 ARCHIVED! Epiplexity={epi:.4f} ({status})\n"
                logs += f"💾 Archive size: {len(self.archive)}\n\n"
            else:
                logs += f"\n💀 REJECTED! Epiplexity={epi:.4f} ({status})\n"
                logs += f"❌ {eval_result.get('stderr', '')[:200]}\n\n"
            
            yield logs
        
        logs += f"\n{'='*50}\n🏁 Evolution Complete — {len(self.archive)} archived\n{'='*50}\n"
        yield logs


# ==============================================================================
#  Legacy Functions (preserved for backward compatibility with Gradio UI)
# ==============================================================================

def dgm_evolution_loop_stream(repo_root):
    logs = "🧬 Starting Darwin Godel Machine (LAMBDA Evolution)\n\n"
    yield logs
    
    # 1. Read Understand-Anything Knowledge Graph
    kg_path = os.path.join(repo_root, '.understand-anything', 'knowledge-graph.json')
    if os.path.exists(kg_path):
        with open(kg_path, 'r', encoding='utf-8') as f:
            knowledge_graph = json.load(f)
        logs += f"🗺️ Loaded Knowledge Graph: Found {len(knowledge_graph.get('nodes', []))} nodes.\n"
    else:
        logs += "⚠️ Knowledge Graph not found. DGM will evolve blindly.\n"
        knowledge_graph = {}
    yield logs
        
    # 2. Setup Sandbox
    sandbox_dir = os.path.join(repo_root, 'dgm_agent', 'sandbox_lambda')
    if os.path.exists(sandbox_dir):
        shutil.rmtree(sandbox_dir)
    os.makedirs(sandbox_dir)
    
    logs += "📦 Creating Evolution Sandbox...\n"
    yield logs
    
    for item in ['LAMBDA.py', 'lambda_app.py', 'conversation.py', 'kernel.py', 'programmer.py', 'inspector.py', 'config.yaml']:
        if os.path.exists(os.path.join(repo_root, item)):
            shutil.copy2(os.path.join(repo_root, item), os.path.join(sandbox_dir, item))
            
    for folder in ['prompt_engineering', 'utils', 'front_end', 'tests']:
        src_folder = os.path.join(repo_root, folder)
        dst_folder = os.path.join(sandbox_dir, folder)
        if os.path.exists(src_folder):
            shutil.copytree(src_folder, dst_folder)
            
    if os.path.exists(os.path.join(repo_root, 'cache')):
        shutil.copytree(os.path.join(repo_root, 'cache'), os.path.join(sandbox_dir, 'cache'))
        
    # 3. Evolution Step
    prompt = f"Improve the LAMBDA system. Here is the architecture graph: {json.dumps(knowledge_graph)[:500]}..."
    target_mutation_file = os.path.join(sandbox_dir, 'LAMBDA.py')
    
    logs += "🧠 [LLM] Generating code mutation for LAMBDA...\n"
    yield logs
    
    # ---- CHOOSE YOUR EVOLUTION ENGINE HERE ----
    # Uncomment to use mock local flow:
    # mutation_log = simulate_llm_mutation(prompt, target_mutation_file)
    
    # We load GROQ_API_KEY from environment or config.yaml to avoid hardcoding credentials
    if not os.environ.get("GROQ_API_KEY"):
        try:
            import yaml
            with open(os.path.join(repo_root, "config.yaml"), "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                if cfg.get("api_key") and cfg["api_key"] != "YOUR_GROQ_API_KEY_HERE":
                    os.environ["GROQ_API_KEY"] = cfg["api_key"]
        except Exception:
            pass
    mutation_log = groq_llm_mutation(prompt, target_mutation_file)
    # -------------------------------------------
    
    logs += f"📝 Mutation applied: {mutation_log}\n\n"
    logs += f"🧪 Evaluating LAMBDA fitness at {sandbox_dir}...\n"
    yield logs
    
    # 4. Evaluation Step (now with 4-stage pipeline including Epiplexity)
    eval_result = run_lambda_eval(sandbox_dir, task_description=prompt)
    logs += eval_result.get('stdout', '') + "\n"
    logs += eval_result.get('stderr', '') + "\n"
    
    # Show Epiplexity info
    epi_score = eval_result.get('epiplexity_score', 0)
    epi_status = eval_result.get('goldilocks_status', 'N/A')
    logs += f"\n📊 Epiplexity Score: {epi_score:.4f} | Status: {epi_status}\n"
    
    # 5. Archive Decision
    if eval_result['is_valid']:
        logs += f"\n🏆 EVOLUTION SUCCESSFUL! Fitness Score: {eval_result['score']}\n"
        logs += "💾 Saving evolved LAMBDA to archive...\n"
    else:
        logs += f"\n💀 EVOLUTION FAILED! Fitness Score: {eval_result['score']}\n"
        logs += "🗑️ Discarding mutation. System rolled back.\n"
    yield logs

def dgm_evolution_loop(repo_root):
    
    # 1. Read Understand-Anything Knowledge Graph
    kg_path = os.path.join(repo_root, '.understand-anything', 'knowledge-graph.json')
    if os.path.exists(kg_path):
        with open(kg_path, 'r', encoding='utf-8') as f:
            knowledge_graph = json.load(f)
        print(f"Loaded Knowledge Graph: Found {len(knowledge_graph.get('nodes', []))} nodes.")
    else:
        print("Knowledge Graph not found. DGM will evolve blindly.")
        knowledge_graph = {}
        
    # 2. Setup Sandbox / Workspace (Mocking Docker copy)
    sandbox_dir = os.path.join(repo_root, 'dgm_agent', 'sandbox_lambda')
    if os.path.exists(sandbox_dir):
        shutil.rmtree(sandbox_dir)
    os.makedirs(sandbox_dir)
    
    # Copy essential LAMBDA files
    for item in ['LAMBDA.py', 'lambda_app.py', 'conversation.py', 'kernel.py', 'programmer.py', 'inspector.py', 'config.yaml']:
        if os.path.exists(os.path.join(repo_root, item)):
            shutil.copy2(os.path.join(repo_root, item), os.path.join(sandbox_dir, item))
            
    # Copy helper directories
    for folder in ['prompt_engineering', 'utils', 'front_end', 'tests']:
        src_folder = os.path.join(repo_root, folder)
        dst_folder = os.path.join(sandbox_dir, folder)
        if os.path.exists(src_folder):
            shutil.copytree(src_folder, dst_folder)
            
    if os.path.exists(os.path.join(repo_root, 'cache')):
        shutil.copytree(os.path.join(repo_root, 'cache'), os.path.join(sandbox_dir, 'cache'))
        
    # 3. Evolution Step (Mutation)
    prompt = f"Improve the LAMBDA system. Here is the architecture graph: {json.dumps(knowledge_graph)[:500]}..."
    target_mutation_file = os.path.join(sandbox_dir, 'LAMBDA.py')
    
    # ---- CHOOSE YOUR EVOLUTION ENGINE HERE ----
    # Uncomment to use the mock local flow:
    # mutation_log = simulate_llm_mutation(prompt, target_mutation_file)
    
    # We load GROQ_API_KEY from environment or config.yaml to avoid hardcoding credentials
    if not os.environ.get("GROQ_API_KEY"):
        try:
            import yaml
            with open(os.path.join(repo_root, "config.yaml"), "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                if cfg.get("api_key") and cfg["api_key"] != "YOUR_GROQ_API_KEY_HERE":
                    os.environ["GROQ_API_KEY"] = cfg["api_key"]
        except Exception:
            pass
    mutation_log = groq_llm_mutation(prompt, target_mutation_file)
    # -------------------------------------------
    
    print(f"Mutation applied: {mutation_log}")
    
    # 4. Evaluation Step (now with 4-stage pipeline including Epiplexity)
    eval_result = run_lambda_eval(sandbox_dir, task_description=prompt)
    
    # 5. Archive Decision
    if eval_result['is_valid']:
        print(f"\nEVOLUTION SUCCESSFUL! Fitness Score: {eval_result['score']}")
        print(f"Epiplexity: {eval_result.get('epiplexity_score', 0):.4f} ({eval_result.get('goldilocks_status', 'N/A')})")
        print("Saving evolved LAMBDA to archive...")
        # In real DGM, this is where we commit the new version to git or update the parent.
    else:
        print(f"\nEVOLUTION FAILED! Fitness Score: {eval_result['score']}")
        print(f"Epiplexity: {eval_result.get('epiplexity_score', 0):.4f} ({eval_result.get('goldilocks_status', 'N/A')})")
        print("Discarding mutation. System rolled back.")

if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Use the new EvolutionaryScheduler for triadic evolution
    scheduler = EvolutionaryScheduler(repo_root)
    scheduler.run_evolution_cycle(iterations=30)
