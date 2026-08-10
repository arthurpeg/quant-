"""LES SURVIVANTS NAS100 SONT-ILS UN CANDIDAT, OU LA BRIQUE 1 SOUS UN AUTRE NOM ?

NAS100 est le seul actif ou la batterie separe le reel du hasard: a preselection
egale, 124/228 = 54.4 % contre 7/46 = 15.2 % pour le placebo (3.57x, p<0.0001).
112 mecanismes y survivent, RoMaD median 0.96, jusqu'a 1.81 — au-dessus d'IBS
(1.59), le meilleur du livre.

Mais un RoMaD standalone n'est PAS le test d'admission du projet. `system.md`
l'ecrit: *"le RoMaD standalone est le test d'admission le plus propre, PUIS on
AJOUTE"*, et la valeur d'une sleeve est sa DECORRELATION. Or les noms des
survivants (`T:Keltner_break_2.5`, `T:X_ER_Keltner`, `T:X_ADX_Keltner`,
`T:X_FRAMA_Keltner`, `T:X_KAMA_Keltner`, `T:X_VIDYA_Keltner`, `T:X_none_Keltner`,
`T:NDB_10`, Donchian-20, cassure 126 barres) disent tous la meme chose: cassure de
canal sur NAS100 — c'est-a-dire la MECANIQUE de la brique 1.

Ce script tranche par la mesure, pas par le nom:
  1. serie de trades de chaque tete, a SON meilleur bracket;
  2. correlation quotidienne AUX BRIQUES DU LIVRE (`brick_baseline.score`);
  3. correlation quotidienne ENTRE ELLES — si elles sont une seule famille, la
     matrice est saturee et "112 mecanismes" est un compte trompeur.

Usage:  python -u scratchpad/nas_candidates.py [n_tetes]
"""
import sys, os, json, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
from corpus_run import TF, FLOOR, session_bars
from battery_full import build_signals, OUT
from brick_baseline import score, load_bricks

SYM = 'NAS100'


def main():
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    d = pd.read_csv(f'{OUT}/battery_verdict_dedup.csv')
    s = d[(d.sym == SYM) & (d.kind == 'reel') & d.passe]
    best = (s.sort_values('RoMaD', ascending=False)
            .groupby('sig', as_index=False).first()
            .sort_values('RoMaD', ascending=False).head(top_n))
    print(f'{len(s)} cellules survivantes / {s.sig.nunique()} mecanismes sur {SYM}; '
          f'on instruit les {len(best)} meilleurs par RoMaD\n')

    want = dict(zip(best.sig, best.corpus))
    ps = json.load(open(f'{OUT}/pine_specs.json'))
    ms = json.load(open(f'{OUT}/mql_specs.json'))
    b = K.Bars(SYM, TF[SYM], source='inx', min_bars=5000)
    b.sym = SYM
    sb = session_bars(b)
    sigs, err = build_signals(b, SYM, want, ps, ms)
    print(f'{len(sigs)} signaux reconstruits, {len(err)} en erreur\n')

    series, rows = {}, []
    for _, r in best.iterrows():
        a = sigs.get(r.sig)
        if a is None:
            continue
        tp = None if pd.isna(r.tp) else float(r.tp)
        tab = K.Table(b, float(r.sl), tp, sb + 1, session=True, floor_spread=FLOOR)
        idx = np.flatnonzero(a != 0)
        idx = idx[idx > K.WARMUP]
        R, xi, ei = tab.walk_idx(idx, a[idx])
        if len(R) < 40:
            continue
        dates = pd.to_datetime(b.time[xi])
        res = score(f'{r.sig} [{r.corpus}] SL{r.sl} TP{r.tp}', R, dates, verbose=False)
        rows.append(dict(sig=r.sig, corpus=r.corpus, sl=r.sl, tp=r.tp, n=res['n'],
                         t=res['t'], Ryr=res['Ryr'], maxDD=res['maxDD'],
                         RoMaD=res['Ryr'] / res['maxDD'] if res['maxDD'] else np.nan,
                         PF=res['PF'], pos_yr=f"{res['pos_years']}/{res['n_years']}",
                         corr_b1_NAS=res['corr']['NAS'], corr_gold=res['corr']['gold'],
                         corr_crypto=res['corr']['crypto']))
        ser = pd.Series(R, index=dates)
        if ser.index.tz is not None:
            ser.index = ser.index.tz_localize(None)
        series[r.sig] = ser.groupby(ser.index.normalize()).sum()

    t = pd.DataFrame(rows).sort_values('RoMaD', ascending=False)
    print('=' * 110)
    print('TETES NAS100 — profil complet et CORRELATION AUX BRIQUES DU LIVRE')
    print('=' * 110)
    print(t.to_string(index=False, float_format=lambda x: f'{x:.3f}'))

    print('\n' + '=' * 110)
    print("CORRELATION QUOTIDIENNE ENTRE LES TETES ELLES-MEMES")
    print("(si elles sont une seule famille, ces nombres sont eleves et "
          "'112 mecanismes' est un compte trompeur)")
    print('=' * 110)
    cal = pd.date_range(min(x.index.min() for x in series.values()),
                        max(x.index.max() for x in series.values()), freq='D')
    M = pd.DataFrame({k: v.reindex(cal).fillna(0) for k, v in series.items()})
    C = M.corr()
    lab = {k: k[:14] for k in C.columns}
    print(C.rename(columns=lab, index=lab).to_string(float_format=lambda x: f'{x:+.2f}'))
    off = C.values[np.triu_indices_from(C.values, 1)]
    print(f'\n  correlation median entre tetes = {np.median(off):+.3f} | '
          f'quartiles [{np.percentile(off,25):+.3f}, {np.percentile(off,75):+.3f}] | '
          f'max {off.max():+.3f}')
    print(f'  paires |corr| > 0.5 : {(np.abs(off) > 0.5).mean():.0%} des '
          f'{len(off)} paires')
    t.to_csv(f'{OUT}/nas_candidates.csv', index=False)
    print(f'\n-> {OUT}/nas_candidates.csv')


if __name__ == '__main__':
    main()
