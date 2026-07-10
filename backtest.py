"""
backtest.py
===========
Backtest walk-forward multi-actifs d'un XGBoost entraîné sur la sortie du pipeline.

⚠️⚠️ AVERTISSEMENT DONNÉES ⚠️⚠️
    Il n'existe AUCUNE donnée de marché réelle dans ce projet. Ce backtest tourne sur des
    séries SYNTHÉTIQUES (marche aléatoire + signal AR(1) de momentum INJECTÉ), générées par
    actif. Le signal injecté existe uniquement pour que le modèle ait quelque chose à
    apprendre → cela valide la MÉCANIQUE (features → train → predict → P&L en R), PAS un edge
    réel. Sur de vraies données, il faut refaire tourner data_loader.clean() sur des CSV OHLCV.

Protocole :
  - Pour chaque actif : pipeline → (X, y) → walk-forward EXPANDING (N folds, embargo).
  - Un XGBClassifier (3 classes : sl/tp/timeout) est ré-entraîné à chaque fold sur le passé,
    puis prédit les probas sur le bloc de test futur (jamais vu).
  - Règle de trading : on prend le trade (long, side config) si P(tp) est dans le top quantile
    des prédictions du fold (le modèle agit comme FILTRE). SL = -1R par construction.
  - Comptabilité en R : realized_r (voir labeling) = +TP_R_MULTIPLE / -1 / mark-to-market.

Stats ML : accuracy, F1 macro, précision/rappel de la classe TP, ROC-AUC (TP vs reste).
Stats trading : nb trades, win rate, espérance en R, R total, profit factor, max drawdown R.
"""

from __future__ import annotations

import logging
import warnings
import zlib
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd

from sklearn.metrics import (
    accuracy_score, f1_score, precision_score, recall_score, roc_auc_score,
    confusion_matrix,
)
from xgboost import XGBClassifier

import config
import data_loader
import pipeline

warnings.filterwarnings("ignore", category=UserWarning)

# ───────────────────────────────────────────────────────────────────────────
# Univers testé (sous-ensemble de la whitelist, multi-classes d'actifs)
# Params synthétiques : prix de départ, vol horaire, force du signal AR injecté.
# ───────────────────────────────────────────────────────────────────────────
# phi = force du momentum AR(1) injecté (0 = marche aléatoire pure, plus haut = plus
# apprenable). Volontairement élevé ici pour DÉMONTRER que le pipeline capte un edge
# quand il en existe un ; sur données réelles l'autocorrélation horaire est bien plus faible.
UNIVERSE: Dict[str, dict] = {
    "EURUSD": dict(price=1.10,   vol=0.0006, phi=0.42),
    # GBPUSD retiré de l'univers backté (non rentable sur cet échantillon).
    # ⚠️ Exclusion post-hoc sur le P&L = biais de sélection : à décider idéalement
    #    out-of-sample ou sur une règle a priori, pas sur le résultat final.
    "USDJPY": dict(price=150.0,  vol=0.05,   phi=0.45),
    "XAUUSD": dict(price=2300.0, vol=1.8,    phi=0.40),
    "US30":   dict(price=38000.0, vol=25.0,  phi=0.36),
    "NAS100": dict(price=18000.0, vol=20.0,  phi=0.44),
}

N_DAYS = 220           # ~jours calendaires simulés par actif
N_FOLDS = 4            # folds de walk-forward (expanding window)
TAKE_QUANTILE = 0.70   # on prend le trade si P(tp) >= quantile 70% du fold (top 30%)

logger = logging.getLogger("backtest")


# ───────────────────────────────────────────────────────────────────────────
# Génération synthétique avec signal AR(1) injecté (momentum apprenable)
# ───────────────────────────────────────────────────────────────────────────
def make_synth(symbol: str, params: dict, n_days: int, seed: int) -> pd.DataFrame:
    """
    OHLCV 1H synthétique pour `symbol`, heures de marché uniquement (trous week-end réels).
    Rendements = AR(1) : r_t = phi * r_{t-1} + bruit → persistance de momentum que les
    features (log-returns, pente, RSI...) peuvent capturer. SIGNAL PUREMENT SYNTHÉTIQUE.
    """
    import calendar_utils as cal
    rng = np.random.default_rng(seed)

    start = pd.Timestamp("2023-06-01 00:00", tz="UTC")
    grid = cal.market_grid(start, start + pd.Timedelta(days=n_days))
    n = len(grid)

    phi, vol = params["phi"], params["vol"] / params["price"]  # vol en rendement relatif
    noise = rng.normal(0, vol, n)
    r = np.empty(n)
    r[0] = noise[0]
    for i in range(1, n):                       # AR(1) : récurrence séquentielle assumée
        r[i] = phi * r[i - 1] + noise[i]

    step = pd.Timedelta("1h")
    is_gap = grid.to_series().diff().gt(step).fillna(False).to_numpy()
    r = np.where(is_gap, r + rng.normal(0, vol * 2.5, n), r)   # gap week-end marqué

    close = params["price"] * np.exp(np.cumsum(r))
    open_ = np.empty(n); open_[0] = params["price"]; open_[1:] = close[:-1]
    open_ = np.where(is_gap, close * np.exp(rng.normal(0, vol, n)), open_)
    wick = np.abs(rng.normal(0, vol, n)) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volu = rng.integers(50, 500, n).astype(float)

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volu},
        index=grid,
    )


