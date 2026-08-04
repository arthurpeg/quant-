"""Replay brick 1's LIVE decision on FRESH Pepperstone bars for the last N days.

Uses the runner's own Broker (same symbol map, same to_true_utc clock) and the same
signals.nas_orb_scan the driver calls, so this is what the live brick would have done.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

from edgelab.intraday.atr_breakout import ATRBreakParams, _mins
from edgelab.live import signals as S
from edgelab.live.runner import _load_live_cfg
from edgelab.live.broker import Broker

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8

cfg = _load_live_cfg()
broker = Broker(cfg)                      # only get_bars* is called below — no orders
broker.connect()

p = ATRBreakParams(regime_mode="low", direction="both")
sym = cfg.get("nas_symbol", "NAS100")
open_m, cut_m, close_m = _mins(p.session_open), _mins(p.entry_cutoff), _mins(p.session_close)
print(f"brick 1 = {sym} | session {p.session_open}-{p.session_close} ET | entry cutoff "
      f"{p.entry_cutoff} | regime {p.regime_mode} (atr3 < {p.regime_factor} x atr20) "
      f"| k_break={p.k_break} k_stop={p.k_stop} rr={p.rr}")

m1 = broker.get_bars(sym, "M1", 60 * 24 * 20)      # ~20 days of M1
d1 = broker.get_bars_raw(sym, "D1", 90)
atr_map = S.prev_day_atrs(d1, p)

loc = m1.index.tz_convert(p.tz)
mins = loc.hour * 60 + loc.minute
day = pd.Series(loc.normalize().tz_localize(None), index=m1.index)
m1 = m1.assign(_m=mins.to_numpy(), _d=day.to_numpy())

days = [d for d, g in m1.groupby("_d")
        if ((g["_m"] >= open_m) & (g["_m"] <= close_m)).sum() >= 10]
print(f"\nlast {N} session days on the LIVE feed:\n")
for d in sorted(days)[-N:]:
    g = m1[m1["_d"] == d]
    sess = g[(g["_m"] >= open_m) & (g["_m"] <= close_m)][["open", "high", "low", "close"]]
    dd = pd.Timestamp(d).date()
    atrs = atr_map.get(dd)
    if atrs is None or not np.isfinite(atrs[0]) or atrs[0] <= 0:
        print(f"  {dd}  -- no prev-day ATR context (would return, no trade)")
        continue
    atr14, atr3, atr20 = atrs
    gate = S.nas_regime_ok(atr3, atr20, p)
    ratio = atr3 / atr20
    res = S.nas_orb_scan(sess, atr14, atr3, atr20, p)
    if not gate:
        verdict = f"NO TRADE  regime gate CLOSED (atr3/atr20={ratio:.3f} >= {p.regime_factor})"
    elif res is None:
        # was the level ever touched inside the entry window?
        o0 = float(sess["open"].iloc[0])
        up, dn = o0 + p.k_break * atr14, o0 - p.k_break * atr14
        win = sess[(g.loc[sess.index, "_m"] <= cut_m)]
        hi, lo = float(win["high"].max()), float(win["low"].min())
        verdict = (f"NO TRADE  low-vol OK (ratio {ratio:.3f}) but no breakout: "
                   f"open {o0:.1f} needs >{up:.1f} or <{dn:.1f}; window high {hi:.1f} low {lo:.1f}")
    else:
        ci, plan = res
        t = pd.Timestamp(sess.index[ci]).tz_convert(p.tz)
        verdict = (f"TRADE {'LONG' if plan.direction > 0 else 'SHORT'} confirmed {t:%H:%M} ET "
                   f"(bar {ci}/{len(sess)}), 1R={plan.sl_dist:.1f} pts, ratio {ratio:.3f}")
    print(f"  {dd} {pd.Timestamp(d).day_name()[:3]}  {verdict}")

broker.disconnect()
