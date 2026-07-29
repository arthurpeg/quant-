"""edgelab — a research-and-validation framework for decorrelated trading edges.

Pipeline: arXiv research -> edge candidates -> BaseEdge implementations ->
event-driven backtest with mandatory SL/TP/time-exit and prop-firm rules ->
decorrelated portfolio -> reports.

Everything tunable lives in ``config.yaml``. Load it with :func:`edgelab.config.load_config`.
"""

__all__ = ["config"]
__version__ = "0.1.0"
