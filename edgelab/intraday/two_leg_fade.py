"""TLF — Two-Leg Fade. NAS100 + US500, M5, short-only, intraday.

WHAT IT IS, AND WHAT IT IS NOT
------------------------------
The bar SELECTION comes from Al Brooks, *Trading Price Action: Trends* (2012): an
always-in trend context (ch. 19), a two-legged pullback inside it (the "high 2 / low 2"
of the glossary, p. xvii-xviii), completed on a strong signal bar (ch. 5, p. 89).

**The DIRECTION is the opposite of what Brooks teaches, and that is the whole point.**
Measured on NAS100 + US500 M5, 2018-2026, on the SAME entry bars:

    direction du signal (Brooks)  E[R] +0.106      tout en SHORT force  E[R] +0.128
    tout en LONG force            E[R] +0.047      sens INVERSE         E[R] -0.006

and against 120 matched-random draws (same bars eligible, same count, same geometry):
random-short −0.018, random-long +0.015, random-mixed +0.001. Decomposition of the
+0.104 R/trade edge over random: **bar SELECTION +0.113 R (108 %, p=0.000 on the short
side), signal DIRECTION −0.022 R (−22 %)**. Brooks' direction is worth nothing here; the
filter's choice of BARS is worth a lot, and on those bars one must SELL.

So: a completed two-leg pullback on a strong signal bar marks EXHAUSTION, not
continuation. Hence the name — Two-Leg Fade — and NOT "Brooks", which would misdescribe
it. (Same discipline the ledger applied to `ADX_System.mq4` and to HMASTO: never let an
author's name circulate as if the author's rule were the validated thing.)

EXECUTION — WHY IT IS A MARKET ENTRY AND NOT A STOP ORDER
---------------------------------------------------------
The research backtest entered on a SELL STOP one tick under the signal bar's low. The
live broker layer of this repo only sends MARKET orders (`Broker.place_market`); there
is no pending-order support, and brick 1 — itself a breakout — is wired the same way
(detect on a completed bar, then market in). Rather than deploy something the backtest
does not describe, the rule was RE-MEASURED under the execution that actually exists:

    signal bar i -> bar i+1 breaks (low[i] - 1 tick) -> MARKET short at the open of i+2

    ordre stop (recherche)        n=1354  E[R] +0.128  +20.25 R/yr  RoMaD 0.74  t_days +3.05
    marche a l'ouverture de i+2   n=1350  E[R] +0.114  +17.93 R/yr  RoMaD 0.71  t_days +2.76

This module implements the SECOND line — the deployable one — and `live/verify.py`
checks it reproduces that backtest trade-for-trade.

⚠️ FORWARD TEST, NOT A PROMOTION. Deployed at 0.5R on the user's explicit instruction.
The reserves are unchanged and they are serious:
  * removing BOTH 2020 and 2022 takes it to t=+1.77 (52.6 % of its R comes from those two years);
  * the detection scale is NOT monotone: M5 +3.05, **M10 −1.54**, M15 +0.91, M30 +0.34;
  * it does not leave US indices: 2/13 assets at t>2, median t −0.57, FX systematically negative;
  * every filter component is load-bearing (drop the leg count -> t +0.13; drop always-in
    -> +0.10; leg 3 instead of leg 2 -> **−0.63**) = a fragile 4-way conjunction;
  * and it was found by FLIPPING THE DIRECTION a posteriori on a 2 709-cell surface.
Do not size it up. Judge it on the trade journal, not on P&L.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.orb import to_true_utc

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"

SLIP_POINTS = 1.0            # per side; a round trip is charged 2 x this
# in-session median feed spread, in points (kauf_lib SPECS 'spread_now'). Indices carry
# no commission on this feed, so the round trip is spread + 2 x slippage and nothing else.
SPREAD_FLOOR = {"NAS100": 10.0, "US500": 4.0}
# ⚠️ Point size is declared HERE and a lookup MISS RAISES. `edgelab.intraday.orb.POINT_SIZE`
# has no US500 entry, and a `.get(sym, 0.01)` fallback silently priced US500 ten times too
# cheap -> the friction gate let through 688 trades instead of 460 (caught by verify).
# A wrong point size is invisible in every metric except the trade count. Never default it.
POINT = {"NAS100": 0.1, "US500": 0.1}
WARMUP = 250


def point_size(symbol: str) -> float:
    try:
        return POINT[symbol]
    except KeyError:
        raise KeyError(
            f"two_leg_fade: no declared point size for {symbol!r}. Add it to POINT "
            f"(and SPREAD_FLOOR) from the broker's symbol_info — do NOT default it.")


@dataclass
class TwoLegFadeParams:
    session_open: str = "09:30"      # first bar close that may signal (ET)
    entry_cutoff: str = "15:30"      # last bar close that may signal (ET)
    session_close: str = "15:55"     # forced flat (ET)
    tz: str = "America/New_York"
    ema_len: int = 20                # Brooks' only moving average (glossary p. xix)
    atr_p: int = 14
    body_min: float = 0.5            # trend bar: body >= half the range (ch. 2)
    pos_min: float = 2 / 3.          # close in the top (resp. bottom) third (ch. 19)
    spike_atr: float = 1.0           # a SPIKE, not any bar: range >= 1 x ATR14
    leg: int = 2                     # high 2 / low 2 (ch. 20 "Two Legs")
    max_pullback_bars: int = 20      # a pullback in a trend is short (ch. 19)
    max_risk_atr: float = 2.0        # skip a setup whose signal bar is too tall
    max_cost_R: float = 0.20         # friction gate: 1R must be >= 5 round trips
    k_stop: float = 3.0              # 1R = 3 x ATR14 at the decision bar
    tp_R: float | None = None        # NO target (a target takes the cost stress negative)
    # 60 bars = 5 h. ⚠️ This used to be commented "the session flat almost always binds
    # first" — it does NOT: the cap is the exit on 58/468 US500 trades (12.4 %) and
    # 106/914 NAS100 (11.6 %). The live driver had no cap at all until 2026-08-12,
    # which cost ~4 % of E[R] (US500 +0.1615 vs +0.1677). Whatever this value is, the
    # driver must read it — `verify_tlf` check (7) is what makes that binding.
    maxbars: int = 60
    bar_minutes: int = 5             # bar spacing; used to clock the NEXT bar
    slippage_points: float = SLIP_POINTS
    size_R: float = 0.5              # fraction of 1R actually risked when deployed
    # "stop"   = the VALIDATED profile: a SELL STOP one tick under the signal bar's low,
    #            living the next bar only. This is what the research measured and what the
    #            live driver now sends (Broker.place_stop, added 2026-08-10).
    # "market" = the fallback used while the broker had no pending-order support; kept so
    #            the two executions stay comparable and the ~10 % they differ by stays
    #            visible (+20.25 vs +17.93 R/yr).
    entry_mode: str = "stop"


# --------------------------------------------------------------------------- primitives
def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x, dtype=float).ewm(span=n, adjust=False).mean().to_numpy()


def wilder_atr(h, l, c, n: int = 14) -> np.ndarray:
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def anatomy(o, h, l, c):
    rng = h - l
    with np.errstate(invalid="ignore", divide="ignore"):
        body = np.where(rng > 0, np.abs(c - o) / rng, 0.0)
        pos = np.where(rng > 0, (c - l) / rng, 0.5)
    return rng, body, pos


def always_in(o, h, l, c, e20, atr, p: TwoLegFadeParams) -> np.ndarray:
    """Brooks' always-in state (glossary p. xiii, ch. 19), as a persistent array.

    Flips LONG on the close of a SPIKE: trend body, close in the top third, range at
    least one ATR, close above the prior bar's high AND above the EMA20. Mirrored for
    short. Between two flips the state PERSISTS — that is the definition of "always in".
    """
    rng, body, pos = anatomy(o, h, l, c)
    ph = np.concatenate(([np.nan], h[:-1]))
    pl = np.concatenate(([np.nan], l[:-1]))
    big = np.isfinite(atr) & (rng >= p.spike_atr * atr)
    up = (c > o) & (body >= p.body_min) & (pos >= p.pos_min) & big & (c > ph) & (c > e20)
    dn = (c < o) & (body >= p.body_min) & (pos <= 1 - p.pos_min) & big & (c < pl) & (c < e20)
    ev = np.where(up, 1, np.where(dn, -1, 0)).astype(np.int8)
    st = pd.Series(np.where(ev == 0, np.nan, ev)).ffill().fillna(0).to_numpy()
    return st.astype(np.int8)


def strong_signal_bar(o, h, l, c, side: int) -> np.ndarray:
    """Brooks' STRONG signal bar (ch. 5 p. 89): trend body AND close in the far third."""
    _, _, pos = anatomy(o, h, l, c)
    if side > 0:
        return (c > o) & (pos >= 2 / 3.)
    return (c < o) & (pos <= 1 / 3.)


