"""
features/mtf.py
===============
Features MULTI-TIMEFRAME projetées sur la base 1H, SANS LEAKAGE.

Le piège classique du multi-TF : au timestamp 1H t, la bougie H4/Daily EN COURS n'est pas
encore clôturée → utiliser ses valeurs = fuite du futur. Règle appliquée ici :

  1. Resampler la base 1H (déjà sur la grille de marché) vers chaque TF supérieur.
  2. Calculer les features causales sur ce TF supérieur (momentum + volatilité + structure).
  3. La feature d'une bougie de TF supérieur d'ouverture O n'est DISPONIBLE qu'à sa clôture
     O + durée. On horodate donc la feature à O+durée, puis merge_asof "backward" sur l'index
     1H → au 1H t, on récupère la dernière bougie supérieure RÉELLEMENT clôturée (≤ t).

Ainsi, à t, une feature "4h" reflète la dernière H4 close, jamais la H4 en formation.
"""
from __future__ import annotations

import pandas as pd

import config
import data_loader
from . import momentum, volatility, structure


def _tf_features(df_tf: pd.DataFrame) -> pd.DataFrame:
    """Sous-ensemble de features causales pertinentes pour un TF supérieur (pas temporel/volume)."""
    parts = [momentum.compute(df_tf), volatility.compute(df_tf), structure.compute(df_tf)]
    return pd.concat(parts, axis=1)


def compute(df_1h: pd.DataFrame) -> pd.DataFrame:
    """
    Renvoie les features multi-TF alignées sur l'index 1H de `df_1h` (mêmes lignes), préfixées
    par le TF (ex : "4h_rsi_14_centered"). Aucune donnée > t n'est utilisée.
    """
    base = pd.DataFrame(index=df_1h.index)
    if not config.ENABLE_MTF:
        return base

    # squelette 1H (uniquement le timestamp) contre lequel chaque TF est aligné indépendamment
    anchor = pd.DataFrame({"_t": df_1h.index}).sort_values("_t")
    aligned = [base]
    for freq, dur in config.MTF_TIMEFRAMES:
        df_tf = data_loader.resample_ohlcv(df_1h, freq=freq)
        if len(df_tf) < 60:                       # pas assez d'historique sur ce TF
            continue
        feats = _tf_features(df_tf).dropna(how="all").copy()
        # disponibilité = clôture de la bougie = open + durée du TF
        feats.index = feats.index + pd.Timedelta(dur)
        feats = feats.add_prefix(f"{freq}_")

        # merge_asof backward : au 1H t, dernière bougie TF clôturée (index ≤ t)
        merged = pd.merge_asof(
            anchor,
            feats.reset_index().rename(columns={feats.index.name or "index": "_t"}).sort_values("_t"),
            on="_t", direction="backward",
        ).set_index("_t")
        merged.index.name = df_1h.index.name
        aligned.append(merged.reindex(df_1h.index))

    out = pd.concat(aligned, axis=1)
    # certaines features de structure/session n'ont pas de sens sur un TF supérieur (ex :
    # distances de session sur bougie Daily) → colonnes entièrement NaN : on les retire.
    all_nan = out.columns[out.isna().all()]
    return out.drop(columns=all_nan)
