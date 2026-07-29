"""Provider factory — build the configured :class:`DataProvider` from a Config."""
from __future__ import annotations

from edgelab.config import Config
from edgelab.data.base import DataProvider
from edgelab.data.mt5_csv import MT5CsvProvider
from edgelab.data.yahoo import YahooProvider


def get_provider(cfg: Config, name: str | None = None) -> DataProvider:
    """Return a provider instance. ``name`` overrides ``config.data.provider``."""
    provider = name or cfg.data["provider"]
    if provider == "mt5_csv":
        return MT5CsvProvider(cfg.resolve_path(cfg.data["mt5_cache_dir"]))
    if provider == "yahoo":
        return YahooProvider(cfg.resolve_path(cfg.data["yahoo_cache_dir"]))
    raise ValueError(f"Unknown data provider: {provider!r}")
