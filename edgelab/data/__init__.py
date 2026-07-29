"""Data layer: one abstract :class:`DataProvider` interface, several backends.

Swap the source (MT5 cache, Yahoo, a future tick provider) without touching the
rest of the framework — everything downstream consumes the same tidy OHLCV frame.
"""
from edgelab.data.base import DataProvider, OHLCV_COLUMNS
from edgelab.data.mt5_csv import MT5CsvProvider
from edgelab.data.yahoo import YahooProvider
from edgelab.data.factory import get_provider

__all__ = [
    "DataProvider",
    "OHLCV_COLUMNS",
    "MT5CsvProvider",
    "YahooProvider",
    "get_provider",
]
