"""Derived clustering features: LLM proposes, measurement decides.

Ratios and interactions between existing columns can express behaviour that raw
magnitudes cannot ("what share of what this buyer paid was shipping"). But measured on a
real 50k-row retail dataset, naively ADDING such a column made clustering worse every
single time (4/4 candidates, silhouette -0.001 to -0.013): a derived column correlates
strongly with the columns it came from, so it mostly dilutes the distance metric. Used as
a REPLACEMENT for its inputs, the same candidates split 2 better / 2 worse — and the one
that sounded most sensible in business terms (freight per item) was the worst of all
(-0.048).

So a proposal is never trusted on plausibility. Every candidate is evaluated against the
actual clustering, greedily, and only measured improvements survive. Anything the model
proposes that fails to parse, references an unknown column, or fails to earn its place is
dropped.

Expressions are evaluated by walking a whitelisted AST, never by ``eval``: these strings
arrive from a language model and are applied to real data.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

#: Only these node types may appear in a derived-feature expression.
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)

#: Silhouette gain a candidate must deliver before it is allowed into the feature set.
#: Small but strictly positive: a change that cannot be distinguished from noise is not
#: worth the reproducibility cost of changing the frozen feature list.
DEFAULT_MIN_GAIN = 0.01

#: Hard cap on accepted derived features. Each one that replaces its inputs changes what
#: every persona is described by, so drift is bounded deliberately rather than by chance.
DEFAULT_MAX_ACCEPTED = 3

_SILHOUETTE_SAMPLE = 8000
_SEED = 42


@dataclass(frozen=True)
class DerivedCandidate:
    """A proposed derived feature.

    Attributes:
        name: Column name to create. Must not collide with an existing column.
        expression: Arithmetic expression over existing column names.
        label: Human-readable label for reports; falls back to ``name`` when empty.
        replaces: Base columns this feature supersedes and that are dropped when it is
            accepted. Empty means the feature is added alongside them — measured to be
            the losing strategy on real data, but left expressible.
    """

    name: str
    expression: str
    replaces: tuple[str, ...] = ()
    label: str = ""


class ExpressionError(ValueError):
    """Raised when an expression is not a safe, evaluable arithmetic formula."""


def _validate_node(node: ast.AST, valid_columns: set[str]) -> None:
    """Recursively reject anything outside the arithmetic whitelist."""
    if isinstance(node, ast.Expression):
        return _validate_node(node.body, valid_columns)
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ExpressionError(f"toán tử không được phép: {type(node.op).__name__}")
        _validate_node(node.left, valid_columns)
        _validate_node(node.right, valid_columns)
        return None
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise ExpressionError(f"toán tử đơn nguyên không được phép: {type(node.op).__name__}")
        return _validate_node(node.operand, valid_columns)
    if isinstance(node, ast.Name):
        if node.id not in valid_columns:
            raise ExpressionError(f"cột không tồn tại: {node.id}")
        return None
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ExpressionError("chỉ chấp nhận hằng số")
        return None
    raise ExpressionError(f"cú pháp không được phép: {type(node).__name__}")


def parse_expression(expression: str, valid_columns) -> ast.Expression:
    """Parse and validate an arithmetic expression over dataset columns.

    Args:
        expression: The formula, e.g. ``"avg_freight_value / avg_items_per_order"``.
        valid_columns: Columns the expression is allowed to reference.

    Returns:
        The validated AST.

    Raises:
        ExpressionError: If the expression is unparseable or uses anything beyond
            ``+ - * /``, numeric constants and known column names.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"không parse được: {e}") from e
    _validate_node(tree, {str(c) for c in valid_columns})
    return tree


