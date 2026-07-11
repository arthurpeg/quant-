"""
xsection_poc.py
===============
Preuve de concept : pourquoi la BREADTH change tout — et pourquoi agréger 200 actions pour
prédire UN indice ne la crée PAS.

  POC A — CROSS-SECTIONNEL ACTIONS (breadth ≈ 200 paris/semaine)
      Features normalisées PAR DATE (on classe les actions entre elles), cible = rendement
      excédentaire à 5 jours vs la moyenne de l'univers. Métriques : IC de Spearman, IR,
      et portefeuille long/short décile net de coûts.

  POC B — MÊMES DONNÉES → PRÉDIRE UN INDICE (breadth = 1 pari)
      On agrège le panel actions en features de "breadth de marché" (% au-dessus de la MM200,
      ratio hausses/baisses, dispersion cross-sectionnelle...) pour prédire le rendement à
      5 jours de US30. Information riche, mais UN SEUL pari.

Loi fondamentale : IR ≈ IC × √(nb de paris indépendants). POC A et POC B ont un IC comparable ;
seul le nombre de paris diffère. C'est ce que cette expérience rend visible.

⚠️ Biais de survivance présent (voir equity_loader). La POC démontre un MÉCANISME, elle ne
   livre pas une stratégie déployable.
"""
from __future__ import annotations
import warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from xgboost import XGBRegressor, XGBClassifier

import config
import equity_loader

warnings.filterwarnings("ignore")

HORIZON = 5          # rendement futur à 5 jours (hebdomadaire)
REBAL = 5            # rebalancement tous les 5 jours ouvrés → cibles non chevauchantes
N_FOLDS = 4
DECILE = 0.10        # top/bottom 10% pour le portefeuille long/short
COST_BPS = 5.0       # coût par côté et par unité de turnover (5 bps) → 10 bps aller-retour
SEED = config.SEED


def _reg():
    return XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                        colsample_bytree=0.8, min_child_weight=20, reg_lambda=2.0,
                        tree_method="hist", random_state=SEED, n_jobs=-1)


# ───────────────────────────────────────────────────────────────────────────
# POC A — features cross-sectionnelles
# ───────────────────────────────────────────────────────────────────────────
def build_xs_features(close: pd.DataFrame, volume: pd.DataFrame) -> dict:
    """Features time-series causales par action (dates × tickers)."""
    logp = np.log(close)
    feats = {}
    # momentum en sautant le dernier mois (effet de reversal court terme séparé)
    feats["mom_12_1"] = logp.shift(21) - logp.shift(252)
    feats["mom_6_1"] = logp.shift(21) - logp.shift(126)
    feats["mom_3_1"] = logp.shift(21) - logp.shift(63)
    feats["rev_5"] = logp - logp.shift(5)                    # reversal court terme
    ret = logp.diff()
    feats["vol_60"] = ret.rolling(60, min_periods=60).std()
    feats["dist_52w_high"] = close / close.rolling(252, min_periods=252).max() - 1.0
    feats["vol_trend"] = (volume.rolling(20, min_periods=20).mean()
                          / volume.rolling(60, min_periods=60).mean())
    feats["ret_skew_60"] = ret.rolling(60, min_periods=60).skew()
    return feats


