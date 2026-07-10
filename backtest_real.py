"""
backtest_real.py
================
Backtest sur DONNÉES RÉELLES (Yahoo, cache CSV via fetch_data.py) avec :
  1. GBPUSD réintégré (univers FX + or, tous ~24/5, cohérents avec le calendrier forex).
  2. Balayage du TP optimal : X ∈ {1.0, 1.5, 2.0, 2.5, 3.0} R (SL fixé à 1R).
  3. Variante "TP TEMPOREL" : pas de cible prix, sortie au timeout (mark-to-market), SL=1R.

Méthodo anti-biais :
  - Walk-forward expanding (4 folds), le modèle ne voit jamais le futur.
  - Le TP fixe le "meilleur sur tout le test" est un DIAGNOSTIC in-sample (optimiste) : on le
    montre, mais le chiffre honnête est la sélection ADAPTATIVE — à chaque fold on choisit le
    TP sur le seul passé (train), puis on l'applique au futur (test). Aucune fuite.
  - Features calculées UNE fois par actif (indépendantes du label) ; seul le labeling/entraînement
    est refait par TP → l'ensemble des lignes valides est identique entre TP.

Volume : Yahoo FX = volume nul → features de volume désactivées pour ce run.
"""
from __future__ import annotations
import logging, warnings
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

import config
config.VOLUME_FEATURES_ENABLED = False        # Yahoo FX : pas de volume exploitable

import data_loader
import pipeline
import labeling
import fetch_data
from features.volatility import atr

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)

ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
TP_GRID = [1.0, 1.5, 2.0, 2.5, 3.0]
N_FOLDS = 4
TAKE_QUANTILE = 0.70          # filtre : top 30% par proba prédite
TEMPORAL_TAG = "temporel"


def make_model(binary: bool = False) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=220, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=6, reg_lambda=1.0,
        eval_metric="logloss" if binary else "mlogloss",
        tree_method="hist", random_state=config.SEED,
        n_jobs=1 if config.STRICT_DETERMINISM else -1,
    )


# ───────────────────────────────────────────────────────────────────────────
# Préparation par actif : features (1×) + labels par TP + variante temporelle
# ───────────────────────────────────────────────────────────────────────────
def prepare_asset(symbol: str) -> dict:
    raw = fetch_data.fetch(symbol)
    df = data_loader.clean(raw, symbol, do_resample=False)   # déjà horaire
    X = pipeline.build_features(df, symbol)

    r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)

    # labels par TP (triple barrier classique)
    ys, rs = {}, {}
    for tp in TP_GRID:
        lab = labeling.triple_barrier(df, tp_mult=tp, sl_mult=config.SL_R_MULTIPLE,
                                      timeout=config.TIMEOUT_BARS, side=config.TRADE_SIDE,
                                      r_unit=r_unit)
        ys[tp] = lab["label"]
        rs[tp] = lab["realized_r"]

    # variante temporelle : TP "infini" → sortie SL ou timeout (mark-to-market)
    lab_t = labeling.triple_barrier(df, tp_mult=1e9, sl_mult=config.SL_R_MULTIPLE,
                                    timeout=config.TIMEOUT_BARS, side=config.TRADE_SIDE,
                                    r_unit=r_unit)
    r_temp = lab_t["realized_r"]
    y_temp = (r_temp > 0).astype("float")            # cible binaire : sortie profitable ?
    y_temp[r_temp.isna()] = np.nan

    # index valide commun (features prêtes + labels définis) — identique entre TP
    valid = X.notna().all(axis=1)
    for tp in TP_GRID:
        valid &= ys[tp].notna()
    valid &= r_temp.notna()

    idx = X.index[valid]
    out = {"symbol": symbol, "X": X.loc[idx],
           "y": {tp: ys[tp].loc[idx].astype(int) for tp in TP_GRID},
           "r": {tp: rs[tp].loc[idx] for tp in TP_GRID},
           "r_temp": r_temp.loc[idx], "y_temp": y_temp.loc[idx].astype(int),
           "span": (df.index[0], df.index[-1])}
    return out


# ───────────────────────────────────────────────────────────────────────────
# Un backtest walk-forward : renvoie les trades pris (realized_r) + AUC moyen
# ───────────────────────────────────────────────────────────────────────────
def _folds(n: int):
    fs = n // (N_FOLDS + 1)
    for k in range(1, N_FOLDS + 1):
        tr_end = k * fs
        te_start = tr_end + config.EMBARGO_BARS
        te_end = min((k + 1) * fs, n)
        if te_start < te_end:
            yield slice(0, tr_end), slice(te_start, te_end)


