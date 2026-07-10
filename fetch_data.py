"""
fetch_data.py
=============
Télécharge des données horaires RÉELLES (Yahoo Finance) pour les actifs prop-firm 24/5
compatibles avec le calendrier forex, et les met en cache CSV (reproductibilité + évite
le rate-limit). Les indices cash ne sont PAS inclus ici : ils ont un calendrier de session
différent (chantier V2 — profil de session "index_cash").

⚠️ Données Yahoo FX = cotations indicatives, volume absent (=0) → features volume désactivées
   en aval. C'est de la vraie donnée de marché mais de qualité "retail", pas institutionnelle.
"""
from __future__ import annotations
import os, time
import pandas as pd
import yfinance as yf

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# symbole prop-firm → ticker Yahoo (actifs réellement ~24/5)
TICKERS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F",       # or (futures COMEX, proxy CFD XAUUSD)
}
PERIOD = "730d"            # max autorisé par Yahoo en intervalle 1h
INTERVAL = "1h"


def _download(ticker: str, retries: int = 5) -> pd.DataFrame:
    last = None
    for k in range(retries):
        try:
            df = yf.download(ticker, period=PERIOD, interval=INTERVAL,
                             progress=False, auto_adjust=False, threads=False)
            if len(df):
                return df
        except Exception as e:  # noqa
            last = e
        time.sleep(4 * (k + 1))   # backoff linéaire contre le 429
    raise RuntimeError(f"Échec download {ticker}: {last}")


def fetch(symbol: str, force: bool = False) -> pd.DataFrame:
    """Renvoie l'OHLCV horaire UTC pour `symbol`, depuis le cache CSV si présent."""
    path = os.path.join(CACHE_DIR, f"{symbol}.csv")
    if os.path.exists(path) and not force:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    raw = _download(TICKERS[symbol])
    # aplatir un éventuel MultiIndex de colonnes (yfinance multi-niveaux)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    raw.index = pd.DatetimeIndex(raw.index)
    raw.index = raw.index.tz_convert("UTC") if raw.index.tz else raw.index.tz_localize("UTC")
    raw = raw[~raw.index.duplicated(keep="first")].sort_index()
    raw = raw.dropna(subset=["open", "high", "low", "close"])
    raw.to_csv(path)
    return raw


if __name__ == "__main__":
    for sym in TICKERS:
        df = fetch(sym)
        print(f"{sym:7s} rows={len(df):6d}  {df.index[0]} -> {df.index[-1]}  "
              f"vol_sum={df['volume'].sum():.0f}")
        time.sleep(2)  # petite pause anti rate-limit entre symboles
