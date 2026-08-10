"""BATTERIE, VERSION 2 — placebo et Null A APPARIES SUR L'HEURE DE SEANCE.

POURQUOI CE SECOND PASSAGE EXISTE
----------------------------------
`battery_full.py` apparie le placebo sur trois choses: le nombre d'entrees, la
fraction longue, et les barres eligibles (en seance). Il **n'apparie pas l'heure
de seance**, et la mesure montre que c'est un trou reel: les signaux qui survivent
concentrent 9 a 14 % de leurs entrees sur la barre d'OUVERTURE, contre 4,8 % pour
un tirage uniforme dans la seance.

L'ouverture n'a pas la meme economie qu'un milieu d'apres-midi (volatilite,
etendue, cout relatif au 1R). Un rapport reel/placebo > 1 peut donc dire
"ces regles tradent a l'ouverture" au lieu de "ces regles ont un edge" — et
Null A, qui tire lui aussi uniformement dans la seance, porte exactement le meme
angle mort. Les deux etalons sont donc re-tires ici **dans le meme histogramme
d'heure de seance que le signal reel**.

CE QUI CHANGE, ET CE QUI NE CHANGE PAS
  * change  : le tirage du placebo ET le tirage de Null A sont contraints a
              reproduire la distribution de `slot` (rang de la barre dans sa
              seance, 0 = ouverture) du signal reel.
  * inchange: Null B (permutation des SIGNES sur les MEMES barres) etait deja
              apparie sur l'heure par construction — il n'avait pas ce defaut.
  * inchange: brackets, execution, couts, criteres de survie, plancher 25 spreads.

LECTURE. On compare le rapport reel/placebo de ce passage a celui de
`battery_full`. S'il s'effondre vers 1, les survivants du premier passage etaient
un effet d'HEURE et non un edge. S'il tient, l'edge n'est pas explique par le
moment de la journee ou les regles se declenchent.

Sortie: `scratchpad/_inx/battery_tod_<SYM>.csv` (meme schema que battery_full).

Usage:  python -u scratchpad/battery_tod.py <SYM> [n_placebo]
        python -u scratchpad/battery_tod.py report
"""
import sys, os, json, glob, time, zlib, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
from corpus_run import TF, FLOOR, session_bars
from battery_full import (UNI, OUT, NDRAW, MIN_TRADES, BRACKETS, PRIMARY,
                          cohort, build_signals, report)


def session_slot(b):
    """`slot[i]` = rang de la barre i parmi les barres EN SEANCE de sa seance
    (0 = premiere barre negociable du jour). -1 hors seance."""
    win = np.asarray(b.in_window, bool)
    slot = np.full(b.n, -1, np.int32)
    cc = pd.Series(np.zeros(int(win.sum()), np.int8)).groupby(b.sess[win]).cumcount()
    slot[win] = cc.to_numpy()
    return slot


class TodSampler:
    """Tirage de barres APPARIE sur l'histogramme d'heure de seance d'un signal."""

    def __init__(self, pool, slot):
        sl = slot[pool]
        self.by = {int(s): pool[sl == s] for s in np.unique(sl)}

    def draw(self, k, lf, ref_slots, rng):
        vals, cnts = np.unique(ref_slots, return_counts=True)
        if k < 5 or not len(vals):
            return None, None
        take = rng.multinomial(int(k), cnts / cnts.sum())
        out = []
        for s, t in zip(vals, take):
            av = self.by.get(int(s))
            if av is None or t == 0:
                continue
            out.append(rng.choice(av, min(int(t), len(av)), replace=False))
        if not out:
            return None, None
        bars = np.sort(np.concatenate(out))
        sgn = np.where(rng.random(len(bars)) < lf, 1, -1).astype(np.int8)
        return bars, sgn


def null_ts_tod(tab, sampler, ref_slots, n, lf, ndraw, rng):
    ts = []
    for _ in range(ndraw):
        bars, sgn = sampler.draw(n, lf, ref_slots, rng)
        if bars is None:
            continue
        R, _, _ = tab.walk_idx(bars, sgn)
        if len(R) >= 5:
            ts.append(K.tstat(R))
    return np.array([x for x in ts if np.isfinite(x)])


