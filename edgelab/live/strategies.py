"""Stateful LIVE drivers for the four bricks: signals -> orders via the broker.

Each strategy is a self-contained object with a ``.step(broker, risk, now_utc)`` method
the runner calls every loop. A strategy:
  1) manages its OPEN position (time-exits always; SL/TP too in dry-run — the live broker
     lets MT5 manage the attached brackets);
  2) if flat and the account gate allows, considers a NEW entry per its brick's rule.
Positions are tagged with a per-brick MAGIC so the shared account view stays unambiguous.

All timing is done in the instrument's session tz via a TRUE-UTC clock; nothing here
re-implements a signal — the decisions come from edgelab.live.signals.
"""
from __future__ import annotations

import logging

import pandas as pd

from edgelab.intraday.atr_breakout import ATRBreakParams
from edgelab.edges.turn_of_month import TurnOfMonthParams
from edgelab.edges.ibs import IBSParams
from edgelab.live import signals as S
from edgelab.live.broker import Broker, MarketClosed
from edgelab.live.risk import LiveRiskManager

logger = logging.getLogger("edgelab.live.strategies")

MAGIC = {"nas_orb": 101, "gold_tom": 102, "btc_macd": 103, "eth_macd": 104, "nas_ibs": 105}


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


class _EntryRetryGuard:
    """Bounds how long a rollover brick keeps retrying an entry that fails **on an open
    market**, without ever bounding the wait for a *closed* one.

    That distinction is the whole point. A signal validated at Friday's close must be
    taken at the Sunday-night reopen — ~48 h after its rollover — because that reopen IS
    the next bar's open, which is where the backtest fills. So the clock must never run
    while the market is shut: ``MarketClosed`` (retcode 10018) and "today's bar has not
    printed yet" do not touch it, and a weekend therefore costs nothing.

    What it does bound is a *tradable* market that keeps rejecting us — invalid stops
    (10016), AutoTrading switched off (10027), a mis-mapped symbol. There the retry can
    run all day and land a fill hours after the rollover, which is no longer the trade the
    backtest measured. Past ``max_hours`` of such failures the brick skips the day instead.

    Only ENTRIES are bounded. An exit is never abandoned.
    """

    def __init__(self, max_hours: float):
        self.max_hours = float(max_hours)
        self._day = None
        self._since: pd.Timestamp | None = None

    def failed(self, day, now_utc: pd.Timestamp) -> bool:
        """Record one open-market failure. True once they have run past ``max_hours``.

        The first failure of a broker day starts the clock, so on a Monday reopen the
        allowance is counted from the reopen, not from the 00:00 rollover.
        """
        if self._day != day:
            self._day, self._since = day, now_utc
            return False
        return (now_utc - self._since) >= pd.Timedelta(hours=self.max_hours)


class _RolloverBrick:
    """Shared entry plumbing for the bricks that decide at the daily-bar rollover (2, 3, 4).

    Subclasses set ``self._retry`` and ``self._acted_day``.
    """

    def _place_entry(self, place, bday, now_utc: pd.Timestamp, label: str) -> None:
        """Send an entry, bailing out of the day if an OPEN market keeps refusing it."""
        try:
            place()
        except MarketClosed:
            raise                      # market shut -> runner's quiet retry, clock untouched
        except Exception as exc:
            if not self._retry.failed(bday, now_utc):
                raise                  # transient -> let the runner log it and retry
            logger.error("%s: entry ABANDONED for %s after %.1f h of failures on an OPEN market "
                         "(last: %s) -> skipping the day. A fill this far from the rollover is "
                         "no longer the backtest's trade.", label, bday, self._retry.max_hours, exc)
            self._acted_day = bday


