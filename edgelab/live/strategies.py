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
from datetime import timedelta

import pandas as pd

from edgelab.intraday.atr_breakout import ATRBreakParams
from edgelab.edges.turn_of_month import TurnOfMonthParams
from edgelab.edges.ibs import IBSParams
from edgelab.intraday.hma_stoch import HmaStochParams
from edgelab.intraday.kaer import KaerParams
from edgelab.intraday.keltner_btc import KeltParams
from edgelab.live import signals as S
from edgelab.live.broker import Broker, MarketClosed
from edgelab.live.risk import LiveRiskManager

logger = logging.getLogger("edgelab.live.strategies")

MAGIC = {"nas_orb": 101, "gold_tom": 102, "btc_macd": 103, "eth_macd": 104, "nas_ibs": 105,
         "nas_kaer": 106, "btc_kelt": 107, "nas_hmasto": 108,
         "nas_tlf": 109, "spx_tlf": 110}

SERVER_TZ = "Europe/Athens"     # the broker's clock: a D1 bar's date IS its server date
ROLLOVER_LEAD_MIN = 10.0        # send a D-rollover time-exit this many minutes EARLY


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _at_rollover_lead(now_utc: pd.Timestamp, lead_min: float = ROLLOVER_LEAD_MIN) -> bool:
    """True in the last ``lead_min`` minutes of the broker day, i.e. just before the D1 close.

    WHY. A time-exit that fires AT the 00:00 rollover is sent into the daily maintenance
    break of every symbol that has one — NAS100 and XAUUSD are both shut **00:00-01:00
    server** (23:00-00:00 Paris) — so it is rejected 10018 and only fills when the market
    reopens. On a Friday that reopen is **Monday**, which is how a sleeve ends up carrying
    a weekend it never agreed to: 13 % of brick 2's exits and 20 % of brick 4's currently
    fill at a Monday open. Firing before the close leaves on the bar we are actually
    leaving.

    WHY 10 MINUTES AND NOT 5. Mon-Thu these symbols quote through 23:55 server, but on
    **FRIDAY the last M5 bar is 23:50** — the session ends at 23:55 server (22:55 Paris)
    exactly. A 5-minute lead would therefore fire precisely at the Friday close, on the
    one day the weekend is at stake. 23:50 server (22:50 Paris) is the last window that is
    live every day of the week. Override per-deployment with ``rollover_lead_min``.

    BTCUSD/ETHUSD have **no** break at all on this feed (verified: every M5 slot present,
    00:00 included), so for the crypto sleeves this is insurance, not a fix.
    """
    srv = now_utc.tz_convert(SERVER_TZ)
    return (srv.hour * 60 + srv.minute) >= (24 * 60 - lead_min)


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
    """Shared entry+exit plumbing for the bricks that decide at the daily-bar rollover (2, 3, 4).

    Subclasses set ``self._retry``, ``self._acted_day`` and ``self._managed_day``.

    TWO SEPARATE DAY MARKERS, and the distinction is the whole point:

    * ``_acted_day`` — "this broker bar is spoken for, do not OPEN on it". Set the moment a
      position is seen, *before* the exit is attempted, because a broker stop that fills
      mid-pass must not be followed by a same-bar entry (the cadence='live' guarantee).
    * ``_managed_day`` — "the exit decision for this bar has RESOLVED". Set only *after*
      the exit attempt returns without raising.

    They used to be one field, and that silently broke exits. ``_acted_day`` was set before
    ``broker.close()``, so the first pass of a broker day consumed the day's only exit
    attempt: a close rejected because the market was shut (weekend, the 00:00-01:00 break)
    was then not retried until the NEXT broker day, ~24 h later — three days over a weekend.
    Measured live 2026-08-07..09: brick 4 tried to leave a NAS100 long six times, was
    refused every time by a closed market, and carried the position ~3 extra days
    (runner.log; the runner's "market reopened, order placed" line made it look successful).
    Splitting the markers makes a refused exit retry on the very next poll, so the close
    lands at the reopen — which is where the backtest exits.
    """

    def _exit_due(self, bday, in_lead: bool) -> bool:
        """True when this pass must (re-)evaluate the exit of an open position.

        Re-evaluate while the day's decision is unresolved (first pass, or every pass after
        a refusal), and always inside the pre-rollover lead window, which is where the
        anticipated time exits fire. An exit is NEVER abandoned — only entries are
        time-boxed (see _EntryRetryGuard).
        """
        return self._managed_day != bday or in_lead

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


