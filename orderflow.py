"""
orderflow.py
============
Piste "order flow" — et ses LIMITES DURES, mesurées et documentées.

Constat empirique (MT5, CFD FX) : les ticks retournés sont des ticks de COTATION
(bid/ask). Les champs `last` et `volume` sont à ZÉRO sur 100% des ticks → il n'existe
ni prix de transaction ni volume de transaction.

Conséquences :
  ✗ Order Flow Imbalance réel (volume acheteur − vendeur)      : IMPOSSIBLE
  ✗ Classification Lee-Ready / tick rule sur transactions       : IMPOSSIBLE
  ✗ Carnet d'ordres (L2/DOM) historique                         : IMPOSSIBLE (MT5 : DOM live only)
  ✓ Microstructure de COTATION (ce module)                      : possible

Ce module extrait donc ce qui est réellement disponible, sans le maquiller en "order flow" :
  - intensité de cotation (nb de ticks/barre) = proxy d'activité
  - spread bid-ask moyen / max
  - volatilité réalisée haute fréquence (à partir des mids)
  - déséquilibre des upticks/downticks du MID (proxy de pression, PAS de l'order flow)

Ces agrégats décrivent la barre t elle-même : ils sont connus à sa clôture → causals,
au même titre que l'OHLC de la barre.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
os.makedirs(CACHE, exist_ok=True)


def _aggregate_chunk(ticks: np.ndarray, freq: str) -> pd.DataFrame:
    """Agrège un lot de ticks bid/ask en features de microstructure par barre."""
    df = pd.DataFrame(ticks)[["time_msc", "bid", "ask"]]
    df["t"] = pd.to_datetime(df["time_msc"], unit="ms", utc=True)
    df = df[(df["bid"] > 0) & (df["ask"] > 0)]
    df["mid"] = (df["bid"] + df["ask"]) / 2.0
    df["spread"] = df["ask"] - df["bid"]
    df["dmid"] = df["mid"].diff()
    df["up"] = (df["dmid"] > 0).astype(np.int8)
    df["dn"] = (df["dmid"] < 0).astype(np.int8)
    df["lr2"] = np.log(df["mid"] / df["mid"].shift(1)) ** 2

    g = df.groupby(pd.Grouper(key="t", freq=freq))
    out = pd.DataFrame({
        "tick_count": g.size(),
        "spread_mean": g["spread"].mean(),
        "spread_max": g["spread"].max(),
        "hf_realized_vol": np.sqrt(g["lr2"].sum()),
        "up_ticks": g["up"].sum(),
        "dn_ticks": g["dn"].sum(),
    })
    tot = (out["up_ticks"] + out["dn_ticks"]).replace(0, np.nan)
    out["tick_imbalance"] = (out["up_ticks"] - out["dn_ticks"]) / tot
    return out.drop(columns=["up_ticks", "dn_ticks"])


def build(symbol: str, months: int = 12, freq: str = "1h", force: bool = False) -> pd.DataFrame:
    """Features de microstructure par barre, sur les `months` derniers mois. Cache CSV."""
    path = os.path.join(CACHE, f"flow_{symbol}_{freq}_{months}m.csv")
    if os.path.exists(path) and not force:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 init: {mt5.last_error()}")
    mt5.symbol_select(symbol, True)

    end = datetime.now(timezone.utc)
    parts = []
    for k in range(months):
        t1 = end - timedelta(days=30 * k)
        t0 = t1 - timedelta(days=30)
        ticks = mt5.copy_ticks_range(symbol, t0, t1, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            continue
        parts.append(_aggregate_chunk(ticks, freq))
        del ticks
    mt5.shutdown()

    if not parts:
        raise RuntimeError(f"Aucun tick pour {symbol}")
    out = pd.concat(parts).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    out = out[out["tick_count"] > 0]
    out.to_csv(path)
    return out


if __name__ == "__main__":
    for sym in ("EURUSD", "XAUUSD"):
        f = build(sym, months=12, freq="1h")
        print(f"{sym}: {f.shape} barres  [{f.index[0].date()} -> {f.index[-1].date()}]")
        print(f.describe().loc[["mean", "std"]].round(6).to_string())