def _eval_node(node: ast.AST, df: pd.DataFrame) -> "pd.Series | float":
    """Evaluate a validated AST against a DataFrame, without ``eval``."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, df)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return pd.to_numeric(df[node.id], errors="coerce")
    if isinstance(node, ast.UnaryOp):
        v = _eval_node(node.operand, df)
        return -v if isinstance(node.op, ast.USub) else v
    left, right = _eval_node(node.left, df), _eval_node(node.right, df)
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    # Division by zero yields NaN rather than inf, so it is imputed like any other
    # missing value instead of dominating the standardised feature space.
    denom = right.replace(0, np.nan) if isinstance(right, pd.Series) else (right or np.nan)
    return left / denom


def evaluate_expression(expression: str, df: pd.DataFrame) -> pd.Series:
    """Compute a derived column, with non-finite values imputed to the median.

    Args:
        expression: Formula already accepted by :func:`parse_expression`.
        df: Source data.

    Returns:
        A float Series aligned with ``df``, free of NaN/inf.

    Raises:
        ExpressionError: If the expression fails validation.
    """
    tree = parse_expression(expression, df.columns)
    out = _eval_node(tree, df)
    if not isinstance(out, pd.Series):
        out = pd.Series(float(out), index=df.index)
    out = out.replace([np.inf, -np.inf], np.nan)
    median = out.median()
    return out.fillna(0.0 if pd.isna(median) else median).astype(float)


#: |Pearson r| at or above which a derived column is treated as a restatement of an
#: existing one rather than new information.
_COLLINEAR_R = 0.99


def _collinear_with(series: pd.Series, frame: pd.DataFrame) -> "str | None":
    """Return the first base column the series merely restates, if any.

    Args:
        series: The candidate derived column.
        frame: The current base feature frame.

    Returns:
        Name of a column with |r| >= :data:`_COLLINEAR_R`, else None.
    """
    values = series.to_numpy(dtype=float)
    if np.std(values) == 0:
        return None
    for col in frame.columns:
        other = frame[col].to_numpy(dtype=float)
        if np.std(other) == 0:
            continue
        r = np.corrcoef(values, other)[0, 1]
        if np.isfinite(r) and abs(r) >= _COLLINEAR_R:
            return str(col)
    return None


def _silhouette(frame: pd.DataFrame, n_clusters: int) -> float:
    """Score a feature set the way the pipeline itself clusters: StandardScaler + KMeans.

    Mirrors the sandbox pipeline's preprocessing deliberately — selecting features under a
    transform the pipeline does not apply would optimise the wrong objective.
    """
    if frame.shape[1] < 2 or len(frame) <= n_clusters:
        return -1.0
    X = StandardScaler().fit_transform(frame.to_numpy(dtype=float))
    labels = KMeans(n_clusters=n_clusters, random_state=_SEED, n_init=10).fit_predict(X)
    if len(set(labels)) < 2:
        return -1.0
    return float(
        silhouette_score(X, labels, sample_size=min(_SILHOUETTE_SAMPLE, len(X)), random_state=_SEED)
    )


def select_derived_features(
    df: pd.DataFrame,
    base_features: list[str],
    candidates: list[DerivedCandidate],
    n_clusters: int = 4,
    min_gain: float = DEFAULT_MIN_GAIN,
    max_accepted: int = DEFAULT_MAX_ACCEPTED,
) -> dict[str, str]:
    """Keep only the candidates that measurably improve the clustering.

    Greedy forward selection: candidates are ranked by their individual gain over the
    baseline, then accepted one at a time only if they still improve the set accepted so
    far. Testing candidates independently and taking every winner is not equivalent —
    derived columns overlap heavily, so a batch of individually-good features can be worse
    together than any of them alone.

    Args:
        df: Source data containing every column referenced by the candidates.
        base_features: The current frozen behavioral feature list.
        candidates: Proposals to evaluate.
        n_clusters: k used for scoring; should match the pipeline's typical k.
        min_gain: Minimum silhouette improvement required to accept a candidate.
        max_accepted: Upper bound on accepted features.

    Returns:
        Accepted feature name -> expression, in acceptance order. Empty when nothing
        earns its place — the caller then keeps the untouched base feature set.
    """
    usable = [f for f in base_features if f in df.columns]
    if len(usable) < 2 or not candidates:
        return {}

    base_frame = df[usable].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    baseline = _silhouette(base_frame, n_clusters)
    print(f"[derived_features] baseline silhouette={baseline:.4f} trên {len(usable)} cột")

    prepared: list[tuple[DerivedCandidate, pd.Series, float]] = []
    for cand in candidates:
        if cand.name in df.columns or cand.name in usable:
            print(f"[derived_features] bỏ '{cand.name}': trùng tên cột đã có")
            continue
        try:
            series = evaluate_expression(cand.expression, df)
        except ExpressionError as e:
            print(f"[derived_features] bỏ '{cand.name}': {e}")
            continue
        if series.nunique() <= 1:
            print(f"[derived_features] bỏ '{cand.name}': hằng số")
            continue
        twin = _collinear_with(series, base_frame)
        if twin is not None:
            # A rescaled copy of an existing column ("c * 1", "a / 2") carries no new
            # information — it just doubles that axis's weight in the distance metric,
            # which can shift silhouette enough to pass the gain test on merit it does not
            # have. Caught in testing: "c * 1" scored +0.0128 and would have been accepted.
            print(f"[derived_features] bỏ '{cand.name}': trùng thông tin với '{twin}' (|r| >= {_COLLINEAR_R})")
            continue
        trial = base_frame.drop(columns=[c for c in cand.replaces if c in base_frame], errors="ignore").copy()
        trial[cand.name] = series.to_numpy()
        prepared.append((cand, series, _silhouette(trial, n_clusters)))

    prepared.sort(key=lambda x: -x[2])
    accepted: dict[str, str] = {}
    current = base_frame
    current_score = baseline
    for cand, series, solo_score in prepared:
        if len(accepted) >= max_accepted:
            break
        trial = current.drop(columns=[c for c in cand.replaces if c in current], errors="ignore").copy()
        trial[cand.name] = series.to_numpy()
        score = _silhouette(trial, n_clusters)
        gain = score - current_score
        verdict = "NHẬN" if gain >= min_gain else "loại"
        print(
            f"[derived_features] {verdict} '{cand.name}' = {cand.expression} "
            f"(riêng lẻ {solo_score:.4f}, kèm tập hiện tại {score:.4f}, Δ {gain:+.4f})"
        )
        if gain >= min_gain:
            accepted[cand.name] = cand.expression
            current, current_score = trial, score
    print(f"[derived_features] nhận {len(accepted)}/{len(candidates)}; silhouette {baseline:.4f} -> {current_score:.4f}")
    return accepted


def resulting_feature_list(
    base_features: list[str],
    candidates: list[DerivedCandidate],
    accepted: dict[str, str],
) -> list[str]:
    """Compute the frozen feature list implied by an acceptance decision.

    Args:
        base_features: The feature list before selection.
        candidates: The candidates that were offered (carry the ``replaces`` sets).
        accepted: Output of :func:`select_derived_features`.

    Returns:
        Base features minus every column an accepted candidate replaces, plus the accepted
        names. Order is stable: surviving base features first, then accepted derived ones.
    """
    if not accepted:
        return list(base_features)
    by_name = {c.name: c for c in candidates}
    replaced: set[str] = set()
    for name in accepted:
        cand = by_name.get(name)
        if cand:
            replaced.update(cand.replaces)
    return [f for f in base_features if f not in replaced] + list(accepted)


class _QualifyColumns(ast.NodeTransformer):
    """Rewrite bare column names into DataFrame subscripts."""

    def __init__(self, frame_name: str):
        self._frame = frame_name

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802 (ast API)
        return ast.Subscript(
            value=ast.Name(id=self._frame, ctx=ast.Load()),
            slice=ast.Constant(value=node.id),
            ctx=ast.Load(),
        )


def to_pandas_expression(expression: str, valid_columns, frame_name: str = "data") -> str:
    """Render an expression as runnable pandas code over a DataFrame.

    ``"a / b"`` becomes ``"data['a'] / data['b']"``. Bare names are meaningless inside the
    sandbox — emitting them verbatim produces a NameError at run time, or worse, silently
    picks up an unrelated local variable of the same name.

    Args:
        expression: A formula accepted by :func:`parse_expression`.
        valid_columns: Columns the expression may reference.
        frame_name: Name of the DataFrame variable in the generated code.

    Returns:
        The equivalent pandas expression as source text.

    Raises:
        ExpressionError: If the expression fails validation.
    """
    tree = parse_expression(expression, valid_columns)
    qualified = ast.fix_missing_locations(_QualifyColumns(frame_name).visit(tree))
    return ast.unparse(qualified.body)
