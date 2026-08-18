"""ETAPE 15 -- le book AGRESSIF SANS la brique 3, avec les deux candidates.

    python research/scripts/15_book_sans_b3.py

ANALYSE SEULE. Ce script ne modifie ni `edgelab/live/config_live.yaml`, ni
`edgelab/reports/books_report.py`, ni quoi que ce soit de la production. La
brique 3 est deployee en live (magics 103 et 104) et son passage a 0,5R le
2026-08-10 avait demande une instruction explicite plus un
`python -m edgelab.live.verify` : retirer une sleeve du book n'est pas un effet
de bord d'un calcul.

CE QUI EST MESURE. `A` = b1 + b2 + b4 @1R, b3 @0,5R, HMASTO + TLF @0,5R, tel que
`books_report.BOOKS['AGRESSIF']` le definit aujourd'hui. On en retire b3, puis on
ajoute les deux candidates de l'etape 14 :

    `skew` US30 H4 k=5 stop 4,0   -- RoMaD net 0,73, corr -0,004
    `vwap_z` GER40 H1 k=24 stop 3,0 -- RoMaD net 0,86, corr +0,218

CE QUE LE RETRAIT DE b3 VAUT, MESURE A L'ETAPE 14 : sur la fenetre commune
2018-07 -> 2026-07, NETTE des couts FTMO, la brique 3 rend **+0,2 R/an pour
21,3 R de drawdown** (RoMaD 0,01) -- elle ne rapporte plus rien et porte le 2e
plus gros drawdown du book. Le depot l'avait deja divisee par deux le
2026-08-10 pour cette raison, en gardant volontairement une demi-dose *"pour
garder l'option sur un retour de regime crypto"*. **Ce script mesure le retrait
complet ; il ne tranche pas l'option.**

LA RESERVE QUI VAUT POUR TOUT LE FICHIER : les deux candidates sont in-sample,
tirees d'une grille de 28 300 cellules. Le retrait de b3, lui, ne depend
d'aucune selection -- c'est une mesure sur une sleeve deja deployee.
"""
from __future__ import annotations

import importlib.util

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import common as C

from edgelab.reports.books_report import SLEEVES, _ftmo_costs, load_sleeves
from edgelab.reports.monte_carlo_static import simulate


def _load(name, fname):
    sp = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / fname)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


S14 = _load("swaptest", "14_swap_test_vs_book.py")
LOG = C.get_logger("15_sans_b3")

W_NOW = dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.5, TLF=0.5)
RISKS_SHOW = (0.005, 0.0075, 0.01, 0.015)


