"""LES TROIS TESTS QUI RESTAIENT SUR `fee9c1a8ce7d` (candidat NAS100 intraday).

Le candidat: HMA(12) croise au-dessus de l'EMA(5) decalee de 2 barres, ET close au-dessus
des deux, ET RSI(14)>50, ET Stoch(12) lisse 3 >50, ET Stoch(5) lisse 3 >50; symetrique en
short. NAS100 M15, sortie forcee en seance, plancher 25 spreads.
Profil deja etabli (bracket ATR PRE-DECLARE du projet, SL 1.0xATR sans cible): t=3.61,
+42.8 R/an, maxDD 25.0 R, RoMaD 1.71, 9/9 annees positives, Null A et Null B p=0.000,
corr brique 1 +0.179. Mono-actif.

CE QUI MANQUAIT, et pourquoi chacun peut le tuer:

  TEST 1 — CORRELATION A LA BRIQUE 4 (IBS). `brick_baseline` ne porte que 3 briques
  (NAS ORB, or, crypto). Or **la brique 4 trade LE MEME SOUS-JACENT, NAS100**, et c'est
  donc la correlation la plus susceptible de disqualifier le candidat. On mesure ici
  contre les SIX sleeves du projet (b1, b2, b3, b4, KAER, KELT), en quotidien ET en
  mensuel, avec la machinerie de `book_optimise`.

  TEST 2 — AJOUT AU LIVRE A RISQUE EGAL. Le test d'admission du projet n'est NI le t NI
  le RoMaD standalone (`system.md`, et la correction du 2026-08-09 qui avait sanctionne
  exactement cette erreur). Sur un compte prop a drawdown STATIQUE on est paye sur le
  CHEMIN: le compte est dimensionne a 2x la maxDD historique, donc la figure de merite
  est **%/an a risque egal = (0.10 / (2 x maxDD)) x R/an**. On compare le livre actuel
  (b1+b2+b3+b4 @1R) a lui-meme + le candidat a 0.25 / 0.5 / 0.75 / 1.0 R.

  TEST 3 — LE BRACKET DE L'AUTEUR. Le profil valide utilise le bracket ATR pre-declare
  du PROJET. Le script d'origine, lui, prevoit un **stop de STRUCTURE asymetrique**
  (long: plus-bas des 2 barres precedentes; short: plus-haut des 2 barres precedentes)
  et une **cible a 1.65 x cette distance**. Si l'edge n'existe qu'avec le bracket du
  projet et meurt avec celui de l'auteur, ce n'est pas la strategie de l'auteur qui
  marche — c'est notre bracket, et il faut le dire.

Usage:  python -u scratchpad/nas_cand_tests.py
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
from book_optimise import perf

# ⚠️ On NE reutilise PAS `book_optimise.sleeves()`: il construit la sleeve KELT via
# `K.Bars('BTCUSD', 'H1')` alors que `kauf_lib.SPECS` ne porte que 11 symboles
# indices/metaux — BTCUSD n'y est pas, donc `sleeves()` leve KeyError. C'est une
# casse PRE-EXISTANTE de `book_optimise.py`, sans rapport avec ce chantier.
# KELT pese 0 dans le livre actuel (b1+b2+b3+b4 @1R), donc on batit la matrice
# sans elle et on le dit plutot que de la reparer en passant.
NAMES = ['b1', 'b2', 'b3', 'b4', 'KAER']


def sleeves():
    from edgelab.reports.monte_carlo_static import build_daily_R
    from edgelab.intraday.kaer import run_kaer
    R, parts, (start, end), _ = build_daily_R()
    idx = pd.date_range(start, end, freq='D')
    b1, b2, b3, b4 = [p.reindex(idx).fillna(0.0) for p in parts]
    kr = run_kaer('NAS100')
    kaer = daily(kr.trades['R'], kr.trades['exit_time'], idx)
    return pd.DataFrame({'b1': b1, 'b2': b2, 'b3': b3, 'b4': b4, 'KAER': kaer}), \
        (start, end)

SIG = 'fee9c1a8ce7d'
SYM = 'NAS100'


def candidate_bars():
    b = K.Bars(SYM, TF[SYM], source='inx', min_bars=5000)
    b.sym = SYM
    ps = json.load(open(f'{OUT}/pine_specs.json'))
    ms = json.load(open(f'{OUT}/mql_specs.json'))
    sigs, err = build_signals(b, SYM, {SIG: 'pine'}, ps, ms)
    if SIG not in sigs:
        sys.exit(f'signal irreconstructible: {err}')
    return b, sigs[SIG], session_bars(b)


def walk(b, a, tab):
    idx = np.flatnonzero(a != 0)
    idx = idx[idx > K.WARMUP]
    return tab.walk_idx(idx, a[idx]), idx


def daily(R, times, idx_cal=None):
    t = pd.DatetimeIndex(times)
    t = t.tz_convert('UTC') if t.tz is not None else t.tz_localize('UTC')
    s = pd.Series(np.asarray(R, float), index=t.tz_localize(None).normalize())
    s = s.groupby(level=0).sum()
    return s.reindex(idx_cal).fillna(0.0) if idx_cal is not None else s


def stats(R, times, lbl):
    s = daily(R, times)
    span = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)
    c = np.cumsum(np.asarray(R, float))
    dd = float(np.max(np.maximum.accumulate(c) - c))
    ryr = float(np.sum(R) / span)
    yrs = pd.Series(R, index=pd.DatetimeIndex(times).year).groupby(level=0).sum()
    g = -np.sum([x for x in R if x <= 0])
    print(f'  {lbl:<38} n={len(R):<5} t={K.tstat(R):+5.2f}  E[R]={np.mean(R):+.3f}  '
          f'R/an={ryr:+6.1f}  maxDD={dd:5.1f}  RoMaD={ryr/dd if dd else np.nan:5.2f}  '
          f'PF={np.sum([x for x in R if x>0])/g if g>0 else np.inf:4.2f}  '
          f'+ans={int((yrs>0).sum())}/{len(yrs)}')
    return dict(n=len(R), t=K.tstat(R), Ryr=ryr, maxDD=dd,
                RoMaD=ryr / dd if dd else np.nan)


def main():
    b, a, sb = candidate_bars()

    # ---------------------------------------------------------------- TEST 3 (bracket)
    print('=' * 100)
    print('TEST 3 — LE BRACKET DE L\'AUTEUR contre le bracket PRE-DECLARE du projet')
    print('=' * 100)
    # stop de structure ASYMETRIQUE, tel que le script Pine l'ecrit
    lo2 = pd.Series(b.l).shift(1).rolling(2).min().to_numpy()
    hi2 = pd.Series(b.h).shift(1).rolling(2).max().to_numpy()
    dist_long = np.fmax(b.c - lo2, 1e-9)
    dist_short = np.fmax(hi2 - b.c, 1e-9)

    def table_author(tp_mult):
        """Table dont le cote LONG et le cote SHORT ont chacun LEUR distance."""
        tl = K.Table(b, None, tp_mult, sb + 1, session=True, floor_spread=FLOOR,
                     dist_override=dist_long)
        ts = K.Table(b, None, tp_mult, sb + 1, session=True, floor_spread=FLOOR,
                     dist_override=dist_short)
        tl.RS, tl.XS = ts.RS, ts.XS
        return tl

    rows = {}
    for lbl, tab in (('AUTEUR: struct(2) + TP 1.65R', table_author(1.65)),
                     ('AUTEUR: struct(2) sans cible', table_author(None)),
                     ('PROJET: 1.0xATR sans cible',
                      K.Table(b, 1.0, None, sb + 1, session=True, floor_spread=FLOOR)),
                     ('PROJET: 1.5xATR sans cible',
                      K.Table(b, 1.5, None, sb + 1, session=True, floor_spread=FLOOR))):
        (R, xi, ei), idx = walk(b, a, tab)
        rows[lbl] = (R, b.time[xi])
        stats(R, b.time[xi], lbl)

    # ------------------------------------------------------- TEST 1 (correlations)
    print('\n' + '=' * 100)
    print('TEST 1 — CORRELATION AUX SIX SLEEVES DU PROJET (b4 = IBS, MEME actif NAS100)')
    print('=' * 100)
    M, (start, end) = sleeves()
    cal = M.index
    Rp, tp_ = rows['PROJET: 1.0xATR sans cible']
    cand = daily(Rp, tp_, cal)
    M2 = M.copy()
    M2['CAND'] = cand
    print(f'fenetre du livre : {start:%Y-%m-%d} -> {end:%Y-%m-%d}\n')
    print('correlations QUOTIDIENNES du candidat:')
    dq = M2.corr()['CAND'].drop('CAND')
    print('  ' + '  '.join(f'{k} {v:+.3f}' for k, v in dq.items()))
    print('correlations MENSUELLES du candidat:')
    mq = M2.resample('ME').sum().corr()['CAND'].drop('CAND')
    print('  ' + '  '.join(f'{k} {v:+.3f}' for k, v in mq.items()))
    worst = max(abs(mq.max()), abs(mq.min()))
    print(f'\n  |corr| mensuelle max = {worst:.3f}   '
          f'(gate du projet: |corr| < 0.30)   -> '
          f'{"PASS" if worst < 0.30 else "ECHEC"}')
    print(f'  ⚠ le chiffre qui compte est b4 (IBS, NAS100, meme sous-jacent): '
          f'quotidien {dq["b4"]:+.3f}, mensuel {mq["b4"]:+.3f}')

    # ------------------------------------------------- TEST 2 (ajout a risque egal)
    print('\n' + '=' * 100)
    print('TEST 2 — AJOUT AU LIVRE A RISQUE EGAL  (%/an = (0.10 / (2 x maxDD)) x R/an)')
    print('=' * 100)
    base = (1, 1, 1, 1, 0)             # livre actuel: b1+b2+b3+b4 @1R (KAER=0)
    A = M[NAMES].to_numpy()
    s0 = pd.Series(A @ np.array(base), index=cal)
    p0 = perf(s0)
    print(f"{'config':<44}{'R/an':>8}{'maxDD':>8}{'RoMaD':>7}{'Sharpe':>8}"
          f"{'pire j':>8}{'%/an':>8}{'delta':>8}")
    print(f"{'livre actuel (b1+b2+b3+b4 @1R)':<44}{p0['Ryr']:>+8.1f}{p0['maxDD']:>8.1f}"
          f"{p0['RoMaD']:>7.2f}{p0['Sharpe']:>8.2f}{p0['worst']:>+8.2f}{p0['pct']:>7.1f}%"
          f"{'—':>8}")
    best = None
    for w in (0.25, 0.5, 0.75, 1.0):
        s = s0 + w * cand
        p = perf(s)
        d = p['pct'] - p0['pct']
        print(f"{'  + candidat @' + f'{w:g}R':<44}{p['Ryr']:>+8.1f}{p['maxDD']:>8.1f}"
              f"{p['RoMaD']:>7.2f}{p['Sharpe']:>8.2f}{p['worst']:>+8.2f}{p['pct']:>7.1f}%"
              f"{d:>+7.1f}pt")
        if best is None or p['pct'] > best[1]:
            best = (w, p['pct'], d)
    # comparaison honnete: faire PLUS de ce qu'on a deja, a la place
    print(f"\n  contre-epreuve — au lieu d'ajouter, faire PLUS de l'existant:")
    for nm, w in (('b1 (meme actif, meme famille) @1.5R', (1.5, 1, 1, 1, 0)),
                  ('b4 (meme actif, IBS) @1.5R', (1, 1, 1, 1.5, 0)),
                  ('KAER@0.5 (candidat deja a l etagere)', (1, 1, 1, 1, 0.5)),
                  ('tout le livre @1.25R', (1.25, 1.25, 1.25, 1.25, 0))):
        s = pd.Series(A @ np.array(w), index=cal)
        p = perf(s)
        print(f"    {nm:<40}{p['Ryr']:>+8.1f}{p['maxDD']:>8.1f}{p['RoMaD']:>7.2f}"
              f"{p['Sharpe']:>8.2f}{p['worst']:>+8.2f}{p['pct']:>7.1f}%"
              f"{p['pct']-p0['pct']:>+7.1f}pt")
    print(f"\n  meilleur ajout du candidat: @{best[0]:g}R -> {best[1]:.1f}%/an "
          f"({best[2]:+.1f} pt sur {p0['pct']:.1f}%)")

    # demi-echantillons du LIVRE avec le candidat (le piege du 2026-08-09)
    mid = cal[len(cal) // 2]
    print(f'\n  demi-echantillons (le piege TSM-Coil: une sleeve dont la contribution '
          f'est concentree sur une moitie):')
    for lbl, s in (('livre seul', s0), (f'livre + candidat @{best[0]:g}R',
                                        s0 + best[0] * cand)):
        for h, sl in (('1re moitie', s.loc[:mid]), ('2e moitie', s.loc[mid:])):
            p = perf(sl)
            print(f'    {lbl:<28} {h:<11} R/an {p["Ryr"]:+7.1f}  maxDD {p["maxDD"]:5.1f}'
                  f'  RoMaD {p["RoMaD"]:5.2f}  %/an {p["pct"]:5.1f}%')
    cs = cand.loc[:mid].sum(), cand.loc[mid:].sum()
    print(f'    candidat seul: 1re moitie {cs[0]:+.1f} R | 2e moitie {cs[1]:+.1f} R')


if __name__ == '__main__':
    main()
