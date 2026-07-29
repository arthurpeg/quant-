"""Prop-firm account rules — hard constraints that gate/stop trading.

The engine feeds daily equity into :class:`PropFirmState`; the state tracks the
running peak, the day's starting equity, trading-day count, and per-day P&L, and
exposes:
  * ``day_locked``  -> daily-loss limit hit -> no more trades TODAY
  * ``failed``      -> total drawdown breached -> account FAILED (stop backtest)
  * ``verdict()``   -> PASSED / FAILED / IN_PROGRESS with the reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class PropVerdict(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass(frozen=True)
class PropFirmRules:
    initial_balance: float
    max_daily_loss_pct: float
    max_total_drawdown_pct: float
    profit_target_pct: float
    min_trading_days: int
    consistency_max_day_share: float | None = None
    drawdown_basis: str = "initial"  # "initial" (static floor) or "peak" (trailing)

    @classmethod
    def from_config(cls, pf: dict) -> "PropFirmRules":
        return cls(
            initial_balance=float(pf["initial_balance"]),
            max_daily_loss_pct=float(pf["max_daily_loss_pct"]),
            max_total_drawdown_pct=float(pf["max_total_drawdown_pct"]),
            profit_target_pct=float(pf["profit_target_pct"]),
            min_trading_days=int(pf["min_trading_days"]),
            consistency_max_day_share=(
                None if pf.get("consistency_max_day_share") is None
                else float(pf["consistency_max_day_share"])
            ),
            drawdown_basis=str(pf.get("drawdown_basis", "initial")),
        )


@dataclass
class PropFirmState:
    """Mutable account state, advanced day by day."""

    rules: PropFirmRules
    equity: float = field(init=False)
    peak_equity: float = field(init=False)
    day_start_equity: float = field(init=False)
    current_day: object = field(default=None, init=False)
    trading_days: int = field(default=0, init=False)
    failed: bool = field(default=False, init=False)
    fail_reason: str = field(default="", init=False)
    day_locked: bool = field(default=False, init=False)
    daily_pnl: dict = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.equity = self.rules.initial_balance
        self.peak_equity = self.rules.initial_balance
        self.day_start_equity = self.rules.initial_balance

    # -- daily-loss floor for the current day --------------------------------
    @property
    def daily_loss_floor(self) -> float:
        return self.day_start_equity - self.rules.max_daily_loss_pct * self.rules.initial_balance

    # -- absolute drawdown floor ---------------------------------------------
    @property
    def drawdown_floor(self) -> float:
        basis = self.peak_equity if self.rules.drawdown_basis == "peak" else self.rules.initial_balance
        return basis - self.rules.max_total_drawdown_pct * self.rules.initial_balance

    def start_day(self, day) -> None:
        """Roll into a new trading day: reset the daily lock and record the open."""
        self.current_day = day
        self.day_start_equity = self.equity
        self.day_locked = False
        self.trading_days += 1

    def update_equity(self, equity: float, day) -> None:
        """Mark equity (intraday or end-of-bar) and re-evaluate hard limits.

        Call ``start_day`` first when the calendar day changes. This method never
        *unlocks* a day and never *un-fails* an account.
        """
        self.equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity

        # Total drawdown = terminal failure.
        if not self.failed and equity <= self.drawdown_floor:
            self.failed = True
            self.fail_reason = (
                f"max total drawdown breached (equity {equity:.2f} <= "
                f"floor {self.drawdown_floor:.2f}, basis={self.rules.drawdown_basis})"
            )

        # Daily loss = lock trading for the rest of the day (not terminal).
        if equity <= self.daily_loss_floor:
            self.day_locked = True

        # Record running daily P&L for the consistency rule.
        self.daily_pnl[day] = equity - self.day_start_equity

    @property
    def can_trade(self) -> bool:
        return not self.failed and not self.day_locked

    @property
    def total_return(self) -> float:
        return self.equity / self.rules.initial_balance - 1.0

    @property
    def hit_profit_target(self) -> bool:
        return self.total_return >= self.rules.profit_target_pct

    def consistency_ok(self) -> tuple[bool, str]:
        """Optional rule: no single day may exceed X% of total profit."""
        if self.rules.consistency_max_day_share is None:
            return True, "consistency rule disabled"
        total_profit = self.equity - self.rules.initial_balance
        if total_profit <= 0:
            return True, "no profit yet; consistency n/a"
        best_day = max(self.daily_pnl.values(), default=0.0)
        share = best_day / total_profit
        ok = share <= self.rules.consistency_max_day_share
        return ok, (
            f"best-day share {share:.1%} vs cap {self.rules.consistency_max_day_share:.0%}"
        )

    def verdict(self) -> tuple[PropVerdict, str]:
        """Final assessment against ALL rules."""
        if self.failed:
            return PropVerdict.FAILED, self.fail_reason
        cons_ok, cons_msg = self.consistency_ok()
        if not cons_ok:
            return PropVerdict.FAILED, f"consistency rule violated ({cons_msg})"
        if self.trading_days < self.rules.min_trading_days:
            return PropVerdict.IN_PROGRESS, (
                f"only {self.trading_days} trading days (< {self.rules.min_trading_days} min)"
            )
        if self.hit_profit_target:
            return PropVerdict.PASSED, (
                f"profit target reached: {self.total_return:.2%} >= "
                f"{self.rules.profit_target_pct:.0%}"
            )
        return PropVerdict.IN_PROGRESS, (
            f"target not yet reached: {self.total_return:.2%} < "
            f"{self.rules.profit_target_pct:.0%}"
        )


def evaluate_equity_curve(rules: PropFirmRules, equity: pd.Series) -> dict:
    """Replay a daily equity curve through the rules and return a summary dict.

    ``equity`` is a daily-indexed equity series (account value at each day's close).
    This is the portfolio-level checker used by reports.
    """
    state = PropFirmState(rules)
    for ts, eq in equity.items():
        day = pd.Timestamp(ts).date()
        if day != state.current_day:
            state.start_day(day)
        state.update_equity(float(eq), day)
        if state.failed:
            break
    verdict, reason = state.verdict()
    return {
        "verdict": verdict.value,
        "reason": reason,
        "final_equity": state.equity,
        "total_return": state.total_return,
        "peak_equity": state.peak_equity,
        "trading_days": state.trading_days,
        "failed": state.failed,
    }
