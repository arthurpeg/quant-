"""Walk-forward / out-of-sample splitting.

The example edges are rule-based (no fit step), so walk-forward here is used to
report **stability across time** and an honest IS-vs-OOS comparison, with an
``embargo`` gap so a trade opened in-sample cannot leak its resolution into OOS.
When edges gain fittable parameters, the same folds drive parameter selection.
"""
from __future__ import annotations

import pandas as pd

from edgelab.backtest.metrics import compute_metrics


def walk_forward_folds(index: pd.DatetimeIndex, n_folds: int, scheme: str = "expanding",
                       oos_fraction: float = 0.25, embargo_bars: int = 10):
    """Yield ``(fold_id, is_slice, oos_slice)`` integer-position slices.

    ``expanding``: IS grows from the start each fold. ``rolling``: fixed-width IS
    window that slides. The last ``oos_fraction`` of each fold window is OOS, with
    ``embargo_bars`` dropped between IS and OOS.
    """
    n = len(index)
    fold_size = n // n_folds
    for k in range(1, n_folds + 1):
        window_end = fold_size * k if k < n_folds else n
        window_start = 0 if scheme == "expanding" else max(0, window_end - fold_size)
        window_len = window_end - window_start
        oos_len = int(window_len * oos_fraction)
        if oos_len <= 0:
            continue
        oos_start = window_end - oos_len
        is_end = max(window_start, oos_start - embargo_bars)
        is_slice = slice(window_start, is_end)
        oos_slice = slice(oos_start, window_end)
        yield k, is_slice, oos_slice


def walk_forward_report(engine, data: pd.DataFrame, signals: pd.Series, symbol: str,
                        edge_name: str, cfg) -> dict:
    """Run the engine per fold and summarise IS vs OOS metrics.

    Returns a dict with per-fold OOS metrics and the pooled OOS metric bundle.
    """
    wf = cfg.backtest["walk_forward"]
    ppy = int(cfg["trading_days_per_year"])
    folds_meta = []
    pooled_oos_returns = []
    pooled_oos_equity_parts = []

    for k, is_sl, oos_sl in walk_forward_folds(
        data.index, int(wf["n_folds"]), str(wf["scheme"]),
        float(wf["oos_fraction"]), int(wf["embargo_bars"])
    ):
        oos_data = data.iloc[oos_sl]
        oos_sig = signals.iloc[oos_sl]
        if len(oos_data) < 5:
            continue
        res = engine.run(oos_data, oos_sig, symbol, edge_name)
        m = compute_metrics(res.equity, res.returns, res.trades, ppy)
        folds_meta.append({
            "fold": k,
            "oos_start": str(oos_data.index[0].date()),
            "oos_end": str(oos_data.index[-1].date()),
            "sharpe": m["sharpe"],
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "n_trades": m["n_trades"],
        })
        pooled_oos_returns.append(res.returns)

    pooled = pd.concat(pooled_oos_returns) if pooled_oos_returns else pd.Series(dtype=float)
    pooled = pooled[~pooled.index.duplicated(keep="first")].sort_index()
    pooled_equity = (1.0 + pooled).cumprod()
    pooled_metrics = compute_metrics(pooled_equity, pooled, pd.DataFrame(), ppy) \
        if not pooled.empty else {}

    return {"folds": folds_meta, "pooled_oos": pooled_metrics}
