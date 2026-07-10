"""
features/volume.py
==================
Features de volume. Toutes causales (center=False).

⚠️ FOREX / CFD : le "volume" fourni par le broker est le plus souvent du TICK VOLUME
   (nombre de ticks), PAS un vrai volume échangé. Interprétation à prendre avec prudence.
   → TOUTE cette section est désactivable via config.VOLUME_FEATURES_ENABLED (ou selon
     SymbolSpec.tick_volume). Si désactivée, compute() renvoie un DataFrame vide.

- Volume Z-Score : (Vol - SMA(Vol,20)) / rolling_std(Vol,20).
- Distance VWAP : (Close - VWAP)/VWAP*100, VWAP cumulée INTRA-SESSION avec RESET quotidien
  (roll DAILY_RESET_UTC) → jamais cumulée sur toute la série (sinon leakage/dérive).
- OBV normalisé (OBV / MA(OBV)).
- Chaikin Money Flow (CMF) sur CMF_PERIOD.
- Money Flow Index (MFI) sur MFI_PERIOD.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config
import calendar_utils as cal


def compute(df: pd.DataFrame, enabled: bool | None = None) -> pd.DataFrame:
    """
    Calcule les features de volume. df OHLCV → DataFrame de features.
    `enabled` prime sur config.VOLUME_FEATURES_ENABLED si fourni (ex : symbole sans volume).
    """
    use = config.VOLUME_FEATURES_ENABLED if enabled is None else enabled
    out = pd.DataFrame(index=df.index)
    if not use:
        return out  # section entièrement désactivée

    h, l, c, v = (df[config.COL_HIGH], df[config.COL_LOW],
                  df[config.COL_CLOSE], df[config.COL_VOLUME])

    # Volume Z-Score
    w = config.VOLUME_ZSCORE_WINDOW
    sma = v.rolling(w, min_periods=w).mean()
    std = v.rolling(w, min_periods=w).std(ddof=0)
    out[f"vol_zscore_{w}"] = (v - sma) / std.replace(0.0, np.nan)

    # Distance VWAP (RESET par journée de marché → intra-session)
    day = pd.Series(cal.market_day(df.index), index=df.index)
    typical = (h + l + c) / 3.0
    pv = typical * v
    cum_pv = pv.groupby(day).cumsum()
    cum_v = v.groupby(day).cumsum().replace(0.0, np.nan)
    vwap = cum_pv / cum_v
    out["vwap_dist_pct"] = (c - vwap) / vwap * 100.0

    # OBV normalisé
    direction = np.sign(c.diff()).fillna(0.0)
    obv = (direction * v).cumsum()
    obv_ma = obv.rolling(config.OBV_MA_WINDOW, min_periods=config.OBV_MA_WINDOW).mean()
    obv_std = obv.rolling(config.OBV_MA_WINDOW, min_periods=config.OBV_MA_WINDOW).std(ddof=0)
    out[f"obv_zscore_{config.OBV_MA_WINDOW}"] = (obv - obv_ma) / obv_std.replace(0.0, np.nan)

    # Chaikin Money Flow (CMF)
    hl = (h - l).replace(0.0, np.nan)
    mf_mult = ((c - l) - (h - c)) / hl        # multiplicateur du money flow
    mf_vol = (mf_mult * v).fillna(0.0)
    p = config.CMF_PERIOD
    out[f"cmf_{p}"] = (
        mf_vol.rolling(p, min_periods=p).sum()
        / v.rolling(p, min_periods=p).sum().replace(0.0, np.nan)
    )

    # Money Flow Index (MFI)
    out[f"mfi_{config.MFI_PERIOD}"] = _mfi(typical, v, config.MFI_PERIOD)

    return out


def _mfi(typical: pd.Series, volume: pd.Series, period: int) -> pd.Series:
    """Money Flow Index (RSI pondéré par le volume), causal, dans [0, 100]."""
    raw_mf = typical * volume
    delta = typical.diff()
    pos_mf = raw_mf.where(delta > 0, 0.0)
    neg_mf = raw_mf.where(delta < 0, 0.0)
    pos_sum = pos_mf.rolling(period, min_periods=period).sum()
    neg_sum = neg_mf.rolling(period, min_periods=period).sum()
    mfr = pos_sum / neg_sum.replace(0.0, np.nan)
    mfi = 100.0 - 100.0 / (1.0 + mfr)
    return mfi.where(neg_sum != 0.0, 100.0)
