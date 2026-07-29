"""Select a decorrelated subset of edges that maximises aggregate Sharpe.

Greedy algorithm: rank candidate edges by standalone Sharpe (best first), then
admit an edge only if its pairwise |correlation| with every already-selected edge
is below ``corr_threshold``. This keeps the surviving book genuinely diversified
rather than several disguised copies of the same bet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def select_decorrelated(
    returns_by_edge: dict[str, pd.Series],
    sharpe_by_edge: dict[str, float],
    corr_threshold: float = 0.30,
    min_sharpe: float = 0.0,
) -> tuple[list[str], pd.DataFrame]:
    """Return ``(selected_names, correlation_matrix)``.

    Only edges with standalone Sharpe >= ``min_sharpe`` are eligible. Among those,
    a greedy pass keeps a maximally-diversified subset under ``corr_threshold``.
    """
    frame = pd.DataFrame(returns_by_edge).fillna(0.0).sort_index()
    corr = frame.corr()

    eligible = [n for n in returns_by_edge if sharpe_by_edge.get(n, -np.inf) >= min_sharpe]
    ranked = sorted(eligible, key=lambda n: sharpe_by_edge.get(n, -np.inf), reverse=True)

    selected: list[str] = []
    for cand in ranked:
        ok = True
        for chosen in selected:
            if abs(corr.loc[cand, chosen]) >= corr_threshold:
                ok = False
                break
        if ok:
            selected.append(cand)
    return selected, corr