def _flat_dt(et: pd.Timestamp, session_close: str) -> pd.Timestamp:
    """Instant d'aplat FORCE pour la journee de ``et``, en UTC.

    Deux regles, et la seconde est celle qui evite un gap de week-end :

    1. lire ``session_close`` du sleeve, JAMAIS un litteral. Les quatre drivers passaient
       `pd.Timedelta(hours=15, minutes=55)` en dur alors que leur backtest lit
       `p.session_close` ; les deux valaient 15:55, donc ils s'accordaient par coincidence
       et non par construction. `verify_flat_times()` interdit desormais le retour d'un
       litteral.

    2. AVANCER l'aplat sur une seance ECOURTEE. Le flux s'arrete a 13:00 les jours feries
       US et les demi-seances ; a 15:55 le marche est deja clos, la cloture est refusee
       (MarketClosed) et la position part a la nuit -- alors que le backtest, lui, sort a
       la derniere barre. Mesure sur la brique 1 : 6 trades sur 830 concernes.
       `us_session_calendar` deduit ces journees de la DATE (aucune liste a maintenir) et
       ne peut qu'AVANCER la sortie, jamais la retarder.

    COUT MESURE de l'avance : -0.143 R sur 8.5 ans pour la brique 1, soit -0.017 R/an
    (-0.13 % de ses +12.93 R/an), contre la suppression du portage de nuit sur 8 journees.
    """
    from edgelab.live.us_session_calendar import flat_minute
    m = flat_minute(et.date(), _mins(session_close))
    return (et.normalize() + pd.Timedelta(minutes=m)).tz_convert("UTC")


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
        if lots <= 0:
            logger.warning("brick1 skip entry on %s: cannot size to 1R (min lot exceeds risk cap)", et_date)
            self._entered_on = et_date
            return
        close_dt = _flat_dt(et, self.p.session_close)
        broker.place_market(self.logical, plan.direction, lots, sl, tp, self.magic,
                            f"brick1_{plan.reason}", plan.sl_dist, ref, now_utc, time_exit_at=close_dt)
        self._entered_on = et_date


class GoldTomStrategy(_RolloverBrick):
    """Brick 2 — XAUUSD turn-of-month. Daily; ~1 trade/month.

    ENTRY is once per broker day, at the 00:00-server rollover (the fresh bar's open, where
    the backtest fills). The EXIT is checked on every pass, because ``run_turn_of_month``
    exits at the **close** of the window's last bar and XAUUSD is shut 00:00-01:00 server —
    so an exit sent at the rollover is rejected and fills an hour late, or on **Monday** when
    that bar is a Friday (13 % of exits). See ``_at_rollover_lead``.
    """

    def __init__(self, cfg_live: dict):
        self.p = TurnOfMonthParams(sl_atr=1.5)
        self.logical = cfg_live.get("gold_symbol", "XAUUSD")
        self.magic = MAGIC["gold_tom"]
        self.lead_min = float(cfg_live.get("rollover_lead_min", ROLLOVER_LEAD_MIN))
        self._acted_day = None
        self._managed_day = None
        self._retry = _EntryRetryGuard(cfg_live.get("entry_retry_max_hours", 2))

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        bday = now_utc.tz_convert(SERVER_TZ).date()
        pos = broker.open_position(self.magic)
        day = pd.Timestamp(bday)

        # ---- open position: exit checked on every pass ---------------------------
        if pos is not None:
            self._acted_day = bday          # holding today => never OPEN on this bar either
            in_lead = _at_rollover_lead(now_utc, self.lead_min)
            if not self._exit_due(bday, in_lead):
                return
            # RAW broker-time D1: a bar's date IS its trading date, which is what both the
            # backtest and tom_state's bar-count exit key on. (get_bars' true-UTC index
            # stamps a session at the *previous* calendar day, which would miscount the
            # month's completed bars whenever the 1st of the month is a trading day.)
            d1 = broker.get_bars_raw(self.logical, "D1", 90)
            st = S.tom_state(d1, day, self.p)
            if not broker.live:
                bar = d1.iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc)
                if closed:
                    broker.close(pos, px, why, now_utc)
                    self._managed_day = bday
                    return
            # `is_exit_day` = the count is already tipped (the rollover has passed, e.g. the
            # runner was down). `bars_done + 1` = the bar closing RIGHT NOW is the one that
            # tips it — that is the bar the backtest exits on, so leave on it.
            due_at_close = (st.bars_done + 1) >= self.p.first_days
            if st.is_exit_day or (due_at_close and in_lead):
                px = float(d1.iloc[-1]["close"])
                broker.close(pos, px, "time_exit", now_utc)
            # reached only if the close went through (or none was due): a refusal raises
            # out of `step` and leaves the day unresolved, so the next poll retries.
            self._managed_day = bday
            return

        # ---- entries: once per broker day, at the rollover ------------------------
        if self._acted_day is not None and bday <= self._acted_day:
            return
        d1 = broker.get_bars_raw(self.logical, "D1", 90)
        st = S.tom_state(d1, day, self.p)

        # entry on the last-trading-day of the month (at the fresh daily open)
        if st.is_entry_day and st.sl_dist > 0:
            ok, why = risk.can_enter()
            if not ok:
                logger.info("brick2 skip entry: %s", why); self._acted_day = bday; return
            ref = float(d1.iloc[-1]["close"])
            sl = ref - st.sl_dist               # long only
            lots = broker.lots_for_risk(self.logical, +1, ref, sl, risk.risk_budget())
            if lots <= 0:
                logger.warning("brick2 skip entry on %s: cannot size to 1R (min lot exceeds risk cap)", bday)
            else:
                self._place_entry(
                    lambda: broker.place_market(self.logical, +1, lots, sl, None, self.magic,
                                                "brick2_turn_of_month", st.sl_dist, ref, now_utc),
                    bday, now_utc, "brick2")
        self._acted_day = bday


