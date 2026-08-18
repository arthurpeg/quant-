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

import numpy as np
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
         "nas_tlf": 109, "spx_tlf": 110,
         # 2026-08-18 : les deux sleeves issues de research/. 111 et 112 sont
         # libres ; a ne pas confondre avec le magic 111111 de l EA etranger
         # [LONNY] mis en quarantaine le 2026-08-10.
         "ger40_rvwap": 111, "us30_rskew": 112}

SERVER_TZ = "Europe/Athens"     # the broker's clock: a D1 bar's date IS its server date
ROLLOVER_LEAD_MIN = 10.0        # send a D-rollover time-exit this many minutes EARLY


def _research_signal(bars: pd.DataFrame, p):
    """S_t de la sleeve research, importe paresseusement (comme partout ici)."""
    from edgelab.intraday.research_sleeves import signal_series
    return signal_series(bars, p)


def _push_alert(cfg: dict, msg: str) -> None:
    """Une ligne Discord ad hoc, depuis une strategie. Ne leve JAMAIS.

    Jumeau de `runner._alert` plutot que son import : `runner` importe `strategies`, et
    faire remonter la dependance dans l'autre sens pour six lignes inverserait les
    couches. `summary` est une feuille (aucun import edgelab), donc ce chemin-ci est sur.
    """
    url = cfg.get("discord_webhook_url")
    if not url:
        return
    try:
        from edgelab.live.summary import send_discord
        send_discord(url, msg, code=False)
    except Exception as exc:
        logger.warning("alerte Discord non envoyee (%s) : %s", exc, msg)


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


