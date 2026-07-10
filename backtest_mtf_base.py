"""
backtest_mtf_base.py
====================
Test de la piste "monter le timeframe de base pour survivre aux coûts", sur DONNÉES MT5.

Idée : le coût d'un trade (spread + commission + slippage) est ~constant EN PRIX quel que
soit le timeframe. Mais 1R = k·ATR grandit avec le timeframe. Donc le coût EN R
( = coût_prix / R_prix ) s'effondre quand on passe de H1 → H4 → D1. On le mesure.

Pour chaque base (H1, H4, D1) : chargement MT5 natif, features causales (volume réel activé),
triple-barrier 2 sens, backtest EXÉCUTABLE non-chevauchant long+short, coût réaliste en prix
converti en R par barre. On compare l'espérance NETTE et le coût médian en R par timeframe.
"""
from __future__ import annotations
import logging, warnings
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import config
config.ENABLE_MTF = False
config.VOLUME_FEATURES_ENABLED = True          # MT5 = vrai tick-volume

import data_loader, pipeline, labeling
import mt5_loader
from features.volatility import atr
from backtest_exec import make_model, _folds, _proba_win, TP_CLS, TAKE_QUANTILE

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30"]
TP = 2.0
# base → (freq pandas, timeout en barres ≈ horizon de détention)
BASES = {"H1": ("1h", 24), "H4": ("4h", 24), "D1": ("1D", 10)}

# Coût aller-retour RÉALISTE en PRIX (spread + commission + slippage), estimation prop-firm.
# ~constant quel que soit le timeframe (c'est tout l'intérêt du test).
COST_PRICE = {"EURUSD": 0.00012, "GBPUSD": 0.00016, "USDJPY": 0.013,
              "XAUUSD": 0.45, "US30": 1.5}


def prepare(symbol: str, tf: str) -> dict:
    freq, timeout = BASES[tf]
    config.PANDAS_FREQ = freq                  # pour la détection de gap (structure/weekend)
    config.TIMEFRAME = tf
    df = data_loader.clean(mt5_loader.fetch(symbol, tf), symbol,
                           do_resample=False, reindex_grid=False)
    X = pipeline.build_features(df, symbol)
    X = X.drop(columns=X.columns[X.isna().all()])     # colonnes dégénérées (ex : session sur D1)
    r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)
    cost_r = (COST_PRICE[symbol] / r_unit).replace([np.inf, -np.inf], np.nan)

    labs = {s: labeling.triple_barrier(df, tp_mult=TP, sl_mult=config.SL_R_MULTIPLE,
                                       timeout=timeout, side=s, r_unit=r_unit)
            for s in (+1, -1)}
    valid = X.notna().all(axis=1) & cost_r.notna()
    for s in (+1, -1):
        valid &= labs[s]["label"].notna()
    idx = X.index[valid]
    return {
        "symbol": symbol, "tf": tf, "X": X.loc[idx], "cost_r": cost_r.loc[idx].to_numpy(),
        "r_unit_med": float(r_unit.loc[idx].median()),
        "lab": {s: {"y": labs[s]["label"].loc[idx].astype(int).to_numpy(),
                    "r": labs[s]["realized_r"].loc[idx].to_numpy(),
                    "bars": labs[s]["barrier_bars"].loc[idx].fillna(1).astype(int).to_numpy()}
                for s in (+1, -1)},
    }


