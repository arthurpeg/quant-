"""ETAPE 12 -- refaire la selection NATIVEMENT NETTE des couts FTMO.

    python research/scripts/12_net_ftmo_shortlist.py [--mc]

L'etape 11 a produit un panier qui ameliore le book (+1,28 pt/an a risque egal)
mais dont **aucune composante ne franchit le plancher RoMaD du depot une fois
nette de FTMO** (0,38 / 0,18 / 0,23 / 0,22). La cause n'est pas le hasard : la
selection avait ete faite sur des couts **Pepperstone**, et le swap FTMO a coupe
les composantes en deux.

L'HYPOTHESE QUI A MOTIVE CETTE ETAPE ETAIT FAUSSE, ET LA MESURE L'A DIT.
Le raisonnement de depart : le swap ne frappe QUE les sleeves qui tiennent la
nuit (`ftmo_costs` : *"b1, HMASTO et TLF sont intraday pures, donc ZERO unite de
swap"*), donc les candidats **M5/M15 a horizon court** devraient survivre le
mieux et le panier de l'etape 11 -- des H1/H4 tenant 1,15 a 1,28 nuits -- serait
du mauvais cote de cette ligne.

**C'est l'inverse.** Les 5 cellules qui franchissent le plancher une fois nettes
portent **1,18 nuit en mediane**, contre **0,32 pour les 20 recalees**. La raison
est que le cout qui MORD n'est pas le meme aux deux echelles : `1R = m x ATR14`
est GRAND en H1/H4, donc le swap y pese peu et le spread encore moins ; il est
PETIT en M5/M15, donc c'est le **spread** qui les tue, pas le swap. `orb_break`
US100 M5 k=12 ne porte que 0,03 nuit -- donc quasiment aucun swap -- et rend
-3,4 R/an quand meme. La granularite protege du swap et expose au spread, et le
second est le plus cher des deux ici.

CE SCRIPT REFAIT DONC LE CLASSEMENT DANS LE BON ORDRE : cout FTMO d'abord,
classement ensuite. Trois differences avec l'etape 10 :

  1. TOUTES les geometries survivantes sont evaluees (94 configurations au seuil
     pre-enregistre), et la deduplication garde la meilleure **NETTE** par
     (signal, actif, UT, k) -- pas la meilleure brute.
  2. Le **nombre de nuits portees** est rendu en colonne : c'est le predicteur
     du cout, et il explique le classement mieux que le signal lui-meme.
  3. Les couts viennent de `research/data/ftmo_specs.json`, RELEVE EN DIRECT sur
     le terminal FTMO le 2026-08-18 (etape 13, lecture seule) : spread mesure
     par la meme methode que chez Pepperstone (mediane des non nuls en heures
     liquides) et swap converti en % annuel du prix. Plus aucun actif n'est
     ecarte faute de taux -- UK100 et GBPJPY sont desormais chiffres.

DEUX FAITS DU RELEVE DU 2026-08-18 QUI CHANGENT LES CONCLUSIONS PRECEDENTES.

* **LE SPREAD FTMO DE GER40 EST PLUS BAS QUE CELUI DE PEPPERSTONE** : 0,531 bps
  contre 0,588. Le balayage de l'etape 9 partait du plancher Pepperstone comme
  borne BASSE et testait 1x a 5x -- la realite est a 0,90x, donc sous le meilleur
  cas envisage.
* **LES COTES LONG ET COURT D'US30 SE SONT INVERSES** depuis le releve du
  2026-08-10 : long +0,77 %/an et court +7,52 %/an aujourd'hui, contre 7,82 et
  -0,33 il y a huit jours. Ce n'est pas une erreur de mesure, c'est le portage
  qui a bouge -- et cela frappe directement `skew` US30, la seule composante
  decorrelee retenue a l'etape 12. Rappel de la limite deja consignee par le
  depot : MT5 ne sert que le taux COURANT, pas son historique ; un backtest de
  huit ans applique donc le taux d'aujourd'hui a des annees ou il etait autre.
"""
from __future__ import annotations

import argparse
import importlib.util
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


def _load(name, fname):
    sp = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / fname)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


BT = _load("bt_engine", "05_vectorized_backtester.py")
GEO = _load("geo_engine", "06_stop_geometry.py")
IC3 = _load("ic_engine", "03_compute_signal_ic.py")
B11 = _load("basket", "11_basket_montecarlo.py")
LOG = C.get_logger("12_net")

Q, MIN_N, BANK_YEAR = 0.90, 300, 360.0
SLIP_BPS = 0.20                    # aller-retour, hypothese ; balayee plus bas

SPECS = json.loads((C.DATA / "ftmo_specs.json").read_text(encoding="utf-8"))
FTMO_SWAP = {k: {+1: v["swap_long_pct"], -1: v["swap_short_pct"]}
             for k, v in SPECS.items()}
FTMO_SPREAD_BPS = {k: v["spread_bps"] for k, v in SPECS.items()}
FTMO_TRIPLE = {k: v["triple_day"] for k, v in SPECS.items()}
NO_RATE = tuple()                  # plus aucun : tout est mesure


