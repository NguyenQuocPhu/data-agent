# Persona Core: Cleanup + DatasetProfile Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dọn rác POC khỏi `main` (an toàn qua archive) và dựng nền `DatasetProfile` auto-inferred để convergence loop chạy trên bất kỳ dataset nào thay vì hardcode telco.

**Architecture:** Tạo git tag/branch `archive/poc` chụp nguyên trạng, rồi xoá dead code + artifact khỏi working tree. Thêm module greenfield `triadic_dgm/persona/dataset_profile.py` — một object bất biến auto-infer từ CSV (labels, behavioral_features, domains) được freeze/cache theo fingerprint. Wire convergence loop lấy `behavioral_features` từ profile thay cho hằng số `FIXED_BEHAVIORAL_FEATURES`.

**Tech Stack:** Python 3.10+, pandas 2.3, scikit-learn, pytest 9.1, git.

## Global Constraints

- Python typing bắt buộc cho mọi cấu trúc dữ liệu Agent Profile / Cognitive State (CLAUDE.md).
- Docstring kiểu Google cho mọi class/function public (CLAUDE.md).
- Giữ modularity: profile generation tách khỏi cognitive logic và simulation loop (CLAUDE.md).
- KHÔNG sửa `data/` (eval datasets / ground-truth) (CLAUDE.md).
- KHÔNG đụng `dgm_agent_v2/`, `evolution_dgm/`, `langgraph_agent/` (user chốt: giữ nguyên).
- Reproducibility: cùng fingerprint ⇒ cùng `behavioral_features` (freeze/cache).
- Chạy test: `python3 -m pytest tests/test_dataset_profile.py -v`.

---

## File Structure

- Create: `triadic_dgm/persona/__init__.py` — package init (rỗng + docstring).
- Create: `triadic_dgm/persona/dataset_profile.py` — DatasetProfile + auto-infer + cache (SRP: chỉ mô tả dataset).
- Create: `tests/test_dataset_profile.py` — unit tests cho module trên.
- Modify: `triadic_dgm/services/convergence_runner.py` — thêm `build_task_prompt(features)`, giữ `FIXED_BEHAVIORAL_FEATURES` làm fallback.
- Modify: `api/services/convergence_loop.py` — build/cache profile lúc `start()`, truyền features vào `run_once`.
- Modify: `.gitignore` — bỏ qua artifact.
- Delete (Phase 0): `triadic_dgm/benchmark/`, `Understand-Anything/`, `.understand-anything/`, `LAMBDA.py`, artifact root.

---

## Phase 0 — Dọn rác repo

### Task 0: Archive POC state rồi xoá rác khỏi main

**Files:**
- Modify: `.gitignore`
- Delete: nhiều (xem bước dưới)

**Interfaces:**
- Consumes: nothing.
- Produces: một `main` sạch; tag `archive/poc-2026-07` + branch `archive/poc` bảo toàn nguyên trạng.

- [ ] **Step 1: Tạo archive tag + branch (bảo toàn toàn bộ trạng thái hiện tại)**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git add -A
git commit -q -m "chore: snapshot before POC cleanup" || echo "nothing to commit"
git tag archive/poc-2026-07
git branch archive/poc
git tag --list 'archive/*'; git branch --list 'archive/*'
```
Expected: liệt kê `archive/poc-2026-07` và `archive/poc`.

- [ ] **Step 2: Xoá dead subsystem + monolith khỏi working tree**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git rm -r -q triadic_dgm/benchmark Understand-Anything .understand-anything app_compile tutorials 2>/dev/null
git rm -q LAMBDA.py 2>/dev/null
echo "removed subsystems"
```
Expected: "removed subsystems" (một số path có thể đã untracked — bỏ qua lỗi).