def cross_sectional_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Rang cross-sectionnel par date, ramené à [-0.5, +0.5] (neutre au marché)."""
    r = df.rank(axis=1, pct=True)
    return r - 0.5


def poc_a(close: pd.DataFrame, volume: pd.DataFrame) -> dict:
    feats = build_xs_features(close, volume)
    logp = np.log(close)
    # cible : rendement futur 5j, EXCÉDENTAIRE vs moyenne de l'univers à cette date
    fwd = logp.shift(-HORIZON) - logp
    fwd_excess = fwd.sub(fwd.mean(axis=1), axis=0)

    dates = close.index[::REBAL]                              # rebalancements non chevauchants
    rows = []
    for d in dates:
        if d not in close.index:
            continue
        x = pd.DataFrame({k: v.loc[d] for k, v in feats.items()})
        y = fwd_excess.loc[d]
        ok = x.notna().all(axis=1) & y.notna()
        if ok.sum() < 50:
            continue
        rows.append((d, x[ok], y[ok]))

    # rang cross-sectionnel par date : on classe les actions ENTRE ELLES (neutre au marché)
    prepared = [(d, x.rank(pct=True) - 0.5, y) for d, x, y in rows]

    n = len(prepared)
    fs = n // (N_FOLDS + 1)
    ics, preds_all = [], []
    for k in range(1, N_FOLDS + 1):
        tr = prepared[: k * fs]
        te = prepared[k * fs + 1 : (k + 1) * fs]              # 1 date d'embargo
        if not te:
            continue
        Xtr = pd.concat([p[1] for p in tr]); ytr = pd.concat([p[2] for p in tr])
        m = _reg(); m.fit(Xtr, ytr)
        for d, xr, y in te:
            p = pd.Series(m.predict(xr), index=xr.index)
            ic = spearmanr(p, y).statistic
            if np.isfinite(ic):
                ics.append(ic)
            preds_all.append((d, p, y))

    ics = np.array(ics)
    mean_ic, std_ic = ics.mean(), ics.std(ddof=1)
    periods_per_year = 252 / REBAL
    ic_ir = mean_ic / std_ic * np.sqrt(periods_per_year)

    # portefeuille long/short décile, net de coûts
    gross, net, prev_w = [], [], None
    for d, p, y in preds_all:
        k = max(int(len(p) * DECILE), 1)
        longs = p.nlargest(k).index; shorts = p.nsmallest(k).index
        w = pd.Series(0.0, index=p.index)
        w[longs] = 0.5 / k; w[shorts] = -0.5 / k              # gross exposure = 1
        r = float((w * y.reindex(w.index).fillna(0)).sum())
        turn = 1.0 if prev_w is None else float(
            (w - prev_w.reindex(w.index).fillna(0)).abs().sum())
        cost = turn * COST_BPS / 1e4
        gross.append(r); net.append(r - cost); prev_w = w

    g, nt = np.array(gross), np.array(net)
    ann = periods_per_year
    def sharpe(x): return x.mean() / x.std(ddof=1) * np.sqrt(ann) if x.std() > 0 else np.nan
    eq = np.cumsum(nt); dd = float((eq - np.maximum.accumulate(eq)).min())
    return {
        "n_rebal": len(preds_all), "avg_names": int(np.mean([len(p) for _, p, _ in preds_all])),
        "mean_ic": mean_ic, "std_ic": std_ic, "ic_ir": ic_ir,
        "gross_ann": g.mean() * ann, "net_ann": nt.mean() * ann,
        "sharpe_gross": sharpe(g), "sharpe_net": sharpe(nt),
        "max_dd": dd, "hit": float((nt > 0).mean()),
    }


# ───────────────────────────────────────────────────────────────────────────
# POC B — mêmes données actions → prédire UN indice
# ───────────────────────────────────────────────────────────────────────────
def build_breadth_features(close: pd.DataFrame) -> pd.DataFrame:
    """Agrégats de marché issus du panel actions (causals). UNE ligne par date."""
    logp = np.log(close)
    ret1 = logp.diff()
    ma200 = close.rolling(200, min_periods=200).mean()
    out = pd.DataFrame(index=close.index)
    out["pct_above_ma200"] = (close > ma200).sum(axis=1) / close.notna().sum(axis=1)
    out["adv_dec_5"] = ((logp - logp.shift(5)) > 0).sum(axis=1) / close.notna().sum(axis=1)
    out["dispersion_5"] = (logp - logp.shift(5)).std(axis=1)
    out["median_mom_12_1"] = (logp.shift(21) - logp.shift(252)).median(axis=1)
    out["breadth_new_high"] = (close >= close.rolling(252, min_periods=252).max()).sum(axis=1) \
        / close.notna().sum(axis=1)
    out["mkt_ret_5"] = ret1.mean(axis=1).rolling(5, min_periods=5).sum()
    out["mkt_vol_20"] = ret1.mean(axis=1).rolling(20, min_periods=20).std()
    out["corr_proxy"] = out["mkt_vol_20"] / out["dispersion_5"].replace(0, np.nan)
    return out


def poc_b(close: pd.DataFrame, index_close: pd.Series) -> dict:
    B = build_breadth_features(close)
    idx = index_close.reindex(B.index).ffill()
    logi = np.log(idx)
    fwd = logi.shift(-HORIZON) - logi                  # rendement futur 5j de l'indice
    y_dir = (fwd > 0).astype(float)

    dates = B.index[::REBAL]
    D = pd.concat([B, fwd.rename("fwd"), y_dir.rename("ydir")], axis=1).loc[dates].dropna()
    if len(D) < 100:
        return {"error": "pas assez de dates"}

    X = D[B.columns]; yfwd = D["fwd"]; ydir = D["ydir"].astype(int)
    n = len(D); fs = n // (N_FOLDS + 1)
    aucs, ics = [], []
    for k in range(1, N_FOLDS + 1):
        tr = slice(0, k * fs); te = slice(k * fs + 1, (k + 1) * fs)
        if te.start >= min(te.stop, n):
            continue
        if ydir.iloc[tr].nunique() < 2 or ydir.iloc[te].nunique() < 2:
            continue
        clf = XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8,
                            colsample_bytree=0.8, min_child_weight=10, eval_metric="logloss",
                            tree_method="hist", random_state=SEED, n_jobs=-1)
        clf.fit(X.iloc[tr], ydir.iloc[tr])
        p = clf.predict_proba(X.iloc[te])[:, 1]
        aucs.append(roc_auc_score(ydir.iloc[te], p))
        reg = _reg(); reg.fit(X.iloc[tr], yfwd.iloc[tr])
        pr = reg.predict(X.iloc[te])
        ic = spearmanr(pr, yfwd.iloc[te]).statistic
        if np.isfinite(ic):
            ics.append(ic)
    periods_per_year = 252 / REBAL
    mean_ic = float(np.mean(ics)) if ics else np.nan
    # IR d'un pari unique : IC × √(nb de paris) avec breadth = 1 pari par période
    ir_single = mean_ic * np.sqrt(periods_per_year)
    return {"n_dates": n, "auc": float(np.mean(aucs)), "mean_ic": mean_ic, "ir_single": ir_single}


def run():
    import sys
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8")
        except Exception: pass
    np.random.seed(SEED)

    panel = equity_loader.build_panel()
    close = panel["close"].unstack("ticker").sort_index()
    volume = panel["volume"].unstack("ticker").sort_index()
    # garder les actions présentes sur ≥80% des dates
    keep = close.notna().mean() >= 0.8
    close, volume = close.loc[:, keep], volume.loc[:, keep]

    print("═" * 88)
    print(" PREUVE DE CONCEPT — l'effet de BREADTH (loi fondamentale : IR ≈ IC × √breadth)")
    print("═" * 88)
    print(f" Univers : {close.shape[1]} actions US · {close.index[0].date()} → {close.index[-1].date()}")
    print(f" Horizon {HORIZON}j · rebalancement {REBAL}j · coût {COST_BPS} bps/côté/turnover")
    print(" ⚠️ biais de survivance présent (symboles encore cotés) — démonstration d'un mécanisme")
    print("═" * 88)

    A = poc_a(close, volume)
    print("\n POC A — CROSS-SECTIONNEL ACTIONS (long/short décile)")
    print(f"   rebalancements={A['n_rebal']}  · actions/date ≈ {A['avg_names']}  → breadth élevée")
    print(f"   IC moyen      = {A['mean_ic']:+.4f}   (écart-type {A['std_ic']:.4f})")
    print(f"   IC-IR annuel  = {A['ic_ir']:+.2f}")
    print(f"   Perf brute    = {A['gross_ann']*100:+.2f}%/an   Sharpe {A['sharpe_gross']:.2f}")
    print(f"   Perf NETTE    = {A['net_ann']*100:+.2f}%/an   Sharpe {A['sharpe_net']:.2f}")
    print(f"   Max DD {A['max_dd']*100:.1f}%   · semaines gagnantes {A['hit']*100:.1f}%")

    # POC B : prédire US30 avec les mêmes données actions
    try:
        import mt5_loader
        idx_df = mt5_loader.fetch("US30", "D1")
        idx_close = idx_df["close"]
        idx_close.index = idx_close.index.normalize()
        cl2 = close.copy(); cl2.index = cl2.index.normalize()
        B = poc_b(cl2, idx_close)
        print("\n POC B — MÊMES DONNÉES → PRÉDIRE UN INDICE (US30)")
        if "error" in B:
            print("  ", B["error"])
        else:
            print(f"   dates={B['n_dates']}  · 1 seul actif prédit → breadth = 1 pari/période")
            print(f"   AUC direction = {B['auc']:.4f}")
            print(f"   IC moyen      = {B['mean_ic']:+.4f}")
            print(f"   IR implicite  = {B['ir_single']:+.2f}  (IC × √52, un seul pari par semaine)")

            print("\n" + "─" * 88)
            print(" COMPARAISON — même qualité de signal, breadth différente")
            print(f"   POC A : IC {A['mean_ic']:+.4f} sur ~{A['avg_names']} paris/semaine → IR {A['ic_ir']:+.2f}")
            print(f"   POC B : IC {B['mean_ic']:+.4f} sur 1 pari/semaine          → IR {B['ir_single']:+.2f}")
    except Exception as e:
        print(f"\n POC B indisponible : {e}")
    print("═" * 88)


if __name__ == "__main__":
    run()
