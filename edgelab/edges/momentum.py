"""Time-series (absolute) momentum edge.

Family: trend / momentum. Hypothesis (well documented, e.g. Moskowitz-Ooi-Pedersen
2012, "Time Series Momentum"): the sign of an asset's own past ``lookback``-bar
return predicts the sign of its next return. Go long after positive past return,
short after negative. Optionally require the move to clear a volatility threshold
so we don't trade noise.

NOTE (wiki discipline): single-asset *direction* has repeatedly shown no edge in
this universe. This edge is included as a canonical, honestly-tested baseline —
the framework's job is to *measure* whether it survives cost, not to assume it does.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edgelab.edges.base import BaseEdge


class TimeSeriesMomentumEdge(BaseEdge):
    family = "momentum"

    def __init__(self, lookback: int = 60, vol_window: int = 20,
                 min_abs_z: float = 0.0, name: str | None = None):
        super().__init__(name=name or f"tsmom_{lookback}",
                         lookback=lookback, vol_window=vol_window, min_abs_z=min_abs_z)
        self.lookback = lookback
        self.vol_window = vol_window
        self.min_abs_z = min_abs_z

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        # Causal past return over the lookback window.
        past_ret = close.pct_change(self.lookback)
        raw = np.sign(past_ret)

        if self.min_abs_z > 0:
            # Scale the past return by its own realised vol; gate weak moves.
            daily_ret = close.pct_change()
            vol = daily_ret.rolling(self.vol_window).std()
            z = past_ret / (vol * np.sqrt(self.lookback))
            raw = raw.where(z.abs() >= self.min_abs_z, 0.0)

        signals = raw.fillna(0)
        return self._validate(signals, data.index)
