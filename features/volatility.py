"""
features/volatility.py
======================
Features de volatilité / dispersion. Toutes causales (center=False).

- Z-Score prix : (Close - EMA(20)) / rolling_std(Close, 20).
- ATR normalisé : ATR(14) / Close * 100.
- Parkinson : sqrt( (1/(4 ln2)) * mean( ln(H/L)^2 ) ) glissant.
- Garman-Klass : 0.5*ln(H/L)^2 - (2 ln2 - 1)*ln(C/O)^2, moyenné glissant → sqrt.
- Ratio de volatilité : std(returns, 5) / std(returns, 30).
- Bollinger %B : (Close - Lower) / (Upper - Lower), bandes = EMA(20) ± 2*std(20).

L'ATR est aussi exposé en unité de PRIX (atr_abs) car le labeling triple-barrier en a besoin.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config

_LN2 = np.log(2.0)


def atr(df: pd.DataFrame, period: int = config.ATR_PERIOD) -> pd.Series:
    """
    Average True Range de Wilder (unité de PRIX), causal.
    TR = max(H-L, |H-C_{t-1}|, |L-C_{t-1}|).
    """
    h, l, c = df[config.COL_HIGH], df[config.COL_LOW], df[config.COL_CLOSE]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule toutes les features de volatilité. df OHLCV → DataFrame de features."""
    o, h, l, c = (df[config.COL_OPEN], df[config.COL_HIGH],
                  df[config.COL_LOW], df[config.COL_CLOSE])
    out = pd.DataFrame(index=df.index)

    # Z-Score prix
    w = config.ZSCORE_PRICE_WINDOW
    ema = c.ewm(span=w, adjust=False, min_periods=w).mean()
    std = c.rolling(w, min_periods=w).std(ddof=0)
    out[f"price_zscore_{w}"] = (c - ema) / std.replace(0.0, np.nan)

    # ATR (exposé en absolu pour le labeling + version normalisée en feature)
    a = atr(df, config.ATR_PERIOD)
    out[f"atr_{config.ATR_PERIOD}_abs"] = a
    out[f"atr_{config.ATR_PERIOD}_norm"] = a / c * 100.0

    # Parkinson (volatilité high-low)
    ln_hl_sq = np.log(h / l) ** 2
    wp = config.PARKINSON_WINDOW
    out[f"parkinson_{wp}"] = np.sqrt(
        (1.0 / (4.0 * _LN2)) * ln_hl_sq.rolling(wp, min_periods=wp).mean()
    )

    # Garman-Klass (formule complète high-low + close-open)
    wg = config.GARMAN_KLASS_WINDOW
    gk_term = 0.5 * np.log(h / l) ** 2 - (2.0 * _LN2 - 1.0) * np.log(c / o) ** 2
    out[f"garman_klass_{wg}"] = np.sqrt(gk_term.rolling(wg, min_periods=wg).mean().clip(lower=0.0))

    # Ratio de volatilité (returns courts / returns longs)
    r = np.log(c / c.shift(1))
    std_fast = r.rolling(config.VOL_RATIO_FAST, min_periods=config.VOL_RATIO_FAST).std(ddof=0)
    std_slow = r.rolling(config.VOL_RATIO_SLOW, min_periods=config.VOL_RATIO_SLOW).std(ddof=0)
    out[f"vol_ratio_{config.VOL_RATIO_FAST}_{config.VOL_RATIO_SLOW}"] = (
        std_fast / std_slow.replace(0.0, np.nan)
    )

    # Bollinger %B
    wb = config.BOLLINGER_WINDOW
    mid = c.ewm(span=wb, adjust=False, min_periods=wb).mean()
    sd = c.rolling(wb, min_periods=wb).std(ddof=0)
    upper = mid + config.BOLLINGER_K * sd
    lower = mid - config.BOLLINGER_K * sd
    width = (upper - lower).replace(0.0, np.nan)
    out[f"bollinger_pctb_{wb}"] = (c - lower) / width

    return out