def net_of(row) -> tuple[pd.Series, dict] | None:
    tr = B11.sleeve_trades(dict(signal=row["signal_type"], asset=row["asset"],
                                tf=row["timeframe"], k=int(row["k"]),
                                stop=float(row["atr_mult"])))
    if tr is None or tr.empty:
        return None
    asset = row["asset"]
    if asset not in FTMO_SPREAD_BPS:
        return None
    # LE SPREAD EST APPLIQUE EN BPS DU PRIX D'ENTREE, pas en points : les
    # echelles de point different entre les deux brokers (GER40 vaut 0,01 chez
    # FTMO et 0,1 chez Pepperstone) et les barres du backtest sont celles de
    # Pepperstone. Le bps est la seule unite commune aux deux.
    rt_bps = FTMO_SPREAD_BPS[asset] + SLIP_BPS
    cost_R = (rt_bps / 1e4) * tr["entry_px"].to_numpy() / tr["r_price"].to_numpy()

    units = swap_units(tr["entry_time"].to_numpy(), tr["exit_time"].to_numpy(),
                       FTMO_TRIPLE.get(asset, 4))
    tbl = FTMO_SWAP[asset]
    pct = np.where(tr["side"].to_numpy() > 0, tbl[+1], tbl[-1])
    swap_R = units * (tr["entry_px"].to_numpy() * pct / 100.0 / BANK_YEAR) \
        / tr["r_price"].to_numpy()
    comm = B11.FTMO_COMM.get(asset, 0.0)
    comm_R = 2.0 * comm * tr["entry_px"].to_numpy() / tr["r_price"].to_numpy()

    net = tr["R_gross"].to_numpy() - cost_R - swap_R - comm_R
    s = pd.Series(net, index=pd.DatetimeIndex(tr["exit_time"]).tz_localize(None))
    s = s.groupby(s.index.normalize()).sum()
    yrs = max((tr["exit_time"].max() - tr["entry_time"].min()).days / 365.25, 1e-9)
    cum = s.cumsum()
    dd = float((cum.cummax() - cum).max())
    gp, gl = net[net > 0].sum(), -net[net < 0].sum()
    return s, dict(nights=float(units.mean()), swap_R=float(np.median(swap_R)),
                   ER_net=float(net.mean()), R_per_yr=float(net.sum() / yrs),
                   maxdd=dd, romad=float(net.sum() / yrs / dd) if dd else np.inf,
                   pf=float(gp / gl) if gl else np.inf, n=int(len(net)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mc", action="store_true", help="lance aussi le Monte-Carlo")
    a = ap.parse_args()

    d = pd.read_parquet(C.DATA / "stop_geometry_results.parquet")
    p = d[d["is_primary_threshold"]]
    surv = p[(p["both_halves_positive"]) & (p["inverse_expectancy_R"] < 0)
             & (p["expectancy_R"] > 0) & (p["n_trades"] >= MIN_N)
             & (p["placebo_beat_frac"] <= 0.10)]
    LOG.info("=" * 104)
    LOG.info("SELECTION NATIVEMENT NETTE FTMO -- %d configurations survivantes "
             "au seuil pre-enregistre", len(surv))
    excl = surv[surv["asset"].isin(NO_RATE)]
    LOG.info("ECARTES faute de taux de swap FTMO releve (%s) : %d configurations, "
             "%d cellules", "/".join(NO_RATE), len(excl),
             excl.groupby(["signal_type", "asset", "timeframe", "k"]).ngroups)
    surv = surv[~surv["asset"].isin(NO_RATE)]

    rows, series = [], {}
    for _, r in surv.iterrows():
        got = net_of(r)
        if got is None:
            continue
        s, m = got
        key = (r["signal_type"], r["asset"], r["timeframe"], int(r["k"]))
        rows.append(dict(signal=r["signal_type"], asset=r["asset"],
                         tf=r["timeframe"], k=int(r["k"]),
                         stop=float(r["atr_mult"]), **m))
        series[(key, float(r["atr_mult"]))] = s

    out = pd.DataFrame(rows)
    # DEDUPLICATION SUR LE NET, pas sur le brut
    out = out.sort_values("romad", ascending=False).drop_duplicates(
        ["signal", "asset", "tf", "k"])

    # correlation au book, net
    M, _x, _y = load_sleeves()
    cst = _ftmo_costs(M.index)
    nb = M.copy()
    for kk, c in cst.items():
        if kk in nb.columns:
            nb[kk] = nb[kk] - c.reindex(nb.index).fillna(0.0)
    W = dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.5, TLF=0.5)
    agg = pd.Series(nb[SLEEVES].to_numpy() @ np.array([W[s] for s in SLEEVES]),
                    index=nb.index)
    agg_m = agg.resample("ME").sum()
    corrs = []
    for _, r in out.iterrows():
        s = series[((r["signal"], r["asset"], r["tf"], r["k"]), r["stop"])]
        sm = s.reindex(agg.index).fillna(0.0).resample("ME").sum()
        ok = (sm != 0) | (agg_m != 0)
        corrs.append(float(np.corrcoef(sm[ok], agg_m[ok])[0, 1]))
    out["corr_book"] = corrs
    out = out.sort_values("romad", ascending=False)
    out.to_parquet(C.DATA / "net_ftmo_shortlist.parquet", index=False)

    LOG.info("-" * 104)
    LOG.info("%-17s %-7s %-4s %3s %5s %7s %7s %8s %7s %7s %8s", "signal", "actif",
             "UT", "k", "stop", "nuits", "R/an", "maxDD", "RoMaD", "PF", "corr")
    for _, r in out.iterrows():
        tag = ""
        if r["romad"] >= 0.79:
            tag = "  << au-dessus de la brique 1"
        elif r["romad"] < 0.38:
            tag = "  (sous le plancher)"
        LOG.info("%-17s %-7s %-4s %3d %5.1f %7.2f %+7.1f %8.1f %7.2f %7.3f %+8.3f%s",
                 r["signal"], r["asset"], r["tf"], r["k"], r["stop"], r["nights"],
                 r["R_per_yr"], r["maxdd"], r["romad"], r["pf"], r["corr_book"], tag)

    LOG.info("-" * 104)
    keep = out[out["romad"] >= 0.38]
    LOG.info("%d cellules sur %d franchissent le plancher RoMaD 0,38 UNE FOIS "
             "NETTES ; mediane des nuits portees : %.2f contre %.2f pour les "
             "recalees", len(keep), len(out), keep["nights"].median(),
             out[out["romad"] < 0.38]["nights"].median())

    # ------------------------------------------------ le panier, refait sur le net
    pick = (keep[keep["corr_book"] <= 0.10]
            .sort_values("romad", ascending=False)
            .drop_duplicates(["signal", "asset"]))
    LOG.info("-" * 104)
    LOG.info("PANIER REFAIT SUR LE NET (corr <= +0,10, RoMaD net >= 0,38, "
             "une config par signal x actif) : %d composantes", len(pick))
    for _, r in pick.iterrows():
        LOG.info("   %-16s %-7s %-4s k=%-2d stop %.1f | %.2f nuits | %+5.1f R/an | "
                 "RoMaD %.2f | corr %+.3f", r["signal"], r["asset"], r["tf"],
                 r["k"], r["stop"], r["nights"], r["R_per_yr"], r["romad"],
                 r["corr_book"])
    if pick.empty:
        LOG.warning("   aucune composante -- le panier net n'existe pas")
        return 0

    idx = pd.date_range(agg.index.min(), agg.index.max(), freq="D")
    comp = [series[((r["signal"], r["asset"], r["tf"], r["k"]), r["stop"])]
            .reindex(idx).fillna(0.0) for _, r in pick.iterrows()]
    basket = sum(comp)
    st = B11.stat(basket[basket.index >= basket[basket != 0].index.min()])
    LOG.info("   PANIER : %+5.1f R/an | maxDD %5.1f R | RoMaD %.2f | somme des "
             "maxDD %.1f -> %.1f R economises",
             st["R_per_yr"], st["maxdd"], st["romad"],
             sum(B11.stat(c[c != 0])["maxdd"] for c in comp),
             sum(B11.stat(c[c != 0])["maxdd"] for c in comp) - st["maxdd"])

    w = agg.index >= basket[basket != 0].index.min()
    agg_w, bk = agg[w], basket.reindex(agg.index).fillna(0.0)[w]
    b0 = B11.stat(agg_w)
    LOG.info("-" * 104)
    LOG.info("APPORT AU BOOK (net des deux cotes)")
    LOG.info("   AGRESSIF seul     : %+6.1f R/an | maxDD %5.1f | RoMaD %.2f | "
             "%%/an a risque egal %5.2f %%", b0["R_per_yr"], b0["maxdd"],
             b0["romad"], 10 * b0["romad"])
    books = {"AGRESSIF (actuel)": agg_w}
    for wt in (0.25, 0.5, 1.0):
        s2 = B11.stat(agg_w + wt * bk)
        books[f"+ panier net @{wt}R"] = agg_w + wt * bk
        LOG.info("   + panier @ %.2fR   : %+6.1f R/an | maxDD %5.1f | RoMaD %.2f | "
                 "%%/an a risque egal %5.2f %% (%+.2f pt)", wt, s2["R_per_yr"],
                 s2["maxdd"], s2["romad"], 10 * s2["romad"],
                 10 * (s2["romad"] - b0["romad"]))

    if a.mc:
        LOG.info("-" * 104)
        LOG.info("MONTE-CARLO")
        for name, s in books.items():
            mc = simulate(s.to_numpy())
            ch = {c["risk"]: c for c in mc["chal"]}
            fu = {f["risk"]: f for f in mc["fund"]}
            LOG.info("   %-22s | 1 an med %+6.1f R | P(valider)@1%% %.1f %% | "
                     "mediane %.1f mois | ruine funded@0,5%% %.1f %%", name,
                     float(np.median(mc["annual"])), 100 * ch[0.01]["p_pass"],
                     ch[0.01]["med_months"], 100 * fu[0.005]["p_ruin"])
    LOG.info("-" * 104)
    LOG.info("resultats -> research/data/net_ftmo_shortlist.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