class CryptoMacdStrategy(_RolloverBrick):
    """Brick 3 — MACD(12,26,9)+RSI on one coin (BTCUSD or ETHUSD). Daily; holds multi-day.

    ENTRIES happen once per broker day at the 00:00-server rollover (the fresh bar's open,
    where the backtest fills). EXITS are checked on **every** pass, because the 30-bar time
    exit has to be able to fire in the ``ROLLOVER_LEAD_MIN`` window before that rollover —
    see ``_at_rollover_lead``.

    ⚠️ The bar count is taken by LOCATING THE ENTRY BAR IN THE BROKER'S OWN D1 FRAME, never
    by subtracting calendar dates. The old version did ``now_utc.date - open_time.date``,
    which mixed a true-UTC date with a server-clock date and silently held **31** bars
    instead of 30 on every trade that reached the cap (31 % of them). Brick 4 already
    counted by index; this brings brick 3 in line.
    """

    def __init__(self, cfg_live: dict, logical: str, risk_cfg: dict):
        self.logical = logical
        self.magic = MAGIC["btc_macd"] if "BTC" in logical else MAGIC["eth_macd"]
        self.risk_cfg = risk_cfg
        # fraction de 1R risquee par trade. 1.0 jusqu'au 2026-08-10, ramenee a 0.5 sur
        # instruction de l'utilisateur : le swap FTMO (-30 %/an des DEUX cotes, verifie
        # en direct sur le terminal) coute 5.71 R/an a cette sleeve, soit exactement ce
        # qu'elle gagne encore en brut depuis 2022 (5.72 R/an) -> contribution NETTE de
        # +0.01 R/an sur les 4 dernieres annees pour 9.7 R/an de volatilite propre.
        # A 0.5R la ruine funded du livre tombe de 60.7 % a 49.2 % (MC periode recente).
        self.size_R = float(cfg_live.get("crypto_size_R", 1.0))
        self.time_exit_bars = int(risk_cfg["time_exit_bars"])
        self.lead_min = float(cfg_live.get("rollover_lead_min", ROLLOVER_LEAD_MIN))
        self._acted_day = None
        self._managed_day = None
        self._retry = _EntryRetryGuard(cfg_live.get("entry_retry_max_hours", 2))

    def _manage(self, broker: Broker, pos, now_utc: pd.Timestamp, bday) -> None:
        """Resolve an open position. Runs on every pass; owns the 30-bar time exit."""
        raw = broker.get_bars_raw(self.logical, "D1", 320)
        raw["time"] = pd.to_datetime(raw["time"], utc=True)
        daily_all = raw.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
        dates = list(raw["time"].dt.date)          # server dates: a bar's date IS its bar

        # `j` = the bar of the CURRENT broker day (still forming — crypto prints one a day).
        # The backtest exits at the OPEN of bar entry_i + time_exit_bars, so:
        #   already there (or past it, e.g. the runner was down) -> close now;
        #   one bar short and the rollover is minutes away  -> close now, early.
        j = len(dates) - 1
        entry_day = pd.Timestamp(pos.open_time).tz_convert(SERVER_TZ).date()
        try:
            bars_now = j - dates.index(entry_day)
        except ValueError:      # entry bar absent from the frame — never seen; stay able to exit
            logger.warning("brick3 %s: entry bar %s not in the broker D1 frame -> calendar "
                           "fallback for the time exit", self.logical, entry_day)
            bars_now = (pd.Timestamp(dates[j]) - pd.Timestamp(entry_day)).days

        if not broker.live:
            bar = daily_all.iloc[-1]                          # forming bar for the SL/TP touch
            closed, px, why = broker.resolve_paper(pos, bar, now_utc, bars_held=bars_now)
            if closed:
                broker.close(pos, px, why, now_utc)
                return

        due_now = bars_now >= self.time_exit_bars
        due_at_rollover = (bars_now + 1) >= self.time_exit_bars
        if due_now or (due_at_rollover and _at_rollover_lead(now_utc, self.lead_min)):
            broker.close(pos, float(daily_all.iloc[-1]["close"]), "time_exit", now_utc)
            # The engine forbids a bar that CLOSED a trade from also opening one
            # (cadence='live'). Closing early means the exit belongs to the bar about to
            # open, so block that one too — otherwise we would re-enter a bar early.
            self._acted_day = (bday + timedelta(days=1)) if not due_now else bday

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        bday = now_utc.tz_convert(SERVER_TZ).date()
        pos = broker.open_position(self.magic)

        if pos is not None:
            # Holding today => never enter on this bar either (that is the cadence='live'
            # guarantee: a bar that closes a trade cannot open one). Set it BEFORE the
            # exit runs, so a stop filled mid-bar cannot be followed by a same-bar entry.
            self._acted_day = bday
            if self._exit_due(bday, _at_rollover_lead(now_utc, self.lead_min)):
                self._manage(broker, pos, now_utc, bday)
                self._managed_day = bday   # only if _manage returned: a refusal raises
            return

        # ---- entries: once per broker day, at the rollover -----------------------
        # ``<=``, not ``==``: an early time-exit parks ``_acted_day`` on TOMORROW's bar
        # (the one the exit belongs to), and the minutes left in today's bar must stay
        # blocked too.
        if self._acted_day is not None and bday <= self._acted_day:
            return

        # RAW broker-time D1 (clean date keying). Drop the still-forming bar of the
        # current broker day so the DECISION uses the last CLOSED bar (matches backtest);
        # keep the forming bar (daily_all) for the current price.
        raw = broker.get_bars_raw(self.logical, "D1", 320)
        raw["time"] = pd.to_datetime(raw["time"], utc=True)
        daily_all = raw.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
        forming = len(daily_all) > 0 and daily_all.index[-1].date() == bday
        daily = daily_all.iloc[:-1] if forming else daily_all   # completed bars only

        plan = S.crypto_entry(daily, self.risk_cfg)              # decide on CLOSED bars
        if plan is not None:
            ok, why = risk.can_enter()
            if not ok:
                logger.info("brick3 %s skip entry: %s", self.logical, why); self._acted_day = bday; return
            ref = float(daily_all.iloc[-1]["close"])   # current price for the market entry
            sl = ref - plan.direction * plan.sl_dist
            tp = ref + plan.direction * plan.tp_dist if plan.tp_dist else None
            budget = risk.risk_budget() * self.size_R
            lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, budget)
            if lots <= 0:
                logger.warning("brick3 %s skip entry on %s: cannot size to %.2fR (min lot exceeds risk cap)",
                               self.logical, bday, self.size_R)
            else:
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
        self.lead_min = float(cfg_live.get("rollover_lead_min", ROLLOVER_LEAD_MIN))
        self._acted_day = None
        self._managed_day = None
        self._wait_logged = None
        self._retry = _EntryRetryGuard(cfg_live.get("entry_retry_max_hours", 2))

    @staticmethod
    def _bars_held(raw: pd.DataFrame, open_time: pd.Timestamp, last_closed_i: int) -> int | None:
        """D1 bars between the entry bar and the last CLOSED bar, or None if not locatable.

        ``open_time`` is a true-UTC instant (``broker.server_epoch_to_utc``), so converting
        it to the server tz gives the broker clock, whose date IS the bar's date.
        """
        entry_day = pd.Timestamp(open_time).tz_convert(SERVER_TZ).date()
        dates = list(pd.to_datetime(raw["time"]).dt.date)
        try:                                   # the entry bar = the bar of the broker day we entered on
            entry_i = dates.index(entry_day)
        except ValueError:
            return None                        # entry day printed no bar (shouldn't happen) -> skip
        return last_closed_i - entry_i

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        bday = now_utc.tz_convert(SERVER_TZ).date()
        pos = broker.open_position(self.magic)
        in_lead = _at_rollover_lead(now_utc, self.lead_min)
        if pos is not None:
            self._acted_day = bday          # holding today => never OPEN on this bar either
            if not self._exit_due(bday, in_lead):
                return
        elif self._acted_day is not None and bday <= self._acted_day:
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

        if pos is not None:
            held = self._bars_held(raw, pos.open_time, last_closed_i)
            if not broker.live:                        # dry-run: resolve the stop on the bar
                bar = daily_all.iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc, bars_held=held)
                if closed:
                    broker.close(pos, px, why, now_utc); self._managed_day = bday; return
            timed = held is not None and held >= self.p.max_hold
            # The bar closing right now is the one that would tip the count at the next
            # rollover -> leave on it rather than into the 00:00-01:00 break / the weekend.
            # ⚠️ ONLY the TIME exit is anticipated. The ``IBS > 0.8`` exit keeps the rollover
            # fill because it must be judged on a fully CLOSED bar; anticipating it would
            # read an IBS that is still 10 minutes from final. (Measured cost of moving it
            # too: +4.81 -> +4.78 R/yr — cheap, but it is a rule change, not a fix. And the
            # time exit itself has fired 0 times in 287 trades, so this branch is dormant.)
            timed_next = held is not None and (held + 1) >= self.p.max_hold
            if st.exit_signal or timed or (timed_next and in_lead):
                why = "ibs_high" if st.exit_signal else "time_exit"
                px = float(daily_all.iloc[-1]["close"])    # current price = the new bar's open
                broker.close(pos, px, why, now_utc)
            # reached only if the close went through (or none was due): a refusal raises
            # out of `step` and leaves the day unresolved, so the next poll retries.
            self._managed_day = bday
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
            if lots <= 0:
                logger.warning("brick4 skip entry on %s: cannot size to 1R (min lot exceeds risk cap)", bday)
            else:
                self._place_entry(
                    lambda: broker.place_market(self.logical, +1, lots, sl, None, self.magic,
                                                "brick4_ibs_reversion", st.sl_dist, ref, now_utc,
                                                bars_held_limit=self.p.max_hold),
                    bday, now_utc, "brick4")
        self._acted_day = bday


