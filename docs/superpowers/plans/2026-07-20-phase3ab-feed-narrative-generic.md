# Phase 3a+3b: Generic Feed Cutover + Deterministic Narrative — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa `distinguishing_signal` (generic, Phase 2) ra lớp feed (JSON API + markdown dashboard) và tạo narrative deterministic generic — để output persona **độc lập dataset**, mà KHÔNG đụng ruột 131KB `report_generator.py` và KHÔNG xoá path telco (còn nằm im).

**Architecture:** Additive tại lớp feed. Thêm hàm `compose_signal_narrative(persona)` (generic, từ `distinguishing_signal`) và làm `describe_persona` hết từ vựng churn. `build_feed_items` + `render_markdown` surface thêm `distinguishing_signal` + `signal_narrative`. Field telco `churn_driver` và LLM `narrative` giữ nguyên (back-compat/dormant); prompt LLM để Phase 4.

**Tech Stack:** Python 3.10+, pytest 9.1, sqlite3 (stdlib).

## Global Constraints

- Strict Python typing + Google-style docstrings (Args:/Returns:) cho function/class public (CLAUDE.md).
- ADDITIVE: KHÔNG xoá/đổi field `churn_driver`, `narrative`, `domain_signature` ở feed/DB. Chỉ THÊM `distinguishing_signal` + `signal_narrative`.
- KHÔNG sửa `report_generator.py`, `prompts.py`, DB schema, UI Next.js.
- `describe_persona` phải giữ **standalone** (không import `characterization` — tránh vòng lặp import; chỉ đọc dict).
- Narrative generic KHÔNG chứa từ vựng churn/telco ("rời mạng", "churn", "CSKH", "khiếu nại"); dùng từ trung lập ("đối tượng", "bản ghi").
- Mọi hàm narrative never-raise (feed chạy mỗi vài phút; 1 persona lỗi không được làm hỏng feed).
- Chạy test: `python3 -m pytest tests/test_narrative.py tests/test_feed_generic.py -v`.

---

## File Structure

- Modify: `triadic_dgm/persona/characterization.py` — thêm `compose_signal_narrative(persona)`.
- Modify: `triadic_dgm/services/persona_json.py` — `describe_persona` bỏ từ vựng churn, dùng `distinguishing_signal.evidence`.
- Modify: `triadic_dgm/services/convergence_feed.py` — `build_feed_items` + `_backfill_incomplete_persona` + `render_markdown` surface signal.
- Test: `tests/test_narrative.py` (mới), `tests/test_feed_generic.py` (mới).

---

## Task 1 (3b): Generic deterministic narrative

**Files:**
- Modify: `triadic_dgm/persona/characterization.py`
- Modify: `triadic_dgm/services/persona_json.py`
- Test: `tests/test_narrative.py`

**Interfaces:**
- Consumes: `persona["distinguishing_signal"]` (Phase 2: `{dominant_domain, stars, top_features, evidence}`).
- Produces: `compose_signal_narrative(persona: dict) -> str` trong `characterization.py`; `describe_persona` (đã có) giờ generic.

- [ ] **Step 1: Viết test thất bại**

Create `tests/test_narrative.py`:

```python
"""Tests for generic, dataset-agnostic persona narrative (no churn vocabulary)."""
from __future__ import annotations

from triadic_dgm.persona.characterization import compose_signal_narrative
from triadic_dgm.services.persona_json import describe_persona

_CHURN_WORDS = ("rời mạng", "churn", "cskh", "khiếu nại")


def _persona_with_signal() -> dict:
    return {
        "persona_name": "Nhóm A",
        "support": 1200,
        "support_pct": 0.42,
        "churn_driver": "Khách hàng âm thầm rời mạng",  # legacy telco field, must be ignored
        "distinguishing_signal": {
            "dominant_domain": "revenue",
            "stars": {"revenue": {"stars": 4, "max_dev": 3.0}},
            "top_features": [{"feature": "revenue_sum", "label": "Doanh thu", "deviation": 3.0}],
            "evidence": "Nhóm nổi bật nhất ở 'revenue': Doanh thu (+300% so với trung bình).",
        },
    }


def test_compose_signal_narrative_is_generic_and_has_size_plus_evidence():
    text = compose_signal_narrative(_persona_with_signal())
    assert "42.0%" in text or "42" in text  # size surfaced
    assert "Doanh thu" in text  # uses embedded label
    low = text.lower()
    for w in _CHURN_WORDS:
        assert w not in low


def test_compose_signal_narrative_empty_without_signal():
    assert compose_signal_narrative({"persona_name": "X", "support": 5}) == ""


def test_describe_persona_no_longer_uses_churn_wording():
    text = describe_persona(_persona_with_signal())
    low = text.lower()
    for w in _CHURN_WORDS:
        assert w not in low
    # still describes the group via the generic evidence
    assert "Doanh thu" in text


def test_describe_persona_never_raises_on_empty():
    assert isinstance(describe_persona({}), str)
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python3 -m pytest tests/test_narrative.py -v`
Expected: FAIL — `ImportError: cannot import name 'compose_signal_narrative'` (và/hoặc assert churn-word ở describe_persona).

