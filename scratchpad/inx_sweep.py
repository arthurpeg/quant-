"""SWEEP INTRADAY — toute la bibliotheque de regles x metaux + indices US + indices EU.

Mandat de l'utilisateur (2026-08-09): *"retourne dans les metaux, indices eu et us,
teste tous les edges potentiels ... je veux uniquement des strategies intraday"*,
et explicitement: **ne pas se servir du ratio placebo comme d'un filtre**, parce
qu'un taux de survie inferieur au hasard n'interdit pas qu'UNE strategie soit
excellente parmi des centaines de mauvaises. Le placebo est donc calcule et
rapporte, mais il ne coupe rien: on sort les meilleures cellules dans tous les cas.

CE QUI EST NEUF PAR RAPPORT AUX PASSES PRECEDENTES
--------------------------------------------------
La passe Kaufman du 2026-08-07 a fait DEUX choses distinctes qu'il ne faut pas
confondre: (a) un sweep de 135 regles x 19 actifs, mais **en D1 et H1 seulement**;
(b) une etude intraday, mais qui n'a extrait du livre que **4 mecanismes**
(Midday S/R, KAMA, Meyers Adaptive Intraday Breakout, cassure N-barres gatee par
l'ER) — c'est de la (b) qu'est sortie KAER. **Personne n'a jamais passe la
bibliotheque COMPLETE en intraday.** C'est exactement ce trou-la.

INTRADAY = SORTIE FORCEE AVANT LA CLOTURE, pas "capee a N barres"
------------------------------------------------------------------
`kauf_lib.Table(..., session=True)` porte un DEADLINE par entree: la derniere
barre de la seance de l'entree strictement anterieure a l'heure de mise a plat.
Une position ouverte 3 barres avant la cloture meurt a la cloture; une position
ouverte a l'ouverture peut vivre toute la journee. Les entrees sont en plus
restreintes a `in_window` (pas d'entree dans la derniere demi-heure).

Execution identique au reste du projet, donc les chiffres sont comparables au
ledger: decision a la cloture de la barre -> fill a l'ouverture de la suivante;
une position a la fois; une barre qui couvre les deux barrieres est resolue
PESSIMISTEMENT au stop; un gap traversant une barriere remplit au pire des deux;
cout = max(spread du flux, plancher de seance) + 2 pts de slippage + commission,
facture une fois a la barre de SIGNAL; R = la distance de stop du trade lui-meme.
"""
import sys, os, itertools, time, warnings
sys.path.insert(0, 'scratchpad')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
import tsam_rules as T
import inx_rules as IR
import inx_data as D

OUT = os.path.join('scratchpad', '_inx')
os.makedirs(OUT, exist_ok=True)

CLS = {**{s: 'metal' for s in D.METAL},
       **{s: 'us_idx' for s in D.US_IDX},
       **{s: 'eu_idx' for s in D.EU_IDX}}

# (symbole, timeframe) a balayer: M5/M15/M30 quand on a du M1 natif, M10 sinon.
CELLS = ([(s, tf) for s in D.M1_SYMS for tf in ('M5', 'M15', 'M30')]
         + [(s, 'M10') for s in D.M10_SYMS])

SLS = (0.75, 1.0, 1.5, 2.0, 3.0)
TPS = (1.0, 1.5, 2.0, 3.0, None)
NULL_DRAWS = 200
LF_BUCKETS = (0.0, 0.25, 0.5, 0.75, 1.0)
MIN_TRADES = 30


def lf_bucket(lf):
    return min(LF_BUCKETS, key=lambda b: abs(b - lf))


def session_bars(b):
    """Mediane du nombre de barres EN SEANCE par seance (≠ b.bars_per_sess, qui
    compte toutes les barres du jour local, hors seance comprises)."""
    s = pd.Series(b.in_window.astype(int)).groupby(b.sess).sum()
    s = s[s > 0]
    return int(max(4, np.median(s.to_numpy())))


