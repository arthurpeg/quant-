"""HMASTO — HMA/EMA crossover with triple-oscillator confirmation (NAS100 M15 intraday).

Origin: a TradingView Pine script, signal ``fee9c1a8ce7d`` of the 2026-08-10 corpus
campaign (`scratchpad/_inx/pine_specs.json`). It is the ONE survivor of that campaign
that is not a channel breakout, which is why it is not redundant with brick 1.

The rule, on M15 bars of the US cash session:

    hma        = HMA(close, 12)
    emaShifted = EMA(close, 5)[2]                     # the EMA as of 2 bars ago
    rsi        = RSI(close, 14)                       # Wilder
    k1         = SMA(stoch(close, high, low, 12), 3)
    k2         = SMA(stoch(close, high, low,  5), 3)

    LONG   if close > hma and close > emaShifted and rsi > 50
              and k1 > 50 and k2 > 50 and hma crosses ABOVE emaShifted
    SHORT  if close < hma and close < emaShifted and rsi < 50
              and k1 < 50 and k2 < 50 and hma crosses BELOW emaShifted

    1R     = max(1.0 * ATR14 at the SIGNAL bar, 25 * spread at the signal bar)
    no take-profit; exit = stop, or forced flat at the session close
    one position at a time; re-arm on the bar the position closes

⚠️ TWO THINGS THIS MODULE IS NOT, both measured (2026-08-10, wiki/log.md).

**(1) It is NOT "the author's strategy".** The Pine script specifies a STRUCTURE stop
(long: lowest low of the 2 previous bars) and a target at 1.65R. Backtested to the letter
that specification FAILS: t=1.88, RoMaD 0.41, 6/9 positive years — and without the target
t=2.40, RoMaD 0.51, 5/9. What clears the bar is the ENTRY CONDITION placed in this
project's pre-declared ATR bracket with NO target: t=3.39, RoMaD 1.53, 8/9. Do not let the
script's name travel as if it were the validated object; the same caution the handoff
imposes for ``ADX_System.mq4``.

**(2) It is NOT a 5th brick.** It correlates **+0.335 monthly (+0.323 daily) with KAER** —
same asset, same timeframe, same intraday-following family — which is why it REPLACES
KAER rather than joining it. Adding it on top of KAER raises the book's maxDD 17.1 -> 20.0
and its funded ruin 7.3% -> 12.3% at 0.5%/trade; swapping cuts maxDD to 15.3 and ruin to
3.8%. Against everything else in the book it is genuinely decorrelated: b1 +0.133,
b2 -0.310, b3 -0.140, **b4 (IBS, same NAS100 underlying) -0.148**.

⚠️ AND IT IS MONO-ASSET, IN-SAMPLE, AND THE BEST OF 112 BY RoMaD on the one asset where
the campaign's selection pressure is strongest (NAS100: real cohort 54.4% survival vs
15.2% placebo). It does not replicate: US30 t=1.59, GER40 1.59, US500 -0.19, FRA40 -0.98,
XAUUSD -0.16. It is deployed at ``size_R`` (0.5R) in KAER's forward-test slot on the DEMO,
on the user's explicit instruction (2026-08-10), NOT as a promoted brick. Do not size it up.

COST MODEL — THIS IS THE PART THAT MUST NOT DRIFT. The validated numbers come from the
campaign engine (`scratchpad/kauf_lib.Table`), whose convention differs from
``kaer.py``'s: 1R carries a **25x-spread floor**, and the round-trip cost is the **full**
spread + 2 slippage points + commission, charged once at the SIGNAL bar (the last spread
known when the trade is decided). ATR and spread are both read at the SIGNAL bar, never at
the fill bar, which would be look-ahead. `verify.py` re-derives the trade list against the
campaign engine; if that check ever fails, this module has forked and must not trade.

Execution: decision at a bar's CLOSE, fill at the NEXT bar's open; a bar covering both
barriers resolves PESSIMISTICALLY at the stop; a gap through a barrier fills at the worse
of the two; R = the trade's own stop distance, so a full stop = -1R net.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.orb import POINT_SIZE, load_bars, to_true_utc

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"

SLIP_POINTS = 1.0           # per side; the engine charges 2 x this per round trip
SPREAD_FLOOR_POINTS = 10.0  # NAS100 in-session spread floor (kauf_lib SPECS 'spread_now')


@dataclass
class HmaStochParams:
    session_open: str = "09:30"     # first bar close that may signal (ET)
    entry_cutoff: str = "15:30"     # last bar close that may signal (ET)
    session_close: str = "15:55"    # forced flat (ET)
    tz: str = "America/New_York"
    hma_len: int = 12
    ema_len: int = 5
    ema_shift: int = 2
    rsi_len: int = 14
    stoch_fast: int = 5
    stoch_slow: int = 12
    stoch_smooth: int = 3
    level: float = 50.0
    atr_p: int = 14
    k_stop: float = 1.0             # 1R = k_stop * ATR14 at the signal bar...
    spread_floor: float = 25.0      # ...floored at this many spreads (KELT lesson)
    # NO target. Swept over 11 values (0.5 -> 6 R) against this None on 2026-08-17
    # (wiki/log.md): not one of them beats it, on any metric, and the curve is MONOTONE
    # in tp_R -- it converges to None FROM BELOW, so there is no interior optimum. The
    # cause is the shape of the distribution, not the level: 117 trades above +4 R
    # (5.3 % of the flow) make +768 R while the other 2082 make -440 R, so a target is
    # precisely the instrument that cuts the tail that pays for every stop. Watch the
    # trap it documents: TP=0.5R RAISES the hit rate to 64.2 % (from 35.2 %) and returns
    # -15.2 R/yr. Do not re-sweep this finer.
    tp_R: float | None = None
    slippage_points: float = SLIP_POINTS
    size_R: float = 0.5             # fraction of 1R actually risked when deployed


# --------------------------------------------------------------------------- primitives
# Mirrored bar-for-bar on the transpiler that produced the validated signal
# (`scratchpad/tv_indicators.py` + `mt4_indicators.py`). Re-implemented here rather than
# imported so `edgelab` never depends on `scratchpad`, and cross-checked in verify.py.
def _sma(x, n):
    """Rolling mean computed as an EXPLICIT windowed sum, not pandas' running sum.

    ⚠️ THIS DEVIATES FROM THE TRANSPILER ON PURPOSE, and it is the single most important
    line in this module. `pd.Series.rolling(n).mean()` maintains a running sum (add the
    entering value, subtract the leaving one), so its float64 rounding error depends on
    ALL the data before the window — the result is not a pure function of the last n
    values. Measured consequence (2026-08-10): at 2018-04-10 16:15 UTC the 12-bar
    stochastic is EXACTLY 50 (close at the midpoint of the range), and its SMA(3) came out
    as 49.999999999999964 over full history but 50.00000000000001 through the live
    driver's 400-bar window. The rule tests `k1 < 50`, so the same bar was a SHORT in the
    backtest and nothing live — a live-vs-backtest fork of 1 trade in 2200, invisible to
    any test that does not replay the truncated window.

    An explicit per-window sum is a pure function of the last n values, so live and
    backtest cannot disagree. It also happens to be the CORRECT answer here: the true
    value is 50, and `50 < 50` is false, so the backtest's short was the rounding error,
    not the driver's silence. Cost: exactly one trade out of 2200 versus the transpiled
    reference (t 3.3872 -> 3.3844), documented in verify.py."""
    x = np.asarray(x, float)
    if n <= 1:
        return x.copy()
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        acc = np.zeros(len(x) - n + 1)
        for k in range(n):                      # fixed summation order, window-local
            acc += x[k:len(x) - n + 1 + k]
        out[n - 1:] = acc / n
    return out


def _wma(x, n):
    w = np.arange(1, n + 1, dtype=float)
    return (pd.Series(x, dtype=float)
            .rolling(n).apply(lambda v: np.dot(v, w) / w.sum(), raw=True).to_numpy())


def _hma(x, n):
    half = _wma(x, max(int(n / 2), 1))
    full = _wma(x, n)
    return _wma(2 * half - full, max(int(np.sqrt(n)), 1))


def _ema(x, n):
    s = pd.Series(x, dtype=float).ewm(span=n, adjust=False).mean()
    s.iloc[:n - 1] = np.nan
    return s.to_numpy()


def _shift(a, k):
    r = np.roll(np.asarray(a, float), k)
    if k > 0:
        r[:k] = np.nan
    return r


def _rsi(price, n=14):
    """Wilder RSI, seeded as MT4's iRSI (the transpiler's `mt4_indicators.rsi`)."""
    p = np.asarray(price, float)
    d = np.diff(p, prepend=p[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(p), np.nan)
    ad = np.full(len(p), np.nan)
    if len(p) <= n:
        return au
    au[n] = up[1:n + 1].mean()
    ad[n] = dn[1:n + 1].mean()
    for i in range(n + 1, len(p)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + au / np.where(ad == 0, np.nan, ad))
    out[np.isfinite(au) & (ad == 0)] = 100.0
    return out


def _stoch(c, h, l, n):
    """Pine ta.stoch(close, high, low, n) -- the RAW %K, unsmoothed."""
    hi = pd.Series(h, dtype=float).rolling(n).max()
    lo = pd.Series(l, dtype=float).rolling(n).min()
    den = (hi - lo).replace(0, np.nan)
    return (100.0 * (pd.Series(c, dtype=float) - lo) / den).to_numpy()


def _crossed_up(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    out = np.zeros(len(a), bool)
    out[1:] = (a[:-1] <= b[:-1]) & (a[1:] > b[1:])
    return out


def _crossed_dn(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    out = np.zeros(len(a), bool)
    out[1:] = (a[:-1] >= b[:-1]) & (a[1:] < b[1:])
    return out


def hma_atr(d: pd.DataFrame, p: HmaStochParams | None = None) -> np.ndarray:
    """Wilder ATR, seeded on the first n true ranges (the project's `kauf_lib.atr`)."""
    p = p or HmaStochParams()
    n = p.atr_p
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def in_window(d: pd.DataFrame, p: HmaStochParams | None = None) -> np.ndarray:
    """Bars whose CLOSE may produce a signal: weekdays, session_open..entry_cutoff ET."""
    p = p or HmaStochParams()
    loc = d.index.tz_convert(p.tz)
    mins = np.asarray(loc.hour * 60 + loc.minute)

    def hm(s):
        return int(s[:2]) * 60 + int(s[3:])

    return ((mins >= hm(p.session_open)) & (mins <= hm(p.entry_cutoff))
            & (np.asarray(loc.dayofweek) < 5))


def hma_signals(d: pd.DataFrame, p: HmaStochParams | None = None) -> np.ndarray:
    """+1 long / -1 short / 0 flat, on the bar whose CLOSE decides. Causal throughout."""
    p = p or HmaStochParams()
    c = d["close"].to_numpy(float)
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)

    hma = _hma(c, p.hma_len)
    ema_sh = _shift(_ema(c, p.ema_len), p.ema_shift)
    rsi = _rsi(c, p.rsi_len)
    k1 = _sma(_stoch(c, h, l, p.stoch_slow), p.stoch_smooth)
    k2 = _sma(_stoch(c, h, l, p.stoch_fast), p.stoch_smooth)
    up = _crossed_up(hma, ema_sh)
    dn = _crossed_dn(hma, ema_sh)
    L = (c > hma) & (c > ema_sh) & (rsi > p.level) & (k1 > p.level) & (k2 > p.level) & up
    S = (c < hma) & (c < ema_sh) & (rsi < p.level) & (k1 < p.level) & (k2 < p.level) & dn

    w = in_window(d, p)
    sig = np.zeros(len(c), np.int8)
    sig[np.nan_to_num(L, nan=False).astype(bool) & w] = 1
    sig[np.nan_to_num(S, nan=False).astype(bool) & w & ~np.nan_to_num(L, nan=False).astype(bool)] = -1
    return sig


