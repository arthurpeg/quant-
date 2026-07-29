"""Combine selected edges into one portfolio return stream.

Weighting: ``equal`` (1/N) or ``risk_parity`` (inverse-volatility, so each edge
contributes similar risk). The combined daily returns are compounded into a
portfolio equity curve which the prop-firm checker re-evaluates at book level.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PortfolioResult:
    weights: dict[str, float]
    returns: pd.Series
    equity: pd.Series
    method: str


def _risk_parity_weights(frame: pd.DataFrame) -> dict[str, float]:
    vol = frame.std(ddof=0).replace(0, np.nan)
    inv = 1.0 / vol
    inv = inv.fillna(0.0)
    if inv.sum() == 0:
        # fall back to equal weight
        w = pd.Series(1.0 / frame.shape[1], index=frame.columns)
    else:
        w = inv / inv.sum()
    return w.to_dict()


def combine_returns(returns_by_edge: dict[str, pd.Series], selected: list[str],
                    method: str = "equal", initial_balance: float = 100000.0
                    ) -> PortfolioResult:
    """Combine ``selected`` edges' daily returns into a portfolio."""
    if not selected:
        empty = pd.Series(dtype=float)
        return PortfolioResult({}, empty, empty, method)

    frame = pd.DataFrame({n: returns_by_edge[n] for n in selected}).fillna(0.0).sort_index()

    if method == "risk_parity":
        weights = _risk_parity_weights(frame)
    else:
        method = "equal"
        weights = {n: 1.0 / len(selected) for n in selected}

    w = pd.Series(weights)
    port_ret = (frame * w).sum(axis=1)
    port_ret.name = "returns"
    equity = (1.0 + port_ret).cumprod() * initial_balance
    equity.name = "equity"
    return PortfolioResult(weights=weights, returns=port_ret, equity=equity, method=method)
