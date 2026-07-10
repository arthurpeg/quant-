"""
macro_loader.py
===============
Séries MACRO / CROSS-ASSET depuis MT5, pour alimenter des features d'une nature DIFFÉRENTE
du prix de l'actif tradé (la seule voie qui reste après l'échec des features techniques).

  - DXY SYNTHÉTIQUE : le symbole broker USDX ne remonte qu'à 2024. On reconstruit l'indice
    dollar avec la formule officielle ICE à partir des 6 paires (toutes disponibles 2018+) :
      DXY = 50.14348112 · EURUSD^-0.576 · USDJPY^0.136 · GBPUSD^-0.119
                        · USDCAD^0.091  · USDSEK^0.042 · USDCHF^0.036
  - VIXY : ETF sur futures VIX → proxy du risque/volatilité implicite (2018+).
  - UST  : proxy taux / obligations US (2018+).

⚠️ VIXY et UST ne cotent qu'aux heures cash US : leurs barres manquent la nuit/le week-end.
   L'alignement se fait par merge_asof "backward" → on ne récupère que la dernière valeur
   RÉELLEMENT connue (causal, aucune fuite).
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
os.makedirs(CACHE, exist_ok=True)

DXY_BASKET = {          # paire → exposant ICE (signe inclus)
    "EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119,
    "USDCAD": 0.091, "USDSEK": 0.042, "USDCHF": 0.036,
}
DXY_CONST = 50.14348112
MACRO_SYMBOLS = ["VIXY", "UST"]      # proxies risque & taux
TF_MAP = {"H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}
START = datetime(2018, 1, 1, tzinfo=timezone.utc)


def _fetch_raw(symbol: str, tf: str) -> pd.DataFrame:
    """Barres brutes MT5 (avec cache CSV) pour un symbole quelconque, index UTC."""
    path = os.path.join(CACHE, f"macro_{symbol}_{tf}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init: {mt5.last_error()}")
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_range(symbol, getattr(mt5, TF_MAP[tf]), START,
                                 datetime.now(timezone.utc))
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"Pas de données MT5 pour {symbol} {tf}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.to_csv(path)
    return df


def build_dxy(tf: str) -> pd.Series:
    """Reconstruit l'indice dollar (formule ICE) à partir des 6 paires du panier."""
    closes = {}
    for pair in DXY_BASKET:
        closes[pair] = _fetch_raw(pair, tf)["close"]
    df = pd.DataFrame(closes).dropna()
    dxy = DXY_CONST * np.prod([df[p] ** w for p, w in DXY_BASKET.items()], axis=0)
    return pd.Series(dxy, index=df.index, name="dxy")


def load_macro(tf: str) -> pd.DataFrame:
    """
    DataFrame des séries macro (close) au timeframe `tf`, index UTC :
    colonnes = dxy, vixy, ust. Index = union des barres disponibles (trous conservés).
    """
    out = {"dxy": build_dxy(tf)}
    for sym in MACRO_SYMBOLS:
        try:
            out[sym.lower()] = _fetch_raw(sym, tf)["close"]
        except Exception as e:                      # symbole absent chez le broker
            print(f"[macro] {sym} indisponible ({e}) — ignoré")
    return pd.DataFrame(out).sort_index()


if __name__ == "__main__":
    for tf in ("H4",):
        m = load_macro(tf)
        print(f"{tf}: {m.shape}  [{m.index[0].date()} -> {m.index[-1].date()}]")
        print(m.notna().sum().to_string())
        print(m.tail(3).to_string())
