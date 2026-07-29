"""Unit tests for prop-firm rules, drawdown accounting and verdicts."""
from __future__ import annotations

import pandas as pd
import pytest

from edgelab.backtest.metrics import max_drawdown
from edgelab.risk.propfirm import (
    PropFirmRules, PropFirmState, PropVerdict, evaluate_equity_curve,
)


def make_rules(**kw):
    base = dict(initial_balance=100_000.0, max_daily_loss_pct=0.05,
                max_total_drawdown_pct=0.10, profit_target_pct=0.10,
                min_trading_days=5, consistency_max_day_share=None,
                drawdown_basis="initial")
    base.update(kw)
    return PropFirmRules(**base)


# ---------------- drawdown math ----------------
def test_max_drawdown_basic():
    eq = pd.Series([100, 120, 90, 110, 80, 130.0])
    # peak 120 -> trough 80 => (120-80)/120 = 0.3333
    assert max_drawdown(eq) == pytest.approx(1 - 80 / 120, abs=1e-9)


def test_max_drawdown_monotonic_up_is_zero():
    eq = pd.Series([100, 101, 102, 103.0])
    assert max_drawdown(eq) == pytest.approx(0.0)


# ---------------- daily loss lock ----------------
def test_daily_loss_locks_trading_not_failed():
    st = PropFirmState(make_rules())
    st.start_day("d1")
    st.update_equity(96_000.0, "d1")   # -4% intraday, within 5%
    assert st.can_trade and not st.failed
    st.update_equity(94_900.0, "d1")   # -5.1% -> locked
    assert st.day_locked and not st.failed and not st.can_trade
    # new day resets the lock
    st.start_day("d2")
    assert st.can_trade


# ---------------- total drawdown fails ----------------
def test_total_drawdown_fails_account_static_basis():
    st = PropFirmState(make_rules(drawdown_basis="initial"))
    st.start_day("d1")
    st.update_equity(89_999.0, "d1")   # below 90k floor -> fail
    assert st.failed
    verdict, _ = st.verdict()
    assert verdict == PropVerdict.FAILED


def test_trailing_drawdown_basis_uses_peak():
    st = PropFirmState(make_rules(drawdown_basis="peak"))
    st.start_day("d1")
    st.update_equity(120_000.0, "d1")  # peak now 120k -> floor 110k
    st.start_day("d2")
    st.update_equity(109_000.0, "d2")  # below trailing floor -> fail
    assert st.failed


# ---------------- profit target & min days ----------------
def test_profit_target_needs_min_days():
    rules = make_rules(min_trading_days=5)
    st = PropFirmState(rules)
    for i in range(3):                 # only 3 days, hit target early
        st.start_day(f"d{i}")
        st.update_equity(111_000.0, f"d{i}")
    v, _ = st.verdict()
    assert v == PropVerdict.IN_PROGRESS   # target hit but < min days
    for i in range(3, 6):
        st.start_day(f"d{i}")
        st.update_equity(111_000.0, f"d{i}")
    v, _ = st.verdict()
    assert v == PropVerdict.PASSED


# ---------------- consistency rule ----------------
def test_consistency_rule_flags_lumpy_profit():
    rules = make_rules(min_trading_days=1, consistency_max_day_share=0.40)
    # one huge day makes up >40% of total profit -> FAIL
    eq = pd.Series(
        [100_000, 108_000, 108_500, 109_000, 109_500, 110_000.0],
        index=pd.date_range("2021-01-01", periods=6, freq="D"),
    )
    out = evaluate_equity_curve(rules, eq)
    assert out["verdict"] == "FAILED"
    assert "consistency" in out["reason"].lower()


def test_evaluate_curve_passes_smooth_growth():
    rules = make_rules(min_trading_days=3, consistency_max_day_share=0.90)
    eq = pd.Series(
        [100_000, 103_000, 106_000, 109_000, 111_000.0],
        index=pd.date_range("2021-01-01", periods=5, freq="D"),
    )
    out = evaluate_equity_curve(rules, eq)
    assert out["verdict"] == "PASSED"
    assert out["total_return"] == pytest.approx(0.11, abs=1e-9)