def main() -> int:
    M, _a, _b = load_sleeves()
    cst = _ftmo_costs(M.index)
    net = M.copy()
    for k, c in cst.items():
        if k in net.columns:
            net[k] = net[k] - c.reindex(net.index).fillna(0.0)

    cands = {n: S14.cand_series(s) for n, s in S14.CANDIDATES.items()}
    start = max(min(v[v != 0].index.min() for v in cands.values()), net.index.min())
    idx = net.index[net.index >= start]
    net = net.loc[idx]
    cands = {n: v.reindex(idx).fillna(0.0) for n, v in cands.items()}
    SK, GE = cands["skew US30"], cands["vwap_z GER40"]

    def mix(w: dict) -> pd.Series:
        return pd.Series(net[SLEEVES].to_numpy() @ np.array([w.get(s, 0.0)
                                                             for s in SLEEVES]),
                         index=idx)

    A = mix(W_NOW)
    W_NO3 = dict(W_NOW, b3=0.0)
    A3 = mix(W_NO3)

    books = {
        "A -- book actuel (b3@0,5R)": A,
        "A sans b3": A3,
        "A sans b3 + les 2 @0,25R": A3 + 0.25 * (SK + GE),
        "A sans b3 + les 2 @0,5R": A3 + 0.5 * (SK + GE),
        "A sans b3 + les 2 @1R": A3 + SK + GE,
        "A AVEC b3 + les 2 @0,5R": A + 0.5 * (SK + GE),
    }

    LOG.info("=" * 104)
    LOG.info("BOOK AGRESSIF SANS LA BRIQUE 3 -- fenetre %s -> %s (%.1f ans), "
             "NET des couts FTMO", idx[0].date(), idx[-1].date(),
             (idx[-1] - idx[0]).days / 365.25)
    LOG.info("ANALYSE SEULE : aucune configuration de production n'est modifiee.")

    LOG.info("-" * 104)
    LOG.info("%-30s %9s %8s %8s %9s %10s %9s", "configuration", "R/an", "maxDD",
             "RoMaD", "Sharpe", "%/an risque egal", "pire mois")
    stats = {}
    for n, x in books.items():
        st = S14.stat(x)
        m = x.resample("ME").sum()
        m = m[:-1] if len(m) > 1 else m
        stats[n] = st
        LOG.info("%-30s %+9.1f %8.1f %8.2f %9.2f %10.2f %9.1f", n,
                 st["R_per_yr"], st["maxdd"], st["romad"], st["sharpe"],
                 st["pct_eq"], float(m.min()))
    base = stats["A -- book actuel (b3@0,5R)"]["pct_eq"]
    LOG.info("-" * 104)
    for n, st in stats.items():
        LOG.info("   %-30s %+6.2f pt contre le book actuel", n, st["pct_eq"] - base)

    # ------------------------------------------------------------------ MC
    LOG.info("-" * 104)
    LOG.info("MONTE-CARLO (block-bootstrap du depot, meme graine, memes blocs)")
    res = {}
    for n, x in books.items():
        res[n] = simulate(x.to_numpy())
        mc = res[n]
        LOG.info("   %-30s | 1 an : median %+6.1f R | P(+) %.1f %% | 5e pct %+6.1f R "
                 "| maxDD median %5.1f R", n, float(np.median(mc["annual"])),
                 100 * float((mc["annual"] > 0).mean()),
                 float(np.percentile(mc["annual"], 5)), float(np.median(mc["mdd"])))

    LOG.info("-" * 104)
    LOG.info("CHALLENGE -- P(valider), delai median et MOYEN, mode d'echec")
    LOG.info("   %-30s %7s %10s %9s %9s %9s %9s", "configuration", "risque",
             "P(valider)", "mediane", "moyenne", "echec DD", "echec jour")
    for n, mc in res.items():
        for c in mc["chal"]:
            if c["risk"] not in RISKS_SHOW:
                continue
            LOG.info("   %-30s %6.2f%% %9.1f %% %6.1f mois %6.1f mois %8.1f %% %8.1f %%",
                     n, 100 * c["risk"], 100 * c["p_pass"],
                     c["med_months"] or float("nan"),
                     c["mean_months"] or float("nan"),
                     100 * c["p_fail_dd"], 100 * c["p_fail_daily"])

    LOG.info("-" * 104)
    LOG.info("FUNDED -- retrait annuel median et ruine")
    LOG.info("   %-30s %7s %15s %10s", "configuration", "risque",
             "retrait median", "ruine")
    for n, mc in res.items():
        for f in mc["fund"]:
            if f["risk"] not in (0.005, 0.0075, 0.01):
                continue
            LOG.info("   %-30s %6.2f%% %13.1f %% %9.1f %%", n, 100 * f["risk"],
                     f["med_wd"], 100 * f["p_ruin"])

    # ------------------------------------------------------------------ par annee
    LOG.info("-" * 104)
    LOG.info("PAR ANNEE (R nets), pour voir ce que le retrait de b3 coute et quand")
    yrs = sorted({t.year for t in idx})
    hdr = "   annee " + " ".join(f"{n[:14]:>15s}" for n in books)
    LOG.info(hdr)
    for y in yrs:
        m = [f"{books[n][idx.year == y].sum():+15.1f}" for n in books]
        LOG.info("   %5d %s", y, " ".join(m))

    LOG.info("-" * 104)
    LOG.info("RESERVE : les deux candidates sont IN-SAMPLE (grille de 28 300 "
             "cellules). Le retrait de b3, lui, ne depend d'aucune selection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
