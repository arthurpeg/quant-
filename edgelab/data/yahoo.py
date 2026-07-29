"""Yahoo (yfinance) provider with a local parquet cache.

Handy for research / longer history, but note the wiki caveat: Yahoo *indices*
carry cash-session hours only, and FX volume is 0. Prefer MT5 for anything that
must match the feed we trade. Symbols are mapped to Yahoo tickers via ``TICKER_MAP``.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from edgelab.data.base import DataProvider

logger = logging.getLogger("edgelab.data.yahoo")

# Map our internal symbols to Yahoo tickers (extend as needed).
TICKER_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "US30": "^DJI",
    "NAS100": "^NDX",
    "SpotCrude": "CL=F",
    "NatGas": "NG=F",
}

_TF_MAP = {"D1": "1d", "H1": "1h", "H4": "1h"}  # Yahoo has no native H4


class YahooProvider(DataProvider):
    name = "yahoo"

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        return self.cache_dir / f"{symbol}_{timeframe}.parquet"

    def get_bars(self, symbol, timeframe, start=None, end=None) -> pd.DataFrame:
        cache = self._cache_path(symbol, timeframe)
        if cache.exists():
            df = pd.read_parquet(cache)
        else:
            df = self._download(symbol, timeframe)
            df.to_parquet(cache)
        return self._normalise(df, start, end)

    def _download(self, symbol: str, timeframe: str) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("yfinance not installed; `pip install yfinance`") from exc

        ticker = TICKER_MAP.get(symbol, symbol)
        interval = _TF_MAP.get(timeframe, "1d")
        logger.info("Downloading %s (%s) @ %s from Yahoo", symbol, ticker, interval)
        raw = yf.download(ticker, interval=interval, auto_adjust=False, progress=False)
        if raw is None or raw.empty:
            raise ValueError(f"Yahoo returned no data for {ticker}")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.rename(columns=str.lower).reset_index()
        return raw

    def available_symbols(self, timeframe: str) -> list[str]:
        return sorted(TICKER_MAP.keys())