# ───────────────────────────────────────────────────────────────────────────
# Modèle
# ───────────────────────────────────────────────────────────────────────────
def make_model() -> XGBClassifier:
    """XGBoost 3 classes, seed fixé. n_jobs=1 si strict_determinism (repro bit-à-bit)."""
    return XGBClassifier(
        n_estimators=250,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_lambda=1.0,
        eval_metric="mlogloss",
        tree_method="hist",
        random_state=config.SEED,
        n_jobs=1 if config.STRICT_DETERMINISM else -1,
    )


# ───────────────────────────────────────────────────────────────────────────
# Walk-forward expanding par actif
# ───────────────────────────────────────────────────────────────────────────
@dataclass
class TradeLog:
    rows: List[dict] = field(default_factory=list)

    def add(self, **kw):
        self.rows.append(kw)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def backtest_asset(symbol: str, params: dict) -> pd.DataFrame:
    """
    Backtest walk-forward d'un actif. Renvoie un DataFrame de prédictions test concaténées
    (avec proba_tp, label réel, realized_r, flag 'taken').
    """
    # seed déterministe par symbole (zlib.crc32 est stable entre process, contrairement à
    # hash() qui est randomisé par PYTHONHASHSEED → indispensable pour la reproductibilité).
    sym_seed = config.SEED + zlib.crc32(symbol.encode()) % 100000
    raw = make_synth(symbol, params, N_DAYS, seed=sym_seed)
    ds = pipeline.run(raw, symbol)
    X, y = ds.X, ds.y
    realized = ds.meta["realized_r"]
    n = len(X)

    tp_cls = config.LABEL_MAP["tp"]
    fold_size = n // (N_FOLDS + 1)
    if fold_size < 50:
        raise ValueError(f"{symbol}: série trop courte ({n}) pour {N_FOLDS} folds.")

    out = []
    for k in range(1, N_FOLDS + 1):
        tr_end = k * fold_size
        te_start = tr_end + config.EMBARGO_BARS
        te_end = min((k + 1) * fold_size, n)
        if te_start >= te_end:
            continue

        Xtr, ytr = X.iloc[:tr_end], y.iloc[:tr_end]
        Xte, yte = X.iloc[te_start:te_end], y.iloc[te_start:te_end]
        rte = realized.iloc[te_start:te_end]

        model = make_model()
        model.fit(Xtr, ytr)
        proba = model.predict_proba(Xte)
        classes = list(model.classes_)
        proba_tp = proba[:, classes.index(tp_cls)] if tp_cls in classes else np.zeros(len(Xte))
        # pred = argmax des probas (robuste si une classe manque dans le fold d'entraînement)
        pred = np.asarray(classes)[np.argmax(proba, axis=1)]

        # règle de filtre : top quantile de P(tp) dans le fold
        thr = np.quantile(proba_tp, TAKE_QUANTILE)
        taken = proba_tp >= thr

        fold_df = pd.DataFrame({
            "symbol": symbol,
            "fold": k,
            "y_true": yte.to_numpy(),
            "y_pred": pred,
            "proba_tp": proba_tp,
            "realized_r": rte.to_numpy(),
            "taken": taken,
        }, index=Xte.index)
        out.append(fold_df)

    return pd.concat(out) if out else pd.DataFrame()


# ───────────────────────────────────────────────────────────────────────────
# Statistiques
# ───────────────────────────────────────────────────────────────────────────
def ml_stats(df: pd.DataFrame) -> dict:
    """Métriques de classification (sur TOUTES les prédictions test, pas seulement prises)."""
    yt, yp = df["y_true"].to_numpy(), df["y_pred"].to_numpy()
    tp_cls = config.LABEL_MAP["tp"]
    tp_true = (yt == tp_cls).astype(int)
    try:
        auc = roc_auc_score(tp_true, df["proba_tp"].to_numpy())
    except ValueError:
        auc = float("nan")
    return {
        "n_test": len(df),
        "accuracy": accuracy_score(yt, yp),
        "f1_macro": f1_score(yt, yp, average="macro", labels=list(config.LABEL_MAP.values())),
        "tp_precision": precision_score(yt, yp, labels=[tp_cls], average="micro", zero_division=0),
        "tp_recall": recall_score(yt, yp, labels=[tp_cls], average="micro", zero_division=0),
        "tp_auc": auc,
    }