def backtest_config(a: dict, tp) -> dict:
    """Backtest d'un actif pour un TP donné (ou TEMPORAL_TAG). Renvoie realized_r des trades pris."""
    X = a["X"]
    binary = tp == TEMPORAL_TAG
    y = a["y_temp"] if binary else a["y"][tp]
    r = a["r_temp"] if binary else a["r"][tp]
    pos_cls = 1 if binary else config.LABEL_MAP["tp"]   # classe "gagnante" à filtrer

    n = len(X)
    taken_r, aucs = [], []
    for tr, te in _folds(n):
        Xtr, ytr = X.iloc[tr], y.iloc[tr]
        Xte = X.iloc[te]
        rte = r.iloc[te].to_numpy()
        if ytr.nunique() < 2:
            continue
        m = make_model(binary=binary)
        m.fit(Xtr, ytr)
        classes = list(m.classes_)
        proba = m.predict_proba(Xte)
        p = proba[:, classes.index(pos_cls)] if pos_cls in classes else np.zeros(len(Xte))
        thr = np.quantile(p, TAKE_QUANTILE)
        take = p >= thr
        taken_r.append(rte[take])
        yte_pos = (y.iloc[te].to_numpy() == pos_cls).astype(int)
        if yte_pos.min() != yte_pos.max():
            aucs.append(roc_auc_score(yte_pos, p))
    r_all = np.concatenate(taken_r) if taken_r else np.array([])
    return {"realized": r_all, "auc": float(np.mean(aucs)) if aucs else np.nan}


def stats(r: np.ndarray) -> dict:
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return dict(n=0, win=np.nan, exp=np.nan, tot=0.0, pf=np.nan, dd=0.0)
    eq = np.cumsum(r); dd = float((eq - np.maximum.accumulate(eq)).min())
    g = r[r > 0].sum(); l = -r[r < 0].sum()
    return dict(n=int(len(r)), win=float((r > 0).mean()), exp=float(r.mean()),
                tot=float(r.sum()), pf=float(g / l) if l > 0 else float("inf"), dd=dd)


# ───────────────────────────────────────────────────────────────────────────
# Sélection adaptative HONNÊTE du TP (walk-forward, choix sur le passé seulement)
# ───────────────────────────────────────────────────────────────────────────
def backtest_adaptive(a: dict) -> dict:
    """
    À chaque fold : choisir le TP maximisant l'espérance en R de 'prendre tout' sur le TRAIN
    (aucun ML, aucune fuite), puis appliquer le filtre ML de ce TP sur le TEST.
    """
    X = a["X"]; n = len(X)
    taken_r, chosen = [], []
    for tr, te in _folds(n):
        # choix du TP sur le passé (train) : meilleure espérance en 'prendre tout'
        best_tp, best_e = TP_GRID[0], -1e9
        for tp in TP_GRID:
            e = a["r"][tp].iloc[tr].mean()
            if e > best_e:
                best_e, best_tp = e, tp
        chosen.append(best_tp)
        # application sur le futur (test) avec filtre ML entraîné sur le train
        y = a["y"][best_tp]; r = a["r"][best_tp]
        Xtr, ytr, Xte = X.iloc[tr], y.iloc[tr], X.iloc[te]
        if ytr.nunique() < 2:
            continue
        m = make_model(); m.fit(Xtr, ytr)
        classes = list(m.classes_); pos = config.LABEL_MAP["tp"]
        proba = m.predict_proba(Xte)
        p = proba[:, classes.index(pos)] if pos in classes else np.zeros(len(Xte))
        take = p >= np.quantile(p, TAKE_QUANTILE)
        taken_r.append(r.iloc[te].to_numpy()[take])
    r_all = np.concatenate(taken_r) if taken_r else np.array([])
    return {"realized": r_all, "chosen_tp": chosen}


