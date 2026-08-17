"""AMPLEUR de l'ecart d'ancrage du stop entre le backtest et le live.

BACKTEST (hma_stoch.py:347-348) : entry = open de la barre SUIVANTE, sl = entry -+ dist
LIVE     (strategies.py:782-783): ref   = close de la barre de SIGNAL,  sl = ref  -+ dist

Le stop live est donc decale de la derive close->open par rapport a celui que le backtest
mesure, et comme 1R est le DENOMINATEUR de chaque trade, l'ecart se lit directement en R :
    erreur_R = direction * (open_suivant - close_signal) / dist
Positif = le stop live est PLUS LOIN du prix d'entree que voulu (sur-risque),
negatif = plus PRES (sous-risque, et sortie stoppee plus probable).

Mesure sur les VRAIS signaux historiques de chaque sleeve, pas sur des barres au hasard.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from edgelab.intraday.hma_stoch import (HmaStochParams, hma_atr, hma_signals, stop_distance,
                                        load_bars as hma_load)
from edgelab.intraday.orb import load_bars


def summarise(name, err_R):
    err_R = np.asarray(err_R, dtype=float)
    err_R = err_R[np.isfinite(err_R)]
    a = np.abs(err_R)
    print(f"\n  {name}  (n={len(err_R)})")
    print(f"    erreur signee sur 1R : moyenne {err_R.mean():+.4f} R | mediane {np.median(err_R):+.4f} R "
          f"| ecart-type {err_R.std(ddof=1):.4f}")
    print(f"    erreur ABSOLUE       : moyenne {a.mean():.4f} R | mediane {np.median(a):.4f} R "
          f"| p90 {np.percentile(a, 90):.4f} | p99 {np.percentile(a, 99):.4f} | max {a.max():.4f}")
    print(f"    part des trades ou |erreur| > 5 % de 1R : {100*(a > 0.05).mean():.1f} % "
          f"| > 10 % : {100*(a > 0.10).mean():.1f} % | > 25 % : {100*(a > 0.25).mean():.1f} %")
    t = err_R.mean() / (err_R.std(ddof=1) / np.sqrt(len(err_R)))
    print(f"    le biais est-il systematique ? t = {t:+.2f} "
          f"({'OUI, biais reel' if abs(t) > 2 else 'non, bruit centre'})")


print('=' * 100)
print("ECART D'ANCRAGE DU STOP — backtest (fill) vs live (close du signal)")
print('=' * 100)

# ------------------------------------------------------------------ HMASTO (M15)
p = HmaStochParams()
d = hma_load('NAS100', 'M15') if callable(hma_load) else None
if d is None or not len(d):
    d = load_bars('NAS100', 'M15')
sig = hma_signals(d, p)
atr = hma_atr(d, p)
o = d['open'].to_numpy(float)
c = d['close'].to_numpy(float)
errs = []
for i in np.flatnonzero(sig != 0):
    if i + 1 >= len(d):
        continue
    dist = stop_distance(d, int(i), p, atr, 'NAS100')
    if dist <= 0:
        continue
    errs.append(int(sig[i]) * (o[i + 1] - c[i]) / dist)
summarise('HMASTO NAS100 M15 (0.5R live, ~256 entrees/an)', errs)

# ------------------------------------------------------------------ BRIQUE 1 (M1)
from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams
r = run_atr_breakout('NAS100', ATRBreakParams(regime_mode='low', direction='both'), 'M1')
tr = r.trades
m1 = load_bars('NAS100', 'M1')
cols = {k.lower(): k for k in tr.columns}
et = pd.DatetimeIndex(pd.to_datetime(tr[cols.get('entry_time', 'entry_time')]))
errs1 = []
idx = m1.index
for k in range(len(tr)):
    ts = et[k]
    j = idx.searchsorted(ts)
    if j <= 0 or j >= len(idx):
        continue
    # le backtest remplit a l'open de la barre j ; le live ancre sur le close de j-1
    dcol = cols.get('sl_dist') or cols.get('r_dist')
    dist = float(tr.iloc[k][dcol]) if dcol else np.nan
    if not np.isfinite(dist) or dist <= 0:
        continue
    s = int(tr.iloc[k][cols.get('direction', 'direction')])
    errs1.append(s * (float(m1['open'].iloc[j]) - float(m1['close'].iloc[j - 1])) / dist)
if errs1:
    summarise('BRIQUE 1 NAS100 M1 (1R live, ~95 entrees/an)', errs1)
else:
    print('\n  BRIQUE 1 : colonnes du trade-log insuffisantes pour la mesure '
          f'(disponibles: {list(tr.columns)})')

print('\n' + '=' * 100)
print("LECTURE : cette erreur n'est PAS dans le signal (verify prouve dist identique a 0 pres)")
print("mais dans le PRIX auquel le stop est accroche. TLF est la seule sleeve qui re-ancre")
print("1R sur le fill (`modify_sl`) ; toutes les autres accrochent sur le close du signal.")
print('=' * 100)
