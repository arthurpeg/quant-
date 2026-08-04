"""Why does the live replay lose R vs the backtest? Compare exit bars trade by trade."""
from __future__ import annotations

import numpy as np
import pandas as pd

from edgelab.edges.turn_of_month import TurnOfMonthParams, _load_d1, _wilder_atr
from edgelab.live import signals as S

p = TurnOfMonthParams(sl_atr=1.5)
d = _load_d1("XAUUSD")
days = d.index.tz_convert("UTC").tz_localize(None).normalize()
print("D1 bars by weekday:", dict(pd.Series(days.day_name()).value_counts()))
print("first/last bar:", days[0].date(), days[-1].date(), "| n =", len(d))

# the backtest's own exit bar per trade
month = pd.PeriodIndex(days, freq="M")
tdom = pd.Series(np.arange(len(d)), index=d.index).groupby(month).rank().astype(int)
months, tdom_a = month.to_numpy(), tdom.to_numpy()
last_pos = {}
for i in range(len(d)):
    last_pos[months[i]] = i
uniq = list(dict.fromkeys(months))

rows = []
for k in range(len(uniq) - 1):
    m, mn = uniq[k], uniq[k + 1]
    ei = last_pos[m]
    nxt = np.where((months == mn) & (tdom_a <= p.first_days))[0]
    if len(nxt) == 0:
        continue
    xi = nxt[-1]
    # what bar does the LIVE calendar first flag as an exit, at or after entry?
    li = None
    for j in range(ei + 1, min(ei + 25, len(d))):
        if S.tom_state(d, days[j], p).is_exit_day:
            li = j; break
    rows.append({"entry": days[ei].date(), "bt_exit_bar": days[xi].date(),
                 "bt_exit_dow": days[xi].day_name()[:3],
                 "want_live_bar": days[xi + 1].date() if xi + 1 < len(d) else None,
                 "live_bar": days[li].date() if li is not None else None,
                 "offset_bars": (li - (xi + 1)) if li is not None else None})

t = pd.DataFrame(rows)
print(f"\n{len(t)} trades; live exit bar vs the wanted bar (xi+1):")
print(t["offset_bars"].value_counts(dropna=False).to_string())
bad = t[t["offset_bars"] != 0]
print(f"\n{len(bad)} mismatched trades:")
print(bad.to_string(index=False))
