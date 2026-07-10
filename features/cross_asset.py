"""
features/cross_asset.py
=======================
Features CROSS-ASSET / MACRO — information d'une nature différente du prix de l'actif tradé.

Sources (macro_loader) : DXY synthétique (indice dollar, formule ICE), VIXY (proxy VIX),
UST (proxy taux US).

Anti-leakage : les séries macro sont au MÊME timeframe que l'actif, donc la barre macro
étiquetée t clôture au même instant que la barre actif t → elle est connue au moment de la
décision (clôture de t). L'alignement se fait par merge_asof "backward" : si une barre macro
manque (VIXY/UST ne cotent qu'aux heures cash US), on ne récupère que la DERNIÈRE valeur
réellement connue — jamais une valeur future.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
import macro_loader


def _align(macro: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """merge_asof backward : dernière valeur macro connue à chaque timestamp de `index`."""
    left = pd.DataFrame({"_t": index}).sort_values("_t")
    right = macro.reset_index().rename(columns={macro.index.name or "index": "_t"}).sort_values("_t")
    out = pd.merge_asof(left, right, on="_t", direction="backward").set_index("_t")
    return out.reindex(index)


def compute(df: pd.DataFrame, tf: str = "H4") -> pd.DataFrame:
    """
    Features cross-asset alignées sur l'index de `df` (barres de l'actif tradé).
    Renvoie un DataFrame de mêmes lignes. Toutes les fenêtres sont causales (center=False).
    """
    out = pd.DataFrame(index=df.index)
    try:
        macro = macro_loader.load_macro(tf)
    except Exception as e:                      # macro indisponible → bloc vide
        print(f"[cross_asset] macro indisponible : {e}")
        return out

    # VIXY/UST ne cotent qu'aux heures cash US : leurs lignes sont NaN le reste du temps.
    # merge_asof matche des LIGNES, pas la dernière valeur par colonne → on propage d'abord
    # la dernière valeur connue de chaque colonne (ffill = strictement causal).
    macro = macro.sort_index().ffill()

    m = _align(macro, df.index)
    asset_ret = np.log(df[config.COL_CLOSE] / df[config.COL_CLOSE].shift(1))

    for col in m.columns:
        s = m[col]
        # rendements log ; pendant un trou macro (valeur ffillée) le rendement vaut 0 :
        # pas de nouvelle information, ce qui est le comportement correct et causal.
        r = np.log(s / s.shift(1)).replace([np.inf, -np.inf], np.nan)
        out[f"{col}_ret_1"] = r
        out[f"{col}_ret_5"] = np.log(s / s.shift(5))
        out[f"{col}_ret_20"] = np.log(s / s.shift(20))
        mean20 = s.rolling(20, min_periods=20).mean()
        std20 = s.rolling(20, min_periods=20).std(ddof=0)
        out[f"{col}_zscore_20"] = (s - mean20) / std20.replace(0.0, np.nan)

        # couplage actif ↔ macro : corrélation et bêta glissants (60 barres)
        out[f"corr_{col}_60"] = asset_ret.rolling(60, min_periods=60).corr(r)
        cov = asset_ret.rolling(60, min_periods=60).cov(r)
        var = r.rolling(60, min_periods=60).var(ddof=0)
        out[f"beta_{col}_60"] = cov / var.replace(0.0, np.nan)

    # force relative de l'actif vs dollar (utile pour paires USD et métaux)
    if "dxy" in m.columns:
        asset_ret20 = np.log(df[config.COL_CLOSE] / df[config.COL_CLOSE].shift(20))
        out["relstrength_vs_dxy_20"] = asset_ret20 - out["dxy_ret_20"]

    return out
