"""Orchestration: run edges over the universe, build the decorrelated portfolio.

An *edge* is evaluated across the whole prop universe: each symbol is a small
sub-account risking a fixed fraction, and the edge's daily return stream is the
equal-weight average across symbols. That single stream per edge is what feeds the
correlation / decorrelation step (the user's "daily returns of each edge").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from edgelab.backtest.engine import BacktestEngine
from edgelab.backtest.metrics import compute_metrics
from edgelab.backtest.walkforward import walk_forward_report
from edgelab.config import Config
from edgelab.data.base import DataProvider
from edgelab.edges.base import BaseEdge
from edgelab.risk.propfirm import PropFirmRules, evaluate_equity_curve

logger = logging.getLogger("edgelab.runner")


@dataclass
class EdgeRun:
    edge_name: str
    family: str
    returns: pd.Series               # aggregated daily returns (equal-weight symbols)
    equity: pd.Series                # aggregated account equity
    metrics: dict
    prop: dict                       # prop verdict on the aggregated equity
    per_symbol_metrics: dict = field(default_factory=dict)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    walk_forward: dict = field(default_factory=dict)


def run_edge_over_universe(cfg: Config, provider: DataProvider, engine: BacktestEngine,
                           edge: BaseEdge, symbols: list[str]) -> EdgeRun:
    tf = cfg.data["timeframe"]
    start, end = cfg.data.get("start"), cfg.data.get("end")
    ppy = int(cfg["trading_days_per_year"])
    init_bal = float(cfg.propfirm["initial_balance"])

    per_symbol_returns: dict[str, pd.Series] = {}
    per_symbol_metrics: dict[str, dict] = {}
    all_trades: list[pd.DataFrame] = []

    for sym in symbols:
        try:
            data = provider.get_bars(sym, tf, start, end)
        except FileNotFoundError:
            logger.warning("  %s: no data for %s, skipping", edge.name, sym)
            continue
        if len(data) < 60:
            logger.warning("  %s: %s too short (%d bars), skipping", edge.name, sym, len(data))
            continue
        signals = edge.generate_signals(data)
        res = engine.run(data, signals, sym, edge.name)
        per_symbol_returns[sym] = res.returns
        per_symbol_metrics[sym] = compute_metrics(res.equity, res.returns, res.trades, ppy)
        if not res.trades.empty:
            all_trades.append(res.trades)

    if not per_symbol_returns:
        empty = pd.Series(dtype=float)
        return EdgeRun(edge.name, edge.family, empty, empty, {}, {})

    # Equal-weight the symbol sub-accounts into one edge return stream.
    ret_frame = pd.DataFrame(per_symbol_returns).sort_index().fillna(0.0)
    agg_returns = ret_frame.mean(axis=1)
    agg_returns.name = "returns"
    agg_equity = (1.0 + agg_returns).cumprod() * init_bal
    agg_equity.name = "equity"

    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    metrics = compute_metrics(agg_equity, agg_returns, trades_df, ppy)
    prop = evaluate_equity_curve(PropFirmRules.from_config(cfg.propfirm), agg_equity)

    return EdgeRun(
        edge_name=edge.name, family=edge.family,
        returns=agg_returns, equity=agg_equity, metrics=metrics, prop=prop,
        per_symbol_metrics=per_symbol_metrics, trades=trades_df,
    )
