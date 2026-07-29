"""Unit tests for the per-trade SL/TP/time-exit resolution."""
from __future__ import annotations

import pandas as pd
import pytest

from edgelab.risk.trade_rules import ExitReason, TradeRules, atr


def make_rules(**kw):
    base = dict(stop_loss_atr=2.0, take_profit_atr=3.0, take_profit_rr=None,
                time_exit_bars=10, pessimistic=True)
    base.update(kw)
    return TradeRules(**base)


def test_barrier_prices_long_and_short():
    rules = make_rules()
    # long: stop below, take above
    stop, take = rules.barrier_prices(entry_price=100.0, direction=1, entry_atr=1.0)
    assert stop == pytest.approx(98.0)   # 100 - 2*1
    assert take == pytest.approx(103.0)  # 100 + 3*1
    # short: mirrored
    stop, take = rules.barrier_prices(entry_price=100.0, direction=-1, entry_atr=1.0)
    assert stop == pytest.approx(102.0)
    assert take == pytest.approx(97.0)


def test_take_profit_rr_overrides_atr():
    rules = make_rules(take_profit_atr=99.0, take_profit_rr=1.5)
    stop, take = rules.barrier_prices(100.0, 1, 1.0)
    # tp distance = stop_loss_atr(2) * rr(1.5) * atr(1) = 3.0
    assert take == pytest.approx(103.0)


def test_stop_hit_long():
    rules = make_rules()
    dec = rules.resolve_bar(direction=1, stop_price=98.0, take_price=103.0,
                            bar_high=101.0, bar_low=97.5, bars_held=1, bar_close=100.0)
    assert dec.exited and dec.reason == ExitReason.STOP_LOSS
    assert dec.price == pytest.approx(98.0)


def test_take_hit_long():
    rules = make_rules()
    dec = rules.resolve_bar(1, 98.0, 103.0, bar_high=103.5, bar_low=99.0,
                            bars_held=1, bar_close=102.0)
    assert dec.exited and dec.reason == ExitReason.TAKE_PROFIT
    assert dec.price == pytest.approx(103.0)


def test_pessimistic_tie_prefers_stop():
    """Bar spans both barriers -> pessimistic resolution takes the STOP."""
    rules = make_rules(pessimistic=True)
    dec = rules.resolve_bar(1, 98.0, 103.0, bar_high=104.0, bar_low=97.0,
                            bars_held=1, bar_close=100.0)
    assert dec.reason == ExitReason.STOP_LOSS


def test_optimistic_tie_prefers_take():
    rules = make_rules(pessimistic=False)
    dec = rules.resolve_bar(1, 98.0, 103.0, bar_high=104.0, bar_low=97.0,
                            bars_held=1, bar_close=100.0)
    assert dec.reason == ExitReason.TAKE_PROFIT


def test_time_exit_when_no_barrier_touched():
    rules = make_rules(time_exit_bars=5)
    # no barrier touched, held reaches the horizon -> exit at close
    dec = rules.resolve_bar(1, 90.0, 110.0, bar_high=101.0, bar_low=99.0,
                            bars_held=5, bar_close=100.5)
    assert dec.exited and dec.reason == ExitReason.TIME_EXIT
    assert dec.price == pytest.approx(100.5)


def test_no_exit_before_horizon():
    rules = make_rules(time_exit_bars=5)
    dec = rules.resolve_bar(1, 90.0, 110.0, bar_high=101.0, bar_low=99.0,
                            bars_held=3, bar_close=100.5)
    assert not dec.exited and dec.reason == ExitReason.NONE


def test_short_stop_and_take():
    rules = make_rules()
    # short stop is ABOVE entry: high crossing stop triggers SL
    dec = rules.resolve_bar(-1, stop_price=102.0, take_price=97.0,
                            bar_high=102.5, bar_low=99.0, bars_held=1, bar_close=100.0)
    assert dec.reason == ExitReason.STOP_LOSS
    # short take is BELOW entry
    dec = rules.resolve_bar(-1, 102.0, 97.0, bar_high=100.5, bar_low=96.5,
                            bars_held=1, bar_close=98.0)
    assert dec.reason == ExitReason.TAKE_PROFIT


def test_invalid_direction_and_atr():
    rules = make_rules()
    with pytest.raises(ValueError):
        rules.barrier_prices(100.0, 0, 1.0)
    with pytest.raises(ValueError):
        rules.barrier_prices(100.0, 1, 0.0)


def test_atr_is_positive_and_causal():
    idx = pd.date_range("2020-01-01", periods=30, freq="D", tz="UTC")
    df = pd.DataFrame({
        "high": range(2, 32), "low": range(0, 30),
        "close": range(1, 31), "open": range(1, 31), "volume": 1,
    }, index=idx).astype(float)
    a = atr(df, 14)
    assert a.dropna().gt(0).all()
    # first (window-1) values are NaN (needs full window) -> causal warmup
    assert a.iloc[:13].isna().all()
