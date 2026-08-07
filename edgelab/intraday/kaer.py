"""KAER — Kaufman Adaptive Efficiency-Ratio intraday breakout (NAS100 M15).

Source: Perry J. Kaufman, *Trading Systems and Methods*, 5th ed. —
  * ch.1 pp.10-14 / ch.20 pp.867-871: the **efficiency ratio** (fractal efficiency) as a
    measure of NOISE, explicitly distinct from volatility;
  * ch.16 pp.759-775: the N-bar intraday breakout, all trades exited on the close;
  * ch.17 p.780: `sc_t = [ER_t*(fast-slow)+slow]^2` — Kaufman reads ER **at the current
    bar**, which is the convention used here;
  * ch.23 pp.1050-1061: a stop must scale with volatility, never a fixed amount.

The rule, on M15 bars of the US cash session:

    ER_t      = |C_t - C_{t-10}| / sum |C_i - C_{i-1}|      over 10 bars
    ER_rank_t = causal percentile of ER_t in its trailing `rank_bars` window
    LONG   if close_t > highest high of the previous 10 bars  and ER_rank_t >= 0.70
    SHORT  if close_t < lowest  low  of the previous 10 bars  and ER_rank_t >= 0.70
    stop   = 2.0 * ATR14 measured at the SIGNAL bar          (1R, mandatory)
    no take-profit; exit = stop, or forced flat at 15:55 ET
    one position at a time; re-arm on the bar the position closes

⚠️ WHAT THIS IS AND IS NOT (2026-08-07, `RESEARCH_LOG_KAUFMAN.md`).
Kaufman's noise LAW — read the state BEFORE the broken range — is directionally right but
worth only +0.010 R/trade against a 0.079 R/trade M15 toll, i.e. ~8x too small to trade.
What survives is ER read **at the signal bar**, which is not a regime filter at all: it is
a **move-quality filter** (buy an efficient one-way break, not a whipsaw). It is also NOT
a decorrelated 5th brick — corr **+0.370** to brick 1 with 40% of its trading days
overlapping, and it replicates on NO other index (US500 t=1.64, GER40 1.30, US30 0.00,
the rest negative). It is deployed on the DEMO account at **half size**, in parallel with
brick 1, purely as a forward test of a possible brick-1 upgrade. Do not size it up and do
not treat its in-sample t as comparable to brick 1's — brick 1 is already forward-committed
and tick-validated (exp-005); KAER's parameters were chosen after seeing the grid.

Execution modelled exactly as the rest of the project: decision at a bar's CLOSE, fill at
the NEXT bar's open; a gap through the stop fills at the worse of (stop, open); cost =
per-bar spread + slippage; R = the trade's own stop distance so a full stop = -1R net.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.orb import POINT_SIZE, load_bars, to_true_utc

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"


@dataclass
class KaerParams:
    session_open: str = "09:30"    # first bar close that may signal (ET)
    entry_cutoff: str = "15:30"    # last bar close that may signal (ET)
    session_close: str = "15:55"   # forced flat (ET)
    tz: str = "America/New_York"
    er_n: int = 10                 # efficiency-ratio lookback (Kaufman: keep it < 14)
    nbrk: int = 10                 # breakout lookback, in bars
    q_hi: float = 0.70             # ER percentile gate (top tercile = efficient move)
    rank_bars: int = 1820          # trailing window for the ER percentile (~20 sessions
                                   # x 91 M15 bars). FIXED, not derived from the loaded
                                   # window, so live and backtest cannot drift apart.
    atr_p: int = 14
    k_stop: float = 2.0            # stop = k_stop * ATR14 -> 1R
    tp_R: float | None = None      # no target: every TP tested degrades it (t 3.19->2.68)
    slippage_points: float = 1.0
    size_R: float = 0.5            # fraction of 1R to actually risk when deployed


@dataclass
class KaerResult:
    symbol: str
    params: KaerParams
    trades: pd.DataFrame
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# indicators — Kaufman's own definitions
# ---------------------------------------------------------------------------
def efficiency_ratio(close: np.ndarray, n: int = 10) -> np.ndarray:
    """ER_t = |C_t - C_{t-n}| / sum |C_i - C_{i-1}|  (TSaM ch.1 p.10, ch.17 p.781).

    1.0 = a straight line over n bars (no noise); 0.0 = pure back-and-forth."""
    close = np.asarray(close, float)
    d = np.abs(np.diff(close, prepend=close[0]))
    vol = pd.Series(d).rolling(n).sum().to_numpy()
    net = np.full(len(close), np.nan)
    net[n:] = np.abs(close[n:] - close[:-n])
    with np.errstate(invalid="ignore", divide="ignore"):
        er = np.where(vol > 0, net / vol, np.nan)
    er[:n] = np.nan
    return er


def wilder_atr(high, low, close, n: int = 14) -> np.ndarray:
    """Wilder ATR, seeded on the first n true ranges — identical to mt4_indicators.atr
    and to the ATR the research sweep used."""
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


def er_percentile(er: np.ndarray, window: int) -> np.ndarray:
    """Causal percentile rank of ER inside its own trailing window, in [0, 1].

    Self-normalising per asset: ch.1's scatter compares markets on their AVERAGE ER, and
    the intraday analogue of "this market is trending" is "this market is more efficient
    now than it usually is". A raw ER threshold would be a fitted constant per asset and
    per timeframe smuggled in as a rule."""
    return (pd.Series(er).rolling(window, min_periods=max(20, window // 4))
            .rank(pct=True).to_numpy())


# ---------------------------------------------------------------------------
# the signal — the ONE function live and backtest share
# ---------------------------------------------------------------------------
def kaer_signals(bars: pd.DataFrame, p: KaerParams | None = None) -> np.ndarray:
    """Decision taken at EACH bar's CLOSE: +1 long, -1 short, 0 nothing.

    ``bars`` must be a TRUE-UTC-indexed OHLC frame of the entry timeframe, with enough
    history in front for the ER percentile window. Nothing here looks past bar i.
    """
    p = p or KaerParams()
    c = bars["close"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    l = bars["low"].to_numpy(float)
    n = len(c)

    hi = pd.Series(h).rolling(p.nbrk).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(p.nbrk).min().shift(1).to_numpy()
    up = np.nan_to_num(c > hi).astype(bool)
    dn = np.nan_to_num(c < lo).astype(bool)

    rank = er_percentile(efficiency_ratio(c, p.er_n), p.rank_bars)
    efficient = np.nan_to_num(rank >= p.q_hi).astype(bool)

    loc = bars.index.tz_convert(p.tz)
    mins = np.asarray(loc.hour * 60 + loc.minute)
    open_m = int(p.session_open[:2]) * 60 + int(p.session_open[3:])
    cut_m = int(p.entry_cutoff[:2]) * 60 + int(p.entry_cutoff[3:])
    in_window = (mins >= open_m) & (mins <= cut_m) & (np.asarray(loc.dayofweek) < 5)

    sig = np.zeros(n, np.int8)
    sig[up & efficient] = 1
    sig[dn & efficient] = -1
    sig[~in_window] = 0
    return sig


def kaer_atr(bars: pd.DataFrame, p: KaerParams | None = None) -> np.ndarray:
    p = p or KaerParams()
    return wilder_atr(bars["high"], bars["low"], bars["close"], p.atr_p)


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_m15(symbol: str, mt5_dir: Path | None = None) -> pd.DataFrame:
    """M15 bars on a TRUE-UTC index. Uses the M15 parquet if present, otherwise
    resamples the M1 cache — the broker only serves ~2 years of M15 directly, while the
    M1 cache reaches back to 2018, and the research numbers are on the resampled series."""
    d = Path(mt5_dir) if mt5_dir else MT5_DIR
    if (d / f"{symbol}_M15.parquet").exists():
        return load_bars(symbol, "M15", d)
    raw = pd.read_parquet(d / f"{symbol}_M1.parquet")
    raw.columns = [c.lower() for c in raw.columns]
    raw["time"] = pd.to_datetime(raw["time"], utc=True)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "spread" in raw.columns:
        agg["spread"] = "median"
    m15 = (raw.set_index("time").resample("15min", label="left", closed="left")
              .agg(agg).dropna(subset=["open"]))
    idx = to_true_utc(pd.DatetimeIndex(m15.index))
    m15 = m15[idx.notna()]
    m15.index = idx[idx.notna()]
    if "spread" not in m15.columns:
        m15["spread"] = 0.0
    return m15.sort_index()


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------
def run_kaer(symbol: str = "NAS100", p: KaerParams | None = None,
             bars: pd.DataFrame | None = None, warmup: int = 250) -> KaerResult:
    """R-based backtest with a MANDATORY stop and a forced session flat.

    Signals fire on a bar close and fill at the NEXT bar's open. The stop is checked
    intrabar (a gap-through fills at the open, i.e. worse). Whatever is still open at the
    last bar before ``session_close`` exits at that bar's close. One position at a time.
    """
    p = p or KaerParams()
    d = bars if bars is not None else load_m15(symbol)
    o = d["open"].to_numpy(float); h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float);  c = d["close"].to_numpy(float)
    n = len(c)
    point = POINT_SIZE.get(symbol, 0.1)
    spread = d["spread"].to_numpy(float) if "spread" in d else np.zeros(n)

    sig = kaer_signals(d, p)
    atr = kaer_atr(d, p)

    loc = d.index.tz_convert(p.tz)
    mins = np.asarray(loc.hour * 60 + loc.minute)
    flat_m = int(p.session_close[:2]) * 60 + int(p.session_close[3:])
    holdable = mins < flat_m
    sess = pd.factorize(loc.normalize())[0]
    # deadline[i] = last bar index of i's own session that may still hold a position
    deadline = np.full(n, -1, dtype=np.int64)
    last = -1
    for i in range(n - 1, -1, -1):
        if i == n - 1 or sess[i] != sess[i + 1]:
            last = -1
        if holdable[i]:
            last = i if last < 0 else max(last, i)
        deadline[i] = last
    deadline[deadline < 0] = np.arange(n)[deadline < 0]

    def cost(i):
        return (0.5 * spread[i] + p.slippage_points) * point

    trades = []
    i = warmup
    while i < n - 1:
        s = int(sig[i])
        if s == 0 or not np.isfinite(atr[i]) or atr[i] <= 0:
            i += 1
            continue
        entry_i = i + 1
        dist = p.k_stop * atr[i]           # ATR as known at the DECISION, not the fill
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
                hit_sl, hit_tp = l[j] <= sl, (tp is not None and h[j] >= tp)
                px_sl = min(sl, o[j]); px_tp = max(tp, o[j]) if tp is not None else None
            else:
                hit_sl, hit_tp = h[j] >= sl, (tp is not None and l[j] <= tp)
                px_sl = max(sl, o[j]); px_tp = min(tp, o[j]) if tp is not None else None
            if hit_sl:                      # PESSIMISTIC: the stop wins a spanning bar
                exit_px, exit_i, why = px_sl, j, "stop"
                break
            if hit_tp:
                exit_px, exit_i, why = px_tp, j, "target"
                break
        if exit_px is None:
            exit_px, exit_i, why = c[end], end, "time_exit"
        net = s * (exit_px - entry) - cost(i) - cost(exit_i)
        trades.append({"entry_time": d.index[entry_i], "exit_time": d.index[exit_i],
                       "direction": s, "entry": entry, "exit": exit_px, "sl": sl,
                       "sl_dist": dist, "R": net / dist, "reason": why,
                       "signal_bar": i, "entry_bar": entry_i, "exit_bar": exit_i})
        i = exit_i                          # re-arm on the bar the position closed
    tr = pd.DataFrame(trades)
    m = {}
    if len(tr):
        R = tr["R"].to_numpy()
        span = max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)
        cum = np.cumsum(R); dd = float(np.max(np.maximum.accumulate(cum) - cum))
        gl = -R[R <= 0].sum()
        m = {"n": len(R), "win": float((R > 0).mean()), "ER": float(R.mean()),
             "R_per_year": float(R.sum() / span),
             "t": float(R.mean() / R.std(ddof=1) * np.sqrt(len(R))),
             "PF": float(R[R > 0].sum() / gl) if gl > 0 else np.inf,
             "maxDD_R": dd, "RoMaD": float((R.sum() / span) / dd) if dd else np.nan}
    return KaerResult(symbol, p, tr, m)


if __name__ == "__main__":  # pragma: no cover
    r = run_kaer()
    print(r.symbol, {k: round(v, 3) for k, v in r.metrics.items()})
