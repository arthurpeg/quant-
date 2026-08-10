"""LE CANDIDAT `fee9c1a8ce7d` CONTRE LE BOOK AGRESSIF (celui qui tourne en live).

Correction demandee par l'utilisateur: mon test precedent comparait a b1+b2+b3+b4 @1R.
**Le livre reel est le book AGRESSIF = b1 + b2 + b3 + b4 @1R + KAER@0.5R** (`BOOKS` dans
`edgelab/reports/books_report.py`, deploye sur la demo, magics 101->106).

CE QUE CA CHANGE, ET POURQUOI C'EST LE BON TEST. Le candidat correle **+0.335 en mensuel
(+0.323 en quotidien) avec KAER** — la seule correlation qui depasse le gate de 0.30 du
projet. Or KAER **est dans le book AGRESSIF**. Comparer le candidat a un livre qui ne
contient pas KAER, c'est donc mesurer un ajout diversifiant contre un livre ampute de la
sleeve avec laquelle il fait doublon: le test le plus flatteur possible, et le mauvais.

Les deux memes actifs (NAS100), le meme timeframe (M15), la meme famille (suivi intraday).
La question honnete n'est pas "faut-il l'ajouter" mais **"faut-il le prendre A LA PLACE de
KAER"**. Ce script pose les trois configurations cote a cote:

    AGRESSIF                    b1 b2 b3 b4 @1R + KAER@0.5R          <- le live
    AGRESSIF + CAND             ... + KAER@0.5R + CAND@wR            <- les deux
    AGRESSIF, KAER -> CAND      ... + CAND@wR, KAER retiree          <- l'echange

Tout est rebati depuis les modules canoniques (`monte_carlo_static.build_daily_R` pour les
quatre briques a la cadence LIVE, `intraday.kaer.run_kaer` pour KAER), donc les chiffres
sont ceux du rapport officiel et ne peuvent pas deriver. Metriques: R/an, maxDD, RoMaD,
Sharpe, pire mois, **%/an a risque egal** = (0.10 / (2 x maxDD)) x R/an, et le
**Monte-Carlo par blocs** (P(ruine), P(passage du challenge)) qui est le chiffre qui
termine reellement un compte.

Usage:  python -u scratchpad/nas_cand_agressif.py
"""
import sys, json, warnings
sys.path.insert(0, 'scratchpad'); sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

import kauf_lib as K
from corpus_run import TF, FLOOR, session_bars
from battery_full import build_signals, OUT
from edgelab.reports.books_report import load_sleeves, stats, SLEEVES
from edgelab.reports.monte_carlo_static import simulate, RISKS

SIG, SYM = 'fee9c1a8ce7d', 'NAS100'
AGRESSIF = dict(b1=1.0, b2=1.0, b3=1.0, b4=1.0, KAER=0.5)


def candidate_daily(idx):
    b = K.Bars(SYM, TF[SYM], source='inx', min_bars=5000)
    b.sym = SYM
    ps = json.load(open(f'{OUT}/pine_specs.json'))
    ms = json.load(open(f'{OUT}/mql_specs.json'))
    sigs, err = build_signals(b, SYM, {SIG: 'pine'}, ps, ms)
    if SIG not in sigs:
        sys.exit(f'signal irreconstructible: {err}')
    a = sigs[SIG]
    tab = K.Table(b, 1.0, None, session_bars(b) + 1, session=True, floor_spread=FLOOR)
    i = np.flatnonzero(a != 0)
    i = i[i > K.WARMUP]
    R, xi, _ = tab.walk_idx(i, a[i])
    t = pd.DatetimeIndex(pd.to_datetime(b.time[xi]))
    t = t.tz_convert('UTC') if t.tz is not None else t.tz_localize('UTC')
    s = pd.Series(np.asarray(R, float), index=t.tz_localize(None).normalize())
    return s.groupby(level=0).sum().reindex(idx).fillna(0.0)


def series(M, cand, w, wc):
    s = pd.Series(M[SLEEVES].to_numpy() @ np.array([w[k] for k in SLEEVES]), index=M.index)
    return s + wc * cand if wc else s


def pct(st):
    """%/an a risque egal: compte dimensionne a 2x la maxDD historique."""
    return 100 * (0.10 / (2 * st['maxDD'])) * st['Ryr'] if st['maxDD'] else np.nan


def line(name, s, ref=None):
    st = stats(s)
    p = pct(st)
    d = f"{p - pct(stats(ref)):+6.1f}pt" if ref is not None else '     —'
    print(f"{name:<40}{st['Ryr']:>+8.1f}{st['maxDD']:>8.1f}{st['RoMaD']:>7.2f}"
          f"{st['Sharpe']:>8.2f}{st['worst_month']:>+9.1f}{st['pos_months']:>8.0%}"
          f"{p:>7.1f}%{d:>10}")
    return st


