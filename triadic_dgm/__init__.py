"""Triadic DGM package exports.

The legacy engine imports the full analytics stack. Keep it lazy so the
RLM-native harness and its lightweight unit tests do not start that stack just
by importing ``triadic_dgm.rlm_agent``.
"""

from typing import Any

__all__ = ["TriadicAgent"]


def __getattr__(name: str) -> Any:
    if name == "TriadicAgent":
        from .engine import TriadicAgent

        return TriadicAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
