"""LLM-inferred human-readable labels for arbitrary dataset columns.

``build_metadata`` defaults every column's description to the column name itself, so a
dataset with no curated metadata produces identity labels — and personas end up named
after raw identifiers ("Nhóm late_delivery_rate cao"). This module asks an LLM what each
column means and returns Vietnamese labels to use instead.

The LLM is soft steering only. Every label it proposes is validated in Python before use,
and any column whose proposal fails validation keeps its raw name — a truthful raw name
beats a confident wrong one. A total failure (no network, bad key, malformed reply)
degrades to exactly the previous behaviour.

Called once per dataset fingerprint: ``load_or_build_cached`` persists the resulting
labels into the profile JSON, so the continuously-running convergence loop does not pay
for an inference on every iteration.
"""
from __future__ import annotations

import json
from typing import Callable, Iterable

import pandas as pd
from pydantic import BaseModel, Field

from triadic_dgm.persona.vocabulary import contains_forbidden_term

# A label is a short noun phrase. Anything longer is the model writing a sentence or
# leaking its reasoning into the field, which would wreck persona names and table cells.
_MAX_LABEL_CHARS = 48
_MAX_COLUMNS = 120
_SAMPLE_VALUES = 3


class _ColumnLabel(BaseModel):
    column: str = Field(description="Tên cột gốc, sao chép CHÍNH XÁC từ input")
    label: str = Field(description="Nhãn tiếng Việt ngắn gọn (2-6 từ), không dấu câu cuối")


class _ColumnLabels(BaseModel):
    labels: list[_ColumnLabel]


def _describe_columns(df: pd.DataFrame, columns: Iterable[str]) -> list[dict]:
    """Summarise columns as name/dtype/sample values for the inference prompt."""
    out: list[dict] = []
    for col in columns:
        series = df[col]
        non_null = series.dropna()
        samples = [str(v) for v in non_null.head(_SAMPLE_VALUES).tolist()]
        if pd.api.types.is_integer_dtype(series):
            dtype = "int"
        elif pd.api.types.is_float_dtype(series):
            dtype = "float"
        else:
            dtype = "string"
        out.append({"column": str(col), "type": dtype, "samples": samples})
    return out


def _build_prompt(dataset_name: str, described: list[dict], allow_domain_terms: bool) -> str:
    """Compose the label-inference prompt.

    Args:
        dataset_name: Human-facing dataset name, for context only.
        described: Output of :func:`_describe_columns`.
        allow_domain_terms: True for a dataset that genuinely carries telco churn columns.
            When False the model is told not to reach for that vocabulary, because the only
            way it could apply is by inventing a domain the data never established.
    """
    domain_rule = (
        "- Dataset này CÓ tín hiệu viễn thông/churn thật, nên dùng thuật ngữ ngành khi cột đúng là như vậy."
        if allow_domain_terms else
        "- TUYỆT ĐỐI KHÔNG dùng thuật ngữ viễn thông/churn (ARPU, cước, thuê bao, CSKH, khiếu nại, "
        "rời mạng, giữ chân...). Dataset này KHÔNG có các khái niệm đó — dùng chúng là bịa ra một "
        "lĩnh vực mà dữ liệu không hề chứng minh."
    )
    return f"""Bạn được cho danh sách cột của một bộ dữ liệu tên "{dataset_name}".
Nhiệm vụ: đặt cho MỖI cột một nhãn tiếng Việt ngắn gọn, dễ đọc cho người làm kinh doanh.

QUY TẮC:
- Nhãn là CỤM DANH TỪ ngắn, 2-6 từ. Không viết câu, không giải thích, không dấu chấm cuối.
- Suy ra ý nghĩa từ TÊN CỘT + KIỂU DỮ LIỆU + GIÁ TRỊ MẪU. Nếu không đủ căn cứ để chắc chắn,
  hãy dịch sát nghĩa đen tên cột thay vì phỏng đoán một khái niệm nghiệp vụ không có trong dữ liệu.
- Giữ nguyên đơn vị nếu tên cột thể hiện rõ (ví dụ "_days" -> "ngày", "_rate" -> "tỷ lệ").
{domain_rule}
- Trả về ĐÚNG một mục cho mỗi cột, trường "column" phải sao chép CHÍNH XÁC tên cột gốc.

DANH SÁCH CỘT:
{json.dumps(described, ensure_ascii=False, indent=1)}"""


