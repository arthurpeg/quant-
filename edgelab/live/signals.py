"""Pure LIVE signal functions for the 4 frozen bricks.

The whole point of this module: it REUSES the exact indicator math the backtest uses
(Wilder ATR, MACD/RSI EWM, turn-of-month calendar, the low-vol regime gate, IBS) so the
live decision cannot silently diverge from the backtest. Every function here takes a
plain OHLC(V) DataFrame (already on a TRUE-UTC index — see edgelab.intraday.orb.to_true_utc)
and returns a small, explicit decision object. NO order routing, NO MT5 here — this
layer is 100% testable offline against cached bars (see edgelab/live/verify.py).

Bricks:
  1) NAS100 US-open ATR breakout, low-vol regime   -> nas_orb_scan()
  2) XAUUSD turn-of-month, SL=1.5*ATR              -> tom_state()
  3) MACD(12,26,9)+RSI on BTC+ETH                   -> macd_rsi() / crypto_entry()
  4) NAS100 IBS reversion, SL=2.5*ATR               -> ibs_state()
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Reuse the SAME primitives the backtest uses (do not re-implement them here).
from edgelab.intraday.atr_breakout import ATRBreakParams, _wilder_atr
from edgelab.edges.turn_of_month import TurnOfMonthParams
from edgelab.edges.ibs import IBSParams, _wilder_atr as _ibs_wilder_atr
from edgelab.risk.trade_rules import atr as engine_atr  # Wilder ATR, min_periods=window


# ---------------------------------------------------------------------------
# Common decision object
# ---------------------------------------------------------------------------
@dataclass
class EntryPlan:
    """A ready-to-place entry. Prices are absolute; sl_dist is the R distance (price)."""
    direction: int          # +1 long, -1 short
    sl_dist: float          # entry-to-stop distance in price = 1R
    tp_dist: float | None   # entry-to-tp distance in price, or None (ride to time-exit)
    reason: str = ""
    ref_price: float | None = None  # the reference/level price (diagnostic)


# ===========================================================================
# BRICK 1 — NAS100 US-open ATR breakout (low-vol regime)
# ===========================================================================
def nas_regime_ok(atr3: float, atr20: float, p: ATRBreakParams) -> bool:
    """The exp-005 volatility-regime gate. Mirrors run_atr_breakout exactly."""
    if p.regime_mode == "low":
        return bool(atr3 < atr20 * p.regime_factor)
    if p.regime_mode == "high":
        return bool(atr3 > atr20 * p.regime_factor)
    return True  # "off"


def prev_day_atrs(d1: pd.DataFrame, p: ATRBreakParams) -> dict:
    """{ET-date: (atr14, atr3, atr20)} using the PREVIOUS day's D1 ATR (shift 1, causal).

    ``d1`` is the raw D1 frame (broker-time index or a 'time' column), same as
    edgelab.intraday.atr_breakout._atr_by_date but callable on a live-pulled frame.
    """
    d = d1.copy()
    d.columns = [c.lower() for c in d.columns]
    if "time" in d.columns:
        d = d.sort_values("time").reset_index(drop=True)
        dates = pd.to_datetime(d["time"]).dt.date
    else:
        d = d.sort_index()
        dates = pd.Series(d.index).dt.date
    a = pd.DataFrame({
        "atr14": _wilder_atr(d, p.atr_p),
        "atr3": _wilder_atr(d, p.regime_short),
        "atr20": _wilder_atr(d, p.regime_long),
    }).shift(1)
    return {dt: (r.atr14, r.atr3, r.atr20) for dt, r in zip(dates, a.itertuples(index=False))}


def nas_orb_scan(session: pd.DataFrame, atr14: float, atr3: float, atr20: float,
                 p: ATRBreakParams) -> tuple[int, EntryPlan] | None:
    """Scan ONE day's US-cash-session M1 bars for the first ATR breakout.

    ``session`` = that day's bars, TRUE-UTC index, minute-of-session already filtered
    to [session_open, session_close] in ET, columns open/high/low/close.
    Returns ``(confirm_idx, EntryPlan)`` where ``confirm_idx`` is the bar whose CLOSE
    confirms the breakout (the fill is the NEXT bar's open) — so a live driver enters
    at market as soon as the just-closed bar equals ``confirm_idx``. None = no trade.

    Faithfully mirrors edgelab.intraday.atr_breakout.run_atr_breakout's entry logic:
    level = open ± k_break*ATR14(prevD1); confirm on prior bar close; entry-cutoff in ET.
    """
    if not np.isfinite(atr14) or atr14 <= 0:
        return None
    if not nas_regime_ok(atr3, atr20, p):
        return None

    loc = session.index.tz_convert(p.tz)
    sm = (loc.hour * 60 + loc.minute).to_numpy()
    cut_m = int(p.entry_cutoff[:2]) * 60 + int(p.entry_cutoff[3:])
    c = session["close"].to_numpy()
    o = session["open"].to_numpy()
    if len(session) < 2:
        return None

    ref_open = o[0]
    long_lvl = ref_open + p.k_break * atr14
    short_lvl = ref_open - p.k_break * atr14
    sl_dist = p.k_stop * atr14
    tp_dist = sl_dist * p.rr

    # i is the ENTRY bar (fill at o[i]); confirmation is c[i-1]. Entry minute <= cutoff.
    for i in range(1, len(session)):
        if sm[i] > cut_m:
            break
        if p.direction in ("both", "long") and c[i - 1] > long_lvl:
            return i - 1, EntryPlan(+1, sl_dist, tp_dist, "breakout_long", long_lvl)
        if p.direction in ("both", "short") and c[i - 1] < short_lvl:
            return i - 1, EntryPlan(-1, sl_dist, tp_dist, "breakout_short", short_lvl)
    return None


# ===========================================================================
# BRICK 2 — XAUUSD turn-of-month
# ===========================================================================
@dataclass
class TomState:
    in_window: bool          # is `day` inside the turn-of-month trade window?
    is_entry_day: bool       # is `day` the entry day (last trading day of month)?
    is_exit_day: bool        # is `day` the window-end (first_days-th day of next month)?
    sl_dist: float = 0.0     # 1R stop distance in price (= sl_atr * prevATR14)


def _business_tom_flags(day: pd.Timestamp, last_days: int, first_days: int) -> tuple:
    """(in_window, is_entry_day, is_exit_day) using a business-day calendar.

    LIVE approximation of the backtest's trading-day-of-month window: the backtest uses
    actual bars; here we use business days (Mon-Fri). Exchange HOLIDAYS can shift the
    true last/first trading day by ~1 day a few times a year -> re-check against the
    D1 bars in production. Gold trades every weekday so this is a close match.
    """
    day = pd.Timestamp(day).normalize()
    bmonth_end = (day + pd.offsets.BMonthEnd(0))            # last business day of THIS month
    # last `last_days` business days of the month:
    last_window_start = bmonth_end - pd.offsets.BDay(last_days - 1)
    # first `first_days` business days of the NEXT month:
    next_first = (day + pd.offsets.BMonthBegin(1)) if day > bmonth_end else \
        ((bmonth_end + pd.offsets.BDay(1)))
    first_window_end = next_first + pd.offsets.BDay(first_days - 1)

    in_last = last_window_start.normalize() <= day <= bmonth_end.normalize()
    in_first = next_first.normalize() <= day <= first_window_end.normalize()
    is_entry = day == bmonth_end.normalize()
    is_exit = day == first_window_end.normalize()
    return (in_last or in_first), is_entry, is_exit


def tom_state(d1: pd.DataFrame, day: pd.Timestamp,
              p: TurnOfMonthParams | None = None) -> TomState:
    """Turn-of-month state for ``day``, with the 1R stop distance from prev-day ATR14.

    ``d1`` = XAUUSD daily bars (TRUE-UTC index or 'time' col) up to at least yesterday.
    """
    p = p or TurnOfMonthParams()
    d = d1.copy()
    d.columns = [c.lower() for c in d.columns]
    if "time" in d.columns:
        d["t"] = pd.to_datetime(d["time"], utc=True)
        d = d.set_index("t")
    d = d[["open", "high", "low", "close"]].astype(float).sort_index()
    atr_prev = _wilder_atr(d, p.atr_p).shift(1)             # prev-day ATR (causal)

    in_win, is_entry, is_exit = _business_tom_flags(day, p.last_days, p.first_days)
    sl_dist = 0.0
    if is_entry:
        # ATR as known the day BEFORE entry = last available value strictly before `day`
        prior = atr_prev[atr_prev.index.tz_convert("UTC").tz_localize(None).normalize()
                         <= pd.Timestamp(day).normalize()]
        val = float(prior.iloc[-1]) if len(prior) else np.nan
        if np.isfinite(val) and val > 0:
            sl_dist = p.sl_atr * val
    return TomState(in_win, is_entry, is_exit, sl_dist)


# ===========================================================================
# BRICK 3 — MACD(12,26,9)+RSI on BTC+ETH (the canonical arXiv 2206.12282 signal)
# ===========================================================================
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def macd_rsi(d: pd.DataFrame) -> pd.Series:
    """Target position in {-1,0,+1} per bar. IDENTICAL to the frozen backtest signal."""
    c = d["close"]
    m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = m.ewm(span=9, adjust=False).mean()
    r = rsi(c)
    base = (m > sig).astype(int) - (m < sig).astype(int)
    return base.where(((base > 0) & (r > 50)) | ((base < 0) & (r < 50)), 0).fillna(0).astype(int)


def crypto_entry(daily: pd.DataFrame, risk_cfg: dict) -> EntryPlan | None:
    """Given completed daily bars, the entry to open at the NEXT bar (if currently flat).

    Mirrors the daily BacktestEngine semantics for brick 3: signal on the last closed
    bar t -> fill at open of t+1; SL = stop_loss_atr*ATR14(t), TP = take_profit_atr*ATR14(t);
    time-exit after ``time_exit_bars`` bars (enforced by the runner). Holds through signal
    flips (the engine ignores new signals while in a position). None = stay flat.
    """
    if len(daily) < 40:
        return None
    target = int(macd_rsi(daily).iloc[-1])
    if target == 0:
        return None
    a = engine_atr(daily, int(risk_cfg["atr_window"]))
    entry_atr = float(a.iloc[-1])                          # ATR at the signal bar = entry_atr
    if not np.isfinite(entry_atr) or entry_atr <= 0:
        return None
    sl_dist = float(risk_cfg["stop_loss_atr"]) * entry_atr
    tp_rr = risk_cfg.get("take_profit_rr")
    if tp_rr is not None:
        tp_dist = float(risk_cfg["stop_loss_atr"]) * float(tp_rr) * entry_atr
    else:
        tp_dist = float(risk_cfg["take_profit_atr"]) * entry_atr
    return EntryPlan(target, sl_dist, tp_dist, f"macd_rsi_{'long' if target>0 else 'short'}")


# ===========================================================================
# BRICK 4 — NAS100 IBS reversion (exp-009)
# ===========================================================================
@dataclass
class IbsState:
    """Decision for the NEXT bar's open, computed from the last CLOSED daily bar."""
    ibs: float               # IBS of the last closed bar (nan if the bar had zero range)
    entry_ok: bool           # IBS < ibs_low and a usable stop -> open LONG at the next open
    exit_signal: bool        # IBS > ibs_high -> close at the next open
    sl_dist: float = 0.0     # 1R in price = sl_atr * ATR14 (see the lag note below)


def ibs_state(daily: pd.DataFrame, p: IBSParams | None = None) -> IbsState:
    """IBS decision from CLOSED daily bars — mirrors edgelab.edges.ibs.run_ibs exactly.

    ``daily`` = completed D1 bars (the still-forming bar of the current broker day must be
    dropped by the caller), columns open/high/low/close, oldest first.

    Index alignment with the backtest loop (entry bar ``t``, signal bar ``t-1``):
      * entry test   ``ibs[t-1] < ibs_low``   -> here ``ibs.iloc[-1]`` (last closed bar);
      * 1R distance  ``sl_atr * atr[t-1]`` where run_ibs's ``atr`` is ALREADY
        ``_wilder_atr(...).shift(1)`` — so the stop uses the ATR through bar ``t-2``, one
        bar staler than the signal bar. That double lag is the FROZEN rule (it is what
        produced t=4.68); it is reproduced here on purpose, not corrected.
      * exit test    ``ibs[t] > ibs_high`` -> also ``ibs.iloc[-1]``, acted on at the next open.
    """
    p = p or IBSParams()
    d = daily.copy()
    d.columns = [c.lower() for c in d.columns]
    d = d[["open", "high", "low", "close"]].astype(float)
    # Only what run_ibs itself requires: >=2 bars (the ATR is an EWM, finite from the start)
    # plus finite IBS/ATR. Do NOT impose a longer warm-up here — that would silently skip
    # entries the backtest takes (verify catches it).
    if len(d) < 2:
        return IbsState(float("nan"), False, False, 0.0)

    h, l, c = d["high"], d["low"], d["close"]
    rng = (h - l).replace(0.0, np.nan)
    last_ibs = float(((c - l) / rng).iloc[-1])

    atr_lagged = _ibs_wilder_atr(d, p.atr_p).shift(1)      # == run_ibs's `atr` series
    atr_val = float(atr_lagged.iloc[-1])
    sl_dist = p.sl_atr * atr_val if np.isfinite(atr_val) and atr_val > 0 else 0.0

    ok = bool(np.isfinite(last_ibs))
    return IbsState(ibs=last_ibs,
                    entry_ok=ok and last_ibs < p.ibs_low and sl_dist > 0,
                    exit_signal=ok and last_ibs > p.ibs_high,
                    sl_dist=sl_dist)