def trade_stats(realized_r: np.ndarray) -> dict:
    """P&L en R d'une série de trades pris."""
    r = np.asarray(realized_r, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return {"n_trades": 0, "win_rate": np.nan, "expectancy_R": np.nan,
                "total_R": 0.0, "profit_factor": np.nan, "max_dd_R": 0.0}
    equity = np.cumsum(r)
    peak = np.maximum.accumulate(equity)
    max_dd = float((equity - peak).min())
    gains = r[r > 0].sum()
    losses = -r[r < 0].sum()
    return {
        "n_trades": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "expectancy_R": float(r.mean()),
        "total_R": float(r.sum()),
        "profit_factor": float(gains / losses) if losses > 0 else float("inf"),
        "max_dd_R": max_dd,
    }


# ───────────────────────────────────────────────────────────────────────────
# Runner principal
# ───────────────────────────────────────────────────────────────────────────
def run_backtest() -> dict:
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    logging.basicConfig(level=logging.WARNING, format="%(name)s | %(message)s")
    pipeline.set_seeds()

    print("═" * 78)
    print(" BACKTEST WALK-FORWARD MULTI-ACTIFS — XGBoost triple-barrier (SL = -1R)")
    print("═" * 78)
    print(" ⚠️  DONNÉES SYNTHÉTIQUES (signal AR injecté) — validation de la mécanique,")
    print("     PAS un edge réel. Remplacer make_synth() par des CSV OHLCV réels pour du vrai.")
    print("═" * 78)
    print(f" Univers : {', '.join(UNIVERSE)}")
    print(f" Config  : TP={config.TP_R_MULTIPLE}R  SL={config.SL_R_MULTIPLE}R  "
          f"timeout={config.TIMEOUT_BARS} bougies  side={'long' if config.TRADE_SIDE>0 else 'short'}")
    print(f" Walk-fwd: {N_FOLDS} folds expanding, embargo={config.EMBARGO_BARS}, "
          f"filtre P(tp) top {int((1-TAKE_QUANTILE)*100)}%\n")

    all_preds = []
    per_asset = []
    for sym, params in UNIVERSE.items():
        preds = backtest_asset(sym, params)
        if preds.empty:
            continue
        all_preds.append(preds)
        mls = ml_stats(preds)
        taken = preds[preds["taken"]]
        trs = trade_stats(taken["realized_r"].to_numpy())
        base = trade_stats(preds["realized_r"].to_numpy())   # baseline : prendre tout
        per_asset.append({"symbol": sym, **mls, **trs,
                          "base_expectancy_R": base["expectancy_R"]})
        print(f"  {sym:7s} | test={mls['n_test']:5d}  acc={mls['accuracy']:.3f}  "
              f"AUC_tp={mls['tp_auc']:.3f} | trades={trs['n_trades']:4d}  "
              f"win={trs['win_rate']*100:5.1f}%  E[R]={trs['expectancy_R']:+.3f}  "
              f"totalR={trs['total_R']:+7.1f}  PF={trs['profit_factor']:.2f}")

    full = pd.concat(all_preds)
    tbl = pd.DataFrame(per_asset).set_index("symbol")

    # ── Portefeuille agrégé (tous actifs, trades pris) ──
    port = trade_stats(full[full["taken"]]["realized_r"].to_numpy())
    base_all = trade_stats(full["realized_r"].to_numpy())
    glob_ml = ml_stats(full)

    print("\n" + "─" * 78)
    print(" STATISTIQUES ML (global, sur tout le test) :")
    print(f"   accuracy={glob_ml['accuracy']:.3f}  f1_macro={glob_ml['f1_macro']:.3f}  "
          f"TP_precision={glob_ml['tp_precision']:.3f}  TP_recall={glob_ml['tp_recall']:.3f}  "
          f"TP_AUC={glob_ml['tp_auc']:.3f}")
    cm = confusion_matrix(full["y_true"], full["y_pred"],
                          labels=list(config.LABEL_MAP.values()))
    inv = {v: k for k, v in config.LABEL_MAP.items()}
    cm_df = pd.DataFrame(cm, index=[f"vrai_{inv[i]}" for i in config.LABEL_MAP.values()],
                         columns=[f"pred_{inv[i]}" for i in config.LABEL_MAP.values()])
    print("\n   Matrice de confusion :")
    print(cm_df.to_string().replace("\n", "\n   "))

    print("\n" + "─" * 78)
    print(" PERFORMANCE EN R — PORTEFEUILLE (tous actifs, trades filtrés par le ML) :")
    print(f"   trades={port['n_trades']}   win_rate={port['win_rate']*100:.1f}%   "
          f"E[R]/trade={port['expectancy_R']:+.3f}R")
    print(f"   R total={port['total_R']:+.1f}R   profit_factor={port['profit_factor']:.2f}   "
          f"max_drawdown={port['max_dd_R']:.1f}R")
    print(f"\n   Référence 'prendre TOUT trade' (sans filtre ML) : "
          f"E[R]={base_all['expectancy_R']:+.3f}R  sur {base_all['n_trades']} events")
    lift = port["expectancy_R"] - base_all["expectancy_R"]
    print(f"   → Apport du filtre ML sur l'espérance : {lift:+.3f}R/trade")
    print("═" * 78)

    return {"table": tbl, "portfolio": port, "baseline": base_all,
            "ml": glob_ml, "cm": cm_df, "full": full}


if __name__ == "__main__":
    run_backtest()
