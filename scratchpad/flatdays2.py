"""Same book, but: (a) what hours do the intraday sleeves fire at, (b) joint base rate
for 'full weekday at zero, then next weekday at zero up to a cutoff hour'."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, '.')
from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams
from edgelab.intraday.hma_stoch import run_hma_stoch
from edgelab.intraday.two_leg_fade import run_two_leg_fade
from edgelab.edges.turn_of_month import run_turn_of_month, TurnOfMonthParams
from edgelab.edges.ibs import run_ibs, IBSParams
from edgelab.reports.monte_carlo_static import eng, macd_rsi, load, START

def naive(x):
    t = pd.DatetimeIndex(pd.to_datetime(x))
    return (t.tz_convert('UTC') if t.tz is not None else t.tz_localize('UTC')).tz_localize(None)
def pick(df, *n):
    for k in n:
        if k in df.columns: return df[k]
    raise KeyError(n)

S = {}
S['b1'] = naive(pick(run_atr_breakout('NAS100', ATRBreakParams(regime_mode='low', direction='both'), 'M1').trades, 'entry_time','entry_dt','time'))
S['b2'] = naive(pick(run_turn_of_month('XAUUSD', TurnOfMonthParams(sl_atr=1.5)), 'date','entry_dt','entry_time'))
for s in ('BTCUSD','ETHUSD'):
    S['b3'+s] = naive(pick(eng.run(load(s), macd_rsi(load(s)), s, 'x').trades, 'entry_time','entry_dt'))
S['b4'] = naive(pick(run_ibs('NAS100', IBSParams(sl_atr=2.5), cadence='live'), 'entry_dt','entry_time'))
S['HMASTO'] = naive(pick(run_hma_stoch('NAS100').trades, 'entry_time','entry_dt'))
for s in ('NAS100','US500'):
    S['TLF'+s] = naive(pick(run_two_leg_fade(s).trades, 'entry_time','entry_dt'))

print('=== heure d entree (histogramme, horodatage brut des parquets) ===')
for k in ('b1','HMASTO','TLFNAS100','TLFUS500'):
    h = pd.Series(S[k].hour).value_counts().sort_index()
    print(f'  {k:10s}', ' '.join(f'{i}h:{v}' for i, v in h.items()))

ent_all = {k: v[v >= START] for k, v in S.items()}
w0 = max(v.min() for v in ent_all.values()).normalize()
w1 = min(v.max() for v in ent_all.values()).normalize()
ent = pd.DatetimeIndex(np.concatenate([v.to_numpy() for v in ent_all.values()])).sort_values()
ent = ent[(ent >= w0) & (ent <= w1)]
cal = pd.date_range(w0, w1, freq='D'); week = cal[cal.dayofweek < 5]
full = pd.Series(1, index=ent.normalize()).groupby(level=0).sum().reindex(week, fill_value=0)

print(f'\n=== base jointe, fenetre {w0.date()} -> {w1.date()} ===')
for cut in (16, 17, 18, 19, 20):
    e2 = ent[ent.hour < cut]
    part = pd.Series(1, index=e2.normalize()).groupby(level=0).sum().reindex(week, fill_value=0)
    zf, zp = (full == 0).to_numpy(), (part == 0).to_numpy()
    joint = zf[:-1] & zp[1:]
    print(f'  coupure {cut:02d}h (horodatage parquet) : P(jour ouvre complet a 0) = {100*zf.mean():4.1f} % | '
          f'P(jour partiel a 0 avant {cut}h) = {100*zp.mean():4.1f} % | '
          f'P(les deux d affilee) = {100*joint.mean():4.2f} %  ({joint.sum()} occurrences sur {len(joint)})')