class KaerStrategy:
    """FORWARD-TEST SLEEVE (not a frozen brick) — NAS100 M15 Kaufman ER breakout.

    Deployed alongside brick 1 on the DEMO account to settle one question the backtest
    cannot: whether this is a better brick 1. It is NOT a 5th brick — corr +0.370 to
    brick 1, 40% of its trading days overlap, and it replicates on no other index
    (see edgelab/intraday/kaer.py and RESEARCH_LOG_KAUFMAN.md).

    Because of that correlation it is deliberately sized at ``size_R`` (0.5R by default):
    the equal-risk book test says +KAER@0.5R improves the book on every axis while
    +KAER@1R makes it worse. Sizing it up is a decision, not a default.

    Cadence: once per COMPLETED M15 bar inside 09:30-15:30 ET. The forming bar is dropped
    explicitly, and a bar older than ``max_bar_age_min`` is skipped rather than chased --
    if the runner was down, the fill would no longer be the next-bar open the backtest
    measured.
    """

    def __init__(self, cfg_live: dict):
        self.p = KaerParams(size_R=float(cfg_live.get("kaer_size_R", 0.5)))
        self.logical = cfg_live.get("kaer_symbol", "NAS100")
        self.magic = MAGIC["nas_kaer"]
        self.bars_needed = int(cfg_live.get("kaer_bars", 2600))
        self.max_bar_age_min = float(cfg_live.get("kaer_max_bar_age_min", 5))
        self._acted_bar = None        # timestamp of the last completed bar we acted on
        self._skip_logged = None

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        et = now_utc.tz_convert(self.p.tz)
        minute = et.hour * 60 + et.minute
        open_m, cut_m = _mins(self.p.session_open), _mins(self.p.entry_cutoff)
        flat_m = _mins(self.p.session_close)

        pos = broker.open_position(self.magic)

        # (1) manage the open position: forced flat at 15:55 ET; dry-run resolves the stop
        if pos is not None:
            if not broker.live:
                bar = broker.get_bars(self.logical, "M15", 3).iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc)
                if closed:
                    broker.close(pos, px, why, now_utc)
                    return
            if minute >= flat_m:
                px = float(broker.get_bars(self.logical, "M15", 2).iloc[-1]["close"])
                broker.close(pos, px, "time_exit", now_utc)
            return

        # (2) entries only inside the signal window
        if not (open_m <= minute <= cut_m + 15):
            return

        bars_all = broker.get_bars(self.logical, "M15", self.bars_needed)
        if len(bars_all) < 3:
            return
        # DROP THE FORMING BAR: a bar stamped t is complete only at t+15min.
        step_ = pd.Timedelta(minutes=15)
        bars = bars_all.iloc[:-1] if (bars_all.index[-1] + step_) > now_utc else bars_all
        if not len(bars):
            return
        last_ts = bars.index[-1]
        if self._acted_bar is not None and last_ts <= self._acted_bar:
            return                                  # already handled this bar

        age_min = (now_utc - (last_ts + step_)).total_seconds() / 60.0
        if age_min > self.max_bar_age_min:
            self._acted_bar = last_ts               # stale (runner was down) -> do not chase
            logger.info("kaer stale bar %s (%.1f min old) -> skip", last_ts, age_min)
            return

        res = S.kaer_scan(bars, self.p)
        self._acted_bar = last_ts
        if res is None:
            return

        _, plan = res
        ok, why = risk.can_enter()
        if not ok:
            if self._skip_logged != et.date():
                logger.info("kaer skip entry: %s", why)
                self._skip_logged = et.date()
            return

        ref = float(bars["close"].iloc[-1])
        sl = ref - plan.direction * plan.sl_dist
        tp = ref + plan.direction * plan.tp_dist if plan.tp_dist else None
        budget = risk.risk_budget() * self.p.size_R
        lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, budget)
        if lots <= 0:
            logger.warning("kaer skip entry at %s: cannot size to %.2fR on the lot grid",
                           last_ts, self.p.size_R)
            return
        close_dt = _flat_dt(et, self.p.session_close)
        broker.place_market(self.logical, plan.direction, lots, sl, tp, self.magic,
                            f"kaer_{plan.reason}", plan.sl_dist, ref, now_utc,
                            time_exit_at=close_dt)


