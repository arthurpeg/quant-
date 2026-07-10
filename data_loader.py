"""
data_loader.py
==============
ÉTAPE 1 du pipeline : chargement + nettoyage + resampling 1H.

Ordre STRICT et déterministe (pas de dépendance à l'ordre des lignes en entrée) :
  1. Valider le symbole (whitelist).
  2. Supprimer les doublons de timestamp (garder la 1ère occurrence).
  3. Tri chronologique + vérification de monotonie.
  4. (Optionnel) resampler vers le TIMEFRAME cible (OHLCV).
  5. Réindexer sur la GRILLE DE MARCHÉ (calendar_utils) + ffill intra-séance UNIQUEMENT.
     → jamais de comblement à travers week-ends / fériés / maintenance.
  6. Filtre spikes/outliers (prix ≤ 0, volume < 0, cohérence OHLC, |logret| > k*std hors gaps).
  7. Log du nombre de lignes supprimées/modifiées à chaque étape.

Le nettoyage renvoie un DataFrame OHLCV réindexé sur la grille de marché : deux lignes
consécutives = deux bougies de marché consécutives (les trous week-end n'existent pas).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

import config
import calendar_utils as cal

logger = logging.getLogger("data_loader")


def _log(step: str, msg: str) -> None:
    logger.info("[clean:%s] %s", step, msg)


def _ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("L'index doit être un DatetimeIndex.")
    if df.index.tz is None:
        raise ValueError("L'index doit être tz-aware (UTC attendu).")
    return df.tz_convert("UTC") if str(df.index.tz) != "UTC" else df


def resample_ohlcv(df: pd.DataFrame, freq: str = config.PANDAS_FREQ) -> pd.DataFrame:
    """
    Resample des données brutes vers le TIMEFRAME cible en respectant l'ancrage broker.
    Produit un OHLCV correct (open=first, high=max, low=min, close=last, volume=sum).
    Les bins vides deviennent NaN (nettoyés/filtrés ensuite par la grille de marché).
    """
    agg = {
        config.COL_OPEN: "first",
        config.COL_HIGH: "max",
        config.COL_LOW: "min",
        config.COL_CLOSE: "last",
        config.COL_VOLUME: "sum",
    }
    out = df.resample(freq, origin=config.RESAMPLE_ORIGIN, label="left", closed="left").agg(agg)
    return out.dropna(subset=[config.COL_OPEN])  # supprime les bins sans aucune donnée


def clean(
    df: pd.DataFrame,
    symbol: str,
    do_resample: bool = True,
    reindex_grid: bool = True,
) -> pd.DataFrame:
    """
    Nettoie et normalise un DataFrame OHLCV brut pour le symbole donné.

    Parameters
    ----------
    df : DataFrame OHLCV, index datetime UTC (colonnes config.OHLCV_COLS).
    symbol : symbole propfirm (validé contre la whitelist).
    do_resample : si True, resample vers config.PANDAS_FREQ avant réindexation.
    reindex_grid : si True, réindexe sur la grille de marché forex 24/5 (adapté aux données
        Yahoo/brutes à trous). Mettre False pour des bougies NATIVES de broker (MT5) déjà
        propres : on leur fait confiance (pas de grille 1H forcée), ce qui permet aussi des
        bases 4H/Daily sans lutter contre le calendrier intraday.

    Returns
    -------
    DataFrame OHLCV nettoyé, trié, sans doublon, filtré.
    """
    spec = config.validate_symbol(symbol)          # 1. validation whitelist
    _log("validate", f"{symbol} OK (classe={spec.asset_class}, tick_volume={spec.tick_volume})")

    df = _ensure_utc_index(df.copy())
    missing = [c for c in config.OHLCV_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes : {missing}")
    df = df[list(config.OHLCV_COLS)]

    n0 = len(df)

    # 2. doublons de timestamp (garder la 1ère)
    dup = df.index.duplicated(keep="first")
    if dup.any():
        df = df[~dup]
        _log("dedup", f"{int(dup.sum())} doublon(s) de timestamp supprimé(s)")

    # 3. tri chronologique strict + monotonie
    if not df.index.is_monotonic_increasing:
        df = df.sort_index(kind="mergesort")   # stable → déterministe
        _log("sort", "index trié (n'était pas monotone croissant)")
    assert df.index.is_monotonic_increasing, "index non monotone après tri"

    # 4. resampling optionnel vers le TIMEFRAME cible
    if do_resample:
        before = len(df)
        df = resample_ohlcv(df)
        _log("resample", f"{before} → {len(df)} lignes après resample {config.TIMEFRAME}")

    if len(df) == 0:
        raise ValueError("DataFrame vide après nettoyage initial.")

    # 5. réindexation sur la grille de marché + ffill intra-séance (données brutes/Yahoo).
    #    Sautée pour des bougies natives de broker (MT5), déjà propres et sur le vrai calendrier.
    if not reindex_grid:
        df = _filter_outliers(df)
        _log("done", f"{n0} → {len(df)} lignes finales (grille native conservée)")
        return df

    grid = cal.market_grid(df.index[0], df.index[-1])
    off_grid = int((~df.index.isin(grid)).sum())   # bougies hors séance présentes en entrée
    if off_grid:
        _log("grid", f"{off_grid} bougie(s) hors séance (week-end/férié) retirée(s)")

    df = df.reindex(grid)
    created = int(df[config.COL_CLOSE].isna().sum())  # trous intra-séance à combler

    if config.FFILL_INTRASESSION and created:
        # ffill OHLC UNIQUEMENT (micro-coupures intra-séance). La grille ne contient pas de
        # week-end → aucun risque de ffill à travers les trous légitimes.
        price_cols = [config.COL_OPEN, config.COL_HIGH, config.COL_LOW, config.COL_CLOSE]
        df[price_cols] = df[price_cols].ffill()
        _log("ffill", f"{created} micro-coupure(s) intra-séance ffill (OHLC)")

    # volume manquant → 0 (jamais ffill)
    vol_na = int(df[config.COL_VOLUME].isna().sum())
    if vol_na:
        df[config.COL_VOLUME] = df[config.COL_VOLUME].fillna(config.VOLUME_FILL_VALUE)
        _log("volume_fill", f"{vol_na} volume(s) manquant(s) → {config.VOLUME_FILL_VALUE}")

    # d'éventuelles lignes tout en tête restées NaN (avant la 1ère vraie donnée) → drop
    lead_na = int(df[config.COL_CLOSE].isna().sum())
    if lead_na:
        df = df.dropna(subset=[config.COL_CLOSE])
        _log("lead_drop", f"{lead_na} ligne(s) NaN de tête supprimée(s)")

    # 6. filtre spikes / outliers / cohérence OHLC
    df = _filter_outliers(df)

    _log("done", f"{n0} → {len(df)} lignes finales")
    return df


def _filter_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filtre :
      - prix ≤ 0 ou volume < 0 → ligne supprimée.
      - cohérence OHLC : High ≥ max(O,C), Low ≤ min(O,C) → réparé (clip) + log.
      - |log-return| > k*std → suppression, en EXCLUANT les gaps de week-end du calcul.
    """
    o, h, l, c, v = (config.COL_OPEN, config.COL_HIGH, config.COL_LOW,
                     config.COL_CLOSE, config.COL_VOLUME)

    # prix ≤ 0 / volume négatif
    bad = (df[[o, h, l, c]] <= 0).any(axis=1) | (df[v] < 0)
    if bad.any():
        df = df[~bad]
        _log("price_sign", f"{int(bad.sum())} ligne(s) prix≤0/volume<0 supprimée(s)")

    # cohérence OHLC : réparer plutôt que jeter (borne High/Low par O,C)
    hi_fix = np.maximum.reduce([df[h].to_numpy(), df[o].to_numpy(), df[c].to_numpy()])
    lo_fix = np.minimum.reduce([df[l].to_numpy(), df[o].to_numpy(), df[c].to_numpy()])
    n_hi = int((df[h].to_numpy() < np.maximum(df[o], df[c])).sum())
    n_lo = int((df[l].to_numpy() > np.minimum(df[o], df[c])).sum())
    if n_hi or n_lo:
        df[h] = hi_fix
        df[l] = lo_fix
        _log("ohlc_coherence", f"High réparé×{n_hi}, Low réparé×{n_lo}")

    # |log-return| > k*std, en excluant les gaps de week-end (frontières de séance)
    logret = np.log(df[c] / df[c].shift(1))
    is_gap = _weekend_gap_mask(df.index)               # True = 1re bougie après un trou
    ref = logret[~is_gap]                               # std hors gaps légitimes
    std = ref.std(ddof=0)
    if std and np.isfinite(std):
        spike = (logret.abs() > config.OUTLIER_LOGRET_STD * std) & (~is_gap)
        if spike.any():
            df = df[~spike.to_numpy()]
            _log("spike", f"{int(spike.sum())} spike(s) |logret|>{config.OUTLIER_LOGRET_STD}σ supprimé(s)")

    return df


def _weekend_gap_mask(index: pd.DatetimeIndex) -> pd.Series:
    """
    True pour une bougie qui suit un TROU de grille (week-end/férié/maintenance) : l'écart
    avec la bougie précédente dépasse le pas nominal du TIMEFRAME. Ces sauts sont légitimes
    et doivent être exclus du filtre spikes.
    """
    step = pd.Timedelta(config.PANDAS_FREQ)
    delta = index.to_series().diff()
    return (delta > step).fillna(True)   # 1re bougie de la série considérée "post-trou"