def setup_bars(d: pd.DataFrame, p: TwoLegFadeParams | None = None,
               symbol: str = "NAS100") -> np.ndarray:
    """+1/-1 on every bar that COMPLETES a two-leg pullback on a strong signal bar.

    The sign is the side of the PULLBACK (i.e. Brooks' intended trade direction); the
    strategy then trades the OPPOSITE. Phases, straight from the glossary (bull case):

        0  outside a correction — wait for a "pullback bar" (low < prior low, p. xx)
        1  first leg — a bar exceeding the prior bar's high ends it (that IS the high 1)
        2  high 1 done — wait for "a bar with a lower high"
        3  second leg — ARMED: each bar is a signal bar for the high 2

    Reset when the always-in state flips, when the pre-pullback extreme is exceeded (the
    trend resumed, a new pullback must form), or after `max_pullback_bars`.
    """
    p = p or TwoLegFadeParams()
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    n = len(c)
    e20 = ema(c, p.ema_len)
    atr = wilder_atr(h, l, c, p.atr_p)
    ai = always_in(o, h, l, c, e20, atr, p)
    tick = point_size(symbol)

    out = np.zeros(n, np.int8)
    target = 1 + 2 * (p.leg - 1)
    for side in (1, -1):
        qual = strong_signal_bar(o, h, l, c, side)
        phase, start, ext = 0, -1, np.nan
        for i in range(1, n):
            if ai[i] != side:
                phase = 0
                continue
            if phase > 0:
                broke = (h[i] > ext) if side > 0 else (l[i] < ext)
                if broke or (i - start) > p.max_pullback_bars:
                    phase = 0
            if phase == 0:
                pb = (l[i] < l[i - 1]) if side > 0 else (h[i] > h[i - 1])
                if not pb:
                    continue
                phase, start = 1, i
                ext = h[i - 1] if side > 0 else l[i - 1]
            else:
                adv = (h[i] > h[i - 1]) if side > 0 else (l[i] < l[i - 1])
                back = (h[i] < h[i - 1]) if side > 0 else (l[i] > l[i - 1])
                if phase % 2 == 1:
                    if adv:
                        phase += 1
                elif back:
                    phase += 1
            if phase != target or not qual[i]:
                continue
            if not (np.isfinite(atr[i]) and atr[i] > 0):
                continue
            risk = (h[i] + tick) - (l[i] - tick)
            if risk <= 0 or risk > p.max_risk_atr * atr[i]:
                continue
            out[i] = side
    out[:WARMUP + 1] = 0
    return out