# ───────────────────────────────────────────────────────────────────────────
# Runner
# ───────────────────────────────────────────────────────────────────────────
def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    pipeline.set_seeds()

    print("═" * 84)
    print(" BACKTEST DONNÉES RÉELLES (Yahoo) — recherche du TP optimal · SL = −1R")
    print("═" * 84)
    print(f" Actifs : {', '.join(ASSETS)}  (GBPUSD réintégré) | features volume OFF (FX sans volume)")
    print(f" Walk-forward {N_FOLDS} folds, filtre top {int((1-TAKE_QUANTILE)*100)}% proba, timeout={config.TIMEOUT_BARS}")
    print("═" * 84)

    prepared = {}
    for sym in ASSETS:
        prepared[sym] = prepare_asset(sym)
        sp = prepared[sym]["span"]
        print(f"  {sym:7s} préparé : {len(prepared[sym]['X']):6d} lignes valides  "
              f"[{sp[0].date()} → {sp[1].date()}]")

    # ── Balayage TP : portefeuille agrégé (tous actifs) par TP fixe ──
    print("\n" + "─" * 84)
    print(" BALAYAGE DU TP (portefeuille = concat. des 4 actifs, TP fixe sur tout le test)")
    print(" ⚠️ diagnostic in-sample (optimiste) — le chiffre honnête est plus bas (adaptatif)\n")
    print(f"   {'TP':>5} | {'trades':>6} | {'win%':>6} | {'E[R]':>7} | {'R tot':>8} | {'PF':>5} | {'maxDD':>7} | {'AUC':>5}")
    sweep = {}
    per_asset_tp = {s: {} for s in ASSETS}
    configs = TP_GRID + [TEMPORAL_TAG]
    for tp in configs:
        allr, aucs = [], []
        for sym in ASSETS:
            res = backtest_config(prepared[sym], tp)
            per_asset_tp[sym][tp] = stats(res["realized"])
            per_asset_tp[sym][tp]["auc"] = res["auc"]
            allr.append(res["realized"]); aucs.append(res["auc"])
        r = np.concatenate(allr); st = stats(r); st["auc"] = np.nanmean(aucs)
        sweep[tp] = st
        lab = f"{tp}R" if tp != TEMPORAL_TAG else "TEMP"
        pf = "inf" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
        print(f"   {lab:>5} | {st['n']:>6} | {st['win']*100:>5.1f}% | {st['exp']:>+7.3f} | "
              f"{st['tot']:>+8.1f} | {pf:>5} | {st['dd']:>7.1f} | {st['auc']:>5.3f}")

    # meilleur TP fixe (diagnostic) par R total
    best_fixed = max(TP_GRID, key=lambda t: sweep[t]["tot"])
    print(f"\n   → Meilleur TP FIXE (diagnostic in-sample) : {best_fixed}R "
          f"(R tot {sweep[best_fixed]['tot']:+.1f})")
    print(f"   → Variante TEMPORELLE : R tot {sweep[TEMPORAL_TAG]['tot']:+.1f}, "
          f"E[R] {sweep[TEMPORAL_TAG]['exp']:+.3f}, win {sweep[TEMPORAL_TAG]['win']*100:.1f}%")

    # ── Sélection adaptative honnête (OOS) ──
    print("\n" + "─" * 84)
    print(" SÉLECTION ADAPTATIVE DU TP (honnête, OOS — TP choisi sur le passé de chaque fold)")
    allr = []; chosen_all = []; adaptive_per_asset = {}
    for sym in ASSETS:
        res = backtest_adaptive(prepared[sym])
        allr.append(res["realized"]); chosen_all += res["chosen_tp"]
        st = stats(res["realized"])
        adaptive_per_asset[sym] = {**st, "chosen_tp": res["chosen_tp"]}
        print(f"   {sym:7s} : TP choisis/fold={res['chosen_tp']}  "
              f"R tot={st['tot']:+7.1f}  E[R]={st['exp']:+.3f}  win={st['win']*100:.1f}%")
    r = np.concatenate(allr); st = stats(r)
    print(f"\n   PORTEFEUILLE ADAPTATIF (OOS) : trades={st['n']}  win={st['win']*100:.1f}%  "
          f"E[R]={st['exp']:+.3f}R  R tot={st['tot']:+.1f}R  PF={st['pf']:.2f}  maxDD={st['dd']:.1f}R")
    from collections import Counter
    print(f"   TP les plus choisis : {dict(Counter(chosen_all))}")
    print("═" * 84)

    return {"sweep": sweep, "per_asset_tp": per_asset_tp, "best_fixed": best_fixed,
            "adaptive": st, "adaptive_per_asset": adaptive_per_asset, "chosen": chosen_all,
            "prepared_spans": {s: prepared[s]["span"] for s in ASSETS}}


if __name__ == "__main__":
    run()