def validate_labels(
    proposed: dict[str, str],
    valid_columns: Iterable[str],
    allow_domain_terms: bool,
) -> dict[str, str]:
    """Keep only labels safe to display; drop the rest so raw names survive.

    Pure function, no I/O — this is the deterministic guarantee behind the soft LLM step,
    and the part worth unit-testing.

    Args:
        proposed: Raw column -> label mapping as proposed by the model.
        valid_columns: Columns that actually exist in the dataset.
        allow_domain_terms: When False, labels carrying telco vocabulary are rejected.

    Returns:
        The accepted subset. A column absent from the result keeps its raw name.
    """
    valid = {str(c) for c in valid_columns}
    accepted: dict[str, str] = {}
    for column, label in (proposed or {}).items():
        col = str(column)
        if col not in valid:
            continue  # hallucinated column
        if not isinstance(label, str):
            continue
        text = " ".join(label.split()).strip().rstrip(".")
        if not text or len(text) > _MAX_LABEL_CHARS:
            continue
        if text == col:
            continue  # no information gained; identity fallback covers it
        if not allow_domain_terms and contains_forbidden_term(text):
            continue
        accepted[col] = text
    return accepted


def infer_column_labels(
    df: pd.DataFrame,
    client_factory: Callable[[], object],
    model_name: str,
    dataset_name: str = "dataset",
    allow_domain_terms: bool = False,
    temperature: float = 0.0,
) -> dict[str, str]:
    """Infer display labels for ``df``'s columns via an LLM. Never raises.

    Args:
        df: The dataset whose columns need labels.
        client_factory: Zero-arg callable returning an ``instructor``-patched client.
            Injected rather than constructed here so this module stays import-light and
            unit-testable without network access.
        model_name: Model id to call.
        dataset_name: Human-facing dataset name, passed to the prompt as context.
        allow_domain_terms: True only when the dataset genuinely has telco churn columns.
        temperature: Sampling temperature; 0.0 by default for reproducible labels.

    Returns:
        Column -> label for the columns that produced a usable label; ``{}`` on any
        failure. Callers merge this over identity labels.
    """
    try:
        columns = [str(c) for c in df.columns][:_MAX_COLUMNS]
        if not columns:
            return {}
        described = _describe_columns(df, columns)
        prompt = _build_prompt(dataset_name, described, allow_domain_terms)
        print(
            f"[label_inference] model={model_name} temperature={temperature} "
            f"columns={len(columns)} allow_domain_terms={allow_domain_terms}"
        )
        client = client_factory()
        result = client.chat.completions.create(
            model=model_name,
            response_model=_ColumnLabels,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        proposed = {item.column: item.label for item in result.labels}
        accepted = validate_labels(proposed, columns, allow_domain_terms)
        print(f"[label_inference] accepted {len(accepted)}/{len(columns)} labels")
        return accepted
    except Exception as e:
        print(f"[label_inference] failed, keeping raw column names: {e}")
        return {}


class _DerivedProposal(BaseModel):
    name: str = Field(description="Tên cột mới, snake_case, không trùng cột đã có")
    expression: str = Field(description="Biểu thức số học CHỈ dùng + - * / và tên cột đã có")
    replaces: list[str] = Field(
        default_factory=list,
        description="Các cột gốc mà cột mới này THAY THẾ (để trống nếu không thay thế cột nào)",
    )
    label: str = Field(description="Nhãn tiếng Việt ngắn gọn (2-6 từ) cho cột mới, dùng hiển thị trong báo cáo")
    rationale: str = Field(description="Một câu vì sao tỷ lệ/tương tác này là hành vi đáng phân cụm")


class _DerivedProposals(BaseModel):
    features: list[_DerivedProposal]


def propose_derived_features(
    df: pd.DataFrame,
    base_features: list[str],
    client_factory: Callable[[], object],
    model_name: str,
    labels: dict[str, str] | None = None,
    max_candidates: int = 8,
    temperature: float = 0.0,
) -> list:
    """Ask an LLM for candidate derived clustering features. Never raises.

    Proposals are candidates only — none is trusted on plausibility. The caller passes
    them to :func:`triadic_dgm.persona.derived_features.select_derived_features`, which
    parses them against a whitelist and keeps only those that measurably improve the
    clustering.

    Args:
        df: Source data (used for column names and sample values).
        base_features: The current frozen behavioral feature list.
        client_factory: Zero-arg callable returning an ``instructor``-patched client.
        model_name: Model id to call.
        labels: Optional column -> human label map, to give the model real semantics
            rather than only identifiers.
        max_candidates: Upper bound on proposals requested.
        temperature: Sampling temperature; 0.0 for reproducible proposals.

    Returns:
        A list of ``DerivedCandidate``; empty on any failure.
    """
    from triadic_dgm.persona.derived_features import DerivedCandidate

    try:
        feats = [f for f in base_features if f in df.columns]
        if len(feats) < 2:
            return []
        labels = labels or {}
        described = [
            {"column": f, "label": labels.get(f, f), "samples": [
                round(float(v), 4) for v in pd.to_numeric(df[f], errors="coerce").dropna().head(3)
            ]}
            for f in feats
        ]
        prompt = f"""Dưới đây là các cột số đang được dùng để phân cụm (KMeans) tạo persona.

Nhiệm vụ: đề xuất tối đa {max_candidates} feature PHÁI SINH (tỷ lệ hoặc tương tác giữa các cột đã có)
có khả năng tách nhóm hành vi TỐT HƠN các cột thô.

QUY TẮC BẮT BUỘC:
- Biểu thức CHỈ được dùng: tên cột trong danh sách, số, và 4 phép + - * /. Không hàm, không log/exp.
- Ưu tiên TỶ LỆ chuẩn hoá quy mô (ví dụ "phần X chiếm trong tổng"), vì chúng mô tả HÀNH VI
  độc lập với độ lớn tuyệt đối — đó là thứ cột thô không diễn đạt được.
- Với mỗi feature, liệt kê ở "replaces" các cột gốc mà nó THAY THẾ. Rất quan trọng: thêm cột
  phái sinh mà vẫn giữ cột gốc thường làm phân cụm TỆ ĐI (đã đo trên dữ liệu thật), vì cột
  phái sinh tương quan mạnh với chính cột sinh ra nó và chỉ làm loãng khoảng cách.
- KHÔNG đề xuất bản sao đổi tỷ lệ của một cột (ví dụ "x * 2") — không thêm thông tin gì.

CÁC CỘT:
{json.dumps(described, ensure_ascii=False, indent=1)}"""
        print(f"[label_inference] đề xuất feature phái sinh: model={model_name} temperature={temperature}")
        client = client_factory()
        result = client.chat.completions.create(
            model=model_name,
            response_model=_DerivedProposals,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        out = []
        for p in result.features[:max_candidates]:
            out.append(DerivedCandidate(
                name=str(p.name).strip(),
                expression=str(p.expression).strip(),
                replaces=tuple(str(r).strip() for r in (p.replaces or []) if str(r).strip() in feats),
                label=str(getattr(p, "label", "") or "").strip(),
            ))
            print(f"[label_inference]   đề xuất {p.name} = {p.expression} (thay {p.replaces}) — {p.rationale}")
        return out
    except Exception as e:
        print(f"[label_inference] đề xuất feature phái sinh thất bại: {e}")
        return []