- [ ] **Step 3: Thêm `compose_signal_narrative` vào `characterization.py`**

Append vào cuối `triadic_dgm/persona/characterization.py`:

```python
def compose_signal_narrative(persona: dict) -> str:
    """Generic, deterministic persona narrative derived from its distinguishing_signal.

    Dataset-agnostic — no churn/telco vocabulary. States group size and the
    standout evidence already computed (with embedded labels). Best-effort:
    returns "" when no usable signal is present, never raises.

    Args:
        persona: A persona dict expected to carry a "distinguishing_signal".

    Returns:
        A short Vietnamese description, or "" if the signal is missing/empty.
    """
    try:
        sig = persona.get("distinguishing_signal")
        if not isinstance(sig, dict) or not sig:
            return ""
        parts: list[str] = []
        support = persona.get("support")
        pct = persona.get("support_pct")
        pct_str = f"{pct * 100:.1f}%" if isinstance(pct, (int, float)) else None
        size_bits = [
            b
            for b in (
                pct_str and f"khoảng {pct_str} tổng thể",
                support and f"~{support:,} bản ghi".replace(",", "."),
            )
            if b
        ]
        if size_bits:
            parts.append(f"Nhóm này chiếm {' — '.join(size_bits)}.")
        evidence = str(sig.get("evidence") or "").strip()
        if evidence:
            parts.append(evidence)
        return " ".join(parts)
    except Exception:
        return ""
```

- [ ] **Step 4: Làm `describe_persona` generic trong `persona_json.py`**

Trong `triadic_dgm/services/persona_json.py`, thay khối churn_driver hiện tại:

```python
    churn_driver = str(p.get("churn_driver") or "").strip()
    if churn_driver.lower() not in _GENERIC_CHURN_DRIVER_VALUES:
        parts.append(f"Nguyên nhân rời mạng chính được ghi nhận: {churn_driver}.")
```
bằng khối generic (đọc `distinguishing_signal.evidence`, không import gì):

```python
    sig = p.get("distinguishing_signal")
    if isinstance(sig, dict):
        evidence = str(sig.get("evidence") or "").strip()
        if evidence:
            parts.append(evidence)
```

Và đổi câu kích thước ngay phía trên cho trung lập (bỏ "khách hàng"/"KH"):

```python
    size_bits = [b for b in (pct_str and f"khoảng {pct_str} tổng số khách hàng", support and f"~{support:,} KH".replace(",", ".")) if b]
```
thành:

```python
    size_bits = [b for b in (pct_str and f"khoảng {pct_str} tổng thể", support and f"~{support:,} bản ghi".replace(",", ".")) if b]
```

(Ghi chú: `_GENERIC_CHURN_DRIVER_VALUES` có thể còn được tham chiếu nơi khác — KHÔNG xoá định nghĩa của nó; chỉ ngừng dùng ở đây.)

- [ ] **Step 5: Chạy test để xác nhận PASS**

Run: `python3 -m pytest tests/test_narrative.py -v`
Expected: PASS toàn bộ 4 test.

- [ ] **Step 6: Commit**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git add triadic_dgm/persona/characterization.py triadic_dgm/services/persona_json.py tests/test_narrative.py
git commit -q -m "feat(persona): generic deterministic narrative from distinguishing_signal, de-churn describe_persona

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git log -1 --oneline
```

## Task 2 (3a): Surface generic signal in the feed (JSON + markdown)

**Files:**
- Modify: `triadic_dgm/services/convergence_feed.py`
- Test: `tests/test_feed_generic.py`

**Interfaces:**
- Consumes: `compose_signal_narrative` (Task 1); `persona["distinguishing_signal"]` persisted in `persona_json`; store API `init_db`, `save_run(db_path, RunResult)`, `build_feed_items`.
- Produces: feed item gains keys `"distinguishing_signal"` và `"signal_narrative"`; markdown per-persona hiển thị tín hiệu generic.

- [ ] **Step 1: Viết test thất bại**

Create `tests/test_feed_generic.py`:

```python
"""The convergence feed must surface the generic distinguishing_signal + signal_narrative."""
from __future__ import annotations

import time

from triadic_dgm.services.convergence_feed import build_feed_items, render_markdown
from triadic_dgm.services.convergence_runner import RunResult
from triadic_dgm.services.convergence_store import init_db, save_run


