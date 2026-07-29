"""Volatility (Donchian/ATR) breakout edge.

Family: volatility / breakout. Hypothesis: a close beyond the prior ``channel``-bar
high/low, by at least ``k`` * ATR, signals a regime break that continues. Go long on
an upside breakout, short on a downside one. Relates to the project's own
exp-005 (intraday ATR breakout), lifted here to daily bars as a clean family example.
"""
from __future__ import annotations

import pandas as pd

from edgelab.edges.base import BaseEdge
from edgelab.risk.trade_rules import atr


class VolatilityBreakoutEdge(BaseEdge):
    family = "volatility_breakout"

    def __init__(self, channel: int = 20, k_atr: float = 0.5,
                 atr_window: int = 14, name: str | None = None):
        super().__init__(name=name or f"volbrk_{channel}",
                         channel=channel, k_atr=k_atr, atr_window=atr_window)
        self.channel = channel
        self.k_atr = k_atr
        self.atr_window = atr_window

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        # Prior-channel extremes exclude the current bar (shift(1)) -> causal.
        prior_high = data["high"].rolling(self.channel).max().shift(1)
        prior_low = data["low"].rolling(self.channel).min().shift(1)
        buf = self.k_atr * atr(data, self.atr_window)

        close = data["close"]
        signals = pd.Series(0, index=data.index, dtype="float64")
        signals[close > prior_high + buf] = 1.0
        signals[close < prior_low - buf] = -1.0
        return self._validate(signals.fillna(0), data.index)
