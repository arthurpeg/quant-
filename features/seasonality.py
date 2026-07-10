"""
features/seasonality.py
=======================
Features de SAISONNALITÉ / CALENDRIER — encodage cyclique riche + saisonnalité empirique
de la volatilité par heure de la journée.

⚠️ Ce qui N'EST PAS ici : le calendrier de news économiques daté (NFP, CPI, FOMC). L'API
   Python de MT5 ne l'expose pas et aucune source fiable hors-ligne n'est disponible ici.
   Prétendre le modéliser serait malhonnête → volontairement omis (voir docs du projet).

Anti-leakage : la saisonnalité empirique de volatilité est calculée en EXPANDING puis
DÉCALÉE d'une barre (shift(1)) par groupe horaire → à t, on n'utilise que les occurrences
passées de la même heure. Le reste est purement déterministe à partir de l'index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Features calendaires + saisonnalité de volatilité. df OHLCV → DataFrame de features."""
    idx = df.index.tz_convert("UTC")
    out = pd.DataFrame(index=df.index)

    # --- encodages cycliques ---
    month = idx.month.to_numpy().astype(float)
    out["month_sin"] = np.sin(2 * np.pi * (month - 1) / 12)
    out["month_cos"] = np.cos(2 * np.pi * (month - 1) / 12)

    dom = idx.day.to_numpy().astype(float)
    out["dom_sin"] = np.sin(2 * np.pi * (dom - 1) / 31)
    out["dom_cos"] = np.cos(2 * np.pi * (dom - 1) / 31)

    # heure de la SEMAINE (0..119 sur 5 jours ouvrés) : capture les effets de session ET de jour
    dow = np.clip(idx.dayofweek.to_numpy(), 0, 4).astype(float)
    hour = idx.hour.to_numpy().astype(float)
    how = dow * 24.0 + hour
    out["how_sin"] = np.sin(2 * np.pi * how / 120.0)
    out["how_cos"] = np.cos(2 * np.pi * how / 120.0)

    # marqueurs de fin de période (rebalancements, fixings)
    out["is_month_end"] = (idx.day >= 28).astype(np.int8)
    out["is_quarter_end"] = ((idx.month % 3 == 0) & (idx.day >= 28)).astype(np.int8)

    # --- saisonnalité EMPIRIQUE de la volatilité par heure de la journée (causale) ---
    ret = np.log(df[config.COL_CLOSE] / df[config.COL_CLOSE].shift(1))
    absret = ret.abs()
    hour_key = pd.Series(idx.hour, index=df.index)
    # moyenne expanding par heure, décalée : n'utilise que les occurrences PASSÉES de cette heure
    out["hour_vol_seasonal"] = (
        absret.groupby(hour_key).transform(lambda s: s.shift(1).expanding(min_periods=5).mean())
    )
    # volatilité actuelle relative à sa saisonnalité horaire (>1 = heure anormalement agitée)
    out["vol_vs_hour_seasonal"] = absret / out["hour_vol_seasonal"].replace(0.0, np.nan)

    return out
