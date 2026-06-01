"""
Blackboard Architecture for Data Science Tasks
================================================
Triển khai cơ chế Blackboard phân tán theo kiến trúc đề xuất trong bài báo
'LLM-based Multi-Agent Blackboard System for Information Discovery in Data Science'
(2510.01285v2), tích hợp vào framework DGM-Agent.

Luồng hoạt động:
  1. MainAgent post Request lên Blackboard ("Cần tìm file chứa cột 'Age' và 'APP-Z'").
  2. FileAgent quét Data Lake → đọc header + 20 dòng đầu → post Response.
  3. MainAgent tổng hợp Context → gọi LLM sinh code pandas.
  4. Kết quả code được chạy qua Sandbox (subprocess).

Usage:
    from dgm_agent.blackboard import Blackboard, BlackboardAgent, run_ds_pipeline
"""

import json
import os
import re
import subprocess
import sys
import time
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(dotenv_path):
        with open(dotenv_path, encoding="utf-8") as fenv:
            for line in fenv:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ────────────────────────────── Data Classes ──────────────────────────────── #

@dataclass
class BlackboardRequest:
    """Yêu cầu được đăng lên Bảng Đen bởi Main Agent."""
    task_id: str
    question: str
    data_lake_dir: str          # Thư mục chứa file dữ liệu của bài toán


@dataclass
class FileContext:
    """Ngữ cảnh đọc được từ một file, do FileAgent tạo ra."""
    file_path: str
    file_type: str              # 'csv', 'xlsx', 'json', 'txt', ...
    columns: List[str] = field(default_factory=list)
    dtypes: Dict[str, str] = field(default_factory=dict)
    sheets: List[str] = field(default_factory=list)
    preview: str = ""           # 20 dòng đầu dưới dạng text
    error: Optional[str] = None


@dataclass
class BlackboardResponse:
    """Phản hồi được đăng lên Bảng Đen bởi File Agent."""
    agent_id: str
    cluster_name: str
    file_contexts: List[FileContext] = field(default_factory=list)
    relevance_score: float = 0.0    # Độ liên quan với Request (0.0 – 1.0)


# ─────────────────────────── Blackboard (Hub) ─────────────────────────────── #

class Blackboard:
    """
    Bảng Đen trung tâm: nơi Main Agent đăng yêu cầu và
    File Agent đăng phản hồi theo cơ chế pub/sub phi tập trung.
    """

    def __init__(self):
        self.request: Optional[BlackboardRequest] = None
        self.responses: List[BlackboardResponse] = []

    def post_request(self, request: BlackboardRequest):
        """Main Agent đăng yêu cầu lên bảng."""
        self.request = request
        self.responses = []
        print(f"\n📋 [Blackboard] Request đăng: '{request.question[:80]}...'")

    def post_response(self, response: BlackboardResponse):
        """File Agent đăng phản hồi lên bảng."""
        self.responses.append(response)

    def get_context_summary(self) -> str:
        """
        Tổng hợp toàn bộ ngữ cảnh file từ tất cả File Agent
        thành một chuỗi văn bản để đưa vào Prompt của Coding Agent.
        """
        if not self.responses:
            return "Không tìm thấy file dữ liệu liên quan trong Data Lake."

        # Sắp xếp theo độ liên quan giảm dần
        sorted_responses = sorted(self.responses, key=lambda r: r.relevance_score, reverse=True)

        lines = ["=== DATA LAKE CONTEXT (Blackboard Summary) ===\n"]
        for resp in sorted_responses:
            lines.append(f"[Cluster: {resp.cluster_name}]")
            for fc in resp.file_contexts:
                if fc.error:
                    lines.append(f"  File: {fc.file_path}  → ⚠️ Error: {fc.error}")
                    continue
                lines.append(f"  File: {fc.file_path}  (type={fc.file_type})")
                if fc.sheets:
                    lines.append(f"    Sheets: {fc.sheets}")
                if fc.columns:
                    lines.append(f"    Columns: {fc.columns}")
                if fc.dtypes:
                    dtype_str = ", ".join(f"{k}: {v}" for k, v in list(fc.dtypes.items())[:15])
                    lines.append(f"    Dtypes: {dtype_str}")
                if fc.preview:
                    lines.append(f"    Preview (20 rows):\n{fc.preview}")
            lines.append("")
            
        full_context = "\n".join(lines)
        # Giới hạn context chặt chẽ hơn (60000 chars) vì dữ liệu bảng chứa nhiều số/token
        if len(full_context) > 60000:
            full_context = full_context[:60000] + "\n...[CONTEXT TRUNCATED DUE TO LENGTH LIMIT]..."
            
        return full_context


