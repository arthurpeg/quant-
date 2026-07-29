"""Performance metrics computed from a daily equity curve and a trades table."""
from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough fractional decline of the equity curve (>= 0)."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(-drawdown.min())  # report as a positive fraction


def _annualisation(returns: pd.Series, periods_per_year: int) -> float:
    return float(np.sqrt(periods_per_year))


def sharpe(returns: pd.Series, periods_per_year: int) -> float:
    r = returns.dropna()
    if r.std(ddof=0) == 0 or len(r) < 2:
        return 0.0
    return float(r.mean() / r.std(ddof=0) * np.sqrt(periods_per_year))


def sortino(returns: pd.Series, periods_per_year: int) -> float:
    r = returns.dropna()
    downside = r[r < 0]
    dd = downside.std(ddof=0)
    if dd == 0 or len(r) < 2:
        return 0.0
    return float(r.mean() / dd * np.sqrt(periods_per_year))


def cagr(equity: pd.Series, periods_per_year: int) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    total_growth = equity.iloc[-1] / equity.iloc[0]
    years = len(equity) / periods_per_year
    if years <= 0 or total_growth <= 0:
        return 0.0
    return float(total_growth ** (1.0 / years) - 1.0)


def compute_metrics(equity: pd.Series, returns: pd.Series,
                    trades: pd.DataFrame, periods_per_year: int = 252) -> dict:
    """Return the standard metric bundle for one backtested series."""
    n_trades = 0 if trades is None or trades.empty else len(trades)
    wins = losses = 0
    win_rate = profit_factor = expectancy = avg_win = avg_loss = 0.0
    exposure = 0.0

    if n_trades > 0:
        pnl = trades["pnl"]
        win_mask = pnl > 0
        wins, losses = int(win_mask.sum()), int((~win_mask).sum())
        win_rate = wins / n_trades
        gross_win = pnl[win_mask].sum()
        gross_loss = -pnl[~win_mask].sum()
        profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")
        expectancy = float(pnl.mean())
        avg_win = float(pnl[win_mask].mean()) if wins else 0.0
        avg_loss = float(pnl[~win_mask].mean()) if losses else 0.0
        exposure = float(trades["bars_held"].sum() / len(equity)) if len(equity) else 0.0

    return {
        "cagr": cagr(equity, periods_per_year),
        "sharpe": sharpe(returns, periods_per_year),
        "sortino": sortino(returns, periods_per_year),
        "max_drawdown": max_drawdown(equity),
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "wins": wins,
        "losses": losses,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "exposure": exposure,
    }
