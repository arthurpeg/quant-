"""ETAPE 14 -- le panier {skew US30 + vwap_z GER40}, et GER40 contre CHAQUE sleeve du book.

    python research/scripts/14_swap_test_vs_book.py [--mc]

Deux questions, posees dans la seule monnaie que le depot utilise pour admettre
une sleeve : le **%/an a risque egal** (chaque configuration dimensionnee a son
plafond prop -10 % statique ; c'est exactement 10 x RoMaD).

  A. LE PANIER : `skew` US30 H4 k=5 (decorrelee, corr -0,004) + `vwap_z` GER40 H1
     k=24 stop 3,0 (la meilleure a correlation moderee, RoMaD net 0,85).
  B. LE TEST DE REMPLACEMENT : GER40 est-elle meilleure qu'une sleeve DEJA en
     place ? `system.md` avait tranche le 2026-07-31 -- *"every GER40
     configuration loses at equal risk"*, *"adding always beats swapping"* --
     mais sur le GER40 ORB, **en brut**, et sur un book sans HMASTO ni TLF. Les
     trois hypotheses ont change, donc la question se repose.

TROIS PRECAUTIONS.

* TOUT EST NET DES DEUX COTES, sur la MEME fenetre. Les sleeves du book ont des
  historiques de longueurs differentes ; les comparer sur leurs spans propres
  fabriquerait un ecart qui n'est que du calendrier. Tout est donc restreint a
  la fenetre commune de la candidate.
* LE COUT FTMO VIENT DU RELEVE DU 2026-08-18 (etape 13) pour les candidates, et
  de `books_report._ftmo_costs` pour les sleeves du book -- c'est-a-dire de la
  machinerie qui produit deja le rapport officiel. Aucune des deux n'est
  reimplementee ici.
* LE SWAP EST LE TAUX COURANT APPLIQUE A TOUT L'HISTORIQUE. MT5 ne sert pas son
  historique, et le releve du 2026-08-18 a montre que **les cotes long/court
  d'US30 se sont inverses en huit jours**. Les conclusions qui dependent
  finement du swap sont donc a lire avec cette reserve -- elle est chiffree en
  fin de script par un rejeu a swap double.
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


B11 = _load("basket", "11_basket_montecarlo.py")
LOG = C.get_logger("14_swap")

SPECS = json.loads((C.DATA / "ftmo_specs.json").read_text(encoding="utf-8"))
SLIP_BPS = 0.20
W_BOOK = dict(b1=1.0, b2=1.0, b3=0.5, b4=1.0, HMASTO=0.5, TLF=0.5)

CANDIDATES = {
    "skew US30":   dict(signal="skew", asset="US30", tf="H4", k=5, stop=4.0),
    "vwap_z GER40": dict(signal="vwap_z", asset="GER40", tf="H1", k=24, stop=3.0),
}


def cand_series(spec: dict, swap_mult: float = 1.0) -> pd.Series:
    tr = B11.sleeve_trades(spec)
    a = spec["asset"]
    s = SPECS[a]
    cost_R = ((s["spread_bps"] + SLIP_BPS) / 1e4) * tr["entry_px"].to_numpy() \
        / tr["r_price"].to_numpy()
    units = swap_units(tr["entry_time"].to_numpy(), tr["exit_time"].to_numpy(),
                       s["triple_day"])
    pct = np.where(tr["side"].to_numpy() > 0, s["swap_long_pct"], s["swap_short_pct"])
    swap_R = swap_mult * units * (tr["entry_px"].to_numpy() * pct / 100.0 / 360.0) \
        / tr["r_price"].to_numpy()
    net = tr["R_gross"].to_numpy() - cost_R - swap_R
    x = pd.Series(net, index=pd.DatetimeIndex(tr["exit_time"]).tz_localize(None))
    return x.groupby(x.index.normalize()).sum()


def stat(x: pd.Series) -> dict:
    yrs = max((x.index.max() - x.index.min()).days / 365.25, 1e-9)
    cum = x.cumsum()
    dd = float((cum.cummax() - cum).max())
    a = x[x != 0]
    return dict(R_per_yr=float(x.sum() / yrs), maxdd=dd,
                romad=float(x.sum() / yrs / dd) if dd else np.inf,
                sharpe=float(a.mean() / a.std() * np.sqrt(252)) if len(a) > 2 else np.nan,
                pct_eq=10.0 * (float(x.sum() / yrs / dd) if dd else np.inf))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mc", action="store_true")
    a = ap.parse_args()

    # ---- book, sleeve par sleeve, NET
    M, _s, _e = load_sleeves()
    cst = _ftmo_costs(M.index)
    net = M.copy()
    for k, c in cst.items():
        if k in net.columns:
            net[k] = net[k] - c.reindex(net.index).fillna(0.0)

    cands = {n: cand_series(s) for n, s in CANDIDATES.items()}
    start = max(min(v[v != 0].index.min() for v in cands.values()),
                net.index.min())
    idx = net.index[net.index >= start]
    net = net.loc[idx]
    cands = {n: v.reindex(idx).fillna(0.0) for n, v in cands.items()}
    book = pd.Series(net[SLEEVES].to_numpy() @ np.array([W_BOOK[s] for s in SLEEVES]),
                     index=idx)

    LOG.info("=" * 98)
    LOG.info("Fenetre commune : %s -> %s (%.1f ans). Tout est NET des deux cotes.",
             idx[0].date(), idx[-1].date(), (idx[-1] - idx[0]).days / 365.25)

    LOG.info("-" * 98)
    LOG.info("A) CHAQUE SLEEVE DU BOOK, SEULE ET NETTE, contre les candidates")
    LOG.info("   %-16s %6s %9s %8s %8s %9s %9s", "sleeve", "poids", "R/an",
             "maxDD", "RoMaD", "Sharpe", "corr book")
    rows = []
    bm = book.resample("ME").sum()
    for s in SLEEVES:
        x = net[s] * W_BOOK[s]
        st = stat(x[x.index >= x[x != 0].index.min()])
        sm = x.resample("ME").sum()
        ok = (sm != 0) | (bm != 0)
        rho = float(np.corrcoef(sm[ok], bm[ok])[0, 1])
        rows.append(dict(nom=s, poids=W_BOOK[s], **st, corr=rho, kind="book"))
        LOG.info("   %-16s %6.2f %+9.1f %8.1f %8.2f %9.2f %9.3f", s, W_BOOK[s],
                 st["R_per_yr"], st["maxdd"], st["romad"], st["sharpe"], rho)
    for n, v in cands.items():
        st = stat(v[v.index >= v[v != 0].index.min()])
        sm = v.resample("ME").sum()
        ok = (sm != 0) | (bm != 0)
        rho = float(np.corrcoef(sm[ok], bm[ok])[0, 1])
        rows.append(dict(nom=n, poids=1.0, **st, corr=rho, kind="candidate"))
        LOG.info("   %-16s %6.2f %+9.1f %8.1f %8.2f %9.2f %9.3f  <-- CANDIDATE",
                 n, 1.0, st["R_per_yr"], st["maxdd"], st["romad"], st["sharpe"], rho)

    tab = pd.DataFrame(rows).sort_values("romad", ascending=False)
    LOG.info("-" * 98)
    LOG.info("CLASSEMENT PAR RoMaD STANDALONE NET (le test d'admission du depot) :")
    for i, (_, r) in enumerate(tab.iterrows(), 1):
        LOG.info("   %d. %-16s RoMaD %.2f  (%+.1f R/an, %s)", i, r["nom"],
                 r["romad"], r["R_per_yr"],
                 "candidate" if r["kind"] == "candidate" else "au book")

    # ---- B) ajouts et remplacements
    LOG.info("-" * 98)
    LOG.info("B) AJOUTS ET REMPLACEMENTS, en %%/an a RISQUE EGAL (= 10 x RoMaD)")
    b0 = stat(book)
    LOG.info("   %-34s %+8.1f R/an | maxDD %5.1f | %%/an %6.2f", "A -- le book",
             b0["R_per_yr"], b0["maxdd"], b0["pct_eq"])
    configs = {}
    for n, v in cands.items():
        for w in (0.5, 1.0):
            configs[f"A + {n} @{w}R"] = book + w * v
    configs["A + les DEUX @1R"] = book + cands["skew US30"] + cands["vwap_z GER40"]
    configs["A + les DEUX @0.5R"] = book + 0.5 * (cands["skew US30"]
                                                  + cands["vwap_z GER40"])
    for s in SLEEVES:
        configs[f"A - {s} + GER40 @1R"] = (book - net[s] * W_BOOK[s]
                                           + cands["vwap_z GER40"])

    out = []
    for name, x in configs.items():
        st = stat(x)
        out.append((name, st))
    for name, st in sorted(out, key=lambda z: -z[1]["pct_eq"]):
        d = st["pct_eq"] - b0["pct_eq"]
        LOG.info("   %-34s %+8.1f R/an | maxDD %5.1f | %%/an %6.2f (%+.2f pt)%s",
                 name, st["R_per_yr"], st["maxdd"], st["pct_eq"], d,
                 "  <-- MIEUX QUE LE BOOK" if d > 0 else "")

    # ---- reserve : swap double
    LOG.info("-" * 98)
    LOG.info("RESERVE -- rejeu a SWAP DOUBLE (le taux courant est applique a tout "
             "l'historique ; US30 a inverse ses cotes en 8 jours)")
    c2 = {n: cand_series(s, swap_mult=2.0).reindex(idx).fillna(0.0)
          for n, s in CANDIDATES.items()}
    for n in cands:
        s1, s2 = stat(cands[n][cands[n] != 0]), stat(c2[n][c2[n] != 0])
        LOG.info("   %-16s RoMaD %.2f -> %.2f | R/an %+.1f -> %+.1f", n,
                 s1["romad"], s2["romad"], s1["R_per_yr"], s2["R_per_yr"])
    st2 = stat(book + c2["skew US30"] + c2["vwap_z GER40"])
    LOG.info("   A + les DEUX @1R : %%/an %6.2f -> %6.2f",
             stat(book + cands["skew US30"] + cands["vwap_z GER40"])["pct_eq"],
             st2["pct_eq"])

    if a.mc:
        LOG.info("-" * 98)
        LOG.info("MONTE-CARLO sur les configurations qui battent le book")
        keep = {"A -- le book": book}
        keep |= {n: configs[n] for n, st in
                 sorted(out, key=lambda z: -z[1]["pct_eq"])[:3]}
        for name, x in keep.items():
            mc = simulate(x.to_numpy())
            ch = {c["risk"]: c for c in mc["chal"]}
            fu = {f["risk"]: f for f in mc["fund"]}
            LOG.info("   %-34s | 1 an med %+6.1f R | P(valider)@1%% %.1f %% | "
                     "mediane %.1f mois | ruine@0,5%% %.1f %%", name,
                     float(np.median(mc["annual"])), 100 * ch[0.01]["p_pass"],
                     ch[0.01]["med_months"], 100 * fu[0.005]["p_ruin"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