- [ ] **Step 3: Xoá artifact ở root (PNG/model/log/HTML/CSV nặng/script one-off)**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git rm -q --ignore-unmatch \
  '*.png' '*.pkl' '*.joblib' '*.log' \
  'data_RM6T.csv' 'data_RM6T_T11_2025.csv' 'data_RM6T_T11_2025_cleaned.csv' \
  'intermediate_features.csv' 'persona_analysis_with_text.csv' \
  'bao-cao-persona-churn-t4-2026.html' 'pipeline_flow.html' \
  'test_approve.py' 'test_eda.py' 'test_hitl.py' 'test_instructor.py' 'test_rg.py' 'test_stream.py' \
  'decision_tree_rules.txt' 'cluster_statistics.csv' 'feature_importance.csv' 'out.log' \
  'Report_Non_FPT_Camera.pdf' 'image.png'
# Xoá khỏi đĩa các file untracked nặng còn sót (không nằm trong git):
rm -f data_RM6T.csv *.png *.pkl *.joblib *.log 2>/dev/null
echo "artifacts removed"
```
Expected: "artifacts removed". `data_RM6T.csv` (~468MB) không còn ở root.

- [ ] **Step 4: Cập nhật `.gitignore`**

Thêm các dòng sau vào cuối `.gitignore` (giữ `data_demo_golden.csv` làm fixture test):

```gitignore

# --- POC cleanup: ignore generated artifacts ---
*.png
*.pkl
*.joblib
*.log
*.pdf
cache/
workspace/
# data files (whitelist the small golden fixture used by tests)
data_*.csv
!data_demo_golden.csv
data_processed_t4_metadata.json
# temp reports
bao-cao-*.html
pipeline_flow.html
```

- [ ] **Step 5: Xác minh hệ thống vẫn import được (không vỡ)**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
python3 -c "import api.services.convergence_loop; import triadic_dgm.services.convergence_runner; print('imports OK')"
```
Expected: `imports OK` (nếu lỗi import do vừa xoá nhầm dependency, khôi phục file đó từ `git checkout archive/poc -- <path>`).

- [ ] **Step 6: Commit**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git add -A
git commit -q -m "chore: remove POC dead code + artifacts from main (archived in archive/poc)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git log -1 --oneline
```
Expected: commit mới hiển thị.

---

## Phase 1 — DatasetProfile (auto-infer + freeze/cache)

### Task 1: Module `dataset_profile.py` + tests

**Files:**
- Create: `triadic_dgm/persona/__init__.py`
- Create: `triadic_dgm/persona/dataset_profile.py`
- Test: `tests/test_dataset_profile.py`

**Interfaces:**
- Consumes: `pandas.DataFrame`.
- Produces:
  - `DatasetProfile` (frozen dataclass): `.dataset_name: str`, `.fingerprint: str`, `.labels: dict[str,str]`, `.behavioral_features: list[str]`, `.domains: dict[str,list[str]]`, method `.label(column: str) -> str`.
  - `compute_fingerprint(columns, n_rows: int) -> str`
  - `build_metadata(df, dataset_name="dataset") -> dict`
  - `select_behavioral_features(df) -> list[str]`
  - `infer_domains(features: list[str]) -> dict[str, list[str]]`
  - `build_profile(df, metadata=None, dataset_name="dataset") -> DatasetProfile`
  - `load_or_build_cached(df, cache_dir, metadata=None, dataset_name="dataset") -> DatasetProfile`

- [ ] **Step 1: Viết test thất bại**

Create `tests/test_dataset_profile.py`:

```python
"""Unit tests for the dataset-agnostic DatasetProfile builder."""
from __future__ import annotations

import pandas as pd
import pytest

from triadic_dgm.persona.dataset_profile import (
    DatasetProfile,
    build_profile,
    compute_fingerprint,
    infer_domains,
    load_or_build_cached,
    select_behavioral_features,
)


def _telco_like_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_id": [1, 2, 3, 4],
            "call_total_6m": [0, 5, 10, 2],
            "call_avg_6m": [0.0, 0.8, 1.6, 0.3],
            "complaint_total_6m": [0, 1, 0, 3],
            "constant_col": [7, 7, 7, 7],
            "region": ["N", "S", "N", "S"],  # non-numeric
        }
    )