class NasOrbStrategy:
    """Brick 1 — NAS100 US-open ATR breakout, low-vol regime. Intraday, 1 trade/day."""

    def __init__(self, cfg_live: dict):
        self.p = ATRBreakParams(regime_mode="low", direction="both")
        self.logical = cfg_live.get("nas_symbol", "NAS100")
        self.magic = MAGIC["nas_orb"]
        self._entered_on = None       # ET date we already traded
        self._skip_logged = None

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        et = now_utc.tz_convert(self.p.tz)
        et_date = et.date()
        minute = et.hour * 60 + et.minute
        open_m, cut_m, close_m = _mins(self.p.session_open), _mins(self.p.entry_cutoff), _mins(self.p.session_close)

        pos = broker.open_position(self.magic)

        # (1) manage open position: time-exit at session close; dry-run resolves SL/TP
        if pos is not None:
            if not broker.live:
                bar = broker.get_bars(self.logical, "M1", 3).iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc)
                if closed:
                    broker.close(pos, px, why, now_utc)
                    return
            if minute >= close_m:
                px = float(broker.get_bars(self.logical, "M1", 2).iloc[-1]["close"])
                broker.close(pos, px, "time_exit", now_utc)
            return

        # (2) entry window only
        if self._entered_on == et_date:
            return
        if not (open_m <= minute <= cut_m):
            return
        ok, why = risk.can_enter()
        if not ok:
            if self._skip_logged != et_date:
                logger.info("brick1 skip entry: %s", why); self._skip_logged = et_date
            return

        # pull today's session bars + prev-day ATR context
        m1 = broker.get_bars(self.logical, "M1", 1200)
        loc = m1.index.tz_convert(self.p.tz)
        mask = (loc.normalize().date == et_date) & \
               ((loc.hour * 60 + loc.minute) >= open_m) & ((loc.hour * 60 + loc.minute) <= close_m)
        sess = m1[mask][["open", "high", "low", "close"]]
        if len(sess) < 2:
            return
        d1 = broker.get_bars_raw(self.logical, "D1", 60)   # RAW date keying (matches backtest)
        atrs = S.prev_day_atrs(d1, self.p).get(et_date)
        if atrs is None:
            return
        res = S.nas_orb_scan(sess, atrs[0], atrs[1], atrs[2], self.p)
        if res is None:
            return
        confirm_idx, plan = res
        # only act on a FRESH breakout (confirm within the last 2 completed bars)
        if confirm_idx < len(sess) - 2:
            self._entered_on = et_date  # stale (runner was down) -> skip today, don't chase
            logger.info("brick1 stale breakout on %s (confirm %d of %d) -> skip", et_date, confirm_idx, len(sess))
            return

        ref = float(sess["close"].iloc[-1])
        sl = ref - plan.direction * plan.sl_dist
        tp = ref + plan.direction * plan.tp_dist if plan.tp_dist else None
        lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, risk.risk_budget())
        close_dt = (et.normalize() + pd.Timedelta(hours=15, minutes=55)).tz_convert("UTC")
        broker.place_market(self.logical, plan.direction, lots, sl, tp, self.magic,
                            f"brick1_{plan.reason}", plan.sl_dist, ref, now_utc, time_exit_at=close_dt)
        self._entered_on = et_date


class GoldTomStrategy(_RolloverBrick):
    """Brick 2 — XAUUSD turn-of-month. Daily; ~1 trade/month."""

    def __init__(self, cfg_live: dict):
        self.p = TurnOfMonthParams(sl_atr=1.5)
        self.logical = cfg_live.get("gold_symbol", "XAUUSD")
        self.magic = MAGIC["gold_tom"]
        self._acted_day = None
        self._retry = _EntryRetryGuard(cfg_live.get("entry_retry_max_hours", 2))

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        # Act ONCE per broker (server) day, triggered right at the daily-bar rollover
        # (00:00 server time). That is where the backtest enters (bar open) and exits
        # (bar close) -> live matches the backtest, no intraday lag.
        bday = now_utc.tz_convert("Europe/Athens").date()
        if bday == self._acted_day:
            return

        d1 = broker.get_bars(self.logical, "D1", 90)
        day = pd.Timestamp(bday)
        st = S.tom_state(d1, day, self.p)
        pos = broker.open_position(self.magic)

        # exit on the window-end day (or dry-run SL)
        if pos is not None:
            if not broker.live:
                bar = d1.iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc)
                if closed:
                    broker.close(pos, px, why, now_utc); self._acted_day = bday; return
            if st.is_exit_day:
                px = float(d1.iloc[-1]["close"])
                broker.close(pos, px, "time_exit", now_utc)
            self._acted_day = bday
            return

        # entry on the last-trading-day of the month (at the fresh daily open)
        if st.is_entry_day and st.sl_dist > 0:
            ok, why = risk.can_enter()
            if not ok:
                logger.info("brick2 skip entry: %s", why); self._acted_day = bday; return
            ref = float(d1.iloc[-1]["close"])
            sl = ref - st.sl_dist               # long only
            lots = broker.lots_for_risk(self.logical, +1, ref, sl, risk.risk_budget())
            self._place_entry(
                lambda: broker.place_market(self.logical, +1, lots, sl, None, self.magic,
                                            "brick2_turn_of_month", st.sl_dist, ref, now_utc),
                bday, now_utc, "brick2")
        self._acted_day = bday


