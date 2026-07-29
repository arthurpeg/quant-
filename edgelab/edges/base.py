"""Abstract base class for all edges.

Contract: :meth:`generate_signals` returns an integer Series aligned to the input
index, valued in {-1, 0, +1}. The value on bar ``t`` is the *desired position to
open*, which the engine executes at the open of bar ``t+1`` (no lookahead). Edges
MUST be causal — never use information from bar ``t+1`` or later to set signal ``t``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseEdge(ABC):
    #: Which edge family this belongs to (for reporting/decorrelation intuition).
    family: str = "unknown"

    def __init__(self, name: str | None = None, **params):
        self.name = name or self.__class__.__name__
        self.params = params

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Return a signal Series in {-1, 0, +1} aligned to ``data.index``."""

    # -- shared validation --------------------------------------------------
    @staticmethod
    def _validate(signals: pd.Series, index: pd.Index) -> pd.Series:
        signals = signals.reindex(index).fillna(0).astype(int)
        bad = set(signals.unique()) - {-1, 0, 1}
        if bad:
            raise ValueError(f"signals must be in {{-1,0,1}}, got {bad}")
        return signals

    def describe(self) -> dict:
        return {"name": self.name, "family": self.family, "params": self.params}

    def __repr__(self) -> str:  # pragma: no cover
        p = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.__class__.__name__}({self.name!r}, {p})"