def _retail_like_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": [10, 11, 12, 13],
            "visits_total": [3, 8, 1, 12],
            "visits_avg": [0.5, 1.3, 0.2, 2.0],
            "revenue_sum": [100.0, 250.0, 30.0, 900.0],
        }
    )


def test_fingerprint_is_stable_and_order_independent():
    a = compute_fingerprint(["b", "a", "c"], 100)
    b = compute_fingerprint(["c", "b", "a"], 100)
    assert a == b
    assert a != compute_fingerprint(["a", "b", "c"], 101)


def test_select_features_drops_id_constant_and_nonnumeric():
    feats = select_behavioral_features(_telco_like_df())
    assert "customer_id" not in feats  # id-like
    assert "constant_col" not in feats  # constant
    assert "region" not in feats  # non-numeric
    assert "call_total_6m" in feats and "complaint_total_6m" in feats
    assert feats == sorted(feats)  # stable order


def test_infer_domains_groups_by_root_generically():
    domains = infer_domains(["call_total_6m", "call_avg_6m", "complaint_total_6m"])
    assert domains["call"] == ["call_total_6m", "call_avg_6m"]
    assert domains["complaint"] == ["complaint_total_6m"]


def test_build_profile_on_non_telco_dataset_has_no_telco_assumptions():
    profile = build_profile(_retail_like_df(), dataset_name="retail")
    assert isinstance(profile, DatasetProfile)
    assert "user_id" not in profile.behavioral_features
    assert set(profile.behavioral_features) == {"visits_total", "visits_avg", "revenue_sum"}
    assert "visits" in profile.domains and "revenue" in profile.domains
    assert profile.label("visits_total") == "visits_total"  # falls back to raw name


def test_cache_freezes_features_across_calls(tmp_path):
    df = _telco_like_df()
    cache_dir = str(tmp_path / "profiles")
    p1 = load_or_build_cached(df, cache_dir, dataset_name="telco")
    # Even if selection logic were to change, a second call with the same fingerprint
    # must return the frozen feature set from cache.
    p2 = load_or_build_cached(df, cache_dir, dataset_name="telco")
    assert p1.fingerprint == p2.fingerprint
    assert p1.behavioral_features == p2.behavioral_features
    import os
    assert os.path.exists(os.path.join(cache_dir, f"{p1.fingerprint}.json"))
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python3 -m pytest tests/test_dataset_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triadic_dgm.persona'`.

- [ ] **Step 3: Tạo package init**

Create `triadic_dgm/persona/__init__.py`:

```python
"""Dataset-agnostic persona pipeline components (profile, characterization, narrative)."""
```

- [ ] **Step 4: Viết implementation tối thiểu**

Create `triadic_dgm/persona/dataset_profile.py`:

```python
"""Auto-inferred, dataset-agnostic profile for the persona pipeline.

Replaces the hardcoded telco/churn couplings (FIXED_BEHAVIORAL_FEATURES,
_DOMAIN_KEYWORD_GROUPS, data_processed_t4_metadata.json). A DatasetProfile is
built ONCE per dataset — keyed by a fingerprint of its columns + row count —
frozen to cache/convergence/profiles/<fingerprint>.json and reloaded on later
runs, so the convergence loop sees a stable feature space (reproducible
clustering) for ANY dataset, not just the telco one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

import pandas as pd

# Column-name tokens that denote identifiers/keys, never behavioral signals.
_ID_NAME_RE = re.compile(
    r"(^|_)(id|uuid|guid|code|msisdn|phone|account|contract|customer|index)(_|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DatasetProfile:
    """Immutable, auto-inferred description of the active dataset.

    Attributes:
        dataset_name: Human-facing dataset name (from metadata or file stem).
        fingerprint: Stable hash of (sorted columns, row count); the cache key.
        labels: Map of raw column name -> human-readable label (any language).
        behavioral_features: Frozen, sorted numeric feature list for clustering.
        domains: Generic domain root -> member columns (auto-grouped by name).
    """

    dataset_name: str
    fingerprint: str
    labels: dict[str, str]
    behavioral_features: list[str]
    domains: dict[str, list[str]]

    def label(self, column: str) -> str:
        """Return the human label for a column, falling back to the raw name."""
        return self.labels.get(column, column)


def compute_fingerprint(columns, n_rows: int) -> str:
    """Stable 16-hex-char id derived from the dataset's columns + row count."""
    raw = json.dumps([sorted(map(str, columns)), int(n_rows)], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_metadata(df: pd.DataFrame, dataset_name: str = "dataset") -> dict:
    """Auto-generate column metadata from a DataFrame.

    Generalizes the old generate_metadata.py. Descriptions default to the column
    name, so a dataset with no curated labels still yields a usable profile.
    """
    columns: list[dict] = []
    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        sample = "" if non_null.empty else str(non_null.iloc[0])
        dtype = "string"
        if pd.api.types.is_integer_dtype(series):
            dtype = "int"
        elif pd.api.types.is_float_dtype(series):
            dtype = "float"
        columns.append(
            {"column": str(col), "type": dtype, "sample": sample, "description": str(col)}
        )
    return {"dataset_name": dataset_name, "columns": columns}


def _labels_from_metadata(metadata: dict) -> dict[str, str]:
    return {
        c["column"]: (c.get("description") or c["column"])
        for c in metadata.get("columns", [])
        if c.get("column")
    }


def select_behavioral_features(df: pd.DataFrame) -> list[str]:
    """Pick numeric, non-identifier, non-constant, low-missing columns.

    Returns a sorted list for a stable, reproducible feature order.
    """
    numeric = df.select_dtypes(include="number")
    n = len(df)
    features: list[str] = []
    for col in numeric.columns:
        name = str(col)
        if _ID_NAME_RE.search(name):
            continue
        series = numeric[col]
        if series.nunique(dropna=True) <= 1:  # constant / all-null
            continue
        if n and series.isna().mean() > 0.5:  # >50% missing
            continue
        features.append(name)
    return sorted(features)


def _feature_root(feature: str) -> str:
    """Collapse aggregation suffixes/prefixes so near-collinear columns
    (call_total_6m, call_avg_6m, call_std ...) share one domain root."""
    r = str(feature).lower()
    r = re.sub(r"_(total|avg|std|trend|cv|ratio|count|sum|mean|min|max)(_6m)?$", "", r)
    r = re.sub(r"^(active|old|recent|no|num|n)_", "", r)
    r = re.sub(r"_(months|6m)$", "", r)
    return r or str(feature).lower()


def infer_domains(features: list[str]) -> dict[str, list[str]]:
    """Group features by shared root token.

    Domain names come from the dataset's own column names (generic), never a
    hardcoded telco domain list.
    """
    domains: dict[str, list[str]] = {}
    for f in features:
        domains.setdefault(_feature_root(f), []).append(f)
    return domains


def build_profile(
    df: pd.DataFrame, metadata: dict | None = None, dataset_name: str = "dataset"
) -> DatasetProfile:
    """Build a DatasetProfile from a DataFrame (+ optional curated metadata)."""
    if metadata is None:
        metadata = build_metadata(df, dataset_name=dataset_name)
    name = metadata.get("dataset_name", dataset_name)
    labels = _labels_from_metadata(metadata)
    features = select_behavioral_features(df)
    domains = infer_domains(features)
    fingerprint = compute_fingerprint(list(df.columns), len(df))
    return DatasetProfile(name, fingerprint, labels, features, domains)


def _to_dict(profile: DatasetProfile) -> dict:
    return {
        "dataset_name": profile.dataset_name,
        "fingerprint": profile.fingerprint,
        "labels": profile.labels,
        "behavioral_features": profile.behavioral_features,
        "domains": profile.domains,
    }


def _from_dict(data: dict) -> DatasetProfile:
    return DatasetProfile(
        dataset_name=data["dataset_name"],
        fingerprint=data["fingerprint"],
        labels=dict(data.get("labels", {})),
        behavioral_features=list(data.get("behavioral_features", [])),
        domains={k: list(v) for k, v in data.get("domains", {}).items()},
    )


def load_or_build_cached(
    df: pd.DataFrame,
    cache_dir: str,
    metadata: dict | None = None,
    dataset_name: str = "dataset",
) -> DatasetProfile:
    """Return the frozen profile for this dataset, building + caching on first sight.

    The fingerprint-keyed cache is what keeps the behavioral feature set STABLE
    across convergence runs — the reproducibility mechanism that replaces the old
    hardcoded FIXED_BEHAVIORAL_FEATURES.
    """
    fingerprint = compute_fingerprint(list(df.columns), len(df))
    path = os.path.join(cache_dir, f"{fingerprint}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return _from_dict(json.load(f))
        except (OSError, json.JSONDecodeError, KeyError):
            pass  # corrupt cache -> rebuild below
    profile = build_profile(df, metadata=metadata, dataset_name=dataset_name)
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_dict(profile), f, ensure_ascii=False, indent=2)
    return profile
```

