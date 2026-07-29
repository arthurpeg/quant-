"""Z-score mean-reversion edge.

Family: mean reversion. Hypothesis: short-horizon deviations of price from a
rolling mean tend to revert. When the close is ``entry_z`` standard deviations
*below* its rolling mean, go long (expect bounce); ``entry_z`` above, go short.
The signal is a *state* (held while stretched), and the engine's barriers/time-exit
manage the trade once opened.

This is a deliberately different family from momentum so the two can decorrelate.
"""
from __future__ import annotations

import pandas as pd

from edgelab.edges.base import BaseEdge


class ZScoreMeanReversionEdge(BaseEdge):
    family = "mean_reversion"

    def __init__(self, window: int = 20, entry_z: float = 1.5,
                 name: str | None = None):
        super().__init__(name=name or f"zrev_{window}_{entry_z}",
                         window=window, entry_z=entry_z)
        self.window = window
        self.entry_z = entry_z

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        # Causal rolling mean/std (uses only past+current bar).
        mean = close.rolling(self.window).mean()
        std = close.rolling(self.window).std()
        z = (close - mean) / std

        signals = pd.Series(0, index=data.index, dtype="float64")
        signals[z <= -self.entry_z] = 1.0    # stretched down -> buy the dip
        signals[z >= self.entry_z] = -1.0    # stretched up   -> fade the rip
        return self._validate(signals.fillna(0), data.index)