def cell_tod(tab, t10, sampler, ref_slots, idx, sgn):
    """Identique a battery_full.cell, sauf que Null A tire dans le meme
    histogramme d'heure de seance que le signal teste."""
    R, xi, ei = tab.walk_idx(idx, sgn)
    if len(R) < MIN_TRADES:
        return None
    t0 = K.tstat(R)
    h = len(R) // 2
    tpre, trec = K.tstat(R[:h]), K.tstat(R[h:])
    R10, _, _ = t10.walk_idx(idx, sgn)
    t10s = K.tstat(R10)
    lf = float((sgn > 0).mean())
    gate1 = bool(t0 > 2 and tpre > 0 and trec > 0 and t10s > 1)

    pA = pB = np.nan
    if gate1:
        nt = null_ts_tod(tab, sampler, ref_slots, len(R), lf, NDRAW,
                         np.random.default_rng(7))
        pA = float((nt >= t0).mean()) if len(nt) else np.nan
        if 0.02 < lf < 0.98:
            rng = np.random.default_rng(11)
            tb = []
            for _ in range(NDRAW):
                Rb, _, _ = tab.walk_idx(idx, rng.permutation(sgn))
                if len(Rb) > 20:
                    tb.append(K.tstat(Rb))
            tb = np.array([x for x in tb if np.isfinite(x)])
            pB = float((tb >= t0).mean()) if len(tb) else np.nan
    passe = bool(gate1 and (pA < 0.05) and (np.isnan(pB) or pB < 0.05))
    st = K.cell_stats(tab.b, R, xi) or {}
    return dict(n=len(R), lf=lf, t=float(t0), t_pre=float(tpre), t_rec=float(trec),
                t_cost10=float(t10s), pA=pA, pB=pB, gate1=gate1, passe=passe,
                Ryr=st.get('Ryr', np.nan), RoMaD=st.get('RoMaD', np.nan),
                PF=st.get('PF', np.nan), win=st.get('win', np.nan))


def run_asset(sym, nplac):
    want = cohort()
    ps = json.load(open(f'{OUT}/pine_specs.json'))
    ms = json.load(open(f'{OUT}/mql_specs.json'))
    print(f'[{sym}] TOD-apparie | cohorte {len(want)} signaux x {len(BRACKETS)} '
          f'brackets x (1 reel + {nplac} placebos)', flush=True)

    T0 = t0 = time.time()
    b = K.Bars(sym, TF[sym], source='inx', min_bars=5000)
    b.sym = sym
    sb = session_bars(b)
    slot = session_slot(b)
    i = np.arange(b.n)
    pool = np.flatnonzero((i > K.WARMUP) & (i < b.n - 1) & np.asarray(b.in_window, bool))
    sampler = TodSampler(pool, slot)

    tabs = {br: K.Table(b, br[0], br[1], sb + 1, session=True, floor_spread=FLOOR)
            for br in BRACKETS}
    c10 = b.cost(extra_pts=10)
    t10s = {br: K.Table(b, br[0], br[1], sb + 1, rt=c10, session=True,
                        floor_spread=FLOOR) for br in BRACKETS}

    sigs, err = build_signals(b, sym, want, ps, ms)
    print(f'[{sym}] {TF[sym]} {b.n} barres, {sb} barres/seance, {len(sigs)} signaux '
          f'construits, {len(err)} en erreur [{time.time()-t0:.0f}s]', flush=True)

    path = f'{OUT}/battery_tod_{sym}.csv'
    rows, done = [], 0
    for name, a in sigs.items():
        done += 1
        idx = np.flatnonzero(a != 0)
        idx = idx[idx > K.WARMUP]
        if len(idx) < MIN_TRADES:
            continue
        ref = slot[idx]
        ref = ref[ref >= 0]
        if not len(ref):
            continue
        rng = np.random.default_rng(zlib.crc32(f'tod|{sym}|{name}'.encode()) % (2**31))
        cohorts = [('reel', idx, a[idx])]
        for r in range(nplac):
            pb, psg = sampler.draw(len(idx), float((a[idx] > 0).mean()), ref, rng)
            if pb is not None:
                cohorts.append((f'placebo{r}', pb, psg))
        for kind, ii, ss in cohorts:
            for br in BRACKETS:
                res = cell_tod(tabs[br], t10s[br], sampler, ref, ii, ss)
                if res:
                    rows.append(dict(kind='reel' if kind == 'reel' else 'placebo',
                                     rep=kind, corpus=want[name], sig=name, sym=sym,
                                     sl=br[0], tp=br[1],
                                     primary=(br == PRIMARY), **res))
        if done % 20 == 0:
            d = pd.DataFrame(rows)
            d.to_csv(path, index=False)
            print(f'[{sym}] {done}/{len(sigs)} | {len(rows)} cellules | '
                  f'survivantes reel={int(d[d.kind=="reel"].passe.sum())} '
                  f'plac={int(d[d.kind=="placebo"].passe.sum())} | '
                  f'{(time.time()-T0)/60:.0f}min', flush=True)

    pd.DataFrame(rows).to_csv(path, index=False)
    print(f'[{sym}] TERMINE {len(rows)} cellules -> {path} '
          f'[{(time.time()-T0)/60:.1f}min]', flush=True)


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else 'report'
    if arg == 'report':
        fs = glob.glob(f'{OUT}/battery_tod_*.csv')
        if not fs:
            sys.exit('aucun battery_tod_<SYM>.csv')
        report(pd.concat([pd.read_csv(f) for f in fs], ignore_index=True))
    elif arg in UNI:
        run_asset(arg, int(sys.argv[2]) if len(sys.argv) > 2 else 2)
    else:
        sys.exit(f'usage: battery_tod.py [{"|".join(UNI)}|report] [n_placebo]')
