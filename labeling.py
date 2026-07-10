"""
labeling.py
===========
Labeling par la méthode TRIPLE BARRIER (López de Prado).

Pour chaque bougie t (événement d'entrée au close_t), on pose trois barrières :
  - haute (TP) : entry + side * (TP_R_MULTIPLE * R)
  - basse (SL) : entry - side * (SL_R_MULTIPLE * R)   (SL fixé à 1R)
  - temporelle : timeout après TIMEOUT_BARS bougies DE MARCHÉ.

R (unité de prix) = R_ATR_MULT * ATR(ATR_PERIOD) évalué à t → distance basée volatilité.

⚠️ Le timeout est compté en BOUGIES DE MARCHÉ. Comme le DataFrame est réindexé sur la
grille de marché (data_loader) — sans bougies de week-end — "N bougies de marché" = un
simple décalage de N lignes. Aucun risque de consommer des bougies inexistantes.

Le label est la PREMIÈRE barrière touchée :
  - "tp"      → cible atteinte avant le SL           (classe 1)
  - "sl"      → SL touché avant la cible             (classe 0)
  - "timeout" → aucune barrière prix avant N bougies (classe 2)

Si une même bougie touche TP et SL, on applique config.AMBIGUOUS_BAR_POLICY (défaut : "sl",
conservateur). Les événements en fin de série qui n'ont pas N bougies de futur ET ne
touchent aucune barrière sont RIGHT-CENSORED → label NaN (à exclure de l'entraînement).

Ces labels décrivent le FUTUR : ils constituent y, jamais X (séparation stricte).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
from features.volatility import atr


def triple_barrier(
    df: pd.DataFrame,
    tp_mult: float = config.TP_R_MULTIPLE,
    sl_mult: float = config.SL_R_MULTIPLE,
    timeout: int = config.TIMEOUT_BARS,
    side: int = config.TRADE_SIDE,
    r_unit: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Applique le triple barrier. Renvoie un DataFrame indexé comme df avec les colonnes :
      - label_str  : {"tp","sl","timeout"} ou NaN (censuré)
      - label      : entier (config.LABEL_MAP) ou NaN
      - barrier_bars : nb de bougies de marché avant résolution (NaN si censuré)
      - r_unit     : 1R en unité de prix utilisé à l'entrée
      - tp_price / sl_price : niveaux des barrières prix

    r_unit : distance 1R (prix) par bougie. Si None → R_ATR_MULT * ATR(ATR_PERIOD).
    """
    if timeout < 1:
        raise ValueError("timeout doit être >= 1 bougie.")

    high = df[config.COL_HIGH].to_numpy(dtype=float)
    low = df[config.COL_LOW].to_numpy(dtype=float)
    close = df[config.COL_CLOSE].to_numpy(dtype=float)
    n = len(df)

    if r_unit is None:
        r_unit = config.R_ATR_MULT * atr(df, config.ATR_PERIOD)
    R = r_unit.to_numpy(dtype=float)

    # Niveaux des barrières prix (dépend du sens du trade)
    tp_price = close + side * (tp_mult * R)
    sl_price = close - side * (sl_mult * R)

    hit = np.zeros(n, dtype=np.int8)      # 0 non résolu, +1 tp, -1 sl
    bars = np.full(n, -1, dtype=np.int64)  # nb de bougies jusqu'à résolution

    valid_R = np.isfinite(R) & (R > 0)     # besoin d'un ATR défini pour poser les barrières

    idx = np.arange(n)
    prefer_sl = config.AMBIGUOUS_BAR_POLICY == "sl"

    # Balayage sur l'horizon : N passes vectorisées (offset h = 1..timeout).
    # À chaque offset, on ne résout que les événements encore ouverts → 1re barrière gagne.
    for h in range(1, timeout + 1):
        j = idx + h
        in_range = j < n
        open_ev = (hit == 0) & valid_R & in_range
        if not open_ev.any():
            if (idx + h >= n).all():
                break
            continue

        jj = np.where(in_range, j, n - 1)  # indices bornés pour le fancy-indexing
        hj = high[jj]
        lj = low[jj]

        if side > 0:  # long : TP au-dessus, SL en dessous
            tp_touch = open_ev & (hj >= tp_price)
            sl_touch = open_ev & (lj <= sl_price)
        else:         # short : TP en dessous, SL au-dessus
            tp_touch = open_ev & (lj <= tp_price)
            sl_touch = open_ev & (hj >= sl_price)

        both = tp_touch & sl_touch
        # Désambiguïsation intra-bougie selon la politique configurée
        if prefer_sl:
            sl_first = sl_touch
            tp_first = tp_touch & ~both
        else:
            tp_first = tp_touch
            sl_first = sl_touch & ~both

        hit[tp_first] = 1
        bars[tp_first] = h
        hit[sl_first] = -1
        bars[sl_first] = h

    # Construction des labels
    label_str = np.full(n, None, dtype=object)
    barrier_bars = np.full(n, np.nan)

    tp_mask = hit == 1
    sl_mask = hit == -1
    label_str[tp_mask] = "tp"
    label_str[sl_mask] = "sl"
    barrier_bars[tp_mask | sl_mask] = bars[tp_mask | sl_mask]

    # Non résolus : timeout si l'horizon complet existe dans les données, sinon censuré (NaN)
    unresolved = (hit == 0) & valid_R
    has_full_future = (idx + timeout) < n
    timeout_mask = unresolved & has_full_future
    label_str[timeout_mask] = "timeout"
    barrier_bars[timeout_mask] = timeout
    # unresolved & ~has_full_future → reste None (right-censored)
    # ~valid_R (ATR indéfini en début de série) → reste None également

    label_int = np.array(
        [config.LABEL_MAP[s] if s in config.LABEL_MAP else np.nan for s in label_str],
        dtype=float,
    )

    # Réalisé en R (comptabilité P&L) : +tp_mult si TP, -sl_mult si SL,
    # et mark-to-market (close de sortie - entrée)/R * side si timeout.
    realized_r = np.full(n, np.nan)
    realized_r[tp_mask] = tp_mult
    realized_r[sl_mask] = -sl_mult
    if timeout_mask.any():
        exit_idx = np.clip(idx + timeout, 0, n - 1)
        mtm = (close[exit_idx] - close) * side / np.where(valid_R, R, np.nan)
        realized_r[timeout_mask] = mtm[timeout_mask]

    return pd.DataFrame(
        {
            "label_str": label_str,
            "label": label_int,
            "barrier_bars": barrier_bars,
            "realized_r": realized_r,
            "r_unit": R,
            "tp_price": np.where(valid_R, tp_price, np.nan),
            "sl_price": np.where(valid_R, sl_price, np.nan),
        },
        index=df.index,
    )
