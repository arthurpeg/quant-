"""exp-005 style ATR breakout — the vendor EA construction, reproduced in R.

Difference vs the textbook ORB in ``orb.py``: the entry levels are the US-open
price ± ``k_break``·ATR(D1, prev day) (not the opening-range high/low), the barriers
are ATR-based (SL = ``k_stop``·ATR14, TP = SL·``rr``), and there is a **volatility-
regime filter** (trade only when ATR3 </> ATR20·factor). This is the construction
[[exp-005]] validated on real ticks (PF ~1.2-1.3); here we run it on real M1.

Causal: level uses YESTERDAY's D1 ATR (shift 1); breakout confirmed on the prior
bar's close, filled at the current bar's open; barriers resolved intrabar with the
stop winning ties. R = SL distance, so a full stop = -1R (minus real per-bar cost).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.orb import POINT_SIZE, load_bars, to_true_utc

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"


@dataclass
class ATRBreakParams:
    session_open: str = "09:30"        # US cash open (ET)
    entry_cutoff: str = "11:05"        # stop looking for a breakout after this (ET)
    session_close: str = "15:55"       # forced flat (ET)
    tz: str = "America/New_York"
    k_break: float = 0.25              # entry level = open ± k_break * ATR14(prev D1)
    k_stop: float = 0.25               # SL distance = k_stop * ATR14
    rr: float = 2.0                    # TP = SL * rr
    atr_p: int = 14
    regime_short: int = 3
    regime_long: int = 20
    regime_factor: float = 1.0
    regime_mode: str = "low"           # "low" | "high" | "off"
    direction: str = "both"            # "both" | "long" | "short"
    slippage_points: float = 1.0


@dataclass
class ATRBreakResult:
    symbol: str
    trades: pd.DataFrame
    metrics: dict = field(default_factory=dict)


def _wilder_atr(d1: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = d1["high"], d1["low"], d1["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def _atr_by_date(symbol: str, p: ATRBreakParams) -> dict:
    """Previous-day D1 ATR (14/short/long) keyed by ET calendar date."""
    d1 = pd.read_parquet(MT5_DIR / f"{symbol}_D1.parquet")
    d1.columns = [c.lower() for c in d1.columns]
    d1 = d1.sort_values("time").reset_index(drop=True)
    a = pd.DataFrame({
        "atr14": _wilder_atr(d1, p.atr_p),
        "atr3": _wilder_atr(d1, p.regime_short),
        "atr20": _wilder_atr(d1, p.regime_long),
    }).shift(1)                                  # previous day -> no leak
    dates = pd.to_datetime(d1["time"]).dt.date
    return {dt: (r.atr14, r.atr3, r.atr20) for dt, r in zip(dates, a.itertuples(index=False))}


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def run_atr_breakout(symbol: str, params: ATRBreakParams | None = None,
                     timeframe: str = "M1") -> ATRBreakResult:
    p = params or ATRBreakParams()
    point = POINT_SIZE.get(symbol, 0.1)
    df = load_bars(symbol, timeframe)
    atr_map = _atr_by_date(symbol, p)

    local = df.tz_convert(p.tz)
    open_m, cut_m, close_m = _mins(p.session_open), _mins(p.entry_cutoff), _mins(p.session_close)
    day_key = local.index.tz_localize(None).normalize().to_numpy()
    work = df.copy()
    work["_m"] = (local.index.hour * 60 + local.index.minute).to_numpy()

    def cost(spread_pts: float) -> float:
        return (0.5 * spread_pts + p.slippage_points) * point

    trades = []
    for _d, g in work.groupby(day_key, sort=True):
        m = g["_m"].to_numpy()
        sess = g[(m >= open_m) & (m <= close_m)]
        sm = m[(m >= open_m) & (m <= close_m)]
        if len(sess) < 10:
            continue
        et_day = pd.Timestamp(sess.index[0]).tz_convert(p.tz).date()
        atrs = atr_map.get(et_day)
        if atrs is None or not np.isfinite(atrs[0]) or atrs[0] <= 0:
            continue
        atr14, atr3, atr20 = atrs

        # volatility-regime gate
        if p.regime_mode == "low" and not (atr3 < atr20 * p.regime_factor):
            continue
        if p.regime_mode == "high" and not (atr3 > atr20 * p.regime_factor):
            continue

        o = sess["open"].to_numpy(); h = sess["high"].to_numpy()
        lo = sess["low"].to_numpy(); c = sess["close"].to_numpy()
        sp = sess["spread"].to_numpy(); tms = sess.index

        ref_open = o[0]
        long_lvl = ref_open + p.k_break * atr14
        short_lvl = ref_open - p.k_break * atr14
        sl_dist = p.k_stop * atr14
        tp_dist = sl_dist * p.rr

        # find first confirmed breakout within the entry window (prev-close crosses level)
        direction = 0; entry_i = None
        for i in range(1, len(sess)):
            if sm[i] > cut_m:
                break
            if p.direction in ("both", "long") and c[i - 1] > long_lvl:
                direction = 1; entry_i = i; break
            if p.direction in ("both", "short") and c[i - 1] < short_lvl:
                direction = -1; entry_i = i; break
        if entry_i is None:
            continue

        entry = o[entry_i]
        stop = entry - direction * sl_dist
        take = entry + direction * tp_dist
        entry_cost = cost(sp[entry_i])
        exit_px = None; reason = "time_exit"; exit_cost = 0.0; exit_t = tms[-1]
        for j in range(entry_i, len(sess)):
            hit_stop = lo[j] <= stop if direction == 1 else h[j] >= stop
            hit_take = h[j] >= take if direction == 1 else lo[j] <= take
            if hit_stop:            # pessimistic: stop wins ties
                exit_px, reason = stop, "stop"
            elif hit_take:
                exit_px, reason = take, "take"
            if exit_px is not None:
                exit_cost = cost(sp[j]); exit_t = tms[j]; break
        if exit_px is None:
            exit_px = c[-1]; exit_cost = cost(sp[-1]); reason = "time_exit"

        net = direction * (exit_px - entry) - entry_cost - exit_cost
        trades.append({"date": et_day, "direction": direction, "entry_time": tms[entry_i],
                       "exit_time": exit_t, "entry": entry, "exit": exit_px, "reason": reason,
                       "r_dist": sl_dist, "R": net / sl_dist})

    tdf = pd.DataFrame(trades)
    return ATRBreakResult(symbol=symbol, trades=tdf, metrics=_metrics(tdf))


def _metrics(t: pd.DataFrame) -> dict:
    if t is None or t.empty:
        return {"n_trades": 0}
    R = t["R"]; wins = R[R > 0]; losses = R[R <= 0]
    gl = -losses.sum()
    span = max((pd.to_datetime(t["date"]).max() - pd.to_datetime(t["date"]).min()).days / 365.25, 1e-9)
    cum = R.cumsum()
    return {
        "n_trades": int(len(R)), "win_rate": float((R > 0).mean()),
        "expectancy_R": float(R.mean()), "total_R": float(R.sum()),
        "R_per_year": float(R.sum() / span),
        "profit_factor": float(wins.sum() / gl) if gl > 0 else float("inf"),
        "max_dd_R": float((cum.cummax() - cum).max()),
        "sharpe_per_trade": float(R.mean() / R.std(ddof=0)) if R.std(ddof=0) > 0 else 0.0,
        "pct_stop": float((t["reason"] == "stop").mean()),
        "pct_take": float((t["reason"] == "take").mean()),
        "pct_timeexit": float((t["reason"] == "time_exit").mean()),
    }
