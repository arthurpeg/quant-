"""Sentinelle: attend les 13 jobs lances hors harnais et imprime la consolidation.

Les runs Pine/freqtrade/sweep ont ete lances en `nohup`, donc le harnais ne les
suit pas et n'emet aucune notification. Ce processus-ci EST suivi: il attend leurs
sorties, puis imprime le tableau consolide. Il ne touche a rien — il observe.
"""
import os, sys, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd

OUT = 'scratchpad/_inx'
UNI = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']
WANT = ([f'{OUT}/corpus_{s}.parquet' for s in UNI]
        + [f'{OUT}/fq_{s}.parquet' for s in UNI]
        + [f'{OUT}/part_FRA40_M10.parquet'])

t0 = time.time()
last = -1
while time.time() - t0 < 6 * 3600:
    done = [w for w in WANT if os.path.exists(w)]
    if len(done) != last:
        last = len(done)
        print(f'[{time.time()-t0:6.0f}s] {len(done)}/{len(WANT)} sorties prites', flush=True)
    if len(done) == len(WANT):
        break
    time.sleep(60)

print('\n' + '=' * 92)
print('  CONSOLIDATION — tous corpus, univers NAS100/US500/US30/GER40/FRA40/XAUUSD')
print('=' * 92)
for tag, pat in (('PINE (674 signaux)', 'corpus_{}.parquet'),
                 ('FREQTRADE (244 fichiers)', 'fq_{}.parquet'),
                 ('MQL (81 signaux)', 'mql_{}.parquet')):
    fs = [f'{OUT}/' + pat.format(s) for s in UNI]
    fs = [f for f in fs if os.path.exists(f)]
    if not fs:
        print(f'\n{tag}: aucune sortie'); continue
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    print(f'\n{tag} — {len(d):,} cellules, {d["sig"].nunique()} signaux')
    g = d.groupby('sym').agg(cellules=('t', 'size'), t_med=('t', 'median'),
                             t_max=('t', 'max'), ER_med=('ER', 'median'))
    print(g.round(3).to_string())
    top = d.sort_values('t', ascending=False).head(8)
    cols = [c for c in ('sym', 'sig', 'file', 'sl', 'tp', 'n', 'ER', 'PF', 't') if c in top]
    print('  meilleures cellules:')
    print(top[cols].round(3).to_string(index=False))
print('\n=== fin ===')