class CryptoMacdStrategy(_RolloverBrick):
    """Brick 3 — MACD(12,26,9)+RSI on one coin (BTCUSD or ETHUSD). Daily; holds multi-day."""

    def __init__(self, cfg_live: dict, logical: str, risk_cfg: dict):
        self.logical = logical
        self.magic = MAGIC["btc_macd"] if "BTC" in logical else MAGIC["eth_macd"]
        self.risk_cfg = risk_cfg
        self.time_exit_bars = int(risk_cfg["time_exit_bars"])
        self._acted_day = None
        self._retry = _EntryRetryGuard(cfg_live.get("entry_retry_max_hours", 2))

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        # Act ONCE per broker (server) day, at the daily-bar rollover (00:00 server time),
        # entering at the fresh bar's open = where the backtest fills. No intraday lag.
        bday = now_utc.tz_convert("Europe/Athens").date()
        if bday == self._acted_day:
            return

        # RAW broker-time D1 (clean date keying). Drop the still-forming bar of the
        # current broker day so the DECISION uses the last CLOSED bar (matches backtest);
        # keep the forming bar (daily_all) for the current price / intraday paper resolve.
        raw = broker.get_bars_raw(self.logical, "D1", 320)
        raw["time"] = pd.to_datetime(raw["time"], utc=True)
        daily_all = raw.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
        forming = len(daily_all) > 0 and daily_all.index[-1].date() == bday
        daily = daily_all.iloc[:-1] if forming else daily_all   # completed bars only
        pos = broker.open_position(self.magic)

        if pos is not None:
            bars_held = (now_utc.normalize() - pos.open_time.normalize()).days  # crypto trades 7d/7
            if not broker.live:
                bar = daily_all.iloc[-1]                          # current forming bar for SL/TP touch
                closed, px, why = broker.resolve_paper(pos, bar, now_utc, bars_held=bars_held)
                if closed:
                    broker.close(pos, px, why, now_utc); self._acted_day = bday; return
            if bars_held >= self.time_exit_bars:
                broker.close(pos, float(daily_all.iloc[-1]["close"]), "time_exit", now_utc)
            self._acted_day = bday
            return

        plan = S.crypto_entry(daily, self.risk_cfg)              # decide on CLOSED bars
        if plan is not None:
            ok, why = risk.can_enter()
            if not ok:
                logger.info("brick3 %s skip entry: %s", self.logical, why); self._acted_day = bday; return
            ref = float(daily_all.iloc[-1]["close"])   # current price for the market entry
            sl = ref - plan.direction * plan.sl_dist
            tp = ref + plan.direction * plan.tp_dist if plan.tp_dist else None
            lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, risk.risk_budget())
            self._place_entry(
                lambda: broker.place_market(self.logical, plan.direction, lots, sl, tp, self.magic,
                                            f"brick3_{plan.reason}", plan.sl_dist, ref, now_utc,
                                            bars_held_limit=self.time_exit_bars),
                bday, now_utc, f"brick3 {self.logical}")
        self._acted_day = bday


