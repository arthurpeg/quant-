"""Base rate: how often does the DEPLOYED book go a full weekday - or two in a row -
with ZERO entries? Sleeves = exactly what runner.py instantiates with the current
config_live.yaml: 101 b1, 102 b2, 103/104 b3, 105 b4, 108 HMASTO, 109/110 TLF."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, '.')
pd.set_option('display.width', 200)

from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams
from edgelab.intraday.hma_stoch import run_hma_stoch
from edgelab.intraday.two_leg_fade import run_two_leg_fade
from edgelab.edges.turn_of_month import run_turn_of_month, TurnOfMonthParams
from edgelab.edges.ibs import run_ibs, IBSParams
from edgelab.reports.monte_carlo_static import eng, macd_rsi, load, START


def naive(x):
    t = pd.DatetimeIndex(pd.to_datetime(x))
    return (t.tz_convert('UTC') if t.tz is not None else t.tz_localize('UTC')).tz_localize(None)


def pick(df, *names):
    for n in names:
        if n in df.columns:
            return df[n]
    raise KeyError(f'{names} absent de {list(df.columns)}')


sleeves = {}
t = run_atr_breakout('NAS100', ATRBreakParams(regime_mode='low', direction='both'), 'M1').trades
sleeves['b1 NAS100 ORB'] = naive(pick(t, 'entry_time', 'entry_dt', 'time'))
print('b1 ok', len(t), flush=True)

g = run_turn_of_month('XAUUSD', TurnOfMonthParams(sl_atr=1.5))
sleeves['b2 XAUUSD ToM'] = naive(pick(g, 'date', 'entry_dt', 'entry_time'))
print('b2 ok', len(g), flush=True)

for s in ('BTCUSD', 'ETHUSD'):
    tr = eng.run(load(s), macd_rsi(load(s)), s, 'x').trades
    sleeves[f'b3 {s}'] = naive(pick(tr, 'entry_time', 'entry_dt'))
    print('b3', s, 'ok', len(tr), flush=True)

i = run_ibs('NAS100', IBSParams(sl_atr=2.5), cadence='live')
sleeves['b4 NAS100 IBS'] = naive(pick(i, 'entry_dt', 'entry_time'))
print('b4 ok', len(i), flush=True)

h = run_hma_stoch('NAS100').trades
sleeves['HMASTO NAS100'] = naive(pick(h, 'entry_time', 'entry_dt'))
print('hmasto ok', len(h), flush=True)

for s in ('NAS100', 'US500'):
    r = run_two_leg_fade(s).trades
    sleeves[f'TLF {s}'] = naive(pick(r, 'entry_time', 'entry_dt'))
    print('tlf', s, 'ok', len(r), flush=True)

# common window: start at the LATEST sleeve start so every sleeve is live in it
ent_all = {k: v[v >= START] for k, v in sleeves.items()}
w_start = max(v.min() for v in ent_all.values()).normalize()
w_end = min(v.max() for v in ent_all.values()).normalize()
print(f'\nfenetre commune (toutes sleeves vivantes) : {w_start.date()} -> {w_end.date()}')

ent = pd.DatetimeIndex(np.concatenate([v.to_numpy() for v in ent_all.values()])).sort_values()
ent = ent[(ent >= w_start) & (ent <= w_end)]
cal = pd.date_range(w_start, w_end, freq='D')
week = cal[cal.dayofweek < 5]
per_day = pd.Series(1, index=ent.normalize()).groupby(level=0).sum()
wk = per_day.reindex(week, fill_value=0)

print(f'\n=== ENTREES PAR JOUR DE SEMAINE ({len(week)} jours ouvres) ===')
print(f'  moyenne {wk.mean():.2f} / mediane {wk.median():.0f} entrees par jour ouvre')
print(f'  jours ouvres a ZERO entree : {(wk==0).sum()} / {len(week)} = {100*(wk==0).mean():.1f} %')
z = (wk == 0).to_numpy()
for k in (1, 2, 3, 4, 5):
    runs = np.convolve(z.astype(int), np.ones(k, int), 'valid') == k
    print(f'  {k} jour(s) ouvre(s) consecutif(s) a zero : {runs.sum():4d} occurrences '
          f'sur {len(runs)} fenetres = {100*runs.mean():5.2f} %')

# longest observed dry spell
best, cur, bstart = 0, 0, None
starts = []
for d, isz in zip(week, z):
    if isz:
        cur += 1
        if cur == 1:
            bstart = d
        if cur > best:
            best, bd = cur, bstart
    else:
        if cur >= 3:
            starts.append((bstart.date(), cur))
        cur = 0
print(f'\n  plus longue serie seche observee : {best} jours ouvres a partir du {bd.date()}')
print(f'  series >= 3 jours ouvres a zero : {len(starts)}')
for s0, n in starts[-12:]:
    print(f'     {s0}  ({n} jours)')

print('\n=== PAR SLEEVE (% des jours ouvres avec >=1 entree) ===')
for k, v in ent_all.items():
    v = v[(v >= w_start) & (v <= w_end)]
    s = pd.Series(1, index=v.normalize()).groupby(level=0).sum().reindex(week, fill_value=0)
    print(f'  {k:18s} {len(v):5d} trades  {s.mean():5.2f}/jour  '
          f'{100*(s>0).mean():5.1f} % des jours ouvres  (P(zero) = {100*(s==0).mean():4.1f} %)')

print('\n=== DERNIERS JOURS COUVERTS PAR LES DONNEES LOCALES ===')
for k, v in sleeves.items():
    print(f'  {k:18s} derniere entree {v.max().date()}')