- [ ] **Step 5: Chạy test để xác nhận PASS**

Run: `python3 -m pytest tests/test_dataset_profile.py -v`
Expected: PASS toàn bộ 5 test.

- [ ] **Step 6: Commit**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git add triadic_dgm/persona/__init__.py triadic_dgm/persona/dataset_profile.py tests/test_dataset_profile.py
git commit -q -m "feat(persona): dataset-agnostic DatasetProfile with auto-infer + freeze/cache

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git log -1 --oneline
```

### Task 2: Wire convergence loop to source features from the profile

**Files:**
- Modify: `triadic_dgm/services/convergence_runner.py` (thêm `build_task_prompt`; `DEFAULT_TASK_PROMPT` dùng nó với `FIXED_BEHAVIORAL_FEATURES` làm fallback)
- Modify: `api/services/convergence_loop.py` (build/cache profile ở `start()`, dùng features ở `_loop`)
- Test: `tests/test_dataset_profile.py` (thêm test cho `build_task_prompt`)

**Interfaces:**
- Consumes: `DatasetProfile.behavioral_features` (Task 1); `run_once(agent, task_prompt=..., report_gen=..., setup_code=...)`.
- Produces: `build_task_prompt(features: list[str]) -> str` trong `convergence_runner`.

- [ ] **Step 1: Viết test thất bại cho `build_task_prompt`**

Thêm vào cuối `tests/test_dataset_profile.py`:

```python
def test_build_task_prompt_embeds_given_features():
    from triadic_dgm.services.convergence_runner import build_task_prompt

    prompt = build_task_prompt(["visits_total", "revenue_sum"])
    assert "visits_total" in prompt and "revenue_sum" in prompt
    # generic call must NOT force the telco fixed list
    assert "cl_total_6m" not in prompt
    # keeps the business-task trigger words the verifier relies on
    assert "phân cụm" in prompt and "persona" in prompt
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python3 -m pytest tests/test_dataset_profile.py::test_build_task_prompt_embeds_given_features -v`
Expected: FAIL — `ImportError: cannot import name 'build_task_prompt'`.

- [ ] **Step 3: Refactor `DEFAULT_TASK_PROMPT` thành `build_task_prompt` trong `convergence_runner.py`**

Thay khối định nghĩa `DEFAULT_TASK_PROMPT` hiện tại (dòng ~261-270) bằng:

```python
def build_task_prompt(features: list[str]) -> str:
    """Build the convergence task prompt for a GIVEN behavioral feature set.

    Feature list is dataset-derived (DatasetProfile.behavioral_features), not the
    hardcoded telco constant — so the same loop works on any dataset. Keeps the
    'phân cụm'/'persona'/'churn' trigger words so SemanticVerifier.is_business_task()
    (triadic_dgm/agent/verifier.py) recognises it as a genuine user request.
    """
    return (
        "Hãy phân tích persona khách hàng churn dựa trên dữ liệu hiện có: thực hiện phân cụm "
        "khách hàng (clustering) và tạo ra các persona mô tả từng nhóm, kèm churn driver, "
        "support/support_pct và các chỉ số nghiệp vụ liên quan.\n\n"
        "BẮT BUỘC: dùng CHÍNH XÁC danh sách behavioral_features sau để train KMeans (KHÔNG thêm, "
        "KHÔNG bớt, KHÔNG tự chọn cột khác thay thế), theo đúng thứ tự này:\n"
        + ", ".join(features)
        + "\nĐây là yêu cầu bắt buộc để đảm bảo kết quả phân cụm ổn định, có thể so sánh được giữa các lần chạy."
    )