class HmaStochStrategy:
    """FORWARD-TEST SLEEVE (not a frozen brick) — NAS100 M15 HMA/EMA cross + 3 oscillators.

    DEPLOYED 2026-08-10 IN KAER'S SLOT, on the user's explicit instruction, after the
    corpus campaign measured it as the only non-breakout survivor on NAS100. It REPLACES
    KAER rather than joining it: the two correlate **+0.335 monthly** (same asset, same
    timeframe, same intraday-following family), so stacking them raises the book's maxDD
    17.1 -> 20.0 and its funded ruin 7.3% -> 12.3% at 0.5%/trade, while SWAPPING cuts
    maxDD to 15.3 and ruin to 3.8%. Standalone it dominates KAER on every axis
    (R/yr +42.8 vs +30.9, RoMaD 1.72 vs 1.22) and its two half-samples GROW where KAER's
    decay.

    ⚠️ It is mono-asset, in-sample, and the best of 112 by RoMaD on the asset where the
    campaign's selection pressure is strongest. Sized at ``size_R`` (0.5R) exactly as KAER
    was, in the same forward-test slot. Sizing it up is a decision, not a default. See
    edgelab/intraday/hma_stoch.py for what this is and is not.

    Cadence: once per COMPLETED M15 bar inside 09:30-15:30 ET, mirroring KAER. The forming
    bar is dropped explicitly, and a bar older than ``max_bar_age_min`` is skipped rather
    than chased -- if the runner was down, the fill would no longer be the next-bar open
    the backtest measured.
    """

    def __init__(self, cfg_live: dict):
        self.p = HmaStochParams(size_R=float(cfg_live.get("hmasto_size_R", 0.5)))
        self.logical = cfg_live.get("hmasto_symbol", "NAS100")
        self.magic = MAGIC["nas_hmasto"]
        self.bars_needed = int(cfg_live.get("hmasto_bars", 400))
        self.max_bar_age_min = float(cfg_live.get("hmasto_max_bar_age_min", 5))
        self._acted_bar = None
        self._skip_logged = None

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        et = now_utc.tz_convert(self.p.tz)
        minute = et.hour * 60 + et.minute
        open_m, cut_m = _mins(self.p.session_open), _mins(self.p.entry_cutoff)
        flat_m = _mins(self.p.session_close)

        pos = broker.open_position(self.magic)

        # (1) manage the open position: forced flat at 15:55 ET; dry-run resolves the stop
        if pos is not None:
            if not broker.live:
                bar = broker.get_bars(self.logical, "M15", 3).iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc)
                if closed:
                    broker.close(pos, px, why, now_utc)
                    return
            if minute >= flat_m:
                px = float(broker.get_bars(self.logical, "M15", 2).iloc[-1]["close"])
                broker.close(pos, px, "time_exit", now_utc)
            return

        # (2) entries only inside the signal window
        if not (open_m <= minute <= cut_m + 15):
            return

        bars_all = broker.get_bars(self.logical, "M15", self.bars_needed)
        if len(bars_all) < 3:
            return
        # DROP THE FORMING BAR: a bar stamped t is complete only at t+15min.
        step_ = pd.Timedelta(minutes=15)
        bars = bars_all.iloc[:-1] if (bars_all.index[-1] + step_) > now_utc else bars_all
        if not len(bars):
            return
        last_ts = bars.index[-1]
        if self._acted_bar is not None and last_ts <= self._acted_bar:
            return                                  # already handled this bar

        age_min = (now_utc - (last_ts + step_)).total_seconds() / 60.0
        if age_min > self.max_bar_age_min:
            self._acted_bar = last_ts               # stale (runner was down) -> do not chase
            logger.info("hmasto stale bar %s (%.1f min old) -> skip", last_ts, age_min)
            return

        res = S.hma_scan(bars, self.p, self.logical)
        self._acted_bar = last_ts
        if res is None:
            return

        _, plan = res
        ok, why = risk.can_enter()
        if not ok:
            if self._skip_logged != et.date():
                logger.info("hmasto skip entry: %s", why)
                self._skip_logged = et.date()
            return

        ref = float(bars["close"].iloc[-1])
        sl = ref - plan.direction * plan.sl_dist
        tp = ref + plan.direction * plan.tp_dist if plan.tp_dist else None
        budget = risk.risk_budget() * self.p.size_R
        lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, budget)
        if lots <= 0:
            logger.warning("hmasto skip entry at %s: cannot size to %.2fR on the lot grid",
                           last_ts, self.p.size_R)
            return
        close_dt = _flat_dt(et, self.p.session_close)
        broker.place_market(self.logical, plan.direction, lots, sl, tp, self.magic,
                            f"hmasto_{plan.reason}", plan.sl_dist, ref, now_utc,
                            time_exit_at=close_dt)