def stop_distance(d: pd.DataFrame, i: int, p: HmaStochParams | None = None,
                  atr: np.ndarray | None = None, symbol: str = "NAS100") -> float:
    """1R for a signal at bar ``i``: k_stop x ATR14, FLOORED at 25 spreads.

    Both inputs are read at the SIGNAL bar -- the last values known when the trade is
    decided. The floor is not cosmetic: it is what forbids trades whose toll would eat
    the R (the KELT lesson), and removing it inflates the sleeve."""
    p = p or HmaStochParams()
    atr = hma_atr(d, p) if atr is None else atr
    a = float(atr[i])
    if not np.isfinite(a) or a <= 0:
        return 0.0
    point = POINT_SIZE.get(symbol, 0.1)
    spread_pts = float(d["spread"].iloc[i]) if "spread" in d.columns else 0.0
    spread_px = max(spread_pts, SPREAD_FLOOR_POINTS) * point
    return float(max(p.k_stop * a, p.spread_floor * spread_px))


def round_trip_cost(d: pd.DataFrame, i: int, p: HmaStochParams | None = None,
                    symbol: str = "NAS100") -> float:
    """Round-trip friction in PRICE units, charged once, at the SIGNAL bar's spread."""
    p = p or HmaStochParams()
    point = POINT_SIZE.get(symbol, 0.1)
    spread_pts = float(d["spread"].iloc[i]) if "spread" in d.columns else 0.0
    return (max(spread_pts, SPREAD_FLOOR_POINTS) + 2 * p.slippage_points) * point


