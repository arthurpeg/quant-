"""Edges: each edge maps OHLCV bars -> a signal series in {-1, 0, +1}.

An edge encodes *only* the entry view. Risk (SL/TP/time-exit) and execution are
applied downstream by the backtest engine, so edges never see costs or barriers.
"""
from edgelab.edges.base import BaseEdge
from edgelab.edges.momentum import TimeSeriesMomentumEdge
from edgelab.edges.mean_reversion import ZScoreMeanReversionEdge
from edgelab.edges.volatility import VolatilityBreakoutEdge

# Registry so the runner can build edges by name from config/CLI.
EDGE_REGISTRY: dict[str, type[BaseEdge]] = {
    "ts_momentum": TimeSeriesMomentumEdge,
    "zscore_mean_reversion": ZScoreMeanReversionEdge,
    "vol_breakout": VolatilityBreakoutEdge,
}

__all__ = [
    "BaseEdge",
    "TimeSeriesMomentumEdge",
    "ZScoreMeanReversionEdge",
    "VolatilityBreakoutEdge",
    "EDGE_REGISTRY",
]
