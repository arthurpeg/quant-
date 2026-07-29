"""Per-trade risk rules: stop-loss, take-profit and time-exit.

EVERY trade carries all three. Given an open position and the next bar's OHLC,
:meth:`TradeRules.resolve_bar` decides whether the bar closes the trade and at
what price, applying the *first-touched* barrier. When a single bar's range spans
both SL and TP we cannot know the intrabar path, so (if ``pessimistic``) we assume
the STOP filled first — never the optimistic assumption.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class ExitReason(str, Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TIME_EXIT = "time_exit"
    NONE = "none"


@dataclass(frozen=True)
class ExitDecision:
    """Outcome of testing one bar against an open position."""

    exited: bool
    price: float | None
    reason: ExitReason


def atr(df: pd.DataFrame, window: int) -> pd.Series:
    """Wilder-style Average True Range. Causal (no lookahead)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


@dataclass(frozen=True)
class TradeRules:
    """Barrier configuration + resolution logic. Barriers are ATR multiples.

    Set ``stop_loss_atr``/``take_profit_atr`` for ATR barriers. If ``take_profit_rr``
    is given it overrides the TP as ``stop_loss_atr * rr`` (a fixed reward:risk).
    """

    stop_loss_atr: float
    take_profit_atr: float | None
    take_profit_rr: float | None
    time_exit_bars: int
    pessimistic: bool = True

    def barrier_prices(
        self, entry_price: float, direction: int, entry_atr: float
    ) -> tuple[float, float]:
        """Return ``(stop_price, take_profit_price)`` for a position.

        ``direction`` is +1 (long) or -1 (short). Distances are frozen at entry
        from the ATR at that time, so the barriers are static for the trade's life.
        """
        if direction not in (1, -1):
            raise ValueError("direction must be +1 or -1")
        if not np.isfinite(entry_atr) or entry_atr <= 0:
            raise ValueError("entry_atr must be positive and finite")

        sl_dist = self.stop_loss_atr * entry_atr
        if self.take_profit_rr is not None:
            tp_dist = self.stop_loss_atr * self.take_profit_rr * entry_atr
        elif self.take_profit_atr is not None:
            tp_dist = self.take_profit_atr * entry_atr
        else:
            raise ValueError("either take_profit_atr or take_profit_rr must be set")

        stop = entry_price - direction * sl_dist
        take = entry_price + direction * tp_dist
        return stop, take

    def resolve_bar(
        self,
        direction: int,
        stop_price: float,
        take_price: float,
        bar_high: float,
        bar_low: float,
        bars_held: int,
        bar_close: float,
    ) -> ExitDecision:
        """Test one bar's range against the barriers. Returns an :class:`ExitDecision`.

        ``bars_held`` is the number of bars the position has been open *including*
        this one (so time-exit triggers when it reaches ``time_exit_bars``).
        """
        hit_stop = bar_low <= stop_price if direction == 1 else bar_high >= stop_price
        hit_take = bar_high >= take_price if direction == 1 else bar_low <= take_price

        if hit_stop and hit_take:
            # Range spans both barriers; path unknown. Pessimistic -> stop wins.
            if self.pessimistic:
                return ExitDecision(True, stop_price, ExitReason.STOP_LOSS)
            return ExitDecision(True, take_price, ExitReason.TAKE_PROFIT)
        if hit_stop:
            return ExitDecision(True, stop_price, ExitReason.STOP_LOSS)
        if hit_take:
            return ExitDecision(True, take_price, ExitReason.TAKE_PROFIT)
        if bars_held >= self.time_exit_bars:
            # Neither barrier touched within the horizon -> forced exit at close.
            return ExitDecision(True, bar_close, ExitReason.TIME_EXIT)
        return ExitDecision(False, None, ExitReason.NONE)

    @classmethod
    def from_config(cls, risk_cfg: dict) -> "TradeRules":
        return cls(
            stop_loss_atr=float(risk_cfg["stop_loss_atr"]),
            take_profit_atr=(
                None if risk_cfg.get("take_profit_atr") is None
                else float(risk_cfg["take_profit_atr"])
            ),
            take_profit_rr=(
                None if risk_cfg.get("take_profit_rr") is None
                else float(risk_cfg["take_profit_rr"])
            ),
            time_exit_bars=int(risk_cfg["time_exit_bars"]),
            pessimistic=bool(risk_cfg.get("pessimistic_touch", True)),
        )