@dataclass
class HmaStochResult:
    trades: pd.DataFrame
    signals: np.ndarray


def load_m15(symbol: str = "NAS100", mt5_dir: Path | None = None) -> pd.DataFrame:
    """M15 bars on a TRUE-UTC index — delegated to the loader KAER already uses.

    Deliberately NOT a second implementation: this sleeve took KAER's live slot, so it
    must see byte-for-byte the same bars, including KAER's M15-parquet-else-resample-M1
    fallback. Two loaders would be two ways to drift."""
    from edgelab.intraday.kaer import load_m15 as _kaer_load_m15
    return _kaer_load_m15(symbol, mt5_dir)


def run_hma_stoch(symbol: str = "NAS100", p: HmaStochParams | None = None,
                  bars: pd.DataFrame | None = None, warmup: int = 250) -> HmaStochResult:
    """R-based backtest reproducing the campaign engine trade-for-trade.

    Signals fire on a bar close and fill at the NEXT bar's open. A bar covering both
    barriers resolves PESSIMISTICALLY at the stop. Whatever is still open at the last
    holdable bar of the entry's own session exits at that bar's close. One position at a
    time; the strategy re-arms on the bar the position closes, so a signal on the exit bar
    is allowed."""
    p = p or HmaStochParams()
    d = bars if bars is not None else load_m15(symbol)
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    n = len(c)

    sig = hma_signals(d, p)
    atr = hma_atr(d, p)

    loc = d.index.tz_convert(p.tz)
    mins = np.asarray(loc.hour * 60 + loc.minute)
    flat_m = int(p.session_close[:2]) * 60 + int(p.session_close[3:])
    holdable = mins < flat_m
    sess = pd.factorize(loc.normalize())[0]
    deadline = np.full(n, -1, dtype=np.int64)
    last = -1
    for i in range(n - 1, -1, -1):
        if i == n - 1 or sess[i] != sess[i + 1]:
            last = -1
        if holdable[i]:
            last = i if last < 0 else max(last, i)
        deadline[i] = last
    deadline[deadline < 0] = np.arange(n)[deadline < 0]

    trades = []
    i = max(warmup, p.atr_p + 2)
    while i < n - 1:
        s = int(sig[i])
        if s == 0:
            i += 1
            continue
        dist = stop_distance(d, i, p, atr, symbol)
        if dist <= 0:
            i += 1
            continue
        rt = round_trip_cost(d, i, p, symbol)
        entry_i = i + 1
        end = int(deadline[entry_i])
        if end < entry_i:
            i += 1
            continue
        entry = o[entry_i]
        sl = entry - s * dist
        tp = entry + s * p.tp_R * dist if p.tp_R else None
        exit_px, exit_i, why = None, end, "time_exit"
        for j in range(entry_i, end + 1):
            if s > 0:
                hit_sl = l[j] <= sl
                hit_tp = tp is not None and h[j] >= tp
                px_sl = min(sl, o[j])
                px_tp = max(tp, o[j]) if tp is not None else None
            else:
                hit_sl = h[j] >= sl
                hit_tp = tp is not None and l[j] <= tp
                px_sl = max(sl, o[j])
                px_tp = min(tp, o[j]) if tp is not None else None
            if hit_sl:                      # PESSIMISTIC: the stop wins a spanning bar
                exit_px, exit_i, why = px_sl, j, "stop"
                break
            if hit_tp:
                exit_px, exit_i, why = px_tp, j, "target"
                break
        if exit_px is None:
            exit_px, exit_i, why = c[end], end, "time_exit"
        R = (s * (exit_px - entry) - rt) / dist
        trades.append(dict(signal_time=d.index[i], entry_time=d.index[entry_i],
                           exit_time=d.index[exit_i], direction=s, entry=entry,
                           exit=exit_px, sl_dist=dist, reason=why, R=R,
                           signal_i=i, exit_i=exit_i))
        i = exit_i                          # re-arm on the exit bar
    return HmaStochResult(pd.DataFrame(trades), sig)