class KeltnerStrategy:
    """FORWARD-TEST SLEEVE (not a frozen brick) — BTCUSD H1 Keltner-band breakout.

    From the 2026-08-07 cross-asset pass over the whole Kaufman canon, where crypto came
    out at 16.8x the matched-random-signal placebo on H1 while FX and the indices came out
    at or below the noise rate. It clears both nulls, both split halves, 9/9 positive
    years, is cost-immune, and survives the 25x-spread floor.

    It is NOT a decorrelated 5th brick — monthly correlation to brick 3 is +0.07..+0.23,
    so it is a second CRYPTO-TREND sleeve (an hourly cousin of the daily MACD). Deployed
    at ``size_R`` (0.5R) on the DEMO as a forward test, like KAER.

    Cadence: once per COMPLETED H1 bar, 24/7 (crypto). Exits are the broker-held stop and
    target plus a **96-bar time exit** the runner owns. The forming bar is dropped
    explicitly and a bar older than ``max_bar_age_min`` is skipped rather than chased.
    """

    def __init__(self, cfg_live: dict):
        self.p = KeltParams(size_R=float(cfg_live.get("kelt_size_R", 0.5)))
        self.logical = cfg_live.get("kelt_symbol", "BTCUSD")
        self.magic = MAGIC["btc_kelt"]
        self.bars_needed = int(cfg_live.get("kelt_bars", 600))
        self.max_bar_age_min = float(cfg_live.get("kelt_max_bar_age_min", 20))
        self.lead_min = float(cfg_live.get("rollover_lead_min", ROLLOVER_LEAD_MIN))
        self._acted_bar = None
        self._skip_logged = None

    @staticmethod
    def _held(bars: pd.DataFrame, open_time: pd.Timestamp) -> int:
        """COMPLETED H1 bars of the trade, counted **in bars of the broker's own frame**.

        Three ways to get this wrong, and the first version managed two of them:

        * ``pos.open_time`` used to carry the SERVER clock labelled as UTC, so subtracting
          it from a true-UTC bar stamp lost the whole +3 h offset (fixed upstream, in
          ``broker.server_epoch_to_utc``);
        * the fill lands a few minutes INTO its entry bar, so a raw span truncates one bar
          low — hence the ``floor`` to the bar boundary;
        * **elapsed hours are not bars.** The BTCUSD H1 feed really does have holes (137
          two-day gaps in the cached history), and ``run_keltner`` caps on ``exit_bar -
          entry_bar``, an INDEX distance. Counting wall-clock hours instead disagreed with
          the backtest on 155 of its first 200 time-exit trades.

        ``method="ffill"`` degrades gracefully if the entry bar itself is missing from the
        frame: the position is then counted from the last bar that precedes it.
        """
        entry_bar = pd.Timestamp(open_time).floor(pd.Timedelta(hours=1))
        loc = int(bars.index.get_indexer([entry_bar], method="ffill")[0])
        if loc < 0:                       # older than the pulled window -> never on a 96-bar cap
            logger.warning("keltner: entry bar %s precedes the %d-bar window -> elapsed-hours "
                           "fallback for the time exit", entry_bar, len(bars))
            return int((bars.index[-1] - entry_bar) / pd.Timedelta(hours=1)) + 1
        return len(bars) - loc            # bars loc..last, inclusive

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        step_ = pd.Timedelta(hours=1)
        bars_all = broker.get_bars(self.logical, "H1", self.bars_needed)
        if len(bars_all) < 3:
            return
        # DROP THE FORMING BAR: a bar stamped t is complete only at t+1h.
        bars = bars_all.iloc[:-1] if (bars_all.index[-1] + step_) > now_utc else bars_all
        if not len(bars):
            return
        last_ts = bars.index[-1]

        pos = broker.open_position(self.magic)

        # (1) manage the open position: the broker holds SL/TP; we own the 96-bar cap.
        if pos is not None:
            held = self._held(bars, pos.open_time)
            if not broker.live:
                closed, px, why = broker.resolve_paper(pos, bars.iloc[-1], now_utc,
                                                       bars_held=held)
                if closed:
                    broker.close(pos, px, why, now_utc)
                    return
            # `held + 1` completes at the next H1 boundary; when that boundary IS the
            # daily rollover, send the close early rather than into the break.
            if held >= self.p.max_bars or ((held + 1) >= self.p.max_bars
                                           and _at_rollover_lead(now_utc, self.lead_min)):
                broker.close(pos, float(bars["close"].iloc[-1]), "time_exit", now_utc)
            return

        # (2) entry, once per completed bar
        if self._acted_bar is not None and last_ts <= self._acted_bar:
            return
        age_min = (now_utc - (last_ts + step_)).total_seconds() / 60.0
        if age_min > self.max_bar_age_min:
            self._acted_bar = last_ts
            logger.info("keltner stale bar %s (%.0f min old) -> skip", last_ts, age_min)
            return

        res = S.keltner_scan(bars, self.p)
        self._acted_bar = last_ts
        if res is None:
            return
        _, plan = res
        ok, why = risk.can_enter()
        if not ok:
            day = now_utc.date()
            if self._skip_logged != day:
                logger.info("keltner skip entry: %s", why)
                self._skip_logged = day
            return

        ref = float(bars["close"].iloc[-1])
        sl = ref - plan.direction * plan.sl_dist
        tp = ref + plan.direction * plan.tp_dist
        budget = risk.risk_budget() * self.p.size_R
        lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, budget)
        if lots <= 0:
            logger.warning("keltner skip entry at %s: cannot size to %.2fR on the lot grid",
                           last_ts, self.p.size_R)
            return
        broker.place_market(self.logical, plan.direction, lots, sl, tp, self.magic,
                            f"kelt_{plan.reason}", plan.sl_dist, ref, now_utc,
                            bars_held_limit=self.p.max_bars)


