"""
backtest_v2.py
==============
Compare l'apport des trois briques V2 sur données réelles, en exécution non-chevauchante
et AVEC coûts de transaction (config.COST_PER_TRADE_R soustrait de chaque trade) :

  A. Baseline    : features 1H seules, filtre ML direct (long @ TP fixe).
  B. + MTF       : on ajoute les features multi-timeframe (H4 + Daily), même filtre direct.
  C. + Meta-label: features 1H+MTF, meta-labeling façon López de Prado :
       - une RÈGLE PRIMAIRE fixe le sens (tendance : long si close>EMA50, short sinon) ;
       - un modèle SECONDAIRE prédit si le trade primaire atteindra son TP avant le SL ;
       - on ne prend le trade que si la proba secondaire dépasse le seuil (le ML "dimensionne").

Objectif : voir si l'AUC décolle de 0.50 et si le R net après coûts devient positif et robuste.
Tout est walk-forward (modèle entraîné sur le passé), sans leakage (MTF vérifié causal).
"""
from __future__ import annotations
import logging, warnings
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import config
config.VOLUME_FEATURES_ENABLED = False

import data_loader, pipeline, labeling, fetch_data
from features.volatility import atr
from backtest_exec import make_model, _folds, _proba_win, TP_CLS, TAKE_QUANTILE

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
TP = 2.0                       # TP fixe pour la comparaison A/B/C
EMA_SIDE = 50                  # EMA de la règle primaire de tendance (meta-labeling)
COST = config.COST_PER_TRADE_R


def prepare(symbol: str) -> dict:
    """Nettoie une fois, calcule X (1H) et X (1H+MTF), labels 2 sens @TP, et le sens de tendance."""
    raw = fetch_data.fetch(symbol)
    df = data_loader.clean(raw, symbol, do_resample=False)
    r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)

    config.ENABLE_MTF = False
    X1 = pipeline.build_features(df, symbol)
    config.ENABLE_MTF = True
    Xm = pipeline.build_features(df, symbol)
    config.ENABLE_MTF = False

    labs = {}
    for side in (+1, -1):
        labs[side] = labeling.triple_barrier(df, tp_mult=TP, sl_mult=config.SL_R_MULTIPLE,
                                              timeout=config.TIMEOUT_BARS, side=side, r_unit=r_unit)
    # sens de tendance (règle primaire) : +1 si close>EMA50 sinon -1
    ema = df[config.COL_CLOSE].ewm(span=EMA_SIDE, adjust=False, min_periods=EMA_SIDE).mean()
    side_series = np.where(df[config.COL_CLOSE] > ema, 1, -1)
    side_series = pd.Series(side_series, index=df.index)

    valid = Xm.notna().all(axis=1) & X1.notna().all(axis=1) & ema.notna()
    for side in (+1, -1):
        valid &= labs[side]["label"].notna()
    idx = Xm.index[valid]

    return {
        "symbol": symbol, "idx": idx,
        "X1": X1.loc[idx], "Xm": Xm.loc[idx],
        "side": side_series.loc[idx].to_numpy(),
        "lab": {side: {"y": labs[side]["label"].loc[idx].astype(int).to_numpy(),
                       "r": labs[side]["realized_r"].loc[idx].to_numpy(),
                       "bars": labs[side]["barrier_bars"].loc[idx].fillna(1).astype(int).to_numpy()}
                for side in (+1, -1)},
    }


def _sim(take, r, bars, cost):
    """Non-chevauchant + coût par trade."""
    n = len(take); i = 0; out = []
    while i < n:
        if take[i] and np.isfinite(r[i]):
            out.append(float(r[i]) - cost)
            i += int(max(bars[i], 1))
        else:
            i += 1
    return out


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, win=np.nan, exp=np.nan, tot=0.0, pf=np.nan, dd=0.0)
    eq = np.cumsum(r); dd = float((eq - np.maximum.accumulate(eq)).min())
    g = r[r > 0].sum(); l = -r[r < 0].sum()
    return dict(n=int(len(r)), win=float((r > 0).mean()), exp=float(r.mean()),
                tot=float(r.sum()), pf=float(g / l) if l > 0 else float("inf"), dd=dd)


