"""ETAPE 9 -- GER40 NET des couts FTMO, puis Monte-Carlo contre le book AGRESSIF.

    python research/scripts/09_ger40_ftmo_montecarlo.py

Suite directe de `08_ger40_book_candidate.py`, qui avait laisse deux trous :
le cout FTMO de GER40 et l'effet sur les temps de passage du challenge.

LE RELEVE FTMO : CE QUI EXISTE, ET CE QUI N'EXISTE PAS.

Le depot a DEJA mesure GER40 sur le terminal FTMO-Demo (compte 1514234500), en
lecture seule, le 2026-08-10 (`scratchpad/ftmo_verify_swaps.py`, valeurs
consignees dans `scratchpad/ftmo_swaps.py`) :

    GER40.cash   long  -447,05 pts -> -6,10 %/an
                 court  -28,54 pts -> -0,39 %/an     taille du point 0,01

La COMMISSION est nulle : chez ce broker les CFD d'indices n'en portent pas
(`ftmo_costs.COMMISSION`, verifie sur NAS100 et US500).

CE QUI MANQUE : LE SPREAD FTMO DE GER40, ET IL N'EST PAS MESURABLE D'ICI.
Aucun terminal MT5 ne tourne sur cette machine, il n'y a qu'une installation, et
elle pointe sur Pepperstone. Basculer sur FTMO demande d'entrer des identifiants
-- ce que je ne fais pas -- et le journal du depot enregistre qu'un simple
`mt5.initialize()` peut RELANCER le terminal et REVEILLER des EA endormis sur un
compte ou le book est deploye (incident du 2026-08-10, magic 111111 / [LONNY]).
Le spread est donc traite par BALAYAGE : on mesure a partir de quelle largeur la
sleeve cesse de convaincre, ce qui transforme l'inconnue en question fermee. Le
plancher Pepperstone (9,0 points) sert de reference basse.

LA COMPARAISON EST FAITE NET DES DEUX COTES. Le book AGRESSIF est reconstruit
par la machinerie canonique de `books_report` (`load_sleeves` + `_ftmo_costs`),
donc net de swap et de commission FTMO, et le Monte-Carlo est celui du depot
(`monte_carlo_static.simulate`) -- meme tirage, meme graine, memes blocs. Rien
n'est reimplemente : seule la sleeve GER40 est ajoutee.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import common as C

from edgelab.reports.books_report import SLEEVES, _ftmo_costs, load_sleeves
from edgelab.reports.ftmo_costs import swap_units
from edgelab.reports.monte_carlo_static import simulate

LOG = C.get_logger("09_ger40_mc")

# --- releve FTMO du 2026-08-10 (lecture seule), cf. scratchpad/ftmo_swaps.py
FTMO_SWAP_PCT = {+1: 6.10, -1: 0.39}      # % ANNUEL du prix, cout positif = on paie
FTMO_TRIPLE_DAY = 4                        # vendredi, comme les autres indices
FTMO_COMMISSION = 0.0                      # CFD indices : aucune commission
BANK_YEAR = 360.0

# --- spread : INCONNU chez FTMO. Balaye en multiples du plancher Pepperstone.
PEPPER_SPREAD_PTS = 9.0
SPREAD_MULTS = (1.0, 2.0, 3.0, 5.0)
SLIPPAGE_PTS = 2.0                         # 1 tick par cote, comme partout ici

WEIGHT = 0.5                               # le poids demande


def ger40_net(spread_mult: float) -> tuple[pd.Series, dict]:
    """Serie journaliere de la sleeve GER40, NETTE des couts FTMO."""
    tr = pd.read_parquet(C.DATA / "ger40_sleeve_trades.parquet")
    meta = C.symbols_meta()["GER40"]
    point = float(meta["point"])

    # --- peage d'entree/sortie : spread + slippage, en R
    px_cost_pts = spread_mult * PEPPER_SPREAD_PTS + SLIPPAGE_PTS
    cost_spread_R = px_cost_pts * point / tr["r_price"].to_numpy()

    # --- swap : units MT5 x taux annuel x prix / 360, rapporte a 1R
    units = swap_units(tr["entry_time"].to_numpy(), tr["exit_time"].to_numpy(),
                       FTMO_TRIPLE_DAY)
    side = tr["side"].to_numpy()
    pct = np.where(side > 0, FTMO_SWAP_PCT[+1], FTMO_SWAP_PCT[-1])
    swap_R = units * (tr["entry_px"].to_numpy() * pct / 100.0 / BANK_YEAR) \
        / tr["r_price"].to_numpy()

    net = tr["R_gross"].to_numpy() - cost_spread_R - swap_R
    s = pd.Series(net, index=pd.DatetimeIndex(tr["exit_time"]).tz_localize(None))
    s = s.groupby(s.index.normalize()).sum()
    yrs = (tr["exit_time"].max() - tr["entry_time"].min()).days / 365.25
    gp, gl = net[net > 0].sum(), -net[net < 0].sum()
    info = dict(spread_pts=spread_mult * PEPPER_SPREAD_PTS,
                ER=float(net.mean()), R_per_yr=float(net.sum() / yrs),
                pf=float(gp / gl) if gl else np.inf,
                cost_spread_R=float(np.median(cost_spread_R)),
                swap_R=float(np.median(swap_R)), units=float(units.mean()),
                t=float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))))
    return s, info


def book_stats(x: pd.Series) -> dict:
    yrs = max((x.index.max() - x.index.min()).days / 365.25, 1e-9)
    cum = x.cumsum()
    dd = float((cum.cummax() - cum).max())
    m = x.resample("ME").sum()
    m = m[:-1] if len(m) > 1 else m
    a = x[x != 0]
    return dict(R_per_yr=float(x.sum() / yrs), maxdd=dd,
                romad=float(x.sum() / yrs / dd) if dd else np.inf,
                sharpe=float(a.mean() / a.std() * np.sqrt(252)),
                worst_month=float(m.min()), pos_months=float((m > 0).mean()))


def main() -> int:
    LOG.info("=" * 78)
    LOG.info("GER40 NET DES COUTS FTMO, PUIS MONTE-CARLO CONTRE AGRESSIF")

    # ---------------------------------------------------------------- 1. net
    LOG.info("-" * 78)
    LOG.info("1) LA SLEEVE, NETTE. Swap FTMO releve le 2026-08-10 : "
             "long -6,10 %%/an, court -0,39 %%/an, triple le vendredi. "
             "Commission nulle (CFD indice).")
    LOG.info("   Spread FTMO INCONNU -> balaye en multiples du plancher "
             "Pepperstone (%.0f pts).", PEPPER_SPREAD_PTS)
    series = {}
    for mult in SPREAD_MULTS:
        s, info = ger40_net(mult)
        series[mult] = s
        LOG.info("   spread %4.0f pts | peage %.4f R + swap %.4f R (%.2f nuits) "
                 "-> E[R] %+.4f | %+5.1f R/an | PF %.3f | t %.2f",
                 info["spread_pts"], info["cost_spread_R"], info["swap_R"],
                 info["units"], info["ER"], info["R_per_yr"], info["pf"], info["t"])

    # ---------------------------------------------------------------- 2. book
    LOG.info("-" * 78)
    LOG.info("2) LE BOOK AGRESSIF, NET (machinerie canonique de books_report)")
    M, start, end = load_sleeves()
    costs = _ftmo_costs(M.index)
    net = M.copy()
    for k, c in costs.items():
        if k in net.columns:
            net[k] = net[k] - c.reindex(net.index).fillna(0.0)
    W = dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.5, TLF=0.5)
    agg = pd.Series(net[SLEEVES].to_numpy() @ np.array([W[s] for s in SLEEVES]),
                    index=net.index)

    # fenetre commune : la sleeve GER40 commence en 2018
    w = agg.index >= series[1.0][series[1.0] != 0].index.min()
    agg_w = agg[w]
    LOG.info("   fenetre de comparaison : %s -> %s (%.1f ans)",
             agg_w.index[0].date(), agg_w.index[-1].date(),
             (agg_w.index[-1] - agg_w.index[0]).days / 365.25)

    b0 = book_stats(agg_w)
    LOG.info("   AGRESSIF net            : %+6.1f R/an | maxDD %5.1f R | "
             "RoMaD %.2f | Sharpe %.2f | pire mois %+.1f R | %.0f %% mois +",
             b0["R_per_yr"], b0["maxdd"], b0["romad"], b0["sharpe"],
             b0["worst_month"], 100 * b0["pos_months"])
    for mult in SPREAD_MULTS:
        gg = series[mult].reindex(agg.index).fillna(0.0)[w]
        b1 = book_stats(agg_w + WEIGHT * gg)
        LOG.info("   + GER40@%.1fR (spr %3.0f pts): %+6.1f R/an | maxDD %5.1f R | "
                 "RoMaD %.2f | Sharpe %.2f | pire mois %+.1f R | %.0f %% mois + %s",
                 WEIGHT, mult * PEPPER_SPREAD_PTS, b1["R_per_yr"], b1["maxdd"],
                 b1["romad"], b1["sharpe"], b1["worst_month"],
                 100 * b1["pos_months"],
                 "  <-- RoMaD AMELIORE" if b1["romad"] > b0["romad"] else "")

    # ---------------------------------------------------------------- 3. MC
    LOG.info("-" * 78)
    LOG.info("3) MONTE-CARLO (block-bootstrap du depot, memes graine et blocs)")
    ref_mult = 2.0            # hypothese de travail : spread FTMO = 2x Pepperstone
    gg = series[ref_mult].reindex(agg.index).fillna(0.0)[w]
    books = {"AGRESSIF (actuel)": agg_w,
             f"AGRESSIF + GER40@{WEIGHT}R": agg_w + WEIGHT * gg}
    LOG.info("   hypothese de spread retenue pour le MC : %.0f pts (2x Pepperstone)",
             ref_mult * PEPPER_SPREAD_PTS)

    res = {}
    for name, s in books.items():
        mc = simulate(s.to_numpy())
        res[name] = mc
        ann, mdd = mc["annual"], mc["mdd"]
        LOG.info("   %-26s | 1 an : median %+6.1f R | P(annee +) %.1f %% | "
                 "maxDD median %5.1f R | 5e pct %+6.1f R", name,
                 float(np.median(ann)), 100 * float((ann > 0).mean()),
                 float(np.median(mdd)), float(np.percentile(ann, 5)))

    LOG.info("-" * 78)
    LOG.info("4) CHALLENGE : P(valider), delai median et MOYEN, par risque/trade")
    LOG.info("   %-26s %7s %9s %9s %9s %9s", "book", "risque", "P(valider)",
             "mediane", "moyenne", "echec DD")
    for name, mc in res.items():
        for c in mc["chal"]:
            if c["risk"] not in (0.005, 0.01, 0.015):
                continue
            LOG.info("   %-26s %6.2f%% %8.1f %% %7.1f mois %6.1f mois %8.1f %%",
                     name, 100 * c["risk"], 100 * c["p_pass"],
                     c["med_months"] or float("nan"),
                     c["mean_months"] or float("nan"), 100 * c["p_fail_dd"])

    LOG.info("-" * 78)
    LOG.info("5) FUNDED : retrait annuel median et ruine")
    LOG.info("   %-26s %7s %14s %10s", "book", "risque", "retrait median", "ruine")
    for name, mc in res.items():
        for f in mc["fund"]:
            if f["risk"] not in (0.005, 0.01):
                continue
            LOG.info("   %-26s %6.2f%% %12.1f %% %9.1f %%", name,
                     100 * f["risk"], f["med_wd"], 100 * f["p_ruin"])

    out = {}
    for name, mc in res.items():
        out[name] = dict(
            annual_median=float(np.median(mc["annual"])),
            p_year_positive=float((mc["annual"] > 0).mean()),
            mdd_median=float(np.median(mc["mdd"])),
            chal=[{k: (float(v) if v is not None else None) for k, v in c.items()}
                  for c in mc["chal"]],
            fund=[{k: float(v) for k, v in f.items()} for f in mc["fund"]])
    (C.DATA / "ger40_montecarlo.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    LOG.info("-" * 78)
    LOG.info("resultats -> research/data/ger40_montecarlo.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