def backtest(a: dict) -> dict:
    """Long+short non-chevauchant. Renvoie R bruts, R nets (coûts), et coût R médian réalisé."""
    X = a["X"]; n = len(X); cost = a["cost_r"]
    gross, net, aucs, costs_used = [], [], [], []
    for tr, te in _folds(n):
        out = {}
        for s, tag in ((+1, "L"), (-1, "S")):
            d = a["lab"][s]; ytr = d["y"][tr]
            if len(np.unique(ytr)) < 2:
                out[tag] = None; continue
            m = make_model(); m.fit(X.iloc[tr], ytr)
            cl = list(m.classes_)
            thr = float(np.quantile(_proba_win(m, X.iloc[tr], cl), TAKE_QUANTILE))
            out[tag] = {"p": _proba_win(m, X.iloc[te], cl), "thr": thr,
                        "r": d["r"][te], "bars": d["bars"][te]}
            ypos = (d["y"][te] == TP_CLS).astype(int)
            if ypos.min() != ypos.max():
                aucs.append(roc_auc_score(ypos, out[tag]["p"]))
        c_te = cost[te]
        # simulation non-chevauchante long+short
        i = 0; m_te = len(c_te)
        while i < m_te:
            L, S = out.get("L"), out.get("S")
            okL = L and L["p"][i] >= L["thr"] and np.isfinite(L["r"][i])
            okS = S and S["p"][i] >= S["thr"] and np.isfinite(S["r"][i])
            if okL or okS:
                take_L = okL and (not okS or (L["p"][i] - L["thr"]) >= (S["p"][i] - S["thr"]))
                o = L if take_L else S
                r = float(o["r"][i]); c = float(c_te[i])
                gross.append(r); net.append(r - c); costs_used.append(c)
                i += int(max(o["bars"][i], 1))
            else:
                i += 1
    return {"gross": np.array(gross), "net": np.array(net),
            "cost_med": float(np.median(costs_used)) if costs_used else np.nan,
            "auc": float(np.mean(aucs)) if aucs else np.nan}


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, win=np.nan, exp=np.nan, tot=0.0, pf=np.nan, dd=0.0)
    eq = np.cumsum(r); dd = float((eq - np.maximum.accumulate(eq)).min())
    g = r[r > 0].sum(); l = -r[r < 0].sum()
    return dict(n=int(len(r)), win=float((r > 0).mean()), exp=float(r.mean()),
                tot=float(r.sum()), pf=float(g / l) if l > 0 else float("inf"), dd=dd)


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    pipeline.set_seeds()
    print("═" * 92)
    print(" BASE TIMEFRAME vs COÛTS — données MT5 réelles · long+short non-chevauchant · TP=2R")
    print("═" * 92)
    print(f" Actifs {', '.join(ASSETS)} | coût réaliste EN PRIX (spread+comm+slippage) converti en R")
    print("═" * 92)
    print(f"   {'base':>5} | {'trades':>6} | {'coût~R':>7} | {'win%':>6} | {'E[R]brut':>8} | {'E[R]net':>8} | {'Rtot net':>8} | {'PF net':>6} | {'AUC':>5}")

    out = {}
    for tf in BASES:
        allg, alln, costs, aucs = [], [], [], []
        per_asset = {}
        for sym in ASSETS:
            a = prepare(sym, tf)
            res = backtest(a)
            allg.append(res["gross"]); alln.append(res["net"])
            if res["cost_med"] == res["cost_med"]:
                costs.append(res["cost_med"])
            if res["auc"] == res["auc"]:
                aucs.append(res["auc"])
            per_asset[sym] = {**stats(res["net"]), "cost_med": res["cost_med"],
                              "gross_exp": stats(res["gross"])["exp"], "auc": res["auc"]}
        g = np.concatenate(allg); nt = np.concatenate(alln)
        sg, sn = stats(g), stats(nt)
        cost_med = float(np.median(costs)) if costs else np.nan
        auc = float(np.mean(aucs)) if aucs else np.nan
        out[tf] = {"gross": sg, "net": sn, "cost_med": cost_med, "auc": auc, "per_asset": per_asset}
        pf = "inf" if sn["pf"] == float("inf") else f"{sn['pf']:.2f}"
        print(f"   {tf:>5} | {sn['n']:>6} | {cost_med:>7.3f} | {sn['win']*100:>5.1f}% | "
              f"{sg['exp']:>+8.3f} | {sn['exp']:>+8.3f} | {sn['tot']:>+8.1f} | {pf:>6} | {auc:>5.3f}")

    print("\n" + "─" * 92)
    print(" Lecture : 'coût~R' = coût médian d'un trade en fraction de R. Il s'effondre quand le")
    print("           timeframe monte → l'espérance NETTE remonte mécaniquement.")
    for tf in BASES:
        o = out[tf]
        print(f"   {tf}: coût {o['cost_med']:.3f}R/trade · E[R] brut {o['gross']['exp']:+.3f} "
              f"→ net {o['net']['exp']:+.3f} · R net total {o['net']['tot']:+.1f}")
    print("═" * 92)
    return out


if __name__ == "__main__":
    run()
