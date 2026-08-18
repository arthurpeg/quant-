"""ETAPE 10 -- la liste COMPLETE des candidats, classee par le test d'admission du depot.

    python research/scripts/10_candidate_shortlist.py

POURQUOI CE FICHIER EXISTE : les deux configurations d'exp-023 (`vwap_z` GER40 et
`orb_break` US100) avaient ete choisies en lisant le HAUT d'un tableau trie par
E[R]. C'est une selection faite a l'oeil, et sur deux plans elle est fausse.

  1. ELLES NE SONT PAS LES SEULES. Au seuil PRE-ENREGISTRE q = 0,90, avec la
     batterie complete (deux moities chronologiques positives, temoin de sens
     negatif, temoin aleatoire battu, N >= 300), **31 cellules distinctes**
     survivent, sur 12 actifs.

  2. E[R] N'EST PAS LE TEST D'ADMISSION. `wiki/system.md` le dit sans ambiguite :
     *"Standalone RoMaD is the cleanest admission test"* -- IBS 1,59, crypto 0,95,
     NAS 0,79, or 0,73, **GER40(ORB) 0,38** (rejete pour cette raison). Une sleeve
     dont le drawdown propre depasse celui du book entier ne vaut que sa
     decorrelation, et se dose a moitie. Classer par E[R] met donc en tete
     exactement ce que le book refuse : les sleeves a gros drawdown.

Ce script rejoue les 31, mesure R/an, maxDD propre, **RoMaD standalone** et la
correlation mensuelle au book AGRESSIF, puis classe par RoMaD.
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


def _load(name: str, fname: str):
    sp = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / fname)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


BT = _load("bt_engine", "05_vectorized_backtester.py")
GEO = _load("geo_engine", "06_stop_geometry.py")
IC3 = _load("ic_engine", "03_compute_signal_ic.py")
LOG = C.get_logger("10_shortlist")

Q = 0.90                    # seuil pre-enregistre, le seul admissible ici
MIN_N = 300

# Le barreme du depot (wiki/system.md, "Admission test for a 5th brick").
BAR = {"IBS (b4)": 1.59, "crypto (b3)": 0.95, "NAS ORB (b1)": 0.79,
       "or ToM (b2)": 0.73, "GER40 ORB (rejete)": 0.38}


def shortlist() -> pd.DataFrame:
    d = pd.read_parquet(C.DATA / "stop_geometry_results.parquet")
    p = d[d["is_primary_threshold"]]
    f = p[(p["both_halves_positive"]) & (p["inverse_expectancy_R"] < 0)
          & (p["expectancy_R"] > 0) & (p["n_trades"] >= MIN_N)
          & (p["placebo_beat_frac"] <= 0.10)]
    return (f.sort_values("expectancy_R", ascending=False)
            .drop_duplicates(["signal_type", "asset", "timeframe", "k"]))


def sleeve_series(row) -> pd.Series | None:
    """Rejoue une cellule et rend sa serie journaliere de R (peage Pepperstone)."""
    asset, tf, k = row["asset"], row["timeframe"], int(row["k"])
    bars = C.load(asset, tf)
    if bars is None:
        return None
    costs = json.loads(C.costs_path().read_text(encoding="utf-8"))
    ref = costs.get(asset, {}).get("H1") or next(iter(costs.get(asset, {}).values()), {})
    meta = C.symbols_meta().get(asset, {})
    rt_price = float(ref.get("rt_pts", 0.0)) * float(meta.get("point", 0.0))

    params = json.loads(row["params"])
    spec = dict(type=row["signal_type"], family=row["family"], sign_prior=0,
                params=params)
    drv = None
    if spec["type"] in SG.CROSS_TYPES:
        drv = IC3.driver_series(params["driver"], tf, bars.t)
        if drv is None:
            return None
    sig = SG.compute(bars, spec, drv)

    atr = bars.atr(C.ATR_LEN)
    r_px = float(row["atr_mult"]) * atr
    cost_R = rt_price / r_px
    pr = BT.causal_rank(sig)
    hi, lo = pr >= Q, pr <= (1 - Q)
    n = len(bars)
    ok = (np.isfinite(sig) & np.isfinite(pr) & np.isfinite(r_px) & (r_px > 0)
          & (np.arange(n) + 1 + k < n))
    cand = np.flatnonzero(ok & (hi | lo))
    if cand.size < 20:
        return None
    side = np.where(hi[cand], 1.0, -1.0) * (1.0 if row["ic_mean"] > 0 else -1.0)
    gross, xi, _ = GEO.simulate_geometry(bars.o, bars.h, bars.l, cand, side,
                                         r_px[cand], k)
    keep = BT.nonoverlap(cand + 1, xi)
    net = gross[keep] - cost_R[cand[keep]]
    s = pd.Series(net, index=pd.DatetimeIndex(bars.t[xi[keep]]).tz_localize(None))
    return s.groupby(s.index.normalize()).sum()


def main() -> int:
    sl = shortlist()
    LOG.info("=" * 100)
    LOG.info("CANDIDATS AU SEUIL PRE-ENREGISTRE q=%.2f, batterie complete : "
             "%d cellules distinctes sur %d actifs", Q, len(sl),
             sl["asset"].nunique())
    LOG.info("Test d'admission du depot = RoMaD STANDALONE. Bareme : %s",
             ", ".join(f"{k} {v}" for k, v in BAR.items()))

    # book AGRESSIF net, pour la correlation
    from edgelab.reports.books_report import SLEEVES, _ftmo_costs, load_sleeves
    M, _s, _e = load_sleeves()
    cost = _ftmo_costs(M.index)
    net = M.copy()
    for kk, c in cost.items():
        if kk in net.columns:
            net[kk] = net[kk] - c.reindex(net.index).fillna(0.0)
    W = dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.5, TLF=0.5)
    agg = pd.Series(net[SLEEVES].to_numpy() @ np.array([W[s] for s in SLEEVES]),
                    index=net.index)
    agg_m = agg.resample("ME").sum()

    rows = []
    for _, r in sl.iterrows():
        s = sleeve_series(r)
        if s is None or s.empty:
            continue
        yrs = max((s.index.max() - s.index.min()).days / 365.25, 1e-9)
        cum = s.cumsum()
        dd = float((cum.cummax() - cum).max())
        rpy = float(s.sum() / yrs)
        sm = s.reindex(agg.index).fillna(0.0).resample("ME").sum()
        ok = (sm != 0) | (agg_m != 0)
        rho = float(np.corrcoef(sm[ok], agg_m[ok])[0, 1])
        rows.append(dict(
            signal=r["signal_type"], asset=r["asset"], tf=r["timeframe"],
            k=int(r["k"]), stop=float(r["atr_mult"]), n=int(r["n_trades"]),
            ER=float(r["expectancy_R"]), pf=float(r["profit_factor"]),
            R_per_yr=rpy, maxdd=dd,
            romad=rpy / dd if dd > 0 else np.inf, corr_book=rho))
    out = pd.DataFrame(rows).sort_values("romad", ascending=False)
    out.to_parquet(C.DATA / "candidate_shortlist.parquet", index=False)

    LOG.info("-" * 100)
    LOG.info("%-17s %-7s %-4s %3s %5s %6s %8s %7s %8s %7s %8s", "signal", "actif",
             "UT", "k", "stop", "N", "E[R]", "R/an", "maxDD", "RoMaD", "corr book")
    for _, r in out.iterrows():
        flag = ""
        if r["romad"] >= BAR["IBS (b4)"]:
            flag = "  <<< au-dessus de l'IBS, la meilleure brique"
        elif r["romad"] >= BAR["NAS ORB (b1)"]:
            flag = "  << au-dessus de la brique 1"
        elif r["romad"] <= BAR["GER40 ORB (rejete)"]:
            flag = "  (sous le GER40 ORB deja rejete)"
        LOG.info("%-17s %-7s %-4s %3d %5.1f %6d %+8.4f %+7.1f %8.1f %7.2f %8.3f%s",
                 r["signal"], r["asset"], r["tf"], r["k"], r["stop"], r["n"],
                 r["ER"], r["R_per_yr"], r["maxdd"], r["romad"], r["corr_book"], flag)

    LOG.info("-" * 100)
    top = out[out["romad"] >= BAR["NAS ORB (b1)"]]
    LOG.info("%d candidats depassent le RoMaD de la brique 1 (0,79) ; "
             "%d depassent celui de l'IBS (1,59).", len(top),
             int((out["romad"] >= BAR["IBS (b4)"]).sum()))
    LOG.info("Pour memoire, les deux d'exp-023 : %s",
             " | ".join(f"{r['signal']} {r['asset']} RoMaD {r['romad']:.2f}"
                        for _, r in out.iterrows()
                        if (r["signal"], r["asset"]) in
                        (("vwap_z", "GER40"), ("orb_break", "US100"))
                        and r["tf"] == "H1"))
    LOG.info("resultats -> research/data/candidate_shortlist.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