def _seed(db_path: str) -> None:
    init_db(db_path)
    persona = {
        "persona_name": "Nhóm doanh thu cao",
        "cluster_id": 0,
        "support": 1200,
        "support_pct": 0.42,
        "feature_means": {"revenue_sum": 900.0},
        "distinguishing_signal": {
            "dominant_domain": "revenue",
            "stars": {"revenue": {"stars": 4, "max_dev": 3.0}},
            "top_features": [{"feature": "revenue_sum", "label": "Doanh thu", "deviation": 3.0}],
            "evidence": "Nhóm nổi bật nhất ở 'revenue': Doanh thu (+300% so với trung bình).",
        },
    }
    now = time.time()
    save_run(db_path, RunResult(run_id="r1", started_at=now, finished_at=now, ok=True, personas=[persona]))


def test_feed_item_exposes_distinguishing_signal_and_narrative(tmp_path):
    db = str(tmp_path / "conv.db")
    _seed(db)
    items = build_feed_items(db, limit=10)
    assert items, "expected at least one feed item"
    item = items[0]
    assert item["distinguishing_signal"]["dominant_domain"] == "revenue"
    assert "Doanh thu" in item["signal_narrative"]
    assert "rời mạng" not in item["signal_narrative"].lower()


def test_markdown_renders_without_error(tmp_path):
    db = str(tmp_path / "conv.db")
    _seed(db)
    md = render_markdown(build_feed_items(db, limit=10))
    assert "Persona Convergence Feed" in md
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python3 -m pytest tests/test_feed_generic.py -v`
Expected: FAIL — `KeyError: 'distinguishing_signal'` (feed item chưa có key này).

- [ ] **Step 3: Import `compose_signal_narrative` trong `convergence_feed.py`**

Sau khối `from .persona_json import (...)` (đầu file), thêm:

```python
from triadic_dgm.persona.characterization import compose_signal_narrative
```

- [ ] **Step 4: Backfill cũng copy `distinguishing_signal`**

Trong `_backfill_incomplete_persona`, đổi dòng:

```python
        for k in ("profile_attributes", "domain_signature", "stats_table"):
```
thành:

```python
        for k in ("profile_attributes", "domain_signature", "stats_table", "distinguishing_signal"):
```

- [ ] **Step 5: Thêm 2 key vào feed item trong `build_feed_items`**

Trong dict `items.append({...})` của `build_feed_items`, ngay sau dòng `"description": full.get("narrative") or describe_persona(full),` thêm:

```python
                # Generic, dataset-agnostic signal (Phase 3a) — surfaced ALONGSIDE the legacy
                # telco churn_driver/narrative so any dataset (not just telco) has a meaningful,
                # non-churn description available to the API/UI.
                "distinguishing_signal": full.get("distinguishing_signal"),
                "signal_narrative": compose_signal_narrative(full),
```

- [ ] **Step 6: Hiển thị tín hiệu generic trong markdown per-persona**

Trong `render_markdown`, trong vòng `for item in repeated:`, NGAY SAU dòng `lines.append(f"### {item['persona_name']} ({len(runs)} lần chạy gần nhất)")` và `lines.append("")`, thêm:

```python
            sig_text = item.get("signal_narrative") or ""
            if sig_text:
                lines.append(f"_Tín hiệu nổi bật (generic): {sig_text}_")
                lines.append("")
```

- [ ] **Step 7: Chạy test để xác nhận PASS + regression**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
python3 -m pytest tests/test_feed_generic.py tests/test_narrative.py tests/test_characterization.py tests/test_dataset_profile.py -q
python3 -c "import api.routers.convergence; import triadic_dgm.services.convergence_feed; print('feed + router import OK')"
```
Expected: tất cả PASS; `feed + router import OK`.

- [ ] **Step 8: Commit**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git add triadic_dgm/services/convergence_feed.py tests/test_feed_generic.py
git commit -q -m "feat(feed): surface generic distinguishing_signal + signal_narrative in JSON + markdown (additive)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git log -1 --oneline
```

---

## Self-Review Notes (đối chiếu spec)

- 3b (narrative generic): ✅ Task 1 — `compose_signal_narrative` + de-churn `describe_persona`, test khẳng định không còn từ vựng churn.
- 3a (feed cutover): ✅ Task 2 — feed JSON + markdown surface `distinguishing_signal`/`signal_narrative`; backfill cũng copy signal.
- Additive/không phá telco: ✅ chỉ THÊM key/hàm; `churn_driver`/`narrative`/DB không đổi; `describe_persona` giữ standalone.
- Never-raise: ✅ `compose_signal_narrative` bọc try/except; test `test_describe_persona_never_raises_on_empty`.
- KHÔNG đụng report_generator/prompts/UI/DB schema: ✅.
- Ngoài phạm vi (ghi rõ): LLM narrative cho dataset non-telco vẫn telco-flavored tới khi Phase 4 (prompts) làm generic; nhãn `get_feature_label` cho stats_table vẫn fallback tên cột thô cho dataset lạ (polish sau, distinguishing_signal đã có nhãn tốt sẵn).