# Fallback prompt when no DatasetProfile is supplied (keeps existing behavior).
DEFAULT_TASK_PROMPT = build_task_prompt(FIXED_BEHAVIORAL_FEATURES)
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `python3 -m pytest tests/test_dataset_profile.py -v`
Expected: PASS toàn bộ (6 test).

- [ ] **Step 5: Build + cache profile trong `ConvergenceLoop.start()`**

Trong `api/services/convergence_loop.py`:

(a) Thêm import ở đầu file (cạnh các import `from .` hiện có):

```python
import pandas as pd
from triadic_dgm.persona.dataset_profile import load_or_build_cached
from triadic_dgm.services.convergence_runner import run_once, build_task_prompt
```
(sửa dòng `from triadic_dgm.services.convergence_runner import run_once` thành import cả `build_task_prompt`.)

(b) Thêm hằng số cạnh `DEFAULT_DB_PATH`:

```python
DEFAULT_PROFILES_DIR = os.path.join(REPO_ROOT, "cache", "convergence", "profiles")
```

(c) Thêm `self._profile = None` vào `__init__` (cạnh `self._tool_layer_code = None`).

(d) Thêm hàm module-level (cạnh `_build_tool_layer_code`) đọc dataset đã auto-select thành DataFrame — mirror logic chọn file của `load_dataset`, nhưng chạy ngoài sandbox:

```python
def _load_convergence_dataframe(workspace_root: str) -> "pd.DataFrame | None":
    """Read the convergence workspace's auto-selected tabular dataset into a DataFrame
    (outside the sandbox) so a DatasetProfile can be built from it. Mirrors the file
    selection in the injected load_dataset(). Returns None if nothing usable is found."""
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        return None
    with open(index_path, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    if not index_data:
        return None
    tabular_exts = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}
    entries = [
        (fid, info) for fid, info in index_data.items()
        if os.path.splitext(info.get("filename", info.get("path", "")))[1].lower() in tabular_exts
    ]
    if not entries:
        return None
    entries.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    info = entries[0][1]
    file_path = os.path.join(workspace_root, info["path"])
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in (".csv", ".tsv"):
            return pd.read_csv(file_path, sep="\t" if ext == ".tsv" else ",")
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(file_path)
    except Exception:
        return None
    return None
```
(đảm bảo `import json` và `import os` đã có ở đầu file — nếu chưa, thêm.)

(e) Trong `start()`, ngay sau dòng `self._agent.run_code(self._tool_layer_code)` (dòng ~157), thêm:

```python
        # Build & freeze a DatasetProfile for whatever dataset the workspace holds,
        # so the loop's clustering features are dataset-derived, not hardcoded telco.
        try:
            df = _load_convergence_dataframe(str(workspace_root))
            if df is not None:
                self._profile = load_or_build_cached(df, DEFAULT_PROFILES_DIR)
                print(f"[convergence] DatasetProfile: {len(self._profile.behavioral_features)} features, fp={self._profile.fingerprint}")
        except Exception as e:
            print(f"[convergence] DatasetProfile build failed, using fallback prompt: {e}")
            self._profile = None
```

