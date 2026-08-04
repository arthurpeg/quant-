"""Which live exit convention reproduces brick 2's backtest exit?

The backtest exits at the CLOSE of the ``first_days``-th trading day of month M+1.
The live driver acts at the daily ROLLOVER, where the price it can get is the OPEN of
the day it wakes up on. So there are two candidate conventions:

  (A) fire on the exit day itself  -> fills at the OPEN of the 2nd trading day
  (B) fire on the NEXT trading day -> fills at the OPEN of the 3rd = the close of the
      2nd, except across a weekend gap (2nd trading day = Friday).

This measures both against the backtest's own exit, in R.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edgelab.edges.turn_of_month import TurnOfMonthParams, _load_d1, _wilder_atr

p = TurnOfMonthParams(sl_atr=1.5)
d = _load_d1("XAUUSD")
atr = _wilder_atr(d, p.atr_p).shift(1)
month = pd.PeriodIndex(d.index.tz_localize(None), freq="M")
tdom = pd.Series(np.arange(len(d)), index=d.index).groupby(month).rank().astype(int)
o, h, l, c = (d["open"].to_numpy(), d["high"].to_numpy(),
              d["low"].to_numpy(), d["close"].to_numpy())
atr_a, months, tdom_a = atr.to_numpy(), month.to_numpy(), tdom.to_numpy()
idx = d.index
cost_frac = 2 * p.cost_bps / 1e4

last_pos = {}
for i in range(len(idx)):
    last_pos[months[i]] = i
uniq = list(dict.fromkeys(months))

rows = []
for k in range(len(uniq) - 1):
    m, mn = uniq[k], uniq[k + 1]
    ei = last_pos[m]
    nxt = np.where((months == mn) & (tdom_a <= p.first_days))[0]
    if len(nxt) == 0:
        continue
    xi = nxt[-1]                                   # the first_days-th trading day of M+1
    entry_atr = atr_a[ei]
    if not np.isfinite(entry_atr) or entry_atr <= 0:
        continue
    entry, sl_dist = o[ei], p.sl_atr * atr_a[ei]
    stop = entry - sl_dist
    # backtest: stop wins ties, checked from entry bar through xi
    hit = None
    for j in range(ei, xi + 1):
        if l[j] <= stop:
            hit = j; break
    def R(px):
        return (px - entry - cost_frac * entry) / sl_dist
    if hit is not None:
        rows.append({"date": idx[ei].date(), "stopped": True,
                     "bt": R(stop), "A": R(stop), "B": R(stop), "gap": 0.0})
        continue
    bt = R(c[xi])                                  # backtest: close of the exit bar
    a = R(o[xi])                                   # (A) open of the exit bar
    # (B) open of the next bar; also check whether that next bar is across a weekend
    b = R(o[xi + 1]) if xi + 1 < len(idx) else bt
    wk = (pd.Timestamp(idx[xi + 1]) - pd.Timestamp(idx[xi])).days if xi + 1 < len(idx) else 0
    rows.append({"date": idx[ei].date(), "stopped": False, "bt": bt, "A": a, "B": b,
                 "gap": b - bt, "wknd": wk >= 2, "exit_dow": pd.Timestamp(idx[xi]).day_name()[:3]})

t = pd.DataFrame(rows)
n = len(t)
yrs = (pd.Timestamp(idx[-1]) - pd.Timestamp(idx[0])).days / 365.25
print(f"{n} monthly trades over {yrs:.1f} yrs ({t['stopped'].sum()} stopped out)\n")
for col, label in (("bt", "BACKTEST  close of the 2nd trading day"),
                   ("A", "(A) live fires ON the exit day    -> open of the 2nd TD"),
                   ("B", "(B) live fires the NEXT day       -> open of the 3rd TD")):
    v = t[col]
    tt = v.mean() / v.std(ddof=1) * np.sqrt(len(v))
    print(f"  {label:52s} total {v.sum():+7.2f} R | {v.sum()/yrs:+5.2f} R/yr | t={tt:5.2f}")

live = t[~t["stopped"]]
print(f"\ntracking error vs the backtest, on the {len(live)} time-exited trades:")
for col in ("A", "B"):
    dv = live[col] - live["bt"]
    print(f"  ({col})  mean {dv.mean():+.4f} R | sd {dv.std(ddof=1):.4f} | "
          f"max |diff| {dv.abs().max():.3f} R | total {dv.sum():+.2f} R")

wk = live[live["wknd"]]
print(f"\nof those, {len(wk)} exit days are followed by a weekend gap "
      f"({len(wk)/len(live)*100:.0f}%, exit day = {sorted(set(wk['exit_dow']))}):")
if len(wk):
    dv = wk["B"] - wk["bt"]
    print(f"  (B) across a weekend: mean {dv.mean():+.4f} R | sd {dv.std(ddof=1):.4f} | "
          f"max |diff| {dv.abs().max():.3f} R")
    dv2 = live[~live["wknd"]]["B"] - live[~live["wknd"]]["bt"]
    print(f"  (B) same-week      : mean {dv2.mean():+.4f} R | sd {dv2.std(ddof=1):.4f} | "
          f"max |diff| {dv2.abs().max():.3f} R")