def round_trip_cost(d: pd.DataFrame, i: int, symbol: str,
                    p: TwoLegFadeParams | None = None) -> float:
    p = p or TwoLegFadeParams()
    pt = point_size(symbol)
    spr = float(d["spread"].iloc[i]) if "spread" in d.columns else 0.0
    return (max(spr, SPREAD_FLOOR.get(symbol, 0.0)) + 2 * p.slippage_points) * pt


def session_masks(d: pd.DataFrame, p: TwoLegFadeParams):
    """(in_window, deadline) — the entry window and the last holdable bar per session."""
    loc = d.index.tz_convert(p.tz)
    mins = np.asarray(loc.hour * 60 + loc.minute)
    def _m(s):
        return int(s[:2]) * 60 + int(s[3:])
    in_win = (mins >= _m(p.session_open)) & (mins <= _m(p.entry_cutoff)) \
        & (np.asarray(loc.dayofweek) < 5)
    holdable = mins < _m(p.session_close)
    sess = pd.factorize(loc.normalize())[0]
    n = len(d)
    dl = np.full(n, -1, dtype=np.int64)
    last = -1
    for i in range(n - 1, -1, -1):
        if i == n - 1 or sess[i] != sess[i + 1]:
            last = -1
        if holdable[i]:
            last = i if last < 0 else max(last, i)
        dl[i] = last
    dl[dl < 0] = np.arange(n)[dl < 0]
    return in_win, dl


