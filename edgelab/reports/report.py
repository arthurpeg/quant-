"""Persist results and draw charts. Matplotlib is optional (guarded import)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("edgelab.reports")


def _ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_json(obj, path: str | Path) -> Path:
    p = Path(path)
    _ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, default=str)
    return p


def save_metrics_table(rows: list[dict], path: str | Path) -> Path:
    p = Path(path)
    _ensure_dir(p.parent)
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def format_metrics_line(name: str, m: dict, verdict: str | None = None) -> str:
    """One compact human-readable summary line for the console."""
    n_trades = m.get("n_trades", 0)
    pf = m.get("profit_factor", 0.0)
    # A combined return-stream has no trade-level stats -> show n/a rather than 0.
    if n_trades == 0:
        pf_s, win_s = "  n/a", "  n/a"
    else:
        pf_s = "  inf" if pf == float("inf") else f"{pf:.2f}"
        win_s = f"{m.get('win_rate', 0):>5.1%}"
    line = (
        f"{name:<26} Sharpe {m.get('sharpe', 0):>6.2f} | "
        f"CAGR {m.get('cagr', 0):>7.2%} | MDD {m.get('max_drawdown', 0):>6.2%} | "
        f"PF {pf_s:>5} | trades {n_trades:>4} | "
        f"win {win_s:>5}"
    )
    if verdict is not None:
        line += f" | prop {verdict}"
    return line


def plot_equity_curves(curves: dict[str, pd.Series], path: str | Path,
                       title: str = "Equity curves") -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # pragma: no cover
        logger.warning("matplotlib not available; skipping %s", path)
        return None

    p = Path(path)
    _ensure_dir(p.parent)
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, eq in curves.items():
        ax.plot(eq.index, eq.values, label=name, linewidth=1.2)
    ax.set_title(title)
    ax.set_ylabel("Equity")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def plot_correlation(corr: pd.DataFrame, path: str | Path,
                     title: str = "Edge return correlation") -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:  # pragma: no cover
        logger.warning("matplotlib not available; skipping %s", path)
        return None

    p = Path(path)
    _ensure_dir(p.parent)
    fig, ax = plt.subplots(figsize=(1.2 * len(corr) + 3, 1.0 * len(corr) + 2))
    im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(range(len(corr)))
    ax.set_yticks(range(len(corr)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(corr.index, fontsize=8)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center",
                    fontsize=7, color="black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p
