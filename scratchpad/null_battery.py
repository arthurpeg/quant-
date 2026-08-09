"""NULL A + NULL B sur les cellules de tete des quatre corpus.

Pourquoi c'est la seule chose qui compte maintenant: la meilleure cellule Pine est
`RSI(14) > 70 -> LONG, jamais de short` sur NAS100 (t=4.24). Long-only sur un indice
qui monte 2018-2026, c'est exactement le piege que ce projet a deja mesure — dans le
travail KAER le null B valait **+1.24 a lui seul** pour un ensemble de cassures a
biais long sur NAS100.

  NULL A — memes bracket, meme NOMBRE d'entrees, meme FRACTION LONGUE, mais des
           barres tirees au hasard dans la fenetre de seance. C'est LE controle de
           derive: des entrees longues aleatoires sur le NAS encaissent la meme
           derive que les notres. Ce qui depasse est de l'information de TIMING.
  NULL B — memes barres, signes permutes. Isole la DIRECTION. Degenere si la regle
           est long-only (permuter des signes tous identiques ne change rien), donc
           on ne le rapporte que quand la regle prend les deux sens.
"""
import sys, os, json, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np, pandas as pd
import kauf_lib as K
from corpus_run import TF, FLOOR, struct_dist, session_bars
NDRAW = 400


def table_for(b, slname, tp, sb):
    tp = None if not tp else float(tp)
    if slname.startswith('atr'):
        return K.Table(b, float(slname[3:]), tp, sb + 1, session=True, floor_spread=FLOOR)
    n = int(slname[3:])
    return K.Table(b, None, tp, sb + 1, session=True, floor_spread=FLOOR,
                   dist_override=struct_dist(b, n))


def battery(sym, sig_arr, slname, tp, label):
    b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
    sb = session_bars(b); win = np.asarray(b.in_window, bool)
    tab = table_for(b, slname, tp, sb)
    idx = np.flatnonzero(sig_arr != 0); idx = idx[idx > K.WARMUP]
    s = sig_arr[idx]
    R, xi, ei = tab.walk_idx(idx, s)
    t0 = K.tstat(R); lf = float((s > 0).mean())
    i = np.arange(b.n); pool = np.flatnonzero((i > K.WARMUP) & (i < b.n - 1) & win)
    nt = K.null_ts(tab, pool, len(R), lf, ndraw=NDRAW, rng=np.random.default_rng(7))
    pA = float((nt >= t0).mean()); medA = float(np.median(nt))
    rng = np.random.default_rng(11); tb = []
    if 0.02 < lf < 0.98:
        for _ in range(NDRAW):
            sp = rng.permutation(s)
            Rb, _, _ = tab.walk_idx(idx, sp)
            if len(Rb) > 20:
                tb.append(K.tstat(Rb))
    pB = float((np.array(tb) >= t0).mean()) if tb else np.nan
    medB = float(np.median(tb)) if tb else np.nan
    print(f'{label:34s} {sym:7s} {slname:7s} n={len(R):5d} lf={lf:.2f} '
          f't={t0:5.2f} | NullA med={medA:+5.2f} p={pA:.3f} | '
          f'NullB med={medB:+5.2f} p={pB:.3f}' if tb else
          f'{label:34s} {sym:7s} {slname:7s} n={len(R):5d} lf={lf:.2f} '
          f't={t0:5.2f} | NullA med={medA:+5.2f} p={pA:.3f} | NullB n/a (long-only)',
          flush=True)


if __name__ == '__main__':
    print('=' * 118)
    print('  NULL A (derive/timing) et NULL B (direction) — 400 tirages chacun')
    print('=' * 118)
    from tv_transpile import Spec
    from tv_pine import F
    import inx_data as D
    ps = json.load(open('scratchpad/_inx/pine_specs.json'))
    for sig, slname, sym in (('f7871dd1cde8', 'atr1.0', 'NAS100'),
                             ('f7871dd1cde8', 'atr1.5', 'NAS100'),
                             ('255f122d29a3', 'atr2.0', 'NAS100'),
                             ('ed171c5755ae', 'atr1.0', 'NAS100'),
                             ('f7871dd1cde8', 'atr1.0', 'GER40')):
        b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
        df = b.d.copy(); df.index = df.index.tz_convert(D.SESSION[sym][0])
        L, S, _, _, _, _ = Spec(ps[sig]['code'], {}).run(F(df, K.SPECS[sym]['point']))
        win = np.asarray(b.in_window, bool)
        a = np.zeros(b.n, np.int8)
        a[np.asarray(L, bool) & win] = 1
        a[np.asarray(S, bool) & win & ~np.asarray(L, bool)] = -1
        battery(sym, a, slname, 0, f'PINE {sig}')
    import mql_transpile as MT
    ms = json.load(open('scratchpad/_inx/mql_specs.json'))
    for sig, slname, sym in (('424e77c1cd10', 'str10', 'GER40'),
                             ('424e77c1cd10', 'atr1.5', 'GER40'),
                             ('424e77c1cd10', 'atr1.5', 'NAS100')):
        b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
        a = np.where(np.asarray(b.in_window, bool),
                     MT.run_compiled(ms[sig]['sides'], b), 0).astype(np.int8)
        battery(sym, a, slname, 0, 'MQL ADX_System')