- [ ] **Step 6: Dùng features của profile trong `_loop`**

Trong `api/services/convergence_loop.py`, sửa dòng ~186:

```python
                result = run_once(self._agent, report_gen=self._report_gen, setup_code=self._tool_layer_code)
```
thành:

```python
                task_prompt = (
                    build_task_prompt(self._profile.behavioral_features)
                    if self._profile and self._profile.behavioral_features
                    else None
                )
                if task_prompt is not None:
                    result = run_once(self._agent, task_prompt=task_prompt, report_gen=self._report_gen, setup_code=self._tool_layer_code)
                else:
                    result = run_once(self._agent, report_gen=self._report_gen, setup_code=self._tool_layer_code)
```

- [ ] **Step 7: Smoke test — profile build trên fixture non-telco + import loop**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
python3 -c "
import pandas as pd
from triadic_dgm.persona.dataset_profile import build_profile
df = pd.read_csv('data_demo_golden.csv')
p = build_profile(df, dataset_name='demo_golden')
print('features:', len(p.behavioral_features), '| domains:', len(p.domains))
assert p.behavioral_features, 'must infer some features'
import api.services.convergence_loop
print('loop import OK')
"
```
Expected: in ra số features > 0, số domains > 0, và `loop import OK`.

- [ ] **Step 8: Chạy full test file + commit**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
python3 -m pytest tests/test_dataset_profile.py -v
git add triadic_dgm/services/convergence_runner.py api/services/convergence_loop.py tests/test_dataset_profile.py
git commit -q -m "feat(convergence): source clustering features from DatasetProfile, not hardcoded telco list

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git log -1 --oneline
```
Expected: tất cả test PASS, commit hiển thị.

---

## Roadmap: Phase 2–4 (plan riêng cho từng phase)

Các phase sau phụ thuộc interface `DatasetProfile` (Task 1) và cần đọc kỹ 2 god-file
(`report_generator.py` 131KB, `prompts.py` 130KB). Mỗi phase sẽ có plan chi tiết riêng
(TDD, code đầy đủ) được viết **sau khi phase trước land** để tránh code phỏng đoán:

- **Phase 2 — `distinguishing_signal` thay `churn_driver` (thuần unsupervised).**
  Thay `_DOMAIN_KEYWORD_GROUPS` bằng `profile.domains`; thay `_classify_churn_driver_from_stars`
  + `_CHURN_DRIVER_RULES_EVIDENCE` bằng bộ tính `distinguishing_signal` generic (domain trội +
  evidence, không từ vựng churn). Migration DB: cột `personas.churn_driver` → `signature`
  (ALTER an toàn theo pattern `persona_fingerprint` đã có).

- **Phase 3 — Narrative/report generic + tách god-file.**
  Tách `report_generator.py` + phần label của `persona_json.py` thành package
  `triadic_dgm/persona/`: `characterization.py`, `narrative.py`, `report.py`. Wire nhãn hiển
  thị (`get_feature_label` trong `convergence_feed.py`) sang `profile.label(...)`. Bỏ map
  `POST_CHURN`/telco.

- **Phase 4 — Prompt độc lập dataset.**
  Cho persona-generation prompt trong `prompts.py` nhận metadata + nhãn cột động thay vì kiến
  thức telco nướng sẵn. Rủi ro cao nhất → làm cuối, có test so sánh chất lượng + giữ
  deterministic fallback.

**Nghiệm thu tổng (cuối Phase 4):** chạy pipeline trên `data_demo_golden.csv` ra persona hợp
lý, convergence ổn định qua ≥3 run, và `grep` sạch mọi tham chiếu `data_processed_t4_metadata.json`
/ `FIXED_BEHAVIORAL_FEATURES` / `churn_driver` trong code path persona.
