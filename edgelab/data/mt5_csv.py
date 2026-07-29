"""MT5 cache provider — reads the ``data_cache_mt5`` CSV/parquet files.

This is the *honest* feed: the daily bars come from the same MT5 pipeline we
would trade on. Files are named ``{SYMBOL}_{TF}.csv`` or ``{SYMBOL}_{TF}.parquet``
(see the existing ``mt5_loader.py`` / ``fx_loader.py`` in the repo root).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from edgelab.data.base import DataProvider

logger = logging.getLogger("edgelab.data.mt5")


class MT5CsvProvider(DataProvider):
    name = "mt5_csv"

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        if not self.cache_dir.exists():
            raise FileNotFoundError(f"MT5 cache dir not found: {self.cache_dir}")

    def _find_file(self, symbol: str, timeframe: str) -> Path | None:
        for ext in (".parquet", ".csv"):
            p = self.cache_dir / f"{symbol}_{timeframe}{ext}"
            if p.exists():
                return p
        return None

    def get_bars(self, symbol, timeframe, start=None, end=None) -> pd.DataFrame:
        path = self._find_file(symbol, timeframe)
        if path is None:
            raise FileNotFoundError(
                f"No MT5 cache file for {symbol} @ {timeframe} in {self.cache_dir}"
            )
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        out = self._normalise(df, start, end)
        logger.debug("MT5 %s %s: %d bars from %s", symbol, timeframe, len(out), path.name)
        return out

    def available_symbols(self, timeframe: str) -> list[str]:
        syms: set[str] = set()
        suffix = f"_{timeframe}"
        for p in self.cache_dir.iterdir():
            if p.suffix in (".csv", ".parquet") and p.stem.endswith(suffix):
                syms.add(p.stem[: -len(suffix)])
        return sorted(syms)
