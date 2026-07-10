"""
mt5_loader.py
=============
Chargement de données RÉELLES depuis MetaTrader 5 (terminal broker local). Nettement
supérieur à Yahoo : vrai tick-volume, spreads réels, high/low fiables, historique profond
(>10 ans), symboles prop-firm natifs (24/5 y compris indices CFD).

Met en cache CSV (data_cache_mt5/) + un spreads.json (spread réel en prix par symbole, pour
modéliser le coût de transaction de façon honnête plutôt qu'un forfait en R).

⚠️ Le champ 'time' de MT5 est en heure SERVEUR du broker (souvent UTC+2/+3). On le traite en
   UTC (approximation) : sur des bases 4H/Daily, le léger décalage n'affecte pas les résultats.
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

CACHE = os.path.join(os.path.dirname(__file__), "data_cache_mt5")
os.makedirs(CACHE, exist_ok=True)
SPREADS_PATH = os.path.join(CACHE, "spreads.json")

# symbole logique → nom broker (résolu via l'exploration MT5)
SYMBOL_MAP = {
    "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY",
    "XAUUSD": "XAUUSD", "US30": "US30",
}

# timeframe logique → (constante MT5, freq pandas, date de début du pull)
def _tf_defs():
    import MetaTrader5 as mt5
    return {
        "H1": (mt5.TIMEFRAME_H1, "1h", datetime(2019, 1, 1, tzinfo=timezone.utc)),
        "H4": (mt5.TIMEFRAME_H4, "4h", datetime(2016, 1, 1, tzinfo=timezone.utc)),
        "D1": (mt5.TIMEFRAME_D1, "1D", datetime(2012, 1, 1, tzinfo=timezone.utc)),
    }


def _ensure_init():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() a échoué : {mt5.last_error()}")
    return mt5


def fetch(symbol: str, tf: str, force: bool = False) -> pd.DataFrame:
    """OHLCV réel pour (symbole, timeframe) depuis MT5, avec cache CSV. Index UTC."""
    path = os.path.join(CACHE, f"{symbol}_{tf}.csv")
    if os.path.exists(path) and not force:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    mt5 = _ensure_init()
    tf_const, _, start = _tf_defs()[tf]
    broker = SYMBOL_MAP[symbol]
    mt5.symbol_select(broker, True)
    rates = mt5.copy_rates_range(broker, tf_const, start, datetime.now(timezone.utc))
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"Pas de données MT5 pour {broker} {tf} : {mt5.last_error()}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df = df.rename(columns={"tick_volume": "volume"})[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="first")].sort_index()

    # capture du spread réel (en prix) pour le modèle de coût
    si = mt5.symbol_info(broker)
    spread_price = float(si.spread * si.point) if si else np.nan
    _save_spread(symbol, spread_price)

    df.to_csv(path)
    return df


def _save_spread(symbol: str, spread_price: float) -> None:
    data = {}
    if os.path.exists(SPREADS_PATH):
        data = json.load(open(SPREADS_PATH))
    data[symbol] = spread_price
    json.dump(data, open(SPREADS_PATH, "w"), indent=1)


def get_spread(symbol: str) -> float:
    """Spread réel (en prix) du symbole, depuis le cache."""
    if os.path.exists(SPREADS_PATH):
        return json.load(open(SPREADS_PATH)).get(symbol, np.nan)
    return np.nan


if __name__ == "__main__":
    for sym in SYMBOL_MAP:
        for tf in ("H1", "H4", "D1"):
            df = fetch(sym, tf)
            print(f"{sym:7s} {tf}: {len(df):6d} barres  [{df.index[0].date()} -> {df.index[-1].date()}]  "
                  f"vol_sum={df['volume'].sum():.0f}  spread={get_spread(sym)}")
