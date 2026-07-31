"""Event-driven, single-symbol backtest engine.

Design guarantees (all wiki-mandated):
  * **No lookahead.** The signal decided on bar ``t`` is executed at the OPEN of
    bar ``t + execution_lag_bars``. Barrier distances use the ATR known *before*
    the entry bar.
  * **Every trade carries SL + TP + time-exit.** Applied by :class:`TradeRules`
    with the first-touched barrier; ties resolved pessimistically (stop first).
  * **Honest costs.** Spread + slippage paid on entry and exit.
  * **Prop-firm aware.** Consults :class:`PropFirmState` before each entry and
    marks equity every bar; a total-drawdown breach stops the run.

One position per symbol at a time; while in a trade, new entry signals are ignored
until the position closes (barrier or time-exit). Position size risks a fixed
fraction of current equity to the stop distance.

``cadence`` controls WHEN those rules are evaluated:

* ``"literal"`` (default, unchanged behaviour) — the classic loop: manage the open
  position against bar ``i``, then consider an entry on that SAME bar. It can therefore
  close and re-open inside one bar, filling the new trade at bar ``i``'s OPEN — a price
  already in the past by the time the exit happened. Time-exit fires at the close of the
  ``time_exit_bars``-th bar.
* ``"live"`` — the cadence a once-per-bar driver can actually run (see
  ``edgelab/live/strategies.py``): at the bar rollover it either manages the position or
  opens one, never both, and the time-exit is decided at the rollover so it fills at the
  bar's OPEN one bar later. Barriers still resolve intrabar (the broker holds them).

Use ``"live"`` for anything that feeds the deployable book; ``"literal"`` reproduces
historical runs. See wiki/system.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from edgelab.backtest.costs import CostModel
from edgelab.risk.propfirm import PropFirmRules, PropFirmState, PropVerdict
from edgelab.risk.trade_rules import ExitDecision, ExitReason, TradeRules, atr

logger = logging.getLogger("edgelab.backtest.engine")


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    size: float
    reason: str
    bars_held: int
    pnl: float          # net of costs, cash
    cost: float         # total round-trip cost, cash
    ret: float          # net return on risked capital (pnl / risk budget)


@dataclass
class BacktestResult:
    symbol: str
    edge_name: str
    trades: pd.DataFrame
    equity: pd.Series           # daily marked-to-market account equity
    returns: pd.Series          # daily returns of the equity curve
    prop_verdict: str
    prop_reason: str
    meta: dict = field(default_factory=dict)


class BacktestEngine:
    def __init__(self, cfg, cost_model: CostModel | None = None,
                 cadence: str = "literal"):
        # "live_reentry" = live cadence PLUS an intraday re-entry at the price the barrier
        # just filled at. It is NOT what the deployed driver does (its `_acted_day` guard
        # blocks a second action the same day) — it measures what a driver change would
        # recover. Do not use it for the book; see wiki/system.md.
        if cadence not in ("literal", "live", "live_reentry"):
            raise ValueError(f"cadence must be 'literal', 'live' or 'live_reentry', got {cadence!r}")
        self.cadence = cadence
        self.cfg = cfg
        self.rules = TradeRules.from_config(cfg.risk)
        self.prop_rules = PropFirmRules.from_config(cfg.propfirm)
        self.costs = cost_model or CostModel.from_config(cfg)
        self.lag = int(cfg.backtest["execution_lag_bars"])
        self.allow_short = bool(cfg.backtest["allow_short"])
        self.atr_window = int(cfg.risk["atr_window"])
        self.risk_per_trade = float(cfg.risk["risk_per_trade"])
        self.initial_balance = float(cfg.propfirm["initial_balance"])

    def run(self, data: pd.DataFrame, signals: pd.Series, symbol: str,
            edge_name: str = "edge") -> BacktestResult:
        data = data.sort_index()
        signals = signals.reindex(data.index).fillna(0).astype(int)
        if not self.allow_short:
            signals = signals.clip(lower=0)

        atr_series = atr(data, self.atr_window)
        opens = data["open"].to_numpy(float)
        highs = data["high"].to_numpy(float)
        lows = data["low"].to_numpy(float)
        closes = data["close"].to_numpy(float)
        atr_arr = atr_series.to_numpy(float)
        sig_arr = signals.to_numpy(int)
        index = data.index
        n = len(data)

        prop = PropFirmState(self.prop_rules)
        equity = self.initial_balance
        equity_curve = np.empty(n, dtype=float)

        # Open-position state.
        in_pos = False
        direction = 0
        entry_price = 0.0
        reentry_price = 0.0
        entry_i = 0
        size = 0.0
        stop_price = 0.0
        take_price = 0.0
        risk_budget = 0.0

        trades: list[Trade] = []

        for i in range(n):
            day = index[i].date()
            prop.start_day(day)  # daily bars: each bar is a fresh day

            realized_equity = equity  # equity from closed trades so far

            # --- 1) manage an OPEN position against THIS bar -----------------
            closed_this_bar = False
            if in_pos:
                bars_held = i - entry_i + 1
                if self.cadence != "literal" and (i - entry_i) >= self.rules.time_exit_bars:
                    # A once-per-bar driver decides the time-exit at the ROLLOVER, before
                    # the bar trades -> it fills at this bar's OPEN, one bar later than the
                    # literal loop's close-of-bar exit.
                    dec = ExitDecision(True, float(opens[i]), ExitReason.TIME_EXIT)
                else:
                    # In live cadence the time-exit is owned by the driver (above), so the
                    # bar may only resolve the BARRIERS -> pass bars_held=0 to suppress it.
                    dec = self.rules.resolve_bar(
                        direction, stop_price, take_price, highs[i], lows[i],
                        0 if self.cadence != "literal" else bars_held, closes[i],
                    )
                if dec.exited:
                    closed_this_bar = True
                    reentry_price = float(dec.price)   # live_reentry fills here, not at the open
                    exit_price = float(dec.price)
                    gross = direction * (exit_price - entry_price) * size
                    exit_cost = self.costs.cost_amount(symbol, exit_price, size)
                    # entry cost was already subtracted at open; here add exit cost
                    pnl_net = gross - exit_cost
                    equity += pnl_net
                    realized_equity = equity
                    entry_cost = self.costs.cost_amount(symbol, entry_price, size)
                    trades.append(Trade(
                        symbol=symbol, direction=direction,
                        entry_time=index[entry_i], entry_price=entry_price,
                        exit_time=index[i], exit_price=exit_price, size=size,
                        reason=dec.reason.value, bars_held=bars_held,
                        pnl=pnl_net - entry_cost,  # subtract entry cost too -> full round-trip net
                        cost=entry_cost + exit_cost,
                        ret=(pnl_net - entry_cost) / risk_budget if risk_budget else 0.0,
                    ))
                    in_pos = False

            # --- 2) mark-to-market for equity curve & prop rules -------------
            if in_pos:
                unreal = direction * (closes[i] - entry_price) * size
                marked = realized_equity + unreal
            else:
                marked = realized_equity
            prop.update_equity(marked, day)
            equity_curve[i] = marked

            if prop.failed:
                # Account blown: stop trading; fill remaining curve flat.
                equity_curve[i + 1:] = marked
                logger.info("PropFirm FAILED at %s: %s", index[i], prop.fail_reason)
                break

            # --- 3) consider a NEW entry (executed at THIS bar's open) -------
            # Signal was decided `lag` bars ago (no lookahead).
            # In live cadence the driver handles the open position and RETURNS, so a bar
            # that closed a trade can never also open one.
            sig_i = i - self.lag
            if (not in_pos) and sig_i >= 0 and prop.can_trade \
                    and not (self.cadence == "live" and closed_this_bar):
                # live_reentry: the same-bar re-open fills at the barrier price the exit
                # just printed, never at this bar's (already past) open.
                desired = sig_arr[sig_i]
                entry_atr = atr_arr[i - 1] if i >= 1 else np.nan
                if desired != 0 and np.isfinite(entry_atr) and entry_atr > 0:
                    direction = int(desired)
                    entry_price = (reentry_price if (self.cadence == "live_reentry"
                                                    and closed_this_bar) else opens[i])
                    stop_price, take_price = self.rules.barrier_prices(
                        entry_price, direction, entry_atr)
                    sl_dist = abs(entry_price - stop_price)
                    if sl_dist > 0:
                        risk_budget = marked * self.risk_per_trade
                        size = risk_budget / sl_dist
                        entry_cost = self.costs.cost_amount(symbol, entry_price, size)
                        equity -= entry_cost  # pay entry cost immediately
                        entry_i = i
                        in_pos = True
                        # The entry bar itself can hit a barrier: re-test now.
                        bars_held = 1
                        dec = self.rules.resolve_bar(
                            direction, stop_price, take_price,
                            highs[i], lows[i], bars_held, closes[i])
                        if dec.exited:
                            exit_price = float(dec.price)
                            gross = direction * (exit_price - entry_price) * size
                            exit_cost = self.costs.cost_amount(symbol, exit_price, size)
                            equity += gross - exit_cost
                            trades.append(Trade(
                                symbol=symbol, direction=direction,
                                entry_time=index[i], entry_price=entry_price,
                                exit_time=index[i], exit_price=exit_price, size=size,
                                reason=dec.reason.value, bars_held=1,
                                pnl=gross - exit_cost - entry_cost,
                                cost=entry_cost + exit_cost,
                                ret=(gross - exit_cost - entry_cost) / risk_budget
                                if risk_budget else 0.0,
                            ))
                            in_pos = False
                            marked = equity
                            equity_curve[i] = marked
                            prop.update_equity(marked, day)

        equity_ser = pd.Series(equity_curve, index=index, name="equity")
        returns_ser = equity_ser.pct_change().fillna(0.0)
        returns_ser.name = "returns"
        trades_df = pd.DataFrame([t.__dict__ for t in trades])

        verdict, reason = prop.verdict()
        return BacktestResult(
            symbol=symbol, edge_name=edge_name, trades=trades_df,
            equity=equity_ser, returns=returns_ser,
            prop_verdict=verdict.value, prop_reason=reason,
            meta={"n_bars": n, "initial_balance": self.initial_balance},
        )