class NasIbsStrategy(_RolloverBrick):
    """Brick 4 — NAS100 IBS reversion. Daily, long-only; holds up to `max_hold` bars.

    Same cadence as bricks 2 & 3: decide ONCE per broker day at the daily-bar rollover
    (00:00 server time), which is where the backtest fills (the next bar's open). No TP —
    the exits are the broker-managed stop, ``IBS > ibs_high`` at a close, and the
    ``max_hold``-bar timeout, both acted on at the following open.

    ``bars_held`` is counted in **D1 BARS** (trading days), not calendar days, by locating
    the entry bar in the broker's own D1 frame — NAS100 does not print a bar at weekends,
    so a calendar-day count (which is right for 7d/7 crypto) would time-exit ~2 days early.

    Over a weekend / market break the entry order is rejected with retcode 10018; the
    runner retries quietly and the fill lands at the reopen — which IS the next bar's open,
    i.e. exactly where the backtest enters. That wait is deliberately UNBOUNDED (a Friday
    signal is taken ~48 h later at the Sunday-night reopen); only failures on an *open*
    market are time-boxed — see _EntryRetryGuard.
    """

    def __init__(self, cfg_live: dict):
        self.p = IBSParams(sl_atr=2.5)
        self.logical = cfg_live.get("ibs_symbol", "NAS100")
        self.magic = MAGIC["nas_ibs"]
        self._acted_day = None
        self._wait_logged = None
        self._retry = _EntryRetryGuard(cfg_live.get("entry_retry_max_hours", 2))

    @staticmethod
    def _bars_held(raw: pd.DataFrame, open_time: pd.Timestamp, last_closed_i: int) -> int | None:
        """D1 bars between the entry bar and the last CLOSED bar, or None if not locatable."""
        entry_day = pd.Timestamp(open_time).tz_convert("Europe/Athens").date()
        dates = list(pd.to_datetime(raw["time"]).dt.date)
        try:                                   # the entry bar = the bar of the broker day we entered on
            entry_i = dates.index(entry_day)
        except ValueError:
            return None                        # entry day printed no bar (shouldn't happen) -> skip
        return last_closed_i - entry_i

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        bday = now_utc.tz_convert("Europe/Athens").date()
        if bday == self._acted_day:
            return

        # RAW broker-time D1 (the backtest keys on the stored broker date — see edges/ibs.py).
        # Drop the still-forming bar so the DECISION uses only completed bars.
        raw = broker.get_bars_raw(self.logical, "D1", 120)
        raw["time"] = pd.to_datetime(raw["time"], utc=True)
        daily_all = raw.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
        forming = len(daily_all) > 0 and daily_all.index[-1].date() == bday
        daily = daily_all.iloc[:-1] if forming else daily_all
        last_closed_i = len(daily) - 1
        if last_closed_i < self.p.atr_p + 3:
            return

        st = S.ibs_state(daily, self.p)
        pos = broker.open_position(self.magic)

        if pos is not None:
            held = self._bars_held(raw, pos.open_time, last_closed_i)
            if not broker.live:                        # dry-run: resolve the stop on the bar
                bar = daily_all.iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc, bars_held=held)
                if closed:
                    broker.close(pos, px, why, now_utc); self._acted_day = bday; return
            if st.exit_signal or (held is not None and held >= self.p.max_hold):
                why = "ibs_high" if st.exit_signal else "time_exit"
                px = float(daily_all.iloc[-1]["close"])    # current price = the new bar's open
                broker.close(pos, px, why, now_utc)
            self._acted_day = bday
            return

        if st.entry_ok:
            ok, why = risk.can_enter()
            if not ok:
                logger.info("brick4 skip entry: %s", why); self._acted_day = bday; return
            if not forming:
                # today's bar has not printed yet (market still in its break) -> the last
                # close is STALE, and sizing/SL off a stale ref would not be a true 1R.
                # Return WITHOUT marking the day done: retry until the session opens, which
                # is where the backtest fills anyway (the next bar's open).
                if self._wait_logged != bday:
                    logger.info("brick4 entry pending: waiting for the %s bar to open", bday)
                    self._wait_logged = bday
                return
            ref = float(daily_all.iloc[-1]["close"])       # fresh bar -> ~ this bar's open
            sl = ref - st.sl_dist                          # long only, no TP
            lots = broker.lots_for_risk(self.logical, +1, ref, sl, risk.risk_budget())
            self._place_entry(
                lambda: broker.place_market(self.logical, +1, lots, sl, None, self.magic,
                                            "brick4_ibs_reversion", st.sl_dist, ref, now_utc,
                                            bars_held_limit=self.p.max_hold),
                bday, now_utc, "brick4")
        self._acted_day = bday