def main():
    M, start, end = load_sleeves()
    cand = candidate_daily(M.index)
    print(f'fenetre canonique du livre : {start:%Y-%m-%d} -> {end:%Y-%m-%d}')
    print(f'candidat: {int((cand != 0).sum())} jours actifs, '
          f'{cand.sum():+.1f} R au total\n')

    print('sleeves seules (rappel):')
    for n in SLEEVES:
        st = stats(M[n])
        print(f"  {n:<6} R/an {st['Ryr']:+7.1f}  maxDD {st['maxDD']:5.1f}  "
              f"RoMaD {st['RoMaD']:5.2f}  Sharpe {st['Sharpe']:5.2f}")
    stc = stats(cand)
    print(f"  {'CAND':<6} R/an {stc['Ryr']:+7.1f}  maxDD {stc['maxDD']:5.1f}  "
          f"RoMaD {stc['RoMaD']:5.2f}  Sharpe {stc['Sharpe']:5.2f}")

    print('\ncorrelations MENSUELLES du candidat aux sleeves du book AGRESSIF:')
    mm = M.copy(); mm['CAND'] = cand
    mq = mm.resample('ME').sum().corr()['CAND'].drop('CAND')
    print('  ' + '  '.join(f'{k} {v:+.3f}' for k, v in mq.items()))

    base = series(M, cand, AGRESSIF, 0)
    print('\n' + '=' * 118)
    print('LE BOOK AGRESSIF (live) CONTRE SES VARIANTES')
    print('=' * 118)
    print(f"{'config':<40}{'R/an':>8}{'maxDD':>8}{'RoMaD':>7}{'Sharpe':>8}"
          f"{'pire mois':>9}{'mois +':>8}{'%/an':>8}{'delta':>10}")
    line('AGRESSIF (b1..b4@1R + KAER@0.5R)', base)
    print('  — on AJOUTE le candidat, KAER reste:')
    for w in (0.25, 0.5, 0.75, 1.0):
        line(f'    + CAND@{w:g}R', series(M, cand, AGRESSIF, w), base)
    print('  — on ECHANGE: KAER retiree, candidat a sa place:')
    noka = dict(AGRESSIF, KAER=0.0)
    for w in (0.5, 0.75, 1.0):
        line(f'    KAER -> CAND@{w:g}R', series(M, cand, noka, w), base)
    print('  — contre-epreuves:')
    line('    KAER@1R (doubler l existant)',
         series(M, cand, dict(AGRESSIF, KAER=1.0), 0), base)
    line('    sans KAER ni candidat', series(M, cand, noka, 0), base)

    print('\n' + '=' * 118)
    print('MONTE-CARLO PAR BLOCS — P(ruine) et P(passage), le chiffre qui termine un compte')
    print('=' * 118)
    cfgs = [('AGRESSIF (live)', base),
            ('AGRESSIF + CAND@0.5R', series(M, cand, AGRESSIF, 0.5)),
            ('KAER -> CAND@0.5R', series(M, cand, noka, 0.5)),
            ('KAER -> CAND@1R', series(M, cand, noka, 1.0))]
    for nm, s in cfgs:
        mc = simulate(s.to_numpy())
        print(f'\n  {nm}   (P(annee positive) = {(mc["annual"] > 0).mean():.1%})')
        for c, f in zip(mc['chal'], mc['fund']):
            mo = f"{c['med_months']:.1f} mois" if c['med_months'] else 'n/a'
            print(f"    risque {c['risk']:.2%}/trade -> challenge: passage {c['p_pass']:.1%} "
                  f"(median {mo}), echec DD {c['p_fail_dd']:.1%}, "
                  f"echec jour {c['p_fail_daily']:.1%}  |  funded: "
                  f"RUINE {f['p_ruin']:.1%}, retrait median {f['med_wd']:.1f}%")

    mid = M.index[len(M) // 2]
    print('\n' + '=' * 118)
    print('DEMI-ECHANTILLONS (le piege TSM-Coil)')
    print('=' * 118)
    for nm, s in cfgs[:3]:
        a, b_ = stats(s.loc[:mid]), stats(s.loc[mid:])
        print(f'  {nm:<26} 1re: R/an {a["Ryr"]:+7.1f} RoMaD {a["RoMaD"]:5.2f} '
              f'%/an {pct(a):5.1f}%  |  2e: R/an {b_["Ryr"]:+7.1f} '
              f'RoMaD {b_["RoMaD"]:5.2f} %/an {pct(b_):5.1f}%')
    print(f'  {"KAER seule":<26} 1re {M["KAER"].loc[:mid].sum():+7.1f} R  |  '
          f'2e {M["KAER"].loc[mid:].sum():+7.1f} R')
    print(f'  {"candidat seul":<26} 1re {cand.loc[:mid].sum():+7.1f} R  |  '
          f'2e {cand.loc[mid:].sum():+7.1f} R')


if __name__ == '__main__':
    main()