def _forming_ibs(bar) -> float:
    """IBS of a bar that is STILL FORMING — its ``close`` is the last traded price.

    NaN on a zero-range bar, so every ``> ibs_high`` test on it is False by construction.
    """
    rng = float(bar["high"]) - float(bar["low"])
    return (float(bar["close"]) - float(bar["low"])) / rng if rng > 0 else float("nan")


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

    ENTRY is once per broker day at the daily-bar rollover (00:00 server), which is where
    the backtest fills (the next bar's open). No TP. The EXITS — ``IBS > ibs_high`` and the
    ``max_hold``-bar timeout — are anticipated to the pre-close LEAD window (23:50 server
    = 22:50 Paris) and leave on the bar that is closing, judging the IBS on that still-
    forming bar; the rollover test on the last CLOSED bar remains as the fallback. That
    trades −0.03 R/yr of gross for +0.21 R/yr of swap never paid — see the exit block.
    The stop is broker-managed and unaffected.

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
            # BOTH exits leave on the bar that is closing, not at its rollover. An exit
            # fired AT 00:00 is sent into the 00:00-01:00 break, so it fills at the REOPEN
            # — one rollover later, and on a Friday that reopen is Monday. The position
            # therefore pays a swap night it never agreed to: 3.20 units per trade against
            # 1.93 leaving on the bar (FTMO NAS100 long −7.52 %/yr, see ftmo_costs).
            # Measured 2018-07..2026-07 on M1 (`scratchpad/ibs_exit_lead.py`):
            #   gross  −0.03 R/yr (+4.80 -> +4.77) — per-trade delta t = −1.05, noise;
            #   swap   +0.21 R/yr saved, deterministic;
            #   NET    +4.27 -> +4.46 R/yr, t 4.57 -> 4.74, maxDD 3.26 -> 3.10 R.
            # The price of reading `IBS > 0.8` 10 minutes from final IS that −0.03 R/yr.
            # ⚠️ The rollover test on the last CLOSED bar stays, as the FALLBACK: if the lead
            # pass is missed (runner down) or the session shut early and quotes nothing at
            # 23:50 (6 of 288 exit days), the next rollover still leaves. The time exit has
            # fired 0/287 times, so `timed*` remains dormant.
            timed_next = held is not None and (held + 1) >= self.p.max_hold
            lead_ibs = bool(in_lead and forming
                            and _forming_ibs(daily_all.iloc[-1]) > self.p.ibs_high)
            if st.exit_signal or timed or ((timed_next or lead_ibs) and in_lead):
                why = "ibs_high" if (st.exit_signal or lead_ibs) else "time_exit"
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
        self.bar_minutes = 15         # cf. HmaStochStrategy: lue par l'alerte de liveness
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
        # UT de la sleeve, en minutes. Lue par `runner._maybe_liveness_alert` pour
        # convertir `_acted_bar` en RETARD DE SCAN : sans elle, on ne peut pas dire si une
        # barre de 16:00 est fraiche (M15) ou vieille de trois barres (M5).
        self.bar_minutes = 15
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
        self.bar_minutes = 60         # cf. HmaStochStrategy: lue par l'alerte de liveness
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

    THREE EXITS, AND NO TARGET. `tp_R` is None on purpose — a target takes the sleeve's
    cost stress negative — so the position leaves on: the broker-side stop at 1R = 3 ×
    ATR14; the forced flat at `session_close` (advanced by `us_session_calendar` on a
    shortened session); or the `maxbars` cap, 60 M5 bars after the entry bar. The cap was
    MISSING live until 2026-08-12 while the backtest always had it — see `step`.

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
        self.bar_minutes = 5        # cf. HmaStochStrategy: lue par l'alerte de liveness
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

    @staticmethod
    def _held(bars: pd.DataFrame, open_time: pd.Timestamp) -> int:
        """Barres M5 COMPLETEES de la position, comptees dans la trame du broker.

        Meme construction que le compteur de Keltner, et pour les memes raisons : le fill
        tombe QUELQUES SECONDES DANS sa barre d'entree (l'ordre stop se declenche en
        intrabarre), donc un ecart brut tronque une barre -- d'ou le `floor` ; et
        `run_two_leg_fade` plafonne sur `end - m`, une distance d'INDEX, pas un nombre de
        minutes ecoulees, donc un trou de flux doit compter pour zero barre et non pour
        les minutes qu'il couvre.

        `bars` ne contient que des barres completees ; le resultat est `maxbars` sur la
        barre ou le backtest sort. `method="ffill"` degrade proprement si la barre
        d'entree elle-meme manque de la trame.
        """
        entry_bar = pd.Timestamp(open_time).floor(pd.Timedelta(minutes=5))
        loc = int(bars.index.get_indexer([entry_bar], method="ffill")[0])
        if loc < 0:
            # 600 barres M5 couvrent ~2 seances et le cap en vaut 60 : inatteignable en
            # pratique. Si ca arrive, le repli surcompte (il lit des minutes, pas des
            # barres) et fait sortir tout de suite -- le bon sens du risque.
            logger.warning("tlf: barre d'entree %s hors de la fenetre de %d barres -> "
                           "repli en minutes ecoulees pour le cap", entry_bar, len(bars))
            return int((bars.index[-1] - entry_bar) / pd.Timedelta(minutes=5)) + 1
        return len(bars) - loc                  # barres loc..derniere, incluses

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
                # premiere fois qu'on voit cette position : l'ordre stop vient de se
                # remplir. C'est le seul instant ou l'entree peut etre journalisee -- rien
                # d'autre ne l'ecrit, l'evenement `stop_order` ne portant que le
                # declencheur, pas le remplissage.
                broker.journal_fill(pos, now_utc)
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
            # LE CAP DE 60 BARRES -- ajoute le 2026-08-12, le live ne l'avait pas.
            # `run_two_leg_fade` sort a `min(m + maxbars - 1, deadline)` : l'aplat de
            # seance passe D'ABORD (au-dessus, egalite comprise) et ce cap prend le relais
            # quand il tombe plus tot. Le commentaire du module disait "the session flat
            # almost always binds first" -- c'est FAUX : le cap mord sur 58/468 trades
            # US500 (12,4 %) et 106/914 NAS100 (11,6 %). Le driver tenait donc ces
            # positions jusqu'a 15:55 alors que le backtest les sortait 5 h apres
            # l'entree : E[R] +0.1615 au lieu de +0.1677 sur US500, +0.0945 au lieu de
            # +0.0989 sur NAS100 (~4 % de l'edge).
            # NOM : le backtest appelle ce cap "time_exit" et l'aplat "session_close" ; le
            # live nomme l'aplat "time_exit" comme la brique 1 et HMASTO, donc ce cap
            # s'appelle "maxbars" -- sinon les deux sorties seraient indistinguables dans
            # le journal.
            bars = self._completed(broker, now_utc)
            if bars is None:
                return
            held = self._held(bars, pos.open_time)
            if held >= self.p.maxbars:
                broker.close(pos, float(bars["close"].iloc[-1]), "maxbars", now_utc)
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


class ResearchSleeveStrategy:
    """FORWARD-TEST SLEEVE — RVWAP (GER40 H1) et RSKEW (US30 H4), issues de `research/`.

    Une instance par sleeve, comme brique 3 pour ses deux coins et TLF pour ses deux
    symboles. Deployees le 2026-08-18 a ``size_R`` sur instruction explicite de
    l'utilisateur.

    CE QU'ELLES TRADENT.
      RVWAP : GER40 H1. Distance au VWAP ancre a l'ouverture de la session NY, en ATR.
              Le signe de l'IC mesure etant NEGATIF, la sleeve SUIT l'ecart au lieu de le
              fader. Sortie a 24 barres H1 ou au stop ; 1R = 3.0 x ATR14.
      RSKEW : US30 H4. Asymetrie des 50 derniers log-rendements, IC POSITIF.
              Sortie a 5 barres H4 ou au stop ; 1R = 4.0 x ATR14.

    PARITE. `S.research_scan` appelle `research_sleeves.decide`, la MEME fonction que
    `run_research_sleeve`. Il n'y a pas deux definitions a garder d'accord.
    `check_live_parity_research.py` rejoue l'historique en TRONQUANT les frames comme MT5
    les sert et exige 0 ecart sur la date d'entree, la date de sortie, la distance de stop
    et le R.

    ⚠️ LA FENETRE TIREE DOIT CONTENIR ASSEZ D'OCCURRENCES, PAS ASSEZ DE BARRES. Le rang
    causal se calcule sur les 1 000 dernieres OCCURRENCES du signal ; le VWAP n'existant
    qu'aux ~6,5 heures de session NY, il faut ~3 700 barres H1 pour en reunir 1 000. C'est
    pourquoi `rvwap_bars` vaut 5 000 et non 600. Une fenetre trop courte ne casse pas
    bruyamment : elle rend un rang DIFFERENT, donc des entrees differentes du backtest.

    ⚠️ IN-SAMPLE, SANS FORWARD-TEST. Tirees d'une grille de 28 300 cellules. KAER, HMASTO
    et TLF sont toutes entrees a 0,5R avant d'etre jugees, et HMASTO a ete retiree de
    FUNDED pour avoir echoue son seul hors-echantillon. Le 1R est une instruction, pas une
    conclusion de mesure.

    Cadence : une passe par barre COMPLETE. La barre en formation est ecartee
    explicitement, et une barre plus vieille que ``max_bar_age_min`` est SAUTEE plutot que
    chassee -- si le runner etait tombe, le fill ne serait plus l'ouverture suivante que le
    backtest mesure.
    """

    def __init__(self, cfg_live: dict, sleeve: str):
        import dataclasses as _dc

        from edgelab.intraday.research_sleeves import SLEEVES as _SL
        base = _SL[sleeve]
        key = sleeve.lower()
        self.p = _dc.replace(base, size_R=float(cfg_live.get(key + "_size_R", 1.0)))
        self.sleeve = sleeve
        self.logical = cfg_live.get(key + "_symbol", base.symbol)
        self.magic = MAGIC["ger40_rvwap" if sleeve == "RVWAP" else "us30_rskew"]
        self.tf = base.timeframe
        self.bar_minutes = base.bar_minutes
        self.bars_needed = int(cfg_live.get(key + "_bars",
                                            5000 if sleeve == "RVWAP" else 1500))
        self.max_bar_age_min = float(cfg_live.get(key + "_max_bar_age_min",
                                                  20 if sleeve == "RVWAP" else 60))
        self.lead_min = float(cfg_live.get("rollover_lead_min", ROLLOVER_LEAD_MIN))
        self.cfg = cfg_live          # pour l'alerte de fenetre (webhook Discord)
        self._acted_bar = None
        self._skip_logged = None
        self._win_alerted = None     # jour de la derniere alerte de fenetre courte

    def _held(self, bars: pd.DataFrame, open_time: pd.Timestamp) -> int:
        """Barres COMPLETES du trade, comptees DANS LE CADRE DU BROKER.

        Un index, jamais des heures d'horloge : les flux ont des trous et
        `run_research_sleeve` plafonne sur une distance d'INDEX. Compter des heures
        divergeait sur 155 des 200 premieres sorties au temps de KELT.
        """
        step = pd.Timedelta(minutes=self.bar_minutes)
        # LA BARRE D'ENTREE SE CHERCHE DANS L'INDEX, JAMAIS SUR L'HORLOGE.
        # `.floor(step)` arrondit sur la grille de l'EPOCH (00:00, 04:00, 08:00...),
        # or les barres H4 du broker tombent a 01/05/09... l'ete et 02/06/10... l'hiver
        # en UTC vraie -- elles ne sont JAMAIS sur cette grille. Le `ffill` rattrapait
        # alors la barre PRECEDENTE et `_held` comptait une barre de trop, donc RSKEW
        # sortait a 4 barres au lieu de 5 (mesure : ecart sur les 7 premieres barres
        # d'un trade, 2026-08-18). H1 y echappait par coincidence : l'heure ronde EST
        # sur la grille. `searchsorted` ne suppose ni alignement ni continuite -- et les
        # flux ont des trous (GER40 n'a pas de barre 23:00).
        entry_bar = pd.Timestamp(open_time)
        loc = int(bars.index.searchsorted(entry_bar, side="right")) - 1
        if loc < 0:
            logger.warning("%s: barre d'entree %s hors de la fenetre de %d barres",
                           self.sleeve, entry_bar, len(bars))
            return int((bars.index[-1] - entry_bar) / step) + 1
        return len(bars) - loc

    def _check_window(self, bars: pd.DataFrame, now_utc: pd.Timestamp) -> None:
        """Crie si la fenetre tiree ne contient plus assez d'OCCURRENCES du signal.

        C'EST LE SEUL MODE DE PANNE ENTIEREMENT SILENCIEUX DE CES DEUX SLEEVES.
        `causal_rank` classe sur `rolling(rank_win, min_periods=rank_min)`, donc :

          * entre `rank_min` et `rank_win` occurrences, le rang est calcule sur une
            fenetre PLUS COURTE que celle du backtest -> le seuil `q` tombe sur un autre
            quantile -> des ENTREES DIFFERENTES, sans la moindre erreur ni exception ;
          * sous `rank_min`, `causal_rank` rend NaN partout, `decide` rend None a chaque
            barre et la sleeve cesse simplement d'entrer.

        Aucun des deux ne se lit dans le journal : une sleeve qui n'entre plus ressemble
        trait pour trait a une sleeve dont le signal ne se declenche pas. Et ce que la
        fenetre contient ne depend pas de nous mais du BROKER (profondeur d'historique
        telechargee, `Max bars in chart` du terminal), donc c'est MESURE a chaque barre
        scannee et jamais suppose : les marges relevees sur le terminal du VPS le
        2026-08-18 sont x1,47 (RVWAP, 1 466 occurrences) et x1,45 (RSKEW, 1 450).

        Le comptage refait `signal_series` a cote du chemin de decision plutot que
        d'instrumenter `decide` : `decide` est la fonction PARTAGEE avec le backtest, et
        la parite prouvee vient precisement de ce qu'elle n'a qu'une definition.

        Une alerte par jour et par sleeve au plus (un H1 en crierait 24).
        """
        occ = int(np.isfinite(_research_signal(bars, self.p)).sum())
        if occ >= self.p.rank_win:
            self._win_alerted = None
            return
        day = now_utc.date()
        if self._win_alerted == day:
            return
        self._win_alerted = day
        blind = occ < self.p.rank_min
        logger.warning("%s FENETRE COURTE : %d occurrences du signal sur %d barres tirees, "
                       "il en faut %d (%s). %s", self.sleeve, occ, len(bars),
                       self.p.rank_win, f"plancher {self.p.rank_min}",
                       "AUCUNE ENTREE POSSIBLE (rang NaN)" if blind else
                       "le rang est calcule sur une fenetre plus courte que le backtest "
                       "-> entrees DIVERGENTES")
        _push_alert(self.cfg,
               f":warning: **{self.sleeve} : FENETRE TROP COURTE** — "
               f"**{occ}** occurrences du signal dans les {len(bars)} barres servies par "
               f"le broker, il en faut **{self.p.rank_win}**"
               + (f" (plancher {self.p.rank_min} : la sleeve N'ENTRE PLUS DU TOUT)."
                  if blind else
                  f" (au-dessus du plancher {self.p.rank_min}, donc elle trade encore — "
                  f"mais sur un rang calcule autrement que le backtest).")
               + f" Cause probable : historique {self.logical} {self.tf} incomplet sur le "
                 f"terminal, ou `Max bars in chart` trop bas. Remede : ouvrir le graphique "
                 f"et le derouler vers le passe, ou augmenter `{self.sleeve.lower()}_bars`.")

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        step_ = pd.Timedelta(minutes=self.bar_minutes)
        bars_all = broker.get_bars(self.logical, self.tf, self.bars_needed)
        if len(bars_all) < 3:
            return
        # ON JETTE LA BARRE EN FORMATION : une barre estampillee t n'est complete qu'a t+UT.
        bars = bars_all.iloc[:-1] if (bars_all.index[-1] + step_) > now_utc else bars_all
        if not len(bars):
            return
        last_ts = bars.index[-1]

        pos = broker.open_position(self.magic)

        # (1) gestion de la position : le broker tient le stop, nous tenons la barriere
        if pos is not None:
            held = self._held(bars, pos.open_time)
            if not broker.live:
                closed, px, why = broker.resolve_paper(pos, bars.iloc[-1], now_utc,
                                                       bars_held=held)
                if closed:
                    broker.close(pos, px, why, now_utc)
                    return
            if held >= self.p.max_bars or ((held + 1) >= self.p.max_bars
                                           and _at_rollover_lead(now_utc, self.lead_min)):
                broker.close(pos, float(bars["close"].iloc[-1]), "time_exit", now_utc)
            return

        # (2) entree, une fois par barre complete
        if self._acted_bar is not None and last_ts <= self._acted_bar:
            return
        age_min = (now_utc - (last_ts + step_)).total_seconds() / 60.0
        if age_min > self.max_bar_age_min:
            self._acted_bar = last_ts
            logger.info("%s barre perimee %s (%.0f min) -> saut", self.sleeve,
                        last_ts, age_min)
            return

        try:
            self._check_window(bars, now_utc)
        except Exception as exc:      # un MONITEUR ne doit jamais tuer ce qu il
            # surveille : la sleeve trade meme si le comptage echoue.
            logger.warning("%s: controle de fenetre impossible (%s)", self.sleeve, exc)

        res = S.research_scan(bars, self.p)
        self._acted_bar = last_ts
        if res is None:
            return
        _, plan = res
        ok, why = risk.can_enter()
        if not ok:
            day = now_utc.date()
            if self._skip_logged != day:
                logger.info("%s entree refusee : %s", self.sleeve, why)
                self._skip_logged = day
            return

        ref = float(bars["close"].iloc[-1])
        sl = ref - plan.direction * plan.sl_dist
        budget = risk.risk_budget() * self.p.size_R
        lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, budget)
        if lots <= 0:
            logger.warning("%s entree impossible a %s : %.2fR non dimensionnable sur la "
                           "grille de lots", self.sleeve, last_ts, self.p.size_R)
            return
        broker.place_market(self.logical, plan.direction, lots, sl, None, self.magic,
                            plan.reason, plan.sl_dist, ref, now_utc,
                            bars_held_limit=self.p.max_bars)
