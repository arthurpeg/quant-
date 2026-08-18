"""ETAPE 11 -- le panier de petits decorreles, NET FTMO, au Monte-Carlo.

    python research/scripts/11_basket_montecarlo.py

`system.md` etablit deux choses qui, mises ensemble, designent ce test :
*"adding always beats swapping"* (aucune rarete de slot) et *"a sleeve with a poor
standalone RoMaD is worth only its decorrelation, so it is dosed at half"*. La
shortlist d'exp-024 montre alors l'arbitrage : les meilleurs RoMaD sont les
sleeves intraday NAS100, donc CORRELEES au book ; les vraiment decorrelees sont
petites. D'ou la question : **plusieurs petites decorrelees valent-elles mieux
qu'une grosse correlee ?**

LE PANIER EST DEFINI PAR UNE REGLE, PAS A L'OEIL. C'est le correctif de l'erreur
d'exp-023 (deux candidats choisis en lisant le haut d'un tableau) :

    corr mensuelle au book <= +0,10     (une correlation NEGATIVE est un bonus)
    RoMaD standalone >= 0,38            (le plancher du GER40 ORB deja rejete)
    une seule configuration par (signal, actif)   -- sinon on compte deux fois
                                                     le meme bord

TROIS PRECAUTIONS.

* LE PANIER HERITE DE TOUTE LA SELECTION QUI L'A PRODUIT. Ses composantes
  viennent d'une grille de 2 595 configurations, elle-meme tiree de 173 cellules
  sur 28 300. Un panier de survivants in-sample reste in-sample, et son RoMaD
  agrege beneficie en plus du fait que les composantes ont ete choisies POSITIVES.
  Le temoin qui compte est donc la comparaison a un panier de MEME taille tire au
  hasard dans la shortlist -- il est calcule ici.
* LE SWAP FTMO EST MESURE POUR LES QUATRE ACTIFS DU PANIER (US30, XAUUSD, GER40),
  releve le 2026-08-10. Le SPREAD FTMO reste inconnu : meme balayage qu'a
  l'etape 9, hypothese de travail a 2x le plancher Pepperstone.
* LE DOSAGE SUIT LA REGLE MAISON : 0,5R par sleeve pour un RoMaD standalone
  faible. 0,25R est teste aussi, parce que quatre sleeves a 0,5R font 2R
  d'exposition ajoutee et que le book en porte deja 4,5.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import common as C
import signals as SG

from edgelab.reports.books_report import SLEEVES, _ftmo_costs, load_sleeves
from edgelab.reports.ftmo_costs import swap_units
from edgelab.reports.monte_carlo_static import simulate


def _load(name: str, fname: str):
    sp = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / fname)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


BT = _load("bt_engine", "05_vectorized_backtester.py")
GEO = _load("geo_engine", "06_stop_geometry.py")
IC3 = _load("ic_engine", "03_compute_signal_ic.py")
LOG = C.get_logger("11_basket")

Q = 0.90
MAX_CORR = 0.10
MIN_ROMAD = 0.38
BANK_YEAR = 360.0
SPREAD_MULT = 2.0          # hypothese de travail, cf. etape 9
SLIP_PTS = 2.0

# Swap FTMO en % ANNUEL du prix, positif = on paie. Releve 2026-08-10, lecture
# seule (scratchpad/ftmo_swaps.py). Le cote court des indices US est NEGATIF :
# on est paye a tenir un short d'indice US la nuit.
FTMO_SWAP = {
    "US30":   {+1: 7.82, -1: -0.33},
    "US100":  {+1: 7.52, -1: -0.04},
    "US500":  {+1: 6.71, -1: 0.77},
    "GER40":  {+1: 6.10, -1: 0.39},
    "XAUUSD": {+1: 7.65, -1: 1.24},
}
FTMO_COMM = {"XAUUSD": 0.000007}       # fraction du notionnel PAR COTE
TRIPLE_DAY = {"XAUUSD": 2}             # mercredi pour l'or, vendredi partout ailleurs


def sleeve_trades(row) -> pd.DataFrame | None:
    """Rejoue une cellule et rend ses trades (R brut + tout ce qu'il faut au cout)."""
    asset, tf, k = row["asset"], row["tf"], int(row["k"])
    bars = C.load(asset, tf)
    if bars is None:
        return None
    d = pd.read_parquet(C.DATA / "stop_geometry_results.parquet")
    cell = d[(d["signal_type"] == row["signal"]) & (d["asset"] == asset)
             & (d["timeframe"] == tf) & (d["k"] == k)
             & (d["atr_mult"] == row["stop"]) & (d["is_primary_threshold"])].iloc[0]
    params = json.loads(cell["params"])
    spec = dict(type=row["signal"], family=cell["family"], sign_prior=0, params=params)
    drv = None
    if spec["type"] in SG.CROSS_TYPES:
        drv = IC3.driver_series(params["driver"], tf, bars.t)
        if drv is None:
            return None
    sig = SG.compute(bars, spec, drv)
    atr = bars.atr(C.ATR_LEN)
    r_px = float(row["stop"]) * atr
    pr = BT.causal_rank(sig)
    hi, lo = pr >= Q, pr <= (1 - Q)
    n = len(bars)
    ok = (np.isfinite(sig) & np.isfinite(pr) & np.isfinite(r_px) & (r_px > 0)
          & (np.arange(n) + 1 + k < n))
    cand = np.flatnonzero(ok & (hi | lo))
    side = np.where(hi[cand], 1.0, -1.0) * (1.0 if cell["ic_mean"] > 0 else -1.0)
    gross, xi, _ = GEO.simulate_geometry(bars.o, bars.h, bars.l, cand, side,
                                         r_px[cand], k)
    keep = BT.nonoverlap(cand + 1, xi)
    i_in = (cand + 1)[keep]
    return pd.DataFrame(dict(
        asset=asset, entry_time=bars.t[i_in], exit_time=bars.t[xi[keep]],
        side=side[keep], R_gross=gross[keep], r_price=r_px[cand[keep]],
        entry_px=bars.o[i_in]))


def net_series(tr: pd.DataFrame, spread_mult: float) -> pd.Series:
    """R net FTMO : spread+slippage a l'aller-retour, swap par nuit, commission."""
    asset = tr["asset"].iloc[0]
    meta = C.symbols_meta()[asset]
    point = float(meta["point"])
    pep = json.loads(C.costs_path().read_text(encoding="utf-8"))[asset]
    floor_pts = float((pep.get("H1") or next(iter(pep.values())))["spread_floor_pts"])

    px_pts = spread_mult * floor_pts + SLIP_PTS
    cost_R = px_pts * point / tr["r_price"].to_numpy()

    units = swap_units(tr["entry_time"].to_numpy(), tr["exit_time"].to_numpy(),
                       TRIPLE_DAY.get(asset, 4))
    side = tr["side"].to_numpy()
    tbl = FTMO_SWAP.get(asset)
    if tbl is None:
        raise KeyError(f"swap FTMO non releve pour {asset}")
    pct = np.where(side > 0, tbl[+1], tbl[-1])
    swap_R = units * (tr["entry_px"].to_numpy() * pct / 100.0 / BANK_YEAR) \
        / tr["r_price"].to_numpy()

    comm = FTMO_COMM.get(asset, 0.0)
    comm_R = (2.0 * comm * tr["entry_px"].to_numpy()) / tr["r_price"].to_numpy()

    net = tr["R_gross"].to_numpy() - cost_R - swap_R - comm_R
    s = pd.Series(net, index=pd.DatetimeIndex(tr["exit_time"]).tz_localize(None))
    return s.groupby(s.index.normalize()).sum()


def stat(x: pd.Series) -> dict:
    yrs = max((x.index.max() - x.index.min()).days / 365.25, 1e-9)
    cum = x.cumsum()
    dd = float((cum.cummax() - cum).max())
    m = x.resample("ME").sum()
    m = m[:-1] if len(m) > 1 else m
    a = x[x != 0]
    return dict(R_per_yr=float(x.sum() / yrs), maxdd=dd,
                romad=float(x.sum() / yrs / dd) if dd else np.inf,
                sharpe=float(a.mean() / a.std() * np.sqrt(252)) if len(a) > 2 else np.nan,
                worst_month=float(m.min()) if len(m) else np.nan)


def main() -> int:
    sl = pd.read_parquet(C.DATA / "candidate_shortlist.parquet")
    LOG.info("=" * 92)
    LOG.info("PANIER DE PETITS DECORRELES -- regle : corr <= %+.2f, RoMaD >= %.2f, "
             "une config par (signal, actif)", MAX_CORR, MIN_ROMAD)

    pick = (sl[(sl["corr_book"] <= MAX_CORR) & (sl["romad"] >= MIN_ROMAD)]
            .sort_values("romad", ascending=False)
            .drop_duplicates(["signal", "asset"]))
    LOG.info("-" * 92)
    LOG.info("%d composantes retenues sur %d candidats :", len(pick), len(sl))
    for _, r in pick.iterrows():
        LOG.info("   %-16s %-7s %-4s k=%-2d stop %.1f | %+5.1f R/an | maxDD %5.1f | "
                 "RoMaD %.2f | corr %+.3f", r["signal"], r["asset"], r["tf"],
                 int(r["k"]), r["stop"], r["R_per_yr"], r["maxdd"], r["romad"],
                 r["corr_book"])

    # ---------------------------------------------------------------- net FTMO
    LOG.info("-" * 92)
    LOG.info("COMPOSANTES NETTES FTMO (swap mesure 2026-08-10 ; spread = %.0fx le "
             "plancher Pepperstone)", SPREAD_MULT)
    comps = {}
    for _, r in pick.iterrows():
        tr = sleeve_trades(r)
        if tr is None or tr.empty:
            continue
        s = net_series(tr, SPREAD_MULT)
        comps[f"{r['signal']} {r['asset']}"] = s
        st = stat(s)
        nights = swap_units(tr["entry_time"].to_numpy(), tr["exit_time"].to_numpy(),
                            TRIPLE_DAY.get(r["asset"], 4)).mean()
        LOG.info("   %-24s %+5.1f R/an | maxDD %5.1f | RoMaD %.2f | %.2f nuits | "
                 "%.0f %% longs", f"{r['signal']} {r['asset']}", st["R_per_yr"],
                 st["maxdd"], st["romad"], nights, 100 * (tr["side"] > 0).mean())

    # ---------------------------------------------------------------- le panier
    idx = pd.date_range(min(s.index.min() for s in comps.values()),
                        max(s.index.max() for s in comps.values()), freq="D")
    basket = sum(s.reindex(idx).fillna(0.0) for s in comps.values())
    bst = stat(basket)
    LOG.info("-" * 92)
    LOG.info("LE PANIER (somme a 1R chacune, avant dosage)")
    LOG.info("   %+5.1f R/an | maxDD %5.1f R | RoMaD %.2f | Sharpe %.2f | "
             "pire mois %+.1f R", bst["R_per_yr"], bst["maxdd"], bst["romad"],
             bst["sharpe"], bst["worst_month"])
    LOG.info("   somme des R/an des composantes : %+.1f | somme des maxDD : %.1f "
             "-> la mutualisation economise %.1f R de drawdown",
             sum(stat(s)["R_per_yr"] for s in comps.values()),
             sum(stat(s)["maxdd"] for s in comps.values()),
             sum(stat(s)["maxdd"] for s in comps.values()) - bst["maxdd"])

    # temoin : un panier de meme taille tire au hasard dans la shortlist
    rng = np.random.default_rng(11)
    romads = []
    pool = sl[sl["romad"] > 0]
    for _ in range(200):
        take = pool.sample(len(pick), random_state=int(rng.integers(1e9)))
        ser = []
        for _, r in take.iterrows():
            tr = sleeve_trades(r)
            if tr is None or tr.empty or r["asset"] not in FTMO_SWAP:
                continue
            ser.append(net_series(tr, SPREAD_MULT).reindex(idx).fillna(0.0))
        if len(ser) >= 2:
            romads.append(stat(sum(ser))["romad"])
        if len(romads) >= 30:
            break
    if romads:
        LOG.info("   temoin : %d paniers de meme taille tires au hasard dans la "
                 "shortlist -> RoMaD median %.2f (le notre : %.2f, %.0f e centile)",
                 len(romads), float(np.median(romads)), bst["romad"],
                 100 * float(np.mean([x < bst["romad"] for x in romads])))

    # ---------------------------------------------------------------- le book
    M, _a, _b = load_sleeves()
    cost = _ftmo_costs(M.index)
    net = M.copy()
    for kk, c in cost.items():
        if kk in net.columns:
            net[kk] = net[kk] - c.reindex(net.index).fillna(0.0)
    W = dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.5, TLF=0.5)
    agg = pd.Series(net[SLEEVES].to_numpy() @ np.array([W[s] for s in SLEEVES]),
                    index=net.index)
    w = agg.index >= basket[basket != 0].index.min()
    agg_w = agg[w]
    bk = basket.reindex(agg.index).fillna(0.0)[w]

    LOG.info("-" * 92)
    LOG.info("APPORT AU BOOK AGRESSIF (net des deux cotes), fenetre %s -> %s",
             agg_w.index[0].date(), agg_w.index[-1].date())
    b0 = stat(agg_w)
    LOG.info("   AGRESSIF seul        : %+6.1f R/an | maxDD %5.1f R | RoMaD %.2f | "
             "Sharpe %.2f | %%/an a risque egal %5.2f %%", b0["R_per_yr"],
             b0["maxdd"], b0["romad"], b0["sharpe"], 10 * b0["romad"])
    books = {"AGRESSIF (actuel)": agg_w}
    for wt in (0.25, 0.5):
        st = stat(agg_w + wt * bk)
        books[f"+ panier @{wt}R"] = agg_w + wt * bk
        LOG.info("   + panier @ %.2fR      : %+6.1f R/an | maxDD %5.1f R | RoMaD %.2f | "
                 "Sharpe %.2f | %%/an a risque egal %5.2f %% (%+.2f pt)", wt,
                 st["R_per_yr"], st["maxdd"], st["romad"], st["sharpe"],
                 10 * st["romad"], 10 * (st["romad"] - b0["romad"]))

    # ---------------------------------------------------------------- MC
    LOG.info("-" * 92)
    LOG.info("MONTE-CARLO (moteur du depot, meme graine, memes blocs)")
    res = {}
    for name, s in books.items():
        mc = simulate(s.to_numpy())
        res[name] = mc
        LOG.info("   %-22s | 1 an median %+6.1f R | P(annee +) %.1f %% | "
                 "maxDD median %5.1f R | 5e pct %+6.1f R", name,
                 float(np.median(mc["annual"])), 100 * float((mc["annual"] > 0).mean()),
                 float(np.median(mc["mdd"])), float(np.percentile(mc["annual"], 5)))

    LOG.info("-" * 92)
    LOG.info("CHALLENGE")
    LOG.info("   %-22s %7s %10s %10s %10s", "book", "risque", "P(valider)",
             "mediane", "moyenne")
    for name, mc in res.items():
        for c in mc["chal"]:
            if c["risk"] not in (0.005, 0.01):
                continue
            LOG.info("   %-22s %6.2f%% %9.1f %% %7.1f mois %7.1f mois", name,
                     100 * c["risk"], 100 * c["p_pass"],
                     c["med_months"] or float("nan"),
                     c["mean_months"] or float("nan"))
    LOG.info("-" * 92)
    LOG.info("FUNDED")
    LOG.info("   %-22s %7s %15s %10s", "book", "risque", "retrait median", "ruine")
    for name, mc in res.items():
        for f in mc["fund"]:
            if f["risk"] not in (0.005, 0.01):
                continue
            LOG.info("   %-22s %6.2f%% %13.1f %% %9.1f %%", name, 100 * f["risk"],
                     f["med_wd"], 100 * f["p_ruin"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
