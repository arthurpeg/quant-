"""KELT — BTCUSD H1 Keltner-band breakout (Kaufman, TSaM 5th ed. ch.8 "Bands and Channels").

Found by the 2026-08-07 cross-asset pass: the whole Kaufman canon was run over 18 assets
and the survivors concentrated on crypto at **16.8x** the rate a matched-random-signal
placebo produces on H1 (6.4x on D1), while forex, US and EU indices came out at or BELOW
the noise rate. This is the single strongest cell of that pass.

The rule, on H1 bars of BTCUSD (24/7):

    band  = EMA(close, 20) +/- 1.5 * ATR_Wilder(20)
    LONG   if close_t > upper band
    SHORT  if close_t < lower band
    stop   = 3.0 * ATR_Wilder(14), **floored at 25x the spread**   (1R, mandatory)
    target = 2R
    time exit after 96 bars (4 days)
    one position at a time; re-arm on the bar the position closes

⚠️ TWO DIFFERENT ATRs, on purpose and not interchangeable: the BAND uses ATR(20) (it is
part of the indicator), the STOP uses ATR(14) (it is the project's standard bracket).

⚠️ THE 25x-SPREAD FLOOR IS PART OF THE RULE, not a refinement. Without it the screened
cell reads +27.1 R/yr; with it, +17.2. The floor exists because the crypto post-mortem
(ledger, 2026-08-04) showed that a stop barely wider than the spread inflates R/yr without
the trade being real — 5% of this cell's unfloored trades had 1R below 5x the spread.
Every number below and every live order is the FLOORED version.

WHAT IT IS AND IS NOT (`RESEARCH_LOG_KAUFMAN2.md` §7b).
It clears every gate this project owns: Null A p=0.000, **Null B (sign permutation)
p=0.000 on a null median of -0.07** (no drift to hide behind), 9/9 positive years, both
split halves beat their own null, cost-IMMUNE (+20 broker points a side moves t from 4.25
to 4.23), and it survives the 25x floor (t 4.25 -> 3.13).
It is NOT a decorrelated 5th brick: monthly correlation to brick 3 is +0.07 to +0.23
depending on the cadence brick 3 is measured on, so it is a **second crypto-trend sleeve**
(an hourly cousin of the daily MACD), not a new mechanism. It is also selected as 1 cell
of 722 crypto-H1 survivors, and it decays across the sample (+35.8 R/yr early, +18.2 late).
Deployed on the DEMO at **half size** as a forward test, exactly like KAER.

Why the H1 friction wall does not bite here, when it has killed every other H1 result in
this project: 3xATR(H1) on BTCUSD is an enormous 1R against a crypto spread (median 44x
after flooring), so the toll is a rounding error. That is a property of the INSTRUMENT,
not of the rule — do not expect it to transfer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.orb import to_true_utc

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"

# Pepperstone BTCUSD: price is quoted to 0.01, and the spread column is in those points.
POINT = 0.01
SPREAD_FLOOR_PTS = 1500.0     # broker's own current spread, used as a floor on the feed
SLIPPAGE_PTS = 1.0


@dataclass
class KeltParams:
    ema_n: int = 20            # band centre
    atr_band_n: int = 20       # band width ATR
    k_band: float = 1.5        # band = EMA +/- k_band * ATR(atr_band_n)
    atr_stop_n: int = 14       # bracket ATR (the project's standard)
    k_stop: float = 3.0        # stop = k_stop * ATR(atr_stop_n)  -> 1R
    tp_R: float = 2.0          # target = tp_R * 1R
    max_bars: int = 96         # time exit, in H1 bars (4 days)
    floor_spread: float = 25.0  # 1R may never be under this many spreads
    size_R: float = 0.5        # fraction of 1R actually risked when deployed


@dataclass
class KeltResult:
    symbol: str
    params: KeltParams
    trades: pd.DataFrame
    metrics: dict = field(default_factory=dict)


def wilder_atr(high, low, close, n: int) -> np.ndarray:
    """Wilder ATR seeded on the first n true ranges — identical to the research engine."""
    high, low, close = map(lambda x: np.asarray(x, float), (high, low, close))
    pc = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - pc), np.abs(low - pc)))
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(close)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def band_atr(high, low, close, n: int) -> np.ndarray:
    """The BAND's ATR. `tsam_rules.wilder_atr` uses an EWM with alpha=1/n (no seeding),
    and the band must reproduce it exactly or the signal array changes."""
    high, low, close = map(lambda x: np.asarray(x, float), (high, low, close))
    pc = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - pc), np.abs(low - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def keltner_signals(bars: pd.DataFrame, p: KeltParams | None = None) -> np.ndarray:
    """Decision at EACH bar's CLOSE: +1 long, -1 short, 0 nothing. Nothing looks ahead."""
    p = p or KeltParams()
    c = bars["close"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    l = bars["low"].to_numpy(float)
    mid = pd.Series(c).ewm(span=p.ema_n, adjust=False).mean().to_numpy()
    at = band_atr(h, l, c, p.atr_band_n)
    up, dn = mid + p.k_band * at, mid - p.k_band * at
    sig = np.zeros(len(c), np.int8)
    sig[np.nan_to_num(c > up).astype(bool)] = 1
    sig[np.nan_to_num(c < dn).astype(bool)] = -1
    return sig


def stop_distance(bars: pd.DataFrame, i: int, p: KeltParams | None = None) -> float:
    """1R for a signal at bar `i`: k_stop * ATR(14)[i], floored at floor_spread spreads.

    `i` is the SIGNAL bar; the fill is bar i+1's open, and both the ATR and the spread are
    read at i, i.e. as they were known when the decision was taken."""
    p = p or KeltParams()
    a = wilder_atr(bars["high"], bars["low"], bars["close"], p.atr_stop_n)[i]
    if not np.isfinite(a) or a <= 0:
        return 0.0
    spr = float(bars["spread"].iloc[i]) if "spread" in bars else SPREAD_FLOOR_PTS
    spread_px = max(spr, SPREAD_FLOOR_PTS) * POINT
    return float(max(p.k_stop * a, p.floor_spread * spread_px))


def load_h1(symbol: str = "BTCUSD", mt5_dir: Path | None = None) -> pd.DataFrame:
    d = Path(mt5_dir) if mt5_dir else MT5_DIR
    df = pd.read_parquet(d / f"{symbol}_H1.parquet")
    df.columns = [c.lower() for c in df.columns]
    idx = to_true_utc(pd.DatetimeIndex(pd.to_datetime(df["time"], utc=True)))
    df = df[idx.notna()]
    df.index = idx[idx.notna()]
    cols = [c for c in ("open", "high", "low", "close", "spread") if c in df.columns]
    return df[cols].astype(float).sort_index()


def run_keltner(symbol: str = "BTCUSD", p: KeltParams | None = None,
                bars: pd.DataFrame | None = None, warmup: int = 250,
                extra_cost_pts: float = 0.0) -> KeltResult:
    """R-based backtest with the MANDATORY floored stop, a 2R target and a 96-bar cap.

    Signal at a bar's close, fill at the next bar's open; a bar spanning both barriers is
    resolved PESSIMISTICALLY as the stop; a gap through a barrier fills at the worse of
    (barrier, open); cost charged once per trade at the SIGNAL bar's spread.
    """
    p = p or KeltParams()
    d = bars if bars is not None else load_h1(symbol)
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    n = len(c)
    spr = d["spread"].to_numpy(float) if "spread" in d else np.full(n, SPREAD_FLOOR_PTS)
    spread_pts = np.maximum(spr, SPREAD_FLOOR_PTS)
    rt = (spread_pts + 2 * (SLIPPAGE_PTS + extra_cost_pts)) * POINT
    spread_px = spread_pts * POINT

    sig = keltner_signals(d, p)
    atr_s = wilder_atr(h, l, c, p.atr_stop_n)

    trades = []
    i = warmup
    while i < n - 1:
        s = int(sig[i])
        if s == 0 or not np.isfinite(atr_s[i]) or atr_s[i] <= 0:
            i += 1
            continue
        dist = max(p.k_stop * atr_s[i], p.floor_spread * spread_px[i])
        m = i + 1
        end = min(m + p.max_bars - 1, n - 1)
        entry = o[m]
        sl = entry - s * dist
        tp = entry + s * p.tp_R * dist
        px, xi, why = None, end, "time_exit"
        for j in range(m, end + 1):
            if s > 0:
                hit_sl, hit_tp = l[j] <= sl, h[j] >= tp
                p_sl, p_tp = min(sl, o[j]), max(tp, o[j])
            else:
                hit_sl, hit_tp = h[j] >= sl, l[j] <= tp
                p_sl, p_tp = max(sl, o[j]), min(tp, o[j])
            if hit_sl:
                px, xi, why = p_sl, j, "stop"
                break
            if hit_tp:
                px, xi, why = p_tp, j, "target"
                break
        if px is None:
            px, xi, why = c[end], end, "time_exit"
        net = s * (px - entry) - rt[i]
        trades.append({"entry_time": d.index[m], "exit_time": d.index[xi], "direction": s,
                       "entry": entry, "exit": px, "sl": sl, "tp": tp, "sl_dist": dist,
                       "R": net / dist, "reason": why,
                       "signal_bar": i, "entry_bar": m, "exit_bar": xi})
        i = xi
    tr = pd.DataFrame(trades)
    m_ = {}
    if len(tr):
        R = tr["R"].to_numpy()
        span = max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)
        cum = np.cumsum(R); dd = float(np.max(np.maximum.accumulate(cum) - cum))
        gl = -R[R <= 0].sum()
        m_ = {"n": len(R), "win": float((R > 0).mean()), "ER": float(R.mean()),
              "R_per_year": float(R.sum() / span),
              "t": float(R.mean() / R.std(ddof=1) * np.sqrt(len(R))),
              "PF": float(R[R > 0].sum() / gl) if gl > 0 else np.inf,
              "maxDD_R": dd, "RoMaD": float((R.sum() / span) / dd) if dd else np.nan}
    return KeltResult(symbol, p, tr, m_)


if __name__ == "__main__":  # pragma: no cover
    r = run_keltner()
    print(r.symbol, {k: round(v, 4) for k, v in r.metrics.items()})
