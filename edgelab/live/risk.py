"""Position sizing + account-level prop-firm gate (shared across all three bricks).

Sizing: 1R = ``risk_per_trade`` x ``initial_balance`` (fixed-fractional on the INITIAL
balance -> NO compounding, matching the prop model and the Monte-Carlo in
edgelab/reports/monte_carlo_static.py). Lots = risk_budget / loss-per-lot-at-stop,
snapped to the symbol's volume step.

Account gate: one shared manager sees the whole account. It enforces the static-DD
prop rules (daily-loss lock, total-drawdown halt) BEFORE any brick is allowed to enter,
so three decorrelated bricks on one account can never collectively breach a limit
unnoticed. Reuses PropFirmRules from the backtest.
"""
from __future__ import annotations

import logging
import math

import pandas as pd

from edgelab.risk.propfirm import PropFirmRules
from edgelab.live.broker import SymbolSpec

logger = logging.getLogger("edgelab.live.risk")


class LiveRiskManager:
    def __init__(self, rules: PropFirmRules, risk_per_trade: float):
        self.rules = rules
        self.risk_per_trade = float(risk_per_trade)
        # ⚠️ DEUX BASES DISTINCTES, ET LES CONFONDRE DESARME LE GARDE-FOU.
        #   * `initial_balance` est la base de SIZING. `runner._sync_account_size` la
        #     recale sur le solde REEL du compte a chaque demarrage et a chaque
        #     reconnexion MT5 — c'est voulu : 1R doit valoir 1 % du compte connecte, pas
        #     1 % d'un nominal de config qui pourrait etre 10x trop grand.
        #   * `floor_basis` est la base des PLANCHERS PROP : le depart du challenge, pose
        #     une seule fois (voir `set_floor_basis` / `runner._challenge_anchor`).
        # Les planchers se calculaient sur `initial_balance`, donc ILS SUIVAIENT LE SOLDE :
        # apres une reconnexion en plein drawdown, le plancher -10 % repartait de plus bas
        # et le compte pouvait descendre indefiniment sans jamais declencher le halt.
        # Trouve le 2026-08-12 en remontant la cause du "%" faux du rapport quotidien.
        self.initial_balance = float(rules.initial_balance)
        self.floor_basis = float(rules.initial_balance)
        self._day = None
        self.day_start_equity = self.initial_balance
        self.peak_equity = self.initial_balance
        self.day_locked = False
        self.failed = False
        self.fail_reason = ""
        self._last_good = None   # last plausible equity, to detect feed glitches
        self._dd_hits = 0        # consecutive valid readings below the DD floor

    def set_floor_basis(self, value: float) -> None:
        """Pose la reference FIXE des planchers prop (le solde de depart du challenge).

        A appeler une fois, au demarrage, avec l'ancre du compte. Jamais depuis la boucle :
        un plancher qui se recale n'est plus un plancher. `peak_equity` n'est aligne que
        tant qu'aucune lecture live n'est encore arrivee — au-dela, seul `on_equity` le
        fait monter, jamais redescendre.
        """
        v = float(value or 0.0)
        if v <= 0:
            logger.warning("base de plancher invalide (%s) — on garde %.2f", value, self.floor_basis)
            return
        self.floor_basis = v
        if self._last_good is None:
            self.peak_equity = v
        logger.warning("planchers prop bases sur %.2f (FIXE) | DD total -%.0f%% -> %.2f | "
                       "perte journaliere -%.0f%% -> %.2f/jour",
                       v, self.rules.max_total_drawdown_pct * 100,
                       v - self.rules.max_total_drawdown_pct * v,
                       self.rules.max_daily_loss_pct * 100, self.rules.max_daily_loss_pct * v)

    def _valid_equity(self, equity: float) -> bool:
        """Reject glitched MT5 feeds. A dropped trade-server link returns equity 0/None;
        1%-risk trades cannot move the account >10% in one 20-second tick, so a huge
        single-tick drop is never real. Never fail the account on a non-sensical reading.

        Le seuil de plausibilite est adosse a `floor_basis` (fixe) et non a la base de
        sizing : un seuil qui suit le solde se laisse entrainer vers le bas avec lui."""
        if equity is None or not math.isfinite(equity) or equity <= 0.5 * self.floor_basis:
            logger.warning("ignoring implausible equity reading (%s) — feed glitch; state unchanged", equity)
            return False
        if self._last_good is not None and equity < self._last_good * 0.90:
            logger.warning("ignoring equity jump %.2f -> %.2f in one tick — feed glitch; state unchanged",
                           self._last_good, equity)
            return False
        return True

    # ---- account-state bookkeeping ---------------------------------------
    def on_equity(self, equity: float, now_utc: pd.Timestamp) -> None:
        """Roll the trading day and re-evaluate the hard limits (never un-locks/un-fails).
        Glitched readings are ignored; a real breach must persist to fail the account."""
        if not self._valid_equity(equity):
            return
        self._last_good = equity
        day = pd.Timestamp(now_utc).date()
        if day != self._day:
            self._day = day
            self.day_start_equity = equity
            self.day_locked = False
        self.peak_equity = max(self.peak_equity, equity)

        # REFERENCE DES PLANCHERS = `floor_basis` (le depart du challenge), jamais la base
        # de sizing : celle-ci suit le solde du compte, donc les planchers auraient suivi.
        ref = self.peak_equity if self.rules.drawdown_basis == "peak" else self.floor_basis
        dd_floor = ref - self.rules.max_total_drawdown_pct * self.floor_basis
        daily_floor = self.day_start_equity - self.rules.max_daily_loss_pct * self.floor_basis

        # DD breach must confirm on 2 consecutive valid readings before failing (anti-glitch)
        if equity <= dd_floor:
            self._dd_hits += 1
            if self._dd_hits >= 2 and not self.failed:
                self.failed = True
                self.fail_reason = f"total DD breached (equity {equity:.2f} <= floor {dd_floor:.2f})"
                logger.error("PROP FAILED: %s", self.fail_reason)
        else:
            self._dd_hits = 0
        if equity <= daily_floor and not self.day_locked:
            self.day_locked = True
            logger.warning("DAILY-LOSS lock hit (equity %.2f <= floor %.2f) -> no new entries today",
                           equity, daily_floor)

    def can_enter(self) -> tuple[bool, str]:
        if self.failed:
            return False, f"account FAILED ({self.fail_reason})"
        if self.day_locked:
            return False, "daily-loss lock active"
        return True, "ok"

    # ---- sizing -----------------------------------------------------------
    def risk_budget(self) -> float:
        """Cash value of 1R = risk_per_trade * initial balance (fixed-fractional)."""
        return self.risk_per_trade * self.initial_balance

    def lots_for(self, sl_dist_price: float, spec: SymbolSpec) -> float:
        """Lots so that a full stop (= sl_dist_price) loses exactly 1R of the initial balance."""
        risk_budget = self.risk_per_trade * self.initial_balance
        if sl_dist_price <= 0 or spec.tick_size <= 0:
            return 0.0
        loss_per_lot = (sl_dist_price / spec.tick_size) * spec.tick_value
        if loss_per_lot <= 0:
            return 0.0
        raw = risk_budget / loss_per_lot
        # snap down to volume step, respect the minimum
        step = spec.volume_step or 0.01
        lots = math.floor(raw / step) * step
        if lots < spec.volume_min:
            # too small to size at this risk -> fall back to the broker minimum (log it)
            logger.warning("computed lots %.4f < min %.4f; using min (risk will exceed 1R)",
                           raw, spec.volume_min)
            return spec.volume_min
        return round(lots, 2)
