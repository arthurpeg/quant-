"""Backtest INTRADAY du corpus freqtrade (1347 fichiers) — meme moteur que Pine/MQL.

`fq_shim` fait deja tourner ces strategies telles quelles (il substitue TA-Lib,
freqtrade, qtpylib, technical, pandas_ta). Ce qui manquait: elles n'avaient JAMAIS
tourne en intraday — `fq_run --tf` valait D1 par defaut — alors que 293 des 353
strategies qui declarent un timeframe sont en 1m/5m/15m (RESEARCH_LOG_CODE.md).

Univers impose: NAS100, US500, US30, GER40, FRA40, XAUUSD, chacune sur les six.
Seule l'ENTREE est prise; `minimal_roi`/`stoploss`/trailing du fichier sont jetes et
c'est notre bracket qui est balaye (ATR 1/1.5/2/3 + structure 10/20, TP aucun ou 2R),
avec sortie forcee avant la cloture et plancher 1R >= 25 spreads.
"""
import os, sys, time, itertools, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd
import kauf_lib as K
import fq_run as FQ
from corpus_run import (UNIVERSE, TF, ATR_SL, STRUCT_N, TPS, FLOOR, MIN_TRADES,
                        struct_dist, session_bars)

OUT = os.path.join('scratchpad', '_inx')
MAX_FIRE = 0.40


def main():
    only = sys.argv[1].split(',') if len(sys.argv) > 1 else UNIVERSE
    files = FQ.candidates()
    print(f'{len(files)} fichiers freqtrade eligibles x {len(only)} actifs', flush=True)
    t0 = time.time()
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
        rows = []
        nrun = nerr = ndeg = 0
        for p in files:
            try:
                classes = FQ.load_classes(p)
            except Exception:
                nerr += 1
                continue
            for nm, cls in classes:
                try:
                    sig, note = FQ.signal_from(cls, b)
                except Exception:
                    nerr += 1
                    continue
                if sig is None:
                    nerr += 1
                    continue
                s = np.where(win, sig, 0).astype(np.int8)
                idx = np.flatnonzero(s != 0)
                idx = idx[idx > K.WARMUP]
                if len(idx) < MIN_TRADES or len(idx) > MAX_FIRE * nwin:
                    ndeg += 1
                    continue
                nrun += 1
                lf = float((s[idx] > 0).mean())
                rid = f'{os.path.relpath(p, FQ.ROOT)}:{nm}'
                for (slname, tp), tab in tables.items():
                    R, xi, ei = tab.walk_idx(idx, s[idx])
                    st = K.cell_stats(b, R, xi)
                    if st is None or st['n'] < MIN_TRADES:
                        continue
                    rows.append(dict(sym=sym, tf=TF[sym], sig=rid, sl=slname,
                                     tp=(tp or 0), lf=lf, **st))
        sub = pd.DataFrame(rows)
        if len(sub):
            sub.to_parquet(f'{OUT}/fq_{sym}.parquet', index=False)
        print(f'{sym:<7} retenues={nrun:>4} degenerees={ndeg:>4} erreurs={nerr:>4} '
              f'cellules={len(sub):>6} '
              f't_max={sub["t"].max() if len(sub) else float("nan"):+5.2f} '
              f'[{time.time()-t0:.0f}s]', flush=True)


if __name__ == '__main__':
    main()