def run_direct(a, use_mtf):
    """A/B : long-direct, filtre P(tp_long)>=seuil. Renvoie trades (net) + AUC test."""
    X = a["Xm"] if use_mtf else a["X1"]
    d = a["lab"][+1]; n = len(X)
    trades, aucs = [], []
    for tr, te in _folds(n):
        ytr = d["y"][tr]
        if len(np.unique(ytr)) < 2:
            continue
        m = make_model(); m.fit(X.iloc[tr], ytr)
        cl = list(m.classes_)
        thr = float(np.quantile(_proba_win(m, X.iloc[tr], cl), TAKE_QUANTILE))
        p = _proba_win(m, X.iloc[te], cl)
        trades += _sim(p >= thr, d["r"][te], d["bars"][te], COST)
        ypos = (d["y"][te] == TP_CLS).astype(int)
        if ypos.min() != ypos.max():
            aucs.append(roc_auc_score(ypos, p))
    return trades, (float(np.mean(aucs)) if aucs else np.nan)


def run_meta(a):
    """C : meta-labeling. Sens = tendance ; secondaire prédit P(trade primaire gagnant)."""
    X = a["Xm"]; n = len(X); side = a["side"]
    rL, rS = a["lab"][+1], a["lab"][-1]
    # outcome du trade primaire (selon le sens de tendance à chaque barre)
    r_prim = np.where(side > 0, rL["r"], rS["r"])
    bars_prim = np.where(side > 0, rL["bars"], rS["bars"])
    y_prim = np.where(side > 0, rL["y"], rS["y"])
    meta = (y_prim == TP_CLS).astype(int)          # cible binaire : trade primaire gagnant ?
    trades, aucs = [], []
    for tr, te in _folds(n):
        ytr = meta[tr]
        if len(np.unique(ytr)) < 2:
            continue
        m = make_model(); m.fit(X.iloc[tr], ytr)
        cl = list(m.classes_)
        pcol = cl.index(1) if 1 in cl else None
        if pcol is None:
            continue
        ptr = m.predict_proba(X.iloc[tr])[:, pcol]
        thr = float(np.quantile(ptr, TAKE_QUANTILE))
        p = m.predict_proba(X.iloc[te])[:, pcol]
        trades += _sim(p >= thr, r_prim[te], bars_prim[te], COST)
        if meta[te].min() != meta[te].max():
            aucs.append(roc_auc_score(meta[te], p))
    return trades, (float(np.mean(aucs)) if aucs else np.nan)


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    pipeline.set_seeds()
    print("═" * 84)
    print(" BACKTEST V2 — MTF + meta-labeling + COÛTS · données réelles · non-chevauchant")
    print("═" * 84)
    print(f" Actifs {', '.join(ASSETS)} | TP={TP}R SL=−1R | coût={COST}R/trade | walk-forward")
    print("═" * 84)

    prep = {s: prepare(s) for s in ASSETS}
    for s in ASSETS:
        print(f"  {s:7s} : {len(prep[s]['idx'])} lignes | features 1H={prep[s]['X1'].shape[1]}  +MTF={prep[s]['Xm'].shape[1]}")

    configs = {
        "A · 1H seul": lambda a: run_direct(a, use_mtf=False),
        "B · 1H+MTF": lambda a: run_direct(a, use_mtf=True),
        "C · MTF+meta": run_meta,
    }
    print("\n" + "─" * 84)
    print(f"   {'config':>14} | {'trades':>6} | {'win%':>6} | {'E[R]net':>8} | {'Rtot net':>8} | {'PF':>5} | {'maxDD':>7} | {'AUC':>5}")
    out = {}
    for name, fn in configs.items():
        allr, aucs = [], []
        for s in ASSETS:
            tr, auc = fn(prep[s])
            allr += tr
            if auc == auc:
                aucs.append(auc)
        st = stats(allr); auc = float(np.mean(aucs)) if aucs else float("nan")
        out[name] = {**st, "auc": auc}
        pf = "inf" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
        print(f"   {name:>14} | {st['n']:>6} | {st['win']*100:>5.1f}% | {st['exp']:>+8.3f} | "
              f"{st['tot']:>+8.1f} | {pf:>5} | {st['dd']:>7.1f} | {auc:>5.3f}")

    print("\n" + "─" * 84)
    a_auc, b_auc = out["A · 1H seul"]["auc"], out["B · 1H+MTF"]["auc"]
    print(f" Effet MTF sur l'AUC : {a_auc:.3f} → {b_auc:.3f}  ({b_auc-a_auc:+.3f})")
    print(f" Effet MTF sur R net : {out['A · 1H seul']['tot']:+.1f} → {out['B · 1H+MTF']['tot']:+.1f} R")
    print(f" Meta-labeling R net : {out['C · MTF+meta']['tot']:+.1f} R (AUC {out['C · MTF+meta']['auc']:.3f})")
    print("═" * 84)
    return out


if __name__ == "__main__":
    run()