def next_in_window(d: pd.DataFrame, p: TwoLegFadeParams) -> np.ndarray:
    """Is the bar that FOLLOWS each bar inside the entry window? Read off the clock.

    Causal by construction: the session window is a property of the wall clock, not of
    price, so `index + bar_minutes` is knowable at the close of the current bar. That is
    what makes the live decision and the backtest decision the same object."""
    nxt = d.index + pd.Timedelta(minutes=p.bar_minutes)
    loc = nxt.tz_convert(p.tz)
    mins = np.asarray(loc.hour * 60 + loc.minute)
    def _m(x):
        return int(x[:2]) * 60 + int(x[3:])
    return ((mins >= _m(p.session_open)) & (mins <= _m(p.entry_cutoff))
            & (np.asarray(loc.dayofweek) < 5))


def armed_bars(d: pd.DataFrame, p: TwoLegFadeParams | None = None,
               symbol: str = "NAS100") -> np.ndarray:
    """-1 on every SETUP bar that survives the entry window and the friction gate.

    That bar carries the live order: a SELL STOP at ``low - 1 tick``, valid for the NEXT
    bar only. This is the array the "stop" execution trades."""
    p = p or TwoLegFadeParams()
    st = setup_bars(d, p, symbol)
    tick = point_size(symbol)
    n = len(d)
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    # ⚠️ The order is for the NEXT bar, so the next bar's window membership decides. Read
    # it off the CLOCK (index + bar_minutes), never off the next ROW: at decision time the
    # next row does not exist, so a row-based test can never fire on the last bar of a
    # truncated window — which is precisely the bar the live driver is deciding on. (This
    # cost a 100 %-mismatch verify failure on 2026-08-10.) The clock test also refuses to
    # carry an order across a session gap: index+5min lands outside the window there,
    # whereas the next ROW would be tomorrow's 09:30 and would arm an overnight order.
    nxt = next_in_window(d, p)
    out = np.zeros(n, np.int8)
    for i in np.flatnonzero(st != 0):
        if not nxt[i]:
            continue
        risk = (h[i] + tick) - (l[i] - tick)
        if risk <= round_trip_cost(d, i, symbol, p) / p.max_cost_R:
            continue
        out[i] = -1                            # SHORT — the fade
    return out


def trigger_bars(d: pd.DataFrame, p: TwoLegFadeParams | None = None,
                 symbol: str = "NAS100") -> np.ndarray:
    """-1 on every bar that TRIGGERS a live entry: the bar after a setup bar, which
    broke one tick under that setup bar's low. The market order goes in on the NEXT
    bar's open (the driver markets in as soon as this bar completes)."""
    p = p or TwoLegFadeParams()
    st = setup_bars(d, p, symbol)
    in_win, _ = session_masks(d, p)
    tick = point_size(symbol)
    l = d["low"].to_numpy(float)
    n = len(l)
    # friction gate + entry window are checked on the SETUP bar, exactly as measured
    ok = np.zeros(n, bool)
    idx = np.flatnonzero(st != 0)
    for i in idx:
        if i + 1 >= n or not in_win[i + 1]:
            continue
        h_i = float(d["high"].iloc[i]); l_i = float(d["low"].iloc[i])
        risk = (h_i + tick) - (l_i - tick)
        if risk <= round_trip_cost(d, i, symbol, p) / p.max_cost_R:
            continue
        ok[i] = True
    trig = np.zeros(n, np.int8)
    cand = np.flatnonzero(ok)
    cand = cand[cand + 1 < n]
    broke = l[cand + 1] <= (l[cand] - tick)
    trig[cand[broke] + 1] = -1                # SHORT — the fade
    return trig