def sweep_one(sym, tf, rows, nulls):
    b = K.Bars(sym, tf, source='inx', min_bars=5000)
    sb = session_bars(b)
    # deux plafonds temps: ~1/3 de seance, et "jusqu'au deadline" (le plafond ne mord
    # plus, c'est la seance qui ferme). On garde les deux pour separer un edge qui a
    # besoin de tenir de un qui se resout vite.
    MAXBARS = (max(4, int(round(sb / 3))), sb + 1)

    # DEUX bibliotheques: le canon d'INDICATEURS (agnostique au TF) + les mecanismes
    # ANCRES SUR LA SEANCE (opening range, VWAP, PDH/PDL, pivots, Supertrend...) que
    # le canon ne contient pas et qui n'ont de sens qu'en intraday.
    rules = {f'T:{k}': v for k, v in T.all_rules(b).items()}
    rules.update({f'S:{k}': v for k, v in IR.all_rules(b).items()})
    i = np.arange(b.n)
    # les entrees ne sont autorisees que DANS la fenetre de seance
    pool = np.flatnonzero((i > K.WARMUP) & (i < b.n - 1) & b.in_window)

    # dedupe sur le TABLEAU DE SIGNAL, jamais sur le nom de famille: le livre donne
    # plusieurs noms au meme mecanisme et le compter 3x gonflerait tous les comptes.
    seen, uniq = {}, {}
    for name, s in rules.items():
        key = s.tobytes()
        if key in seen:
            continue
        seen[key] = name
        uniq[name] = s

    prep = {}
    for name, s in uniq.items():
        s = np.where(b.in_window, s, 0)          # pas d'entree hors seance
        idx = np.flatnonzero(s != 0)
        idx = idx[idx > K.WARMUP]
        if len(idx) < MIN_TRADES:
            continue
        prep[name] = (idx, s[idx], float((s[idx] > 0).mean()))

    for sl, tp, mb in itertools.product(SLS, TPS, MAXBARS):
        tab = K.Table(b, sl, tp, mb, session=True)          # <- deadline de seance
        rep_n = int(np.median([len(v[0]) for v in prep.values()])) if prep else 100
        for lfb in LF_BUCKETS:
            nt = K.null_ts(tab, pool, rep_n, lfb, ndraw=NULL_DRAWS,
                           rng=np.random.default_rng(
                               abs(hash((sym, tf, sl, tp, mb, lfb))) % 99991))
            if len(nt):
                nulls.append(dict(sym=sym, tf=tf, sl=sl, tp=tp, mb=mb, lfb=lfb,
                                  null_med=float(np.median(nt)),
                                  null_p95=float(np.percentile(nt, 95)),
                                  null_n=len(nt), rep_n=rep_n))
        for name, (idx, sgn, lf) in prep.items():
            R, xi, ei = tab.walk_idx(idx, sgn)
            st = K.cell_stats(b, R, xi)
            if st is None or st['n'] < MIN_TRADES:
                continue
            rows.append(dict(sym=sym, cls=CLS[sym], tf=tf, rule=name, sl=sl, tp=tp,
                             mb=mb, sess_bars=sb, lf=lf, lfb=lf_bucket(lf), **st))
    return len(uniq), sb


def main():
    only = sys.argv[1].split(',') if len(sys.argv) > 1 and sys.argv[1] != '-' else None
    tfs = sys.argv[2].split(',') if len(sys.argv) > 2 else None
    cells = [(s, tf) for s, tf in CELLS
             if (only is None or s in only) and (tfs is None or tf in tfs)]
    rows, nulls = [], []
    t0 = time.time()
    for sym, tf in cells:
        try:
            n0 = len(rows)
            nu, sb = sweep_one(sym, tf, rows, nulls)
            sub = pd.DataFrame(rows[n0:])
            if len(sub):
                print(f'{sym:<7} {tf:<4} regles={nu:>3} barres/seance={sb:>3} '
                      f'cellules={len(sub):>5} t_med={sub["t"].median():+5.2f} '
                      f't_max={sub["t"].max():+5.2f} '
                      f'hits(t>2)={int((sub["t"] > 2).sum()):>4}  [{time.time()-t0:.0f}s]',
                      flush=True)
            else:
                print(f'{sym:<7} {tf:<4} regles={nu:>3} AUCUNE cellule', flush=True)
            if len(sub):
                sub.to_parquet(f'{OUT}/part_{sym}_{tf}.parquet', index=False)
                pd.DataFrame([x for x in nulls if x['sym'] == sym and x['tf'] == tf]
                             ).to_parquet(f'{OUT}/partnull_{sym}_{tf}.parquet', index=False)
        except Exception as e:
            print(f'{sym:<7} {tf:<4} SKIP {type(e).__name__}: {e}', flush=True)

    df = pd.DataFrame(rows)
    nl = pd.DataFrame(nulls)
    tag = ('-'.join(only) if only else 'all') + ('_' + '-'.join(tfs) if tfs else '')
    df.to_parquet(f'{OUT}/cells_{tag}.parquet', index=False)
    nl.to_parquet(f'{OUT}/nulls_{tag}.parquet', index=False)
    j = df.merge(nl[['sym', 'tf', 'sl', 'tp', 'mb', 'lfb', 'null_med', 'null_p95']],
                 on=['sym', 'tf', 'sl', 'tp', 'mb', 'lfb'], how='left')
    j['excess'] = j['t'] - j['null_med']
    j.to_parquet(f'{OUT}/scored_{tag}.parquet', index=False)

    print(f'\n=== {len(df):,} cellules, {df["rule"].nunique()} regles distinctes, '
          f'{time.time()-t0:.0f}s ===')
    print(f'  t median {df["t"].median():+.3f} | cellules t>2 {int((df["t"]>2).sum()):,} '
          f'| t>2.9 {int((df["t"]>2.9).sum()):,} | t>4 {int((df["t"]>4).sum()):,}')
    print(f'  au-dessus de leur null p95: {int((j["t"]>j["null_p95"]).sum()):,} '
          f'({(j["t"]>j["null_p95"]).mean():.1%}; hasard = 5%)')
    print('\npar classe:')
    print(j.groupby('cls').apply(lambda g: pd.Series({
        'cellules': len(g), 't_med': g['t'].median(), 'exces_med': g['excess'].median(),
        'au_dessus_p95': (g['t'] > g['null_p95']).mean(), 't_max': g['t'].max()})).to_string())
    print('\npar timeframe:')
    print(j.groupby('tf').apply(lambda g: pd.Series({
        'cellules': len(g), 't_med': g['t'].median(), 'exces_med': g['excess'].median(),
        'au_dessus_p95': (g['t'] > g['null_p95']).mean(), 't_max': g['t'].max()})).to_string())
    print(f'\n-> {OUT}/scored_{tag}.parquet')


if __name__ == '__main__':
    main()
