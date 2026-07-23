"""Expressions come from a language model and are applied to real data — parsing must be
a whitelist, and selection must be measured rather than trusted.
"""
import numpy as np
import pandas as pd
import pytest

from triadic_dgm.persona.derived_features import (
    DerivedCandidate,
    ExpressionError,
    evaluate_expression,
    parse_expression,
    select_derived_features,
)

_COLS = ["a", "b", "c"]


def _df(n=200, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"a": rng.normal(10, 2, n), "b": rng.normal(4, 1, n), "c": rng.normal(1, 0.2, n)})


# --- parsing is a whitelist, not a blacklist ----------------------------------------

def test_accepts_plain_arithmetic():
    assert parse_expression("a / b", _COLS) is not None
    assert parse_expression("(a + b) * 2 - c", _COLS) is not None
    assert parse_expression("-a / (b + 1)", _COLS) is not None


@pytest.mark.parametrize("expr", [
    "__import__('os').system('rm -rf /')",
    "open('/etc/passwd').read()",
    "a.__class__.__mro__",
    "[x for x in range(10)]",
    "a if b else c",
    "lambda: a",
    "a ** 999999999",          # not in the arithmetic whitelist
    "df['a']",
])
def test_rejects_anything_that_is_not_arithmetic(expr):
    with pytest.raises(ExpressionError):
        parse_expression(expr, _COLS)


def test_rejects_unknown_columns():
    with pytest.raises(ExpressionError):
        parse_expression("a / unknown_column", _COLS)


def test_rejects_unparseable_text():
    with pytest.raises(ExpressionError):
        parse_expression("a / / b", _COLS)


# --- evaluation ---------------------------------------------------------------------

def test_evaluates_without_eval_and_matches_pandas():
    df = _df()
    got = evaluate_expression("a / b", df)
    pd.testing.assert_series_equal(got, (df.a / df.b).astype(float), check_names=False)


def test_division_by_zero_becomes_median_not_inf():
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 2.0, 0.0, 4.0]})
    out = evaluate_expression("a / b", df)
    assert np.isfinite(out).all()
    assert out[2] == pytest.approx(out.drop(index=2).median())


def test_all_nan_column_does_not_produce_nan():
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [0.0, 0.0]})
    assert np.isfinite(evaluate_expression("a / b", df)).all()


# --- selection is measured ----------------------------------------------------------

def _separable_frame(n=600):
    """Two groups separable only by the RATIO a/b, not by a or b alone."""
    rng = np.random.default_rng(7)
    scale = rng.uniform(1, 50, n)          # scale swamps the raw columns
    ratio = np.where(np.arange(n) % 2 == 0, 5.0, 0.5)
    return pd.DataFrame({
        "a": scale * ratio + rng.normal(0, 0.05, n),
        "b": scale + rng.normal(0, 0.05, n),
        "noise": rng.normal(0, 1, n),
    })


def test_accepts_a_ratio_that_actually_separates_the_data():
    df = _separable_frame()
    accepted = select_derived_features(
        df, ["a", "b", "noise"],
        [DerivedCandidate(name="ratio", expression="a / b", replaces=("a", "b"))],
        n_clusters=2,
    )
    assert accepted == {"ratio": "a / b"}


def test_rejects_a_rescaled_copy_of_an_existing_column():
    """A duplicate carries no new information, it just doubles that axis's weight — and
    that reweighting alone shifted silhouette by +0.0128 here, enough to pass the gain
    test on merit it does not have."""
    df = _df()
    accepted = select_derived_features(
        df, _COLS, [DerivedCandidate(name="useless", expression="c * 1", replaces=())],
        n_clusters=3,
    )
    assert accepted == {}


def test_rejects_a_candidate_that_does_not_help():
    df = _df()
    accepted = select_derived_features(
        df, _COLS, [DerivedCandidate(name="mix", expression="a + b + c", replaces=())],
        n_clusters=3,
    )
    assert accepted == {}


def test_drops_unsafe_and_unknown_candidates_without_raising():
    df = _df()
    accepted = select_derived_features(
        df, _COLS,
        [
            DerivedCandidate(name="evil", expression="__import__('os')"),
            DerivedCandidate(name="ghost", expression="a / nope"),
            DerivedCandidate(name="a", expression="b / c"),  # name collides with a column
        ],
        n_clusters=3,
    )
    assert accepted == {}


def test_constant_candidate_is_dropped():
    df = _df()
    accepted = select_derived_features(
        df, _COLS, [DerivedCandidate(name="const", expression="1 * 1")], n_clusters=3,
    )
    assert accepted == {}


def test_respects_max_accepted():
    df = _separable_frame()
    cands = [
        DerivedCandidate(name=f"ratio{i}", expression="a / b", replaces=("a", "b"))
        for i in range(4)
    ]
    accepted = select_derived_features(df, ["a", "b", "noise"], cands, n_clusters=2, max_accepted=1)
    assert len(accepted) <= 1


def test_empty_inputs_are_safe():
    assert select_derived_features(_df(), ["a", "b"], []) == {}
    assert select_derived_features(pd.DataFrame(), [], []) == {}
