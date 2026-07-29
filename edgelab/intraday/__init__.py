"""Intraday, session-aware strategies (Opening Range Breakout) reported in R.

Separate from the daily bar engine because the execution semantics differ:
a session opening range, an end-of-session time-exit, and per-bar spread costs.
Every trade is normalised so a full stop = -1R.
"""
from edgelab.intraday.orb import (
    POINT_SIZE, load_m10, run_orb, orb_metrics_R,
)

__all__ = ["POINT_SIZE", "load_m10", "run_orb", "orb_metrics_R"]
