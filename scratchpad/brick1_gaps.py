"""How often does brick 1 go N days without a trade? + why it skipped a given day.

Answers the operational question "no trade for 3-4 days - normal?" with the
strategy's OWN historical gap distribution, from the frozen backtest.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams, _mins
from edgelab.intraday.orb import load_bars
from edgelab.live import signals as S

p = ATRBreakParams(regime_mode="low", direction="both")
res = run_atr_breakout("NAS100", p, "M1")
tr = res.trades
dates = pd.to_datetime(pd.Series(tr["date"].astype(str))).dt.normalize()
print(f"backtest: {len(tr)} trades, {dates.min().date()} -> {dates.max().date()}")

# --- trading-day universe (days the session actually exists) ---
m1 = load_bars("NAS100", "M1")
loc = m1.index.tz_convert(p.tz)
open_m, close_m = _mins(p.session_open), _mins(p.session_close)
mins = loc.hour * 60 + loc.minute
sess_days = pd.Series(pd.to_datetime(loc.normalize().tz_localize(None)))[
    (mins >= open_m) & (mins <= close_m)]
counts = sess_days.value_counts()
univ = np.sort(counts[counts >= 10].index.values)          # real session days
print(f"session days: {len(univ)}  ({len(tr)/len(univ)*100:.1f}% of days carry a trade)")

# --- gap distribution, in SESSION days ---
pos = {d: i for i, d in enumerate(pd.to_datetime(univ))}
idx = sorted(pos[d] for d in dates if d in pos)
gaps = np.diff(idx)                                        # session days between trades
print("\nGAP between consecutive brick-1 trades (in trading days):")
for q in (50, 75, 90, 95, 99):
    print(f"  p{q:<3} = {np.percentile(gaps, q):.0f} days")
print(f"  max  = {gaps.max()} days")
for n in (2, 3, 4, 5, 7, 10):
    share = (gaps >= n).mean()
    print(f"  P(gap >= {n:2d} days) = {share*100:5.1f}%   "
          f"({int((gaps>=n).sum())} times in {len(gaps)} gaps)")

# how many droughts of >=4 trading days per year?
yrs = (pd.to_datetime(univ[-1]) - pd.to_datetime(univ[0])).days / 365.25
for n in (4, 5, 7):
    print(f"  droughts of >={n} days: {(gaps>=n).sum()} in {yrs:.1f} yrs "
          f"= {(gaps>=n).sum()/yrs:.1f}/yr")

# --- WHY each of the last N session days did or did not trade ---
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
print(f"\nLAST {N} SESSION DAYS - decision + reason (cached data):")
d1 = pd.read_parquet("data_cache_mt5/NAS100_D1.parquet")
atr_map = S.prev_day_atrs(d1, p)
traded = set(dates)
work = m1.copy()
work["_m"] = mins.to_numpy()
day_key = loc.normalize().tz_localize(None).to_numpy()
for d in univ[-N:]:
    day = pd.Timestamp(d)
    g = work[day_key == d]
    sess = g[(g["_m"] >= open_m) & (g["_m"] <= close_m)]
    atrs = atr_map.get(day.date())
    if atrs is None or not np.isfinite(atrs[0]):
        print(f"  {day.date()}  no ATR context"); continue
    atr14, atr3, atr20 = atrs
    regime = S.nas_regime_ok(atr3, atr20, p)
    r = S.nas_orb_scan(sess[["open", "high", "low", "close"]], atr14, atr3, atr20, p)
    tag = "TRADE" if day in traded else "  -  "
    why = ("regime HIGH-vol -> gated OFF" if not regime else
           ("breakout, entry" if r is not None else "low-vol OK but no breakout in window"))
    print(f"  {day.date()} {tag}  atr3/atr20={atr3/atr20:5.2f} (gate <{p.regime_factor})  {why}")
