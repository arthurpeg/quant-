"""Backtest intraday des signaux MQL (81 distincts) — meme moteur que le corpus Pine.

Univers impose: NAS100, US500, US30, GER40, FRA40, XAUUSD. Chaque signal sur les six.
Le bracket est le NOTRE (ATR 1/1.5/2/3 + structure 10/20 barres, TP aucun ou 2R),
puisque le transpileur jette celui du fichier. Sortie forcee avant la cloture.

FILTRE DE DEGENERESCENCE, en remplacement de la garde `uses_ind` retiree du
transpileur: un signal qui tire sur plus de 40% des barres de seance ne selectionne
rien (c'est une condition quasi-toujours vraie), et un signal sous 25 trades n'est
pas mesurable. Les deux sont ecartes ICI, empiriquement, plutot qu'en refusant a
priori des familles entieres de strategies.
"""
import os, sys, json, time, itertools, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd
import kauf_lib as K
import mql_transpile as MT
from corpus_run import (UNIVERSE, TF, ATR_SL, STRUCT_N, TPS, FLOOR, MIN_TRADES,
                        struct_dist, session_bars)

OUT = os.path.join('scratchpad', '_inx')
MAX_FIRE = 0.40


def main():
    specs = json.load(open(f'{OUT}/mql_specs.json'))
    only = sys.argv[1].split(',') if len(sys.argv) > 1 else UNIVERSE
    t0 = time.time()
    rows = []
    for sym in only:
        b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
        sb = session_bars(b)
        win = np.asarray(b.in_window, bool)
        nwin = int(win.sum())
        tables = {}
        for sl, tp in itertools.product(ATR_SL, TPS):
            tables[(f'atr{sl}', tp)] = K.Table(b, sl, tp, sb + 1, session=True,
                                               floor_spread=FLOOR)
        for nn, tp in itertools.product(STRUCT_N, TPS):
            tables[(f'str{nn}', tp)] = K.Table(b, None, tp, sb + 1, session=True,
                                               floor_spread=FLOOR,
                                               dist_override=struct_dist(b, nn))
        nrun = nerr = ndeg = 0
        for sig, sp in specs.items():
            try:
                s = MT.run_compiled(sp['sides'], b)
            except Exception:
                nerr += 1
                continue
            s = np.where(win, s, 0).astype(np.int8)
            idx = np.flatnonzero(s != 0)
            idx = idx[idx > K.WARMUP]
            if len(idx) < MIN_TRADES or len(idx) > MAX_FIRE * nwin:
                ndeg += 1
                continue
            nrun += 1
            lf = float((s[idx] > 0).mean())
            for (slname, tp), tab in tables.items():
                R, xi, ei = tab.walk_idx(idx, s[idx])
                st = K.cell_stats(b, R, xi)
                if st is None or st['n'] < MIN_TRADES:
                    continue
                rows.append(dict(sym=sym, tf=TF[sym], sig=sig, lang=sp['lang'],
                                 file=sp['file'], sl=slname, tp=(tp or 0), lf=lf, **st))
        sub = pd.DataFrame([r for r in rows if r['sym'] == sym])
        if len(sub):
            sub.to_parquet(f'{OUT}/mql_{sym}.parquet', index=False)
        print(f'{sym:<7} retenus={nrun:>3} degeneres={ndeg:>3} erreurs={nerr:>3} '
              f'cellules={len(sub):>5} '
              f't_max={sub["t"].max() if len(sub) else float("nan"):+5.2f} '
              f'[{time.time()-t0:.0f}s]', flush=True)
    pd.DataFrame(rows).to_parquet(f'{OUT}/mql_all.parquet', index=False)
    print(f'\n=== {len(rows)} cellules -> {OUT}/mql_all.parquet')


if __name__ == '__main__':
    main()
