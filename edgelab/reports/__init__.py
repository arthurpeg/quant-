"""Reporting: persist metrics/correlation to disk and (optionally) plot curves."""
from edgelab.reports.report import (
    save_json,
    save_metrics_table,
    plot_equity_curves,
    plot_correlation,
    format_metrics_line,
)

__all__ = [
    "save_json",
    "save_metrics_table",
    "plot_equity_curves",
    "plot_correlation",
    "format_metrics_line",
]
