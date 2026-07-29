"""Correlation of DAILY returns across edge strategies."""
from __future__ import annotations

import pandas as pd


def align_returns(returns_by_edge: dict[str, pd.Series]) -> pd.DataFrame:
    """Align each edge's daily returns onto a common calendar (missing = 0)."""
    frame = pd.DataFrame(returns_by_edge)
    return frame.fillna(0.0).sort_index()


def correlation_matrix(returns_by_edge: dict[str, pd.Series]) -> pd.DataFrame:
    """Pairwise Pearson correlation of the aligned daily-return series."""
    frame = align_returns(returns_by_edge)
    return frame.corr()
