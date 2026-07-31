"""IBS reversion edge (brick #4 candidate).

Family: intraday-position reversion. IBS = Internal Bar Strength =
``(close - low) / (high - low)`` — where the close sits inside the day's range. A low
IBS = closed near the low = oversold within the bar → buy weakness; exit on strength
(high IBS) or a time-out. Origin: user Pine v5 "ES NIBBA" (see
[[exp-009-ibs-reversion-4th-brick]]).

Found on **US equity indices** (NAS100 t=4.68, US500 3.36, US2000 2.70; Europe/Asia ≈ 0),
net of cost, robust to split-half + cost + bootstrap, and **decorrelated** from all three
existing bricks (|corr| ≤ 0.02). Long-only reversion → structurally long equity beta:
size ≤ 1R, do not over-weight. Reported as a trades frame with an ``R`` column so it
composes with the other bricks in the portfolio / Monte-Carlo.

Rule (Pine base + mandatory ATR stop):
    entry : IBS < ibs_low  & flat  -> fill at NEXT bar open
    stop  : entry - sl_atr*ATR14 (set at entry, prev-day ATR -> R = that distance)
    exits : STOP intrabar (low<=stop, gap-aware) | IBS>ibs_high at close -> next open
            | held >= max_hold bars -> next open
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"


@dataclass
class IBSParams:
    ibs_low: float = 0.20        # buy when IBS below this
    ibs_high: float = 0.80       # exit when IBS above this
    max_hold: int = 30           # time-exit after this many bars
    sl_atr: float = 2.5          # stop = sl_atr * ATR14(prev day); R = that distance
    atr_p: int = 14
    cost_price: float = 2.0      # round-trip cost in PRICE units (NAS100 ~2pt; cost-robust to 6)


def _load_d1(symbol: str) -> pd.DataFrame:
    for ext in (".parquet", ".csv"):
        p = MT5_DIR / f"{symbol}_D1{ext}"
        if p.exists():
            d = pd.read_parquet(p) if ext == ".parquet" else pd.read_csv(p)
            d.columns = [c.lower() for c in d.columns]
            d["t"] = pd.to_datetime(d["time"], utc=True)
            return d.set_index("t")[["open", "high", "low", "close"]].astype(float).sort_index()
    raise FileNotFoundError(f"no D1 file for {symbol}")


def _wilder_atr(d: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = d["high"], d["low"], d["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def run_ibs(symbol: str = "NAS100", params: IBSParams | None = None) -> pd.DataFrame:
    """R-based IBS backtest with a MANDATORY stop. One position at a time.

    Signals fire on a bar close and fill at the NEXT bar's open (Pine default). The stop
    is checked intrabar on the daily low (gap-aware: a gap-through fills at the open).
    Returns a trades frame with an ``R`` column (net of round-trip cost) and ``exit_dt``.
    """
    p = params or IBSParams()
    d = _load_d1(symbol)
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
    rng = np.where((h - l) == 0, np.nan, h - l)
    ibs = (c - l) / rng
    atr = _wilder_atr(d, p.atr_p).shift(1).to_numpy()   # prev-day ATR (causal, known at entry)
    idx = d.index
    n = len(d)

    in_pos = False
    entry_bar = -1
    entry_px = stop = risk = np.nan
    trades: list[dict] = []

    for t in range(n):
        if in_pos:
            reason = None
            exit_px = np.nan
            if l[t] <= stop:                                   # intrabar stop
                exit_px = stop if o[t] >= stop else o[t]        # gap-through -> open
                reason = "stop"
            else:
                sig = (ibs[t] > p.ibs_high) or ((t - entry_bar) >= p.max_hold)
                if sig and t + 1 < n:
                    exit_px = o[t + 1]
                    reason = "ibs" if ibs[t] > p.ibs_high else "time"
                elif sig:
                    exit_px = c[t]
                    reason = "eod"
            if reason:
                R = (exit_px - entry_px - p.cost_price) / risk
                trades.append({"entry_dt": pd.Timestamp(idx[entry_bar]).tz_localize(None),
                               "exit_dt": pd.Timestamp(idx[t]).tz_localize(None),
                               "entry": entry_px, "exit": exit_px, "reason": reason,
                               "bars_held": t - entry_bar, "r_dist": risk, "R": R})
                in_pos = False

        if (not in_pos) and t >= 1 and (ibs[t - 1] < p.ibs_low) \
                and np.isfinite(ibs[t - 1]) and np.isfinite(atr[t - 1]) and atr[t - 1] > 0:
            entry_bar = t
            entry_px = o[t]
            risk = p.sl_atr * atr[t - 1]
            stop = entry_px - risk
            in_pos = True
            if l[t] <= stop:                                    # entry-bar intrabar stop
                exit_px = stop if o[t] >= stop else o[t]
                R = (exit_px - entry_px - p.cost_price) / risk
                trades.append({"entry_dt": pd.Timestamp(idx[t]).tz_localize(None),
                               "exit_dt": pd.Timestamp(idx[t]).tz_localize(None),
                               "entry": entry_px, "exit": exit_px, "reason": "stop",
                               "bars_held": 0, "r_dist": risk, "R": R})
                in_pos = False

    return pd.DataFrame(trades)


def ibs_daily_R(symbol: str = "NAS100", params: IBSParams | None = None,
                start: pd.Timestamp | None = None) -> pd.Series:
    """Daily-R series (R summed on exit dates) — composes with the other bricks."""
    tr = run_ibs(symbol, params)
    s = pd.Series(tr["R"].to_numpy(), index=pd.to_datetime(tr["exit_dt"]))
    s = s.groupby(s.index.normalize()).sum()
    if start is not None:
        s = s[s.index >= start]
    s.name = f"ibs_{symbol}"
    return s
