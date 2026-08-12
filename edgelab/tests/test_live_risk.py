"""Les planchers prop du runner live ne doivent PAS suivre le solde du compte.

Regression du 2026-08-12. `LiveRiskManager` n'avait qu'une base, `initial_balance`, et
`runner._sync_account_size` la recalait sur le solde reel a chaque demarrage ET a chaque
reconnexion MT5. C'est juste pour le SIZING (1R = 1 % du compte connecte) et faux pour les
PLANCHERS : `dd_floor = initial - 10 % x initial` valait toujours 90 % du solde courant,
donc un drawdown etale sur plusieurs reconnexions ne le franchissait jamais.
"""
from __future__ import annotations

import pandas as pd

from edgelab.risk.propfirm import PropFirmRules
from edgelab.live.risk import LiveRiskManager
from edgelab.live import runner


class FakeBroker:
    """Juste ce que `_sync_account_size` / `_arm_floors` lisent : un solde."""

    def __init__(self, balance: float) -> None:
        self.bal = float(balance)

    def balance(self) -> float:
        return self.bal


RULES = PropFirmRules(initial_balance=100_000.0, max_daily_loss_pct=0.05,
                      max_total_drawdown_pct=0.10, profit_target_pct=0.15,
                      min_trading_days=5, drawdown_basis="initial")
CFG = {"size_from_account": True, "propfirm": {"challenge_start_balance": 60_000.0}}
T0 = pd.Timestamp("2026-08-13 12:00", tz="UTC")


def _armed() -> LiveRiskManager:
    runner._ANCHOR = None                      # l'ancre est memoisee par processus
    risk = LiveRiskManager(RULES, 0.01)
    runner._arm_floors(FakeBroker(60_000.0), risk, CFG)
    runner._sync_account_size(FakeBroker(60_000.0), risk, CFG)
    return risk


def test_floor_basis_is_the_anchor_not_the_config_nominal():
    risk = _armed()
    assert risk.floor_basis == 60_000.0        # planchers : le depart du challenge
    assert risk.initial_balance == 60_000.0    # sizing : le solde reel
    assert risk.risk_budget() == 600.0


def test_dd_floor_does_not_follow_the_balance_through_reconnects():
    """Un drawdown avec une reconnexion a CHAQUE passe doit quand meme faire failer."""
    risk = _armed()
    for i, eq in enumerate([59_000, 57_000, 55_500, 54_500, 53_900, 53_800]):
        risk.on_equity(float(eq), T0 + pd.Timedelta(minutes=i))
        runner._sync_account_size(FakeBroker(float(eq)), risk, CFG)   # la reconnexion
        assert risk.floor_basis == 60_000.0, "le plancher a suivi le solde"
    # plancher = 60000 - 10 % x 60000 = 54000, franchi (deux lectures consecutives)
    assert risk.failed
    assert "54000.00" in risk.fail_reason
    # avec l'ancien calcul, le plancher valait 0.9 x 53800 = 48420 a cet instant :
    assert 0.9 * 53_800 < 54_000


def test_sizing_base_still_tracks_the_account():
    """Le correctif ne doit pas figer le sizing : 1R reste 1 % du compte CONNECTE."""
    risk = _armed()
    runner._sync_account_size(FakeBroker(50_000.0), risk, CFG)
    assert risk.initial_balance == 50_000.0
    assert risk.risk_budget() == 500.0
    assert risk.floor_basis == 60_000.0


def test_daily_lock_survives_a_reconnect():
    """`day_start_equity` ne doit plus etre efface en cours de journee."""
    risk = _armed()
    risk.on_equity(60_000.0, T0)
    for eq in (58_500, 57_500, 56_900):        # -3100 : au-dela du -5 % (3000) du jour
        risk.on_equity(float(eq), T0 + pd.Timedelta(minutes=1))
        runner._sync_account_size(FakeBroker(float(eq)), risk, CFG)
        assert risk.day_start_equity == 60_000.0
    assert risk.day_locked
    assert risk.can_enter()[0] is False


def test_new_day_rolls_the_daily_reference():
    risk = _armed()
    risk.on_equity(60_000.0, T0)
    risk.on_equity(58_000.0, T0 + pd.Timedelta(minutes=1))
    risk.on_equity(58_000.0, T0 + pd.Timedelta(days=1))
    assert risk.day_start_equity == 58_000.0   # nouveau jour = nouvelle reference
    assert risk.day_locked is False