class TwoLegFadeStrategy:
    """FORWARD-TEST SLEEVE (not a frozen brick) — TLF, Two-Leg Fade. M5, SHORT-ONLY.

    One instance per symbol: NAS100 (magic 109) and US500 (magic 110), like brick 3's two
    coins. Deployed 2026-08-10 at ``size_R`` (0.5R) on the user's explicit instruction.

    WHAT IT TRADES. Bar selection from Brooks (always-in context + two-leg pullback +
    strong signal bar), but the trade is the OPPOSITE of what he teaches: on those bars
    the direction worth money is the SHORT. Decomposition of the +0.104 R/trade edge over
    matched-random: bar selection +0.113 R (p=0.000), signal direction −0.022 R. See
    edgelab/intraday/two_leg_fade.py.

    ENTRY = A WORKING STOP ORDER, and that is not cosmetic. The validated profile enters
    on a SELL STOP one tick under the signal bar's low, and the order EXPIRES if the next
    bar never touches it. A market-entry approximation was measured and is 10 % worse
    (+17.93 vs +20.25 R/yr, t 2.76 vs 3.05) — so `Broker.place_stop` / `cancel_pending`
    were added rather than deploying the approximation.

    THE ORDER LIVES EXACTLY ONE BAR. It is cancelled by US on the next completed bar, not
    by a broker-side expiry: expiry granularity is minutes and varies by symbol, which
    cannot express "one M5 bar".

    1R IS RE-ANCHORED ON THE FILL. The pending order carries SL = trigger + 1R; if price
    gapped through the trigger the backtest measures 1R from the FILL, so the live stop is
    moved to match. Without that, a stop-out would not be −1.00 R.

    ⚠️ The reserves are in the module docstring and they are serious (ex-2020-AND-2022
    t=+1.77; M10 = −1.54 while M5 = +3.05; 2/13 assets; direction flipped a posteriori on
    a 2 709-cell surface). Do not size it up.
    """

    def __init__(self, cfg_live: dict, logical: str):
        from edgelab.intraday.two_leg_fade import TwoLegFadeParams
        self.p = TwoLegFadeParams(size_R=float(cfg_live.get("tlf_size_R", 0.5)))
        self.logical = logical
        self.magic = MAGIC["nas_tlf"] if "NAS" in logical.upper() else MAGIC["spx_tlf"]
        self.bars_needed = int(cfg_live.get("tlf_bars", 600))
        self.max_bar_age_min = float(cfg_live.get("tlf_max_bar_age_min", 2))
        self._acted_bar = None      # last bar we scanned
        self._order_bar = None      # bar whose close armed the working order
        self._anchored = None       # ticket whose SL we already re-anchored on the fill
        self._skip_logged = None

    def _completed(self, broker: Broker, now_utc: pd.Timestamp):
        bars_all = broker.get_bars(self.logical, "M5", self.bars_needed)
        if len(bars_all) < 300:
            return None
        step_ = pd.Timedelta(minutes=5)
        bars = bars_all.iloc[:-1] if (bars_all.index[-1] + step_) > now_utc else bars_all
        return bars if len(bars) else None

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        et = now_utc.tz_convert(self.p.tz)
        minute = et.hour * 60 + et.minute
        open_m, cut_m = _mins(self.p.session_open), _mins(self.p.entry_cutoff)
        flat_m = _mins(self.p.session_close)

        pos = broker.open_position(self.magic)

        # (1) an open position: re-anchor 1R on the fill, then manage it
        if pos is not None:
            self._order_bar = None
            if pos.ticket is not None and self._anchored != pos.ticket:
                want = pos.entry_price - pos.direction * pos.sl_dist
                if abs(want - pos.sl) > 1e-9:
                    broker.modify_sl(pos, want, now_utc)
                self._anchored = pos.ticket
            if not broker.live:
                bar = broker.get_bars(self.logical, "M5", 3).iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc)
                if closed:
                    broker.close(pos, px, why, now_utc)
                    return
            if minute >= flat_m:
                px = float(broker.get_bars(self.logical, "M5", 2).iloc[-1]["close"])
                broker.close(pos, px, "time_exit", now_utc)
            return

        bars = self._completed(broker, now_utc)
        if bars is None:
            return
        last_ts = bars.index[-1]

        # (2) a working order: resolve it, then let it live EXACTLY one bar
        po = broker.pending_order(self.magic)
        if po is not None:
            if self._order_bar is not None and last_ts <= self._order_bar:
                return                                  # still its own bar — wait
            if not broker.live:
                filled = broker.resolve_paper_stop(po, bars.iloc[-1], now_utc)
                if filled is not None:
                    self._order_bar = None
                    return
                po = broker.pending_order(self.magic)
            if po is not None:
                broker.cancel_pending(po, "one_bar_expiry", now_utc)
            self._order_bar = None
            # fall through: this bar may itself arm a new order

        # (3) flat and no order — scan, inside the signal window only
        if not (open_m <= minute <= cut_m + 5):
            return
        if self._acted_bar is not None and last_ts <= self._acted_bar:
            return
        age_min = (now_utc - (last_ts + pd.Timedelta(minutes=5))).total_seconds() / 60.0
        if age_min > self.max_bar_age_min:
            self._acted_bar = last_ts                   # stale -> do NOT chase
            logger.info("tlf %s stale bar %s (%.1f min old) -> skip", self.logical,
                        last_ts, age_min)
            return

        res = S.tlf_scan(bars, self.p, self.logical)
        self._acted_bar = last_ts
        if res is None:
            return
        _, plan = res
        ok, why = risk.can_enter()
        if not ok:
            if self._skip_logged != et.date():
                logger.info("tlf %s skip entry: %s", self.logical, why)
                self._skip_logged = et.date()
            return

        sl = plan.trigger - plan.direction * plan.sl_dist        # short -> SL above
        tp = plan.trigger + plan.direction * plan.tp_dist if plan.tp_dist else None
        budget = risk.risk_budget() * self.p.size_R
        lots = broker.lots_for_risk(self.logical, plan.direction, plan.trigger, sl, budget)
        if lots <= 0:
            logger.warning("tlf %s skip entry at %s: cannot size to %.2fR on the lot grid",
                           self.logical, last_ts, self.p.size_R)
            return
        close_dt = _flat_dt(et, self.p.session_close)
        broker.place_stop(self.logical, plan.direction, lots, plan.trigger, sl, tp,
                          self.magic, f"tlf_{plan.reason}", plan.sl_dist, now_utc,
                          time_exit_at=close_dt)
        self._order_bar = last_ts
