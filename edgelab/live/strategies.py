"""Stateful LIVE drivers for the three bricks: signals -> orders via the broker.

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
from edgelab.live import signals as S
from edgelab.live.broker import Broker
from edgelab.live.risk import LiveRiskManager

logger = logging.getLogger("edgelab.live.strategies")

MAGIC = {"nas_orb": 101, "gold_tom": 102, "btc_macd": 103, "eth_macd": 104}


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


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


class GoldTomStrategy:
    """Brick 2 — XAUUSD turn-of-month. Daily; ~1 trade/month."""

    def __init__(self, cfg_live: dict):
        self.p = TurnOfMonthParams(sl_atr=1.5)
        self.logical = cfg_live.get("gold_symbol", "XAUUSD")
        self.magic = MAGIC["gold_tom"]
        self.decision_min = _mins(cfg_live.get("daily_decision_et", "09:45"))
        self._acted_day = None

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        et = now_utc.tz_convert("America/New_York")
        minute = et.hour * 60 + et.minute
        # act once per day, shortly after the ET open (one clean decision point)
        if et.date() == self._acted_day or minute < self.decision_min:
            return

        d1 = broker.get_bars(self.logical, "D1", 90)
        day = pd.Timestamp(et.date())
        st = S.tom_state(d1, day, self.p)
        pos = broker.open_position(self.magic)

        # exit on the window-end day (or dry-run SL)
        if pos is not None:
            if not broker.live:
                bar = d1.iloc[-1]
                closed, px, why = broker.resolve_paper(pos, bar, now_utc)
                if closed:
                    broker.close(pos, px, why, now_utc); self._acted_day = et.date(); return
            if st.is_exit_day:
                px = float(d1.iloc[-1]["close"])
                broker.close(pos, px, "time_exit", now_utc)
            self._acted_day = et.date()
            return

        # entry on the last-trading-day of the month
        if st.is_entry_day and st.sl_dist > 0:
            ok, why = risk.can_enter()
            if not ok:
                logger.info("brick2 skip entry: %s", why); self._acted_day = et.date(); return
            ref = float(d1.iloc[-1]["close"])
            sl = ref - st.sl_dist               # long only
            lots = broker.lots_for_risk(self.logical, +1, ref, sl, risk.risk_budget())
            broker.place_market(self.logical, +1, lots, sl, None, self.magic,
                                "brick2_turn_of_month", st.sl_dist, ref, now_utc)
        self._acted_day = et.date()


class CryptoMacdStrategy:
    """Brick 3 — MACD(12,26,9)+RSI on one coin (BTCUSD or ETHUSD). Daily; holds multi-day."""

    def __init__(self, cfg_live: dict, logical: str, risk_cfg: dict):
        self.logical = logical
        self.magic = MAGIC["btc_macd"] if "BTC" in logical else MAGIC["eth_macd"]
        self.risk_cfg = risk_cfg
        self.time_exit_bars = int(risk_cfg["time_exit_bars"])
        self.decision_min = _mins(cfg_live.get("daily_decision_et", "09:45"))
        self._acted_day = None

    def step(self, broker: Broker, risk: LiveRiskManager, now_utc: pd.Timestamp) -> None:
        et = now_utc.tz_convert("America/New_York")
        minute = et.hour * 60 + et.minute
        if et.date() == self._acted_day or minute < self.decision_min:
            return

        # RAW broker-time D1 (clean date keying). Drop the still-forming bar of the
        # current broker day so the DECISION uses the last CLOSED bar (matches backtest);
        # keep the forming bar (daily_all) for the current price / intraday paper resolve.
        raw = broker.get_bars_raw(self.logical, "D1", 320)
        raw["time"] = pd.to_datetime(raw["time"], utc=True)
        daily_all = raw.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
        server_today = pd.Timestamp(now_utc).tz_convert("Europe/Athens").date()
        forming = len(daily_all) > 0 and daily_all.index[-1].date() == server_today
        daily = daily_all.iloc[:-1] if forming else daily_all   # completed bars only
        pos = broker.open_position(self.magic)

        if pos is not None:
            bars_held = (now_utc.normalize() - pos.open_time.normalize()).days  # crypto trades 7d/7
            if not broker.live:
                bar = daily_all.iloc[-1]                          # current forming bar for SL/TP touch
                closed, px, why = broker.resolve_paper(pos, bar, now_utc, bars_held=bars_held)
                if closed:
                    broker.close(pos, px, why, now_utc); self._acted_day = et.date(); return
            if bars_held >= self.time_exit_bars:
                broker.close(pos, float(daily_all.iloc[-1]["close"]), "time_exit", now_utc)
            self._acted_day = et.date()
            return

        plan = S.crypto_entry(daily, self.risk_cfg)              # decide on CLOSED bars
        if plan is not None:
            ok, why = risk.can_enter()
            if not ok:
                logger.info("brick3 %s skip entry: %s", self.logical, why); self._acted_day = et.date(); return
            ref = float(daily_all.iloc[-1]["close"])   # current price for the market entry
            sl = ref - plan.direction * plan.sl_dist
            tp = ref + plan.direction * plan.tp_dist if plan.tp_dist else None
            lots = broker.lots_for_risk(self.logical, plan.direction, ref, sl, risk.risk_budget())
            broker.place_market(self.logical, plan.direction, lots, sl, tp, self.magic,
                                f"brick3_{plan.reason}", plan.sl_dist, ref, now_utc,
                                bars_held_limit=self.time_exit_bars)
        self._acted_day = et.date()
