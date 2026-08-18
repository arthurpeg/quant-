"""ETAPE 8 -- GER40 est-il un candidat pour le book AGRESSIF ?

    python research/scripts/08_ger40_book_candidate.py

La question n'est pas "cette sleeve gagne-t-elle" (exp-023 : +0,128 R/trade) mais
"**ce book-la** est-il meilleur avec elle qu'sans elle". Ce sont deux questions
differentes, et ce depot a deja repondu non a la seconde en repondant oui a la
premiere (KELT : +17,2 R/an brut, retiree parce que le swap FTMO la ramenait a
+5,0 R/an a t=0,87 et que l'enlever ameliorait strictement le drawdown).

L'admission d'une sleeve dans ce book se juge sur quatre choses, dans cet ordre :

  1. LE COUT DU BROKER DU BOOK, pas celui du broker de la recherche. Les chiffres
     d'exp-021 a exp-023 sont en peage **Pepperstone**. Le book tourne sur
     **FTMO**, dont les taux different et dont le swap a deja tue une sleeve.
  2. LA DECORRELATION aux sleeves deja en place. Une sleeve rentable et correlee
     n'ajoute que du levier.
  3. L'APPORT AU BOOK : R/an, mais surtout effet sur le drawdown et le RoMaD.
  4. LA ROBUSTESSE : hors-echantillon, ou a defaut annees et moities.

Ce script mesure les quatre. Il ne decide rien : il pose les chiffres.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
LOG = C.get_logger("08_ger40")

# La configuration retenue par exp-022/023 : la meilleure sortie connue est la
# plus simple (stop dur 2,0 x ATR14 + barriere de temps), au seuil pre-enregistre.
CFG = dict(signal_type="vwap_z", asset="GER40", timeframe="H1", k=24,
           params={"session": "NY", "atr_period": 14},
           atr_mult=2.0, q=0.90)


def build_trades() -> pd.DataFrame:
    """Rejoue la sleeve et rend un trade par ligne, avec ses dates."""
    bars = C.load(CFG["asset"], CFG["timeframe"])
    costs = json.loads(C.costs_path().read_text(encoding="utf-8"))
    ref = costs[CFG["asset"]]["H1"]
    meta = C.symbols_meta()[CFG["asset"]]
    rt_price = float(ref["rt_pts"]) * float(meta["point"])

    d = pd.read_parquet(C.DATA / "ic_results_scored.parquet")
    cell = d[(d["signal_type"] == CFG["signal_type"]) & (d["asset"] == CFG["asset"])
             & (d["timeframe"] == CFG["timeframe"]) & (d["k"] == CFG["k"])
             & (d["params"] == json.dumps(CFG["params"]))].iloc[0]
    ic_sign = 1.0 if cell["ic_mean"] > 0 else -1.0

    spec = dict(type=CFG["signal_type"], family=cell["family"], sign_prior=0,
                params=CFG["params"])
    sig = SG.compute(bars, spec)
    atr = bars.atr(C.ATR_LEN)
    r_px_all = CFG["atr_mult"] * atr
    cost_R_all = rt_price / r_px_all

    pr = BT.causal_rank(sig)
    hi_t, lo_t = pr >= CFG["q"], pr <= (1.0 - CFG["q"])
    n, k = len(bars), CFG["k"]
    ok = (np.isfinite(sig) & np.isfinite(pr) & np.isfinite(r_px_all)
          & (r_px_all > 0) & (np.arange(n) + 1 + k < n))
    cand = np.flatnonzero(ok & (hi_t | lo_t))
    side = np.where(hi_t[cand], 1.0, -1.0) * ic_sign

    gross, xi, why = GEO.simulate_geometry(bars.o, bars.h, bars.l, cand, side,
                                           r_px_all[cand], k)
    keep = BT.nonoverlap(cand + 1, xi)
    i_in, i_out = (cand + 1)[keep], xi[keep]
    return pd.DataFrame(dict(
        entry_time=bars.t[i_in], exit_time=bars.t[i_out],
        side=side[keep], R_gross=gross[keep],
        cost_R=cost_R_all[cand[keep]],
        R=gross[keep] - cost_R_all[cand[keep]],
        stopped=(why[keep] == GEO.EX_STOP),
        r_price=r_px_all[cand[keep]], entry_px=bars.o[i_in]))


def stats(r: np.ndarray, years: float) -> dict:
    eq = np.cumsum(r)
    dd = float((eq - np.maximum.accumulate(eq)).min())
    gp, gl = float(r[r > 0].sum()), float(-r[r < 0].sum())
    return dict(n=len(r), ER=float(r.mean()), total_R=float(r.sum()),
                R_per_yr=float(r.sum() / years),
                win=float((r > 0).mean()), pf=gp / gl if gl else np.inf,
                maxdd_R=dd, romad=float(r.sum() / years / abs(dd)) if dd else np.inf,
                t=float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))))


def main() -> int:
    LOG.info("=" * 78)
    LOG.info("GER40 comme candidat au book AGRESSIF -- %s %s %s k=%d, stop %.1f x ATR14",
             CFG["signal_type"], CFG["asset"], CFG["timeframe"], CFG["k"],
             CFG["atr_mult"])

    tr = build_trades()
    years = (tr["exit_time"].max() - tr["entry_time"].min()).days / 365.25
    s = stats(tr["R"].to_numpy(), years)
    LOG.info("-" * 78)
    LOG.info("SLEEVE SEULE (peage Pepperstone) : %d trades sur %.1f ans", s["n"], years)
    LOG.info("  E[R] %+.4f | %+.1f R/an | PF %.3f | gain %.1f %% | maxDD %.1f R | "
             "RoMaD %.2f | t %.2f", s["ER"], s["R_per_yr"], s["pf"],
             100 * s["win"], s["maxdd_R"], s["romad"], s["t"])
    LOG.info("  peage median %.4f R | sorties au stop %.1f %%",
             tr["cost_R"].median(), 100 * tr["stopped"].mean())

    # ---------------------------------------------------------------- 1. nuits
    # La sleeve tient-elle la nuit ? C'est ce qui decide si le SWAP la concerne.
    ent, ext = tr["entry_time"], tr["exit_time"]
    nights = (ext.dt.normalize() - ent.dt.normalize()).dt.days
    LOG.info("-" * 78)
    LOG.info("EXPOSITION DE NUIT (ce qui declenche le swap)")
    LOG.info("  trades fermes le JOUR MEME : %.1f %% | 1 nuit : %.1f %% | "
             "2 nuits et + : %.1f %%",
             100 * (nights == 0).mean(), 100 * (nights == 1).mean(),
             100 * (nights >= 2).mean())
    LOG.info("  nuits portees en moyenne : %.2f", nights.mean())
    LOG.info("  repartition des sens : %.1f %% longs", 100 * (tr["side"] > 0).mean())

    # ---------------------------------------------------------------- 2. par an
    yr = tr.set_index("exit_time")["R"].groupby(lambda t: t.year)
    LOG.info("-" * 78)
    LOG.info("PAR ANNEE")
    for y, g in yr:
        LOG.info("  %d : %5d trades | %+7.1f R | E[R] %+.4f", y, len(g), g.sum(),
                 g.mean())
    ann = yr.sum()
    LOG.info("  annees positives : %d / %d", int((ann > 0).sum()), len(ann))

    # ---------------------------------------------------------------- 3. swap
    # GER40 N'EST PAS dans la table de couts FTMO du depot : son taux n'a jamais
    # ete releve. On ne l'invente pas -- on mesure a partir de quel taux la
    # sleeve meurt, ce qui transforme l'inconnue en question fermee.
    LOG.info("-" * 78)
    LOG.info("SENSIBILITE AU SWAP (GER40 est ABSENT de la table FTMO du depot)")
    px = tr["entry_px"].to_numpy()
    rpx = tr["r_price"].to_numpy()
    nights_n = nights.to_numpy().astype(float)
    # une nuit longue a `pct` %/an coute px * pct/100/360 en prix, soit /R en R
    for pct in (0.0, 2.5, 5.0, 7.52, 10.0, 15.0):
        cost_night_R = px * (pct / 100.0) / 360.0 / rpx
        # cote court : sur les indices FTMO le court est proche de zero, on le
        # traite comme gratuit, ce qui est l'hypothese FAVORABLE.
        pay = np.where(tr["side"].to_numpy() > 0, nights_n * cost_night_R, 0.0)
        net = tr["R"].to_numpy() - pay
        LOG.info("  swap long %5.2f %%/an -> E[R] %+.4f | %+6.1f R/an | PF %.3f",
                 pct, net.mean(), net.sum() / years,
                 float(net[net > 0].sum() / -net[net < 0].sum()))

    # ---------------------------------------------------------------- 4. book
    LOG.info("-" * 78)
    LOG.info("DECORRELATION AUX QUATRE BRIQUES")
    try:
        sys.path.insert(0, str(C.REPO))
        from edgelab.reports.monte_carlo_static import build_daily_R
        R, parts, (start, end), tr_bricks = build_daily_R()
        names = list(tr_bricks.keys())
        idx = pd.date_range(start, end, freq="D")

        mine = tr.set_index(pd.DatetimeIndex(tr["exit_time"]).tz_localize(None))["R"]
        mine = mine.groupby(mine.index.normalize()).sum().reindex(idx).fillna(0.0)

        book = pd.Series(R, index=idx)
        LOG.info("  fenetre commune : %s -> %s", start.date(), end.date())
        # correlation MENSUELLE : c'est l'echelle a laquelle le book est juge
        mm = mine.resample("ME").sum()
        for nm, p in zip(names, parts):
            pm = pd.Series(p.values, index=idx).resample("ME").sum()
            ok = (mm != 0) | (pm != 0)
            LOG.info("    corr mensuelle vs %-8s : %+.3f", nm,
                     float(np.corrcoef(mm[ok], pm[ok])[0, 1]))
        bm = book.resample("ME").sum()
        ok = (mm != 0) | (bm != 0)
        rho_book = float(np.corrcoef(mm[ok], bm[ok])[0, 1])
        LOG.info("    corr mensuelle vs BOOK 4 briques : %+.3f", rho_book)

        # apport au book, a 0,5R et a 1R
        LOG.info("-" * 78)
        LOG.info("APPORT AU BOOK (4 briques, meme fenetre, peage Pepperstone)")
        base = book[book.index >= mine.index.min()]
        mine_w = mine[mine.index >= mine.index.min()]
        yrs = (base.index[-1] - base.index[0]).days / 365.25

        def book_stats(x: pd.Series) -> tuple:
            eq = x.cumsum()
            dd = float((eq - eq.cummax()).min())
            m = x.resample("ME").sum()
            return (float(x.sum() / yrs), dd, float(x.sum() / yrs / abs(dd)),
                    float(m.mean() / m.std(ddof=1) * np.sqrt(12)))

        r0, d0, rm0, sh0 = book_stats(base)
        LOG.info("  book seul          : %+6.1f R/an | maxDD %6.1f R | "
                 "RoMaD %.2f | Sharpe %.2f", r0, d0, rm0, sh0)
        for w in (0.5, 1.0):
            r1, d1, rm1, sh1 = book_stats(base + w * mine_w)
            LOG.info("  + GER40 @ %.1fR      : %+6.1f R/an | maxDD %6.1f R | "
                     "RoMaD %.2f | Sharpe %.2f  (%s)", w, r1, d1, rm1, sh1,
                     "AMELIORE" if (rm1 > rm0 and sh1 > sh0) else
                     "mitige" if (rm1 > rm0 or sh1 > sh0) else "DEGRADE")
    except Exception as e:
        LOG.warning("  briques non reconstruites (%r) -- correlation non mesuree", e)

    tr.to_parquet(C.DATA / "ger40_sleeve_trades.parquet", index=False)
    LOG.info("-" * 78)
    LOG.info("trades ecrits -> research/data/ger40_sleeve_trades.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