# ─────────────────────────── File Agent ───────────────────────────────────── #

class FileAgent:
    """
    Agent quản lý một cụm (cluster) file dữ liệu.
    Tự động đọc header + 20 dòng đầu và đánh giá độ liên quan với Request.
    """

    def __init__(self, agent_id: str, cluster_name: str, file_paths: List[str]):
        self.agent_id = agent_id
        self.cluster_name = cluster_name
        self.file_paths = file_paths

    # ── Đọc file ── #

    def _compute_ncd(self, x: bytes, y: bytes) -> float:
        if not x and not y:
            return 0.0
        if not x or not y:
            return 1.0
        cx = len(zlib.compress(x))
        cy = len(zlib.compress(y))
        cxy = len(zlib.compress(x + b' ' + y))
        return (cxy - min(cx, cy)) / max(cx, cy)

    def _prune_dataframe(self, df: pd.DataFrame, goal_hint: str) -> str:
        if df.empty or not goal_hint:
            return df.head(20).to_string(index=False, max_rows=20, max_cols=15)
        
        goal_bytes = goal_hint.encode('utf-8')
        scored_rows = []
        
        # Limit to 1000 rows
        df_limited = df.head(1000)
        columns = df_limited.columns.tolist()
        
        for idx, row in df_limited.iterrows():
            # Header-Row Injection
            row_parts = []
            for col, val in zip(columns, row.values):
                row_parts.append(f"{col}: {val}")
            row_str = ", ".join(row_parts)
            
            row_bytes = row_str.encode('utf-8')
            score = self._compute_ncd(goal_bytes, row_bytes)
            scored_rows.append((score, row_str))
            
        scored_rows.sort(key=lambda x: x[0])
        top_rows = [x[1] for x in scored_rows[:20]]
        return "\n".join(top_rows)

    def _prune_text(self, lines: List[str], goal_hint: str) -> str:
        if not lines or not goal_hint:
            return "".join(lines[:20])[:2000]
            
        goal_bytes = goal_hint.encode('utf-8')
        scored_lines = []
        
        # Limit to 1000 lines
        limited_lines = lines[:1000]
        
        for line in limited_lines:
            line_str = line.strip()
            if not line_str:
                continue
            line_bytes = line_str.encode('utf-8')
            score = self._compute_ncd(goal_bytes, line_bytes)
            scored_lines.append((score, line_str))
            
        scored_lines.sort(key=lambda x: x[0])
        top_lines = [x[1] for x in scored_lines[:20]]
        return "\n".join(top_lines)[:2000]

    def _read_csv(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            df = pd.read_csv(fpath, nrows=1000, encoding="utf-8", on_bad_lines="skip")
            preview = self._prune_dataframe(df, goal_hint)
            return FileContext(
                file_path=fpath,
                file_type="csv",
                columns=list(df.columns),
                dtypes={col: str(df[col].dtype) for col in df.columns},
                preview=preview,
            )
        except Exception as e:
            return FileContext(file_path=fpath, file_type="csv", error=str(e))

    def _read_xlsx(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            xl = pd.ExcelFile(fpath)
            sheets = xl.sheet_names
            # Đọc sheet đầu tiên để lấy cột + preview
            df = pd.read_excel(fpath, sheet_name=sheets[0], nrows=1000)
            preview = self._prune_dataframe(df, goal_hint)
            return FileContext(
                file_path=fpath,
                file_type="xlsx",
                columns=list(df.columns),
                dtypes={col: str(df[col].dtype) for col in df.columns},
                sheets=sheets,
                preview=preview,
            )
        except Exception as e:
            return FileContext(file_path=fpath, file_type="xlsx", error=str(e))

    def _read_json(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            preview = self._prune_text(lines, goal_hint)
            
            try:
                obj = json.loads("".join(lines))
                if isinstance(obj, list) and obj:
                    cols = list(obj[0].keys()) if isinstance(obj[0], dict) else []
                else:
                    cols = []
            except Exception:
                cols = []
            return FileContext(file_path=fpath, file_type="json", columns=cols, preview=preview)
        except Exception as e:
            return FileContext(file_path=fpath, file_type="json", error=str(e))

    def _read_generic(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            preview = self._prune_text(lines, goal_hint)
            return FileContext(file_path=fpath, file_type="txt", preview=preview)
        except Exception as e:
            return FileContext(file_path=fpath, file_type="other", error=str(e))

    def read_file(self, fpath: str, goal_hint: str) -> FileContext:
        ext = Path(fpath).suffix.lower()
        if ext == ".csv":
            return self._read_csv(fpath, goal_hint)
        elif ext in (".xlsx", ".xls", ".ods"):
            return self._read_xlsx(fpath, goal_hint)
        elif ext == ".json":
            return self._read_json(fpath, goal_hint)
        else:
            return self._read_generic(fpath, goal_hint)

    # ── Đánh giá độ liên quan ── #

    def _compute_relevance(self, question: str, file_contexts: List[FileContext]) -> float:
        """
        Tính độ liên quan dựa trên keyword matching giữa câu hỏi
        và tên cột + tên file. Đơn giản nhưng hiệu quả với DS-Bench.
        """
        question_lower = question.lower()
        # Tokenize thành từ, loại bỏ stop words
        keywords = set(re.findall(r"\b\w{3,}\b", question_lower))
        stop_words = {"the", "and", "for", "with", "from", "this", "that", "are", "have",
                      "what", "find", "which", "data", "calculate", "compute", "using", "each"}
        keywords -= stop_words

        if not keywords:
            return 0.1

        match_count = 0
        total_signals = 0

        for fc in file_contexts:
            if fc.error:
                continue
            # Kiểm tra tên cột
            for col in fc.columns:
                col_lower = col.lower().replace("_", " ").replace("-", " ")
                col_tokens = set(re.findall(r"\b\w{3,}\b", col_lower))
                if col_tokens & keywords:
                    match_count += len(col_tokens & keywords)
                    total_signals += 1
            # Kiểm tra tên file
            fname_lower = Path(fc.file_path).stem.lower()
            fname_tokens = set(re.findall(r"\b\w{3,}\b", fname_lower))
            if fname_tokens & keywords:
                match_count += 1

        return min(1.0, match_count / max(len(keywords), 1) * 0.8) if total_signals > 0 else 0.05

    # ── Trigger khi có request ── #

    def handle_request(self, request: BlackboardRequest) -> BlackboardResponse:
        """Đọc các file trong cụm và trả về FileContexts."""
        print(f"  🤖 FileAgent [{self.agent_id}] đang quét cụm '{self.cluster_name}' ({len(self.file_paths)} files)...")
        file_contexts = [self.read_file(fp, request.question) for fp in self.file_paths]
        relevance = self._compute_relevance(request.question, file_contexts)
        return BlackboardResponse(
            agent_id=self.agent_id,
            cluster_name=self.cluster_name,
            file_contexts=file_contexts,
            relevance_score=relevance,
        )


# ─────────────────────────── Cluster Factory ──────────────────────────────── #

def build_file_agents(data_lake_dir: str, max_files_per_cluster: int = 5) -> List[FileAgent]:
    """
    Tự động nhóm các file trong data_lake_dir thành các cụm (cluster)
    dựa trên prefix chung hoặc thư mục con, rồi tạo FileAgent cho mỗi cụm.
    
    Args:
        data_lake_dir: Thư mục chứa tất cả file dữ liệu của bài toán.
        max_files_per_cluster: Số file tối đa trong 1 cụm.
    
    Returns:
        Danh sách các FileAgent.
    """
    data_root = Path(data_lake_dir)
    if not data_root.exists():
        print(f"  ⚠️ Data Lake không tồn tại: {data_lake_dir}")
        return []

    DATA_EXTS = {".csv", ".xlsx", ".xls", ".ods", ".json", ".txt", ".tsv"}
    all_files = [str(f) for f in data_root.rglob("*") if f.is_file() and f.suffix.lower() in DATA_EXTS]

    if not all_files:
        print(f"  ⚠️ Không tìm thấy file dữ liệu trong: {data_lake_dir}")
        return []

    # Gom cụm theo thư mục con
    clusters: Dict[str, List[str]] = defaultdict(list)
    for fpath in all_files:
        rel = Path(fpath).relative_to(data_root)
        cluster_key = str(rel.parent) if str(rel.parent) != "." else "_root_"
        clusters[cluster_key].append(fpath)

    # Nếu 1 cụm quá nhiều file, chia nhỏ tiếp theo tiền tố
    final_clusters: Dict[str, List[str]] = {}
    for cluster_name, files in clusters.items():
        if len(files) <= max_files_per_cluster:
            final_clusters[cluster_name] = files
        else:
            # Chia theo tiền tố 3 ký tự đầu tên file
            sub: Dict[str, List[str]] = defaultdict(list)
            for f in files:
                prefix = Path(f).stem[:3].lower()
                sub[prefix].append(f)
            for sub_key, sub_files in sub.items():
                name = f"{cluster_name}_{sub_key}"
                final_clusters[name] = sub_files

    agents = []
    for idx, (cluster_name, files) in enumerate(final_clusters.items()):
        agent = FileAgent(
            agent_id=f"file_agent_{idx:02d}",
            cluster_name=cluster_name,
            file_paths=files,
        )
        agents.append(agent)

    print(f"  📂 Đã tạo {len(agents)} FileAgent cho {len(all_files)} files trong Data Lake.")
    return agents


# ─────────────────────────── Main DS Agent ────────────────────────────────── #

class DSBlackboardAgent:
    """
    Agent điều phối chính (Main Agent) kết hợp Blackboard + DGM Coding Agent.
    """

    def __init__(self, model: str = "hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8",
                 sandbox_dir: str = "./dgm_agent/lcb_sandbox",
                 max_debug_rounds: int = 3):
        self.model = model
        self.sandbox_dir = sandbox_dir
        self.max_debug_rounds = max_debug_rounds
        self.blackboard = Blackboard()
        os.makedirs(sandbox_dir, exist_ok=True)

        # Khởi tạo LLM client
        from llm import create_client
        self.client, self.model_name = create_client(model)

    def _call_llm(self, user_prompt: str, system_prompt: str = "") -> str:
        """Gọi LLM qua proxy, trả về nội dung text."""
        from llm import get_response_from_llm
        response, _ = get_response_from_llm(
            msg=user_prompt,
            client=self.client,
            model=self.model_name,
            system_message=system_prompt or "You are an expert data scientist. Generate clean, executable Python code.",
            temperature=0.2,
        )
        return response or ""

    def _extract_python_code(self, text: str) -> str:
        match = re.search(r"```python\n(.*?)\n```", text, re.DOTALL)
        return match.group(1).strip() if match else text.strip()

    def _run_in_sandbox(self, code: str, task_id: str, timeout: int = 30) -> Tuple[bool, str]:
        """Chạy code Python trong subprocess, trả về (success, output/traceback)."""
        script_path = os.path.join(self.sandbox_dir, f"ds_{task_id}.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace"
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, (result.stderr + "\n" + result.stdout).strip()
        except subprocess.TimeoutExpired:
            return False, f"TimeoutError: Code chạy quá {timeout}s"
        except Exception as e:
            return False, str(e)

    def _build_coding_prompt(self, question: str, context: str) -> str:
        return f"""You are an expert Data Scientist. Solve the following data science question using Python.

QUESTION:
{question}

{context}

INSTRUCTIONS:
- Use the exact file paths shown above to load the data.
- Use pandas, numpy, or other standard data science libraries.
- Handle missing values (NaN) appropriately.
- DO NOT use print() to output results. Instead, define the specific variables requested in the question (e.g., 'avg_salary') and assign the final calculated result to them.
- Return ONLY valid, executable Python code inside ```python ``` blocks.
"""

    def solve(self, task_id: str, question: str, data_lake_dir: str, test_code: str = "") -> Dict[str, Any]:
        """
        Giải một bài toán DA-Code bằng Blackboard + DGM pipeline.
        Returns dict với answer, code, success, traceback.
        """
        print(f"\n{'='*60}")
        print(f"🚀 [DS-Agent] Đang xử lý Task: {task_id}")
        print(f"{'='*60}")
        t_start = time.time()

        # ── Pha 1: Blackboard Discovery ── #
        request = BlackboardRequest(
            task_id=task_id,
            question=question,
            data_lake_dir=data_lake_dir,
        )
        self.blackboard.post_request(request)

        file_agents = build_file_agents(data_lake_dir)
        for agent in file_agents:
            response = agent.handle_request(request)
            self.blackboard.post_response(response)

        context = self.blackboard.get_context_summary()
        print(f"\n📊 [Blackboard] Context tổng hợp ({len(context)} chars)")

        # ── Pha 2: Coding Agent sinh code pandas ── #
        coding_prompt = self._build_coding_prompt(question, context)
        
        print("\n🧠 [Coding Agent] Đang sinh code pandas...")
        raw_response = self._call_llm(coding_prompt)
        code = self._extract_python_code(raw_response)

        # ── Pha 3: Execution + Self-Debug vòng lặp ── #
        success = False
        output = ""
        traceback_info = ""

        for round_idx in range(self.max_debug_rounds):
            print(f"\n⚙️  [Sandbox] Chạy thử (round {round_idx})...")
            
            # Combine generated code with test_code
            combined_code = code + "\n\n# --- TEST CODE ---\n" + test_code
            
            execution_success, output = self._run_in_sandbox(combined_code, f"{task_id}_r{round_idx}")
            
            if execution_success:
                print(f"  ✅ Thực thi thành công (Pass toàn bộ assert)!")
                success = True
                break
            else:
                success = False
                traceback_info = output
                print(f"  ❌ Lỗi Runtime / Assertion (round {round_idx}): {output[:300]}")

            # Nếu fail (runtime hoặc logic) thì debug
            if not success and round_idx < self.max_debug_rounds - 1:
                debug_prompt = f"""The following Python code produced an AssertionError or Runtime Error when tested. Fix it.

ORIGINAL QUESTION:
{question}

{context}

CURRENT CODE:
```python
{code}
```

TEST CODE THAT FAILED:
```python
{test_code}
```

ERROR OR INCORRECT OUTPUT:
{traceback_info[-5000:] if len(traceback_info) > 5000 else traceback_info}

Return ONLY the fixed Python code inside ```python ``` blocks. Do not include the test code in your response, just the main logic."""
                print(f"  🔧 [Self-Debug] Đang sửa lỗi (round {round_idx+1})...")
                raw_fix = self._call_llm(debug_prompt)
                code = self._extract_python_code(raw_fix)

        elapsed = time.time() - t_start
        return {
            "task_id": task_id,
            "question": question,
            "data_lake_dir": data_lake_dir,
            "success": success,
            "code": code,
            "traceback": traceback_info,
            "elapsed_sec": round(elapsed, 2),
            "num_files_discovered": sum(len(r.file_contexts) for r in self.blackboard.responses),
        }


# ─────────────────────────── Public API ───────────────────────────────────── #

def run_ds_pipeline(
    tasks_manifest_path: str,
    model: str = "hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8",
    output_dir: str = "data/results",
    max_debug_rounds: int = 3,
) -> List[Dict]:
    """
    Chạy toàn bộ DS-Bench pipeline cho một manifest tasks.
    
    Args:
        tasks_manifest_path: Path tới file tasks_manifest.jsonl
                             (được tạo bởi download_dsbench.py).
        model: Model LLM để dùng.
        output_dir: Thư mục lưu kết quả.
        max_debug_rounds: Số vòng Self-Debug tối đa.
    
    Returns:
        Danh sách kết quả cho mỗi bài toán.
    """
    os.makedirs(output_dir, exist_ok=True)
    agent = DSBlackboardAgent(model=model, max_debug_rounds=max_debug_rounds)

    tasks = []
    with open(tasks_manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))

    results = []
    for i, task in enumerate(tasks):
        print(f"\n\n[{i+1}/{len(tasks)}] Processing task: {task['task_id']}")
        test_code = task.get("test_code", "")
        data_lake_dir = task.get("data_lake_dir", task.get("task_dir", ""))
        
        # Đọc nội dung câu hỏi thật từ file txt nếu có (dành cho log DS-Bench cũ)
        q_id = task['task_id'].split('_')[-1] # vd: 'question7'
        q_file_path = os.path.join(data_lake_dir, f"{q_id}.txt")
        actual_question = task["question"]
        if os.path.exists(q_file_path):
            try:
                with open(q_file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        actual_question = content
            except Exception as e:
                print(f"  ⚠️ Lỗi khi đọc câu hỏi thật: {e}")

        result = agent.solve(
            task_id=task["task_id"],
            question=actual_question,
            data_lake_dir=data_lake_dir,
            test_code=test_code,
        )
        results.append(result)

        result_path = os.path.join(output_dir, f"{task['task_id']}.json")
        with open(result_path, "w", encoding="utf-8") as rf:
            json.dump(result, rf, indent=2, ensure_ascii=False)

    # Tổng kết
    passed = sum(1 for r in results if r["success"])
    print(f"\n{'='*60}")
    print(f"📊 DS-BENCH EVALUATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Total Tasks: {len(results)}")
    print(f"  ✅ Passed: {passed}")
    print(f"  ❌ Failed: {len(results) - passed}")
    print(f"  📈 Pass Rate: {passed/len(results)*100:.1f}%")
    print(f"{'='*60}")

    report_path = os.path.join(output_dir, "ds_report.json")
    with open(report_path, "w", encoding="utf-8") as rep:
        json.dump({"total": len(results), "passed": passed,
                   "pass_rate": passed/len(results) if results else 0,
                   "results": results}, rep, indent=2, ensure_ascii=False)
    print(f"  📁 Report: {report_path}")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run DS-Bench evaluation with Blackboard Agent")
    parser.add_argument("--manifest", type=str, default="data/local_test/tasks_manifest.jsonl",
                        help="Path to tasks manifest file")
    parser.add_argument("--model", type=str, default="hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8",
                        help="LLM model to use")
    parser.add_argument("--output_dir", type=str, default="data/results",
                        help="Output directory for results")
    parser.add_argument("--max_debug_rounds", type=int, default=3,
                        help="Max Self-Debug rounds")
    args = parser.parse_args()

    run_ds_pipeline(
        tasks_manifest_path=args.manifest,
        model=args.model,
        output_dir=args.output_dir,
        max_debug_rounds=args.max_debug_rounds,
    )