def load_m5(symbol: str, mt5_dir: Path | None = None) -> pd.DataFrame:
    """M5 bars on a TRUE-UTC index, resampled from the project's M1 cache.

    Same rule as `km_encyclopedia.bars` (label/closed left, spread = median), so the
    live module sees byte-for-byte the bars the research measured."""
    root = Path(mt5_dir) if mt5_dir else MT5_DIR
    p5 = root / f"{symbol}_M5.parquet"
    p1 = root / f"{symbol}_M1.parquet"
    if p1.exists():
        d = pd.read_parquet(p1)
        d.columns = [c.lower() for c in d.columns]
        d["time"] = pd.to_datetime(d["time"], utc=True)
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "spread" in d.columns:
            agg["spread"] = "median"
        d = (d.set_index("time").resample("5min", label="left", closed="left")
               .agg(agg).dropna(subset=["open"]).reset_index())
    elif p5.exists():
        d = pd.read_parquet(p5)
        d.columns = [c.lower() for c in d.columns]
        d["time"] = pd.to_datetime(d["time"], utc=True)
    else:
        raise FileNotFoundError(f"no M1 or M5 cache for {symbol}")
    idx = to_true_utc(pd.DatetimeIndex(d["time"]))
    d = d.loc[idx.notna()].copy()
    d.index = idx[idx.notna()]
    if "spread" not in d.columns:
        d["spread"] = 0.0
    return d.drop(columns=["time"]).sort_index()


@dataclass
class TwoLegFadeResult:
    trades: pd.DataFrame
    triggers: np.ndarray


def run_two_leg_fade(symbol: str = "NAS100", p: TwoLegFadeParams | None = None,
                     bars: pd.DataFrame | None = None) -> TwoLegFadeResult:
    """R-based backtest of the DEPLOYABLE rule (market entry), trade-for-trade.

    Decision on a bar close, fill at the NEXT bar's open. A bar covering both barriers
    resolves PESSIMISTICALLY at the stop. Whatever is still open at the last holdable bar
    of the entry's own session exits at that bar's close. One position at a time; the
    strategy re-arms on the bar the position closes. Cost is charged once, at the
    decision bar's spread. R is the trade's own initial stop distance, so a full stop-out
    is exactly −1 R net of cost."""
    p = p or TwoLegFadeParams()
    d = bars if bars is not None else load_m5(symbol)
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    n = len(c)
    atr = wilder_atr(h, l, c, p.atr_p)
    _, deadline = session_masks(d, p)
    tick = point_size(symbol)
    stop_mode = p.entry_mode == "stop"
    sig = armed_bars(d, p, symbol) if stop_mode else trigger_bars(d, p, symbol)

    rows = []
    idx = np.flatnonzero(sig != 0)
    q = 0
    while q < len(idx):
        i = int(idx[q])
        m = i + 1
        if m >= n or m <= WARMUP:
            q += 1
            continue
        dist = p.k_stop * atr[i]
        if not (np.isfinite(dist) and dist > 0) or deadline[m] < m:
            q += 1
            continue
        if stop_mode:
            # SELL STOP one tick under the signal bar's low, living bar m only.
            trigger = l[i] - tick
            if h[m] < trigger and l[m] > trigger:
                pass                                  # (kept explicit; touch test below)
            if not (l[m] <= trigger):
                q += 1
                continue                              # never touched -> the order expires
            entry = min(trigger, o[m])                # a gap through it costs the gap
        else:
            entry = o[m]
        rt = round_trip_cost(d, i, symbol, p)
        sl = entry + dist                             # short
        tp = entry - p.tp_R * dist if p.tp_R else None
        end = min(m + p.maxbars - 1, n - 1, int(deadline[m]))
        px, xi, why = None, end, "time_exit"
        for j in range(m, end + 1):
            hit_sl = h[j] >= sl
            hit_tp = tp is not None and l[j] <= tp
            if hit_sl:
                px, xi, why = max(sl, o[j]), j, "stop"
                break
            if hit_tp:
                px, xi, why = min(tp, o[j]), j, "target"
                break
        if px is None:
            px, xi = c[end], end
            why = "session_close" if end == int(deadline[m]) else "time_exit"
        R = ((entry - px) - rt) / dist
        rows.append(dict(symbol=symbol, direction=-1, signal_time=d.index[i],
                         entry_time=d.index[m], exit_time=d.index[xi], entry=entry,
                         exit=px, sl=sl, r_dist=dist, R=float(R), reason=why,
                         bars=xi - m + 1,
                         trigger=(l[i] - tick) if stop_mode else float("nan")))
        q = int(np.searchsorted(idx, xi, side="left"))
        q = max(q, int(np.searchsorted(idx, i, side="left")) + 1)
    return TwoLegFadeResult(pd.DataFrame(rows), sig)
