"""Smoke + no-lookahead tests for the backtest engine on synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from edgelab.backtest.engine import BacktestEngine
from edgelab.config import load_config


def _synthetic(n=200, seed=0):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0003, 0.01, n)
    close = 100 * np.exp(np.cumsum(ret))
    idx = pd.date_range("2019-01-01", periods=n, freq="D", tz="UTC")
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": 1.0}, index=idx)


def test_engine_runs_and_produces_equity():
    cfg = load_config()
    eng = BacktestEngine(cfg)
    data = _synthetic()
    sig = pd.Series(1, index=data.index)  # always-long
    res = eng.run(data, sig, "EURUSD", "always_long")
    assert len(res.equity) == len(data)
    assert res.equity.iloc[0] == cfg.propfirm["initial_balance"]
    assert res.prop_verdict in {"PASSED", "FAILED", "IN_PROGRESS"}


def test_no_lookahead_zero_signal_no_trades():
    cfg = load_config()
    eng = BacktestEngine(cfg)
    data = _synthetic()
    sig = pd.Series(0, index=data.index)  # never trade
    res = eng.run(data, sig, "EURUSD", "flat")
    assert res.trades.empty
    # flat account never moves from the initial balance
    assert np.allclose(res.equity.values, cfg.propfirm["initial_balance"])


def test_future_signal_cannot_affect_past():
    """A single signal on the LAST bar can never open a trade (no bar t+1)."""
    cfg = load_config()
    eng = BacktestEngine(cfg)
    data = _synthetic()
    sig = pd.Series(0, index=data.index)
    sig.iloc[-1] = 1  # signal on the very last bar -> executes at t+1 which doesn't exist
    res = eng.run(data, sig, "EURUSD", "late")
    assert res.trades.empty
