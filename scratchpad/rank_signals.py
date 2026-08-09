"""Classement de TOUS les signaux t>2, par REPLICATION cross-actifs.

Le probleme: ~1000 cellules depassent t=2 sur les trois corpus. Les tester une par
une reproduirait la selection qu'on cherche a eviter — la tete d'une grande grille
est chere en tests multiples, et le ledger note qu'une short-list choisie sur un
null repasse son propre null 81% du temps.

La sortie: on ne classe pas des CELLULES, on classe des SIGNAUX, et le critere est
la REPLICATION sur les 6 actifs imposes (regle standing de l'utilisateur). Pour
chaque signal on prend, PAR ACTIF, la MEDIANE de ses brackets — pas son maximum,
qui est la statistique contaminee. Un signal qui vit sur un seul actif tombe donc
mecaniquement, sans qu'on ait a lui faire passer un null.

Score = nombre d'actifs dont la mediane de brackets depasse le seuil, puis la
mediane des medianes comme departage.
"""
import sys, os, glob, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np, pandas as pd

OUT = 'scratchpad/_inx'
UNI = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']


def load(pat, corpus, sigcol='sig'):
    fs = glob.glob(f'{OUT}/{pat}')
    if not fs:
        return pd.DataFrame()
    d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    d['corpus'] = corpus
    if sigcol != 'sig':
        d = d.rename(columns={sigcol: 'sig'})
    return d[['corpus', 'sig', 'sym', 't', 'ER', 'PF', 'n']]


parts = [load('corpus_*.parquet', 'pine'), load('mql_*.parquet', 'mql'),
         load('fq_*.parquet', 'freqtrade')]
ts = glob.glob(f'{OUT}/part_*.parquet')
if ts:
    d = pd.concat([pd.read_parquet(f) for f in ts], ignore_index=True)
    d = d[d['sym'].isin(UNI)]
    d['corpus'] = 'tsam'
    parts.append(d.rename(columns={'rule': 'sig'})[['corpus', 'sig', 'sym', 't', 'ER', 'PF', 'n']])
D = pd.concat([p for p in parts if len(p)], ignore_index=True)
D = D[D['sym'].isin(UNI)]
print(f'{len(D):,} cellules | {D["sig"].nunique():,} signaux | corpus: '
      + ', '.join(f'{k}={v:,}' for k, v in D.groupby("corpus").size().items()))
print(f'cellules t>2: {int((D["t"]>2).sum()):,}\n')

# mediane des brackets, PAR (signal, actif)
m = D.groupby(['corpus', 'sig', 'sym'])['t'].median().unstack('sym')
for s in UNI:
    if s not in m:
        m[s] = np.nan
m = m[UNI]
cov = m.notna().sum(axis=1)
m = m[cov >= 4]                      # mesure sur au moins 4 des 6 actifs
for THR in (2.0, 1.5, 1.0):
    hits = (m >= THR).sum(axis=1)
    print(f'signaux dont la MEDIANE de brackets depasse {THR} sur ... actifs:  '
          + '  '.join(f'{k}:{int(v)}' for k, v in hits.value_counts().sort_index(ascending=False).items()))
print()
hits2 = (m >= 2.0).sum(axis=1)
hits1 = (m >= 1.0).sum(axis=1)
rank = pd.DataFrame({'n_ge2': hits2, 'n_ge1': hits1, 'med': m.median(axis=1)}).join(m)
rank = rank.sort_values(['n_ge2', 'n_ge1', 'med'], ascending=False)
print('=== TOP 25 SIGNAUX PAR REPLICATION (mediane de brackets par actif) ===')
print(rank.head(25).round(2).to_string())
rank.to_csv(f'{OUT}/signal_ranking.csv')
print(f'\n-> {OUT}/signal_ranking.csv  ({len(rank)} signaux couverts sur >=4 actifs)')
