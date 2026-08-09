"""BACKTEST INTRADAY DU CORPUS — 674 signaux Pine x 6 actifs x 12 brackets.

Univers FIXE PAR L'UTILISATEUR et applique sans exception: **NAS100, US500, US30,
GER40, FRA40, XAUUSD**. Chaque signal est score sur les SIX, y compris quand son
auteur affirme qu'il ne marche que sur un marche: cette affirmation est une
opinion, pas une donnee.

CE QUI CHANGE PAR RAPPORT AUX PASSES PRECEDENTES
  * **L'absence de SL n'elimine plus.** On compile la regle d'ENTREE seule
    (`compile_script(require_bracket=False)`) et c'est nous qui balayons le stop.
  * **Deux familles de stop**, comme demande: ATR (1.0/1.5/2.0/3.0 x ATR14) et
    STRUCTURE (distance au plus-bas/plus-haut des 10 ou 20 dernieres barres) —
    cette derniere via `dist_override`, verifie non-regressif contre l'ATR.
  * **Intraday strict**: `Table(session=True)` porte un deadline par entree, donc
    une position ouverte 3 barres avant la cloture meurt a la cloture.
  * **Plancher 1R >= 25 spreads** (lecon KELT): interdit mecaniquement les trades
    dont le peage mangerait le R.

L'HORLOGE. Les scripts Pine qui portent une regle d'heure (`hour >= 9`) parlent de
l'horloge de la PLACE, pas d'UTC. On construit donc le frame `F` sur un index
converti dans le fuseau de la seance de l'actif, sinon toute regle horaire est
decalee silencieusement.
"""
import os, sys, json, time, itertools, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
import inx_data as D

OUT = os.path.join('scratchpad', '_inx')
UNIVERSE = ['NAS100', 'US500', 'US30', 'GER40', 'FRA40', 'XAUUSD']
TF = {'NAS100': 'M15', 'US500': 'M15', 'US30': 'M15', 'GER40': 'M15',
      'FRA40': 'M10', 'XAUUSD': 'M15'}
ATR_SL = (1.0, 1.5, 2.0, 3.0)
STRUCT_N = (10, 20)
TPS = (None, 2.0)
FLOOR = 25.0
MIN_TRADES = 25


def struct_dist(b, n):
    """Stop de STRUCTURE: distance au plus-bas (long) / plus-haut (short) des n
    dernieres barres. On prend le max des deux cotes pour avoir UNE distance par
    barre, comparable au 1R de l'ATR, et on la planche a 0.25 x ATR pour qu'une
    serie plate ne produise pas un stop nul."""
    lo = pd.Series(b.l).rolling(n, min_periods=n).min().to_numpy()
    hi = pd.Series(b.h).rolling(n, min_periods=n).max().to_numpy()
    d = np.fmax(b.c - lo, hi - b.c)
    return np.fmax(d, 0.25 * b.atr)


def session_bars(b):
    s = pd.Series(b.in_window.astype(int)).groupby(b.sess).sum()
    return int(max(4, np.median(s[s > 0].to_numpy())))


def load_specs():
    from tv_transpile import Spec
    raw = json.load(open(f'{OUT}/pine_specs.json'))
    return [Spec(v['code'], {}) for v in raw.values()], list(raw.keys())


def run_asset(sym, specs, sigs, rows):
    tf = TF[sym]
    b = K.Bars(sym, tf, source='inx', min_bars=5000)
    sb = session_bars(b)
    tz = D.SESSION[sym][0]
    df = b.d.copy()
    df.index = df.index.tz_convert(tz)          # horloge de la PLACE, cf. entete
    from tv_pine import F
    f = F(df, K.SPECS[sym]['point'])
    win = np.asarray(b.in_window, bool)

    tables = {}
    for sl, tp in itertools.product(ATR_SL, TPS):
        tables[(f'atr{sl}', tp)] = K.Table(b, sl, tp, sb + 1, session=True,
                                           floor_spread=FLOOR)
    for nn, tp in itertools.product(STRUCT_N, TPS):
        tables[(f'str{nn}', tp)] = K.Table(b, None, tp, sb + 1, session=True,
                                           floor_spread=FLOOR,
                                           dist_override=struct_dist(b, nn))
    nrun = nerr = 0
    for sig, sp in zip(sigs, specs):
        try:
            L, S, _, _, _, _ = sp.run(f)
        except Exception:
            nerr += 1
            continue
        L = np.asarray(L, bool) & win
        S = np.asarray(S, bool) & win
        s = np.zeros(b.n, np.int8)
        s[L] = 1
        s[S & ~L] = -1
        idx = np.flatnonzero(s != 0)
        idx = idx[idx > K.WARMUP]
        if len(idx) < MIN_TRADES:
            continue
        nrun += 1
        lf = float((s[idx] > 0).mean())
        for (slname, tp), tab in tables.items():
            R, xi, ei = tab.walk_idx(idx, s[idx])
            st = K.cell_stats(b, R, xi)
            if st is None or st['n'] < MIN_TRADES:
                continue
            rows.append(dict(sym=sym, tf=tf, sig=sig, sl=slname, tp=(tp or 0),
                             lf=lf, **st))
    return nrun, nerr


if __name__ == '__main__':
    t0 = time.time()
    specs, sigs = load_specs()
    only = sys.argv[1].split(',') if len(sys.argv) > 1 else UNIVERSE
    print(f'{len(specs)} signaux Pine distincts x {len(only)} actifs x '
          f'{len(ATR_SL)*len(TPS) + len(STRUCT_N)*len(TPS)} brackets', flush=True)
    rows = []
    for sym in only:
        n0 = len(rows)
        try:
            nrun, nerr = run_asset(sym, specs, sigs, rows)
        except Exception as e:
            print(f'{sym:<7} SKIP {type(e).__name__}: {e}', flush=True)
            continue
        sub = pd.DataFrame(rows[n0:])
        if len(sub):
            sub.to_parquet(f'{OUT}/corpus_{sym}.parquet', index=False)
            print(f'{sym:<7} signaux_actifs={nrun:>4} erreurs={nerr:>4} '
                  f'cellules={len(sub):>6} t_med={sub["t"].median():+5.2f} '
                  f't_max={sub["t"].max():+5.2f} [{time.time()-t0:.0f}s]', flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(f'{OUT}/corpus_all.parquet', index=False)
    print(f'\n=== {len(df):,} cellules, {time.time()-t0:.0f}s -> {OUT}/corpus_all.parquet')
