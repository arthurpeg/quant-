"""
features/momentum.py
====================
Features de momentum / tendance. Toutes causales (center=False, aucune donnée future).

- Log-returns multi-horizons : ln(P_t / P_{t-n}), n ∈ config.LOGRET_HORIZONS.
- Rendement cumulé glissant sur X bougies.
- Pente de régression linéaire des closes sur fenêtres (polyfit vectorisé).
- RSI décentré : RSI(14) - 50.
- ROC : (P_t/P_{t-X} - 1) * 100.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    """
    Pente de la régression linéaire des `window` dernières valeurs (abscisse 0..window-1).
    Vectorisé : slope = cov(x, y) / var(x), avec x fixe → dénominateur constant.
    center=False implicite (rolling causal).
    """
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    denom = np.sum((x - x_mean) ** 2)  # var(x)*window, constant

    def _slope(y: np.ndarray) -> float:
        y_mean = y.mean()
        return float(np.dot(x - x_mean, y - y_mean) / denom)

    return series.rolling(window, min_periods=window).apply(_slope, raw=True)


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule toutes les features de momentum. df OHLCV en entrée → DataFrame de features."""
    close = df[config.COL_CLOSE]
    out = pd.DataFrame(index=df.index)

    # Log-returns multi-horizons
    log_close = np.log(close)
    for n in config.LOGRET_HORIZONS:
        out[f"logret_{n}"] = log_close - log_close.shift(n)

    # Rendement cumulé glissant (somme des log-returns 1 pas sur X bougies)
    r1 = log_close.diff()
    w = config.CUM_RETURN_WINDOW
    out[f"cumret_{w}"] = r1.rolling(w, min_periods=w).sum()

    # Pentes de régression linéaire
    for w in config.SLOPE_WINDOWS:
        out[f"slope_{w}"] = _rolling_slope(close, w)

    # RSI décentré
    out[f"rsi_{config.RSI_PERIOD}_centered"] = _rsi(close, config.RSI_PERIOD) - 50.0

    # ROC
    x = config.ROC_PERIOD
    out[f"roc_{x}"] = (close / close.shift(x) - 1.0) * 100.0

    return out


def _rsi(close: pd.Series, period: int) -> pd.Series:
    """
    RSI de Wilder (lissage EMA type Wilder via ewm alpha=1/period, adjust=False, causal).
    Renvoie une valeur dans [0, 100].
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # loss == 0 → RSI = 100 (que du gain)
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    return rsi
