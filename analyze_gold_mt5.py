"""
analyze_gold_mt5.py
===================
Performance de l'OR (XAUUSD) sur données MT5 PROPRES — test direct de l'hypothèse
"le short or @1R de Yahoo était un artefact de données".

Compare, sur MT5 :
  - le taux de base short@1R (tous events) et la version filtrée ML non-chevauchante ;
  - à plusieurs timeframes (H1/H4) ;
  - brut ET net (coût réel spread or converti en R) ;
  - ventilation par année.
Référence Yahoo : taux de base 52.5%, filtré 62.2%, +202 R/an (brut).
"""
from __future__ import annotations
import logging, warnings
import numpy as np
import pandas as pd

import config
config.ENABLE_MTF = False
config.VOLUME_FEATURES_ENABLED = True

import data_loader, pipeline, labeling, mt5_loader
from features.volatility import atr
from backtest_exec import make_model, _folds, _proba_win, TP_CLS, TAKE_QUANTILE

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

SYM = "XAUUSD"
COST_PRICE = 0.45      # coût aller-retour réaliste en prix (or), ~constant selon TF
BASES = {"H1": ("1h", 24), "H4": ("4h", 24)}


def prepare(tf: str, tp: float, side: int):
    freq, timeout = BASES[tf]
    config.PANDAS_FREQ = freq; config.TIMEFRAME = tf
    df = data_loader.clean(mt5_loader.fetch(SYM, tf), SYM, do_resample=False, reindex_grid=False)
    X = pipeline.build_features(df, SYM)
    X = X.drop(columns=X.columns[X.isna().all()])
    r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)
    cost_r = (COST_PRICE / r_unit).replace([np.inf, -np.inf], np.nan)
    lab = labeling.triple_barrier(df, tp_mult=tp, sl_mult=config.SL_R_MULTIPLE,
                                  timeout=timeout, side=side, r_unit=r_unit)
    valid = X.notna().all(axis=1) & lab["label"].notna() & cost_r.notna()
    idx = X.index[valid]
    return {"X": X.loc[idx], "idx": idx, "cost_r": cost_r.loc[idx].to_numpy(),
            "y": lab["label"].loc[idx].astype(int).to_numpy(),
            "r": lab["realized_r"].loc[idx].to_numpy(),
            "bars": lab["barrier_bars"].loc[idx].fillna(1).astype(int).to_numpy()}


def exec_walk(a):
    """Short/long non-chevauchant filtré ML. Renvoie DataFrame (time, r_gross, r_net)."""
    X = a["X"]; n = len(X); idx = a["idx"]; cost = a["cost_r"]
    rows = []
    base_win = float((a["r"] > 0).mean())      # taux de base (tous events)
    for tr, te in _folds(n):
        ytr = a["y"][tr]
        if len(np.unique(ytr)) < 2:
            continue
        m = make_model(); m.fit(X.iloc[tr], ytr)
        cl = list(m.classes_)
        thr = float(np.quantile(_proba_win(m, X.iloc[tr], cl), TAKE_QUANTILE))
        p = _proba_win(m, X.iloc[te], cl)
        rt = a["r"][te]; bt = a["bars"][te]; ct = cost[te]
        start = te.start
        i = 0; mlen = len(rt)
        while i < mlen:
            if p[i] >= thr and np.isfinite(rt[i]):
                rows.append((idx[start + i], float(rt[i]), float(rt[i] - ct[i])))
                i += int(max(bt[i], 1))
            else:
                i += 1
    df = pd.DataFrame(rows, columns=["t", "gross", "net"]).set_index("t").sort_index()
    return df, base_win


def summarize(df, col):
    r = df[col].to_numpy()
    if len(r) == 0:
        return {}
    eq = np.cumsum(r); dd = float((eq - np.maximum.accumulate(eq)).min())
    g = r[r > 0].sum(); l = -r[r < 0].sum()
    span = (df.index[-1] - df.index[0]).days / 365.25
    return dict(n=len(r), win=float((r > 0).mean()) * 100, exp=float(r.mean()),
                tot=float(r.sum()), pf=float(g / l) if l > 0 else float("inf"),
                dd=dd, per_year=float(r.sum()) / span if span else np.nan)


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    pipeline.set_seeds()
    print("═" * 86)
    print(" OR (XAUUSD) sur données MT5 PROPRES — l'artefact Yahoo survit-il ?")
    print("═" * 86)
    print(" Réf. Yahoo (H1) : taux base 52.5% · filtré ML 62.2% · +202 R/an (BRUT, sans coûts)")
    print("═" * 86)

    for tf in BASES:
        for tp, side, name in [(1.0, -1, "SHORT @1R"), (2.0, +1, "LONG @2R"), (2.0, -1, "SHORT @2R")]:
            a = prepare(tf, tp, side)
            df, base_win = exec_walk(a)
            if df.empty:
                print(f" {tf} {name}: pas de trades"); continue
            sg = summarize(df, "gross"); sn = summarize(df, "net")
            print(f"\n {tf} · {name}  (coût médian {np.median(a['cost_r']):.3f} R/trade)")
            print(f"   taux de base (tous events) : {base_win*100:.1f}% win")
            print(f"   filtré ML  : {sn['n']} trades · win {sg['win']:.1f}%")
            print(f"   BRUT : E[R] {sg['exp']:+.3f} · R tot {sg['tot']:+.1f} · {sg['per_year']:+.1f} R/an · maxDD {sg['dd']:.1f}")
            print(f"   NET  : E[R] {sn['exp']:+.3f} · R tot {sn['tot']:+.1f} · {sn['per_year']:+.1f} R/an · PF {sn['pf']:.2f}")
            if tf == "H1" and name == "SHORT @1R":
                yrs = df.index.year
                print("   Ventilation annuelle (NET) :")
                for y in sorted(set(yrs)):
                    ry = df["net"].to_numpy()[yrs == y]; rg = df["gross"].to_numpy()[yrs == y]
                    print(f"      {y}: {ry.sum():+6.1f} R net  ({len(ry):4d} trades, win {(rg>0).mean()*100:.1f}%)")
    print("═" * 86)


if __name__ == "__main__":
    run()
