"""Abstract data-provider interface and the canonical OHLCV contract.

Every provider returns the SAME shape so edges/backtests are source-agnostic:
  * index : tz-aware ``DatetimeIndex`` (UTC), sorted, unique
  * columns: exactly ``open, high, low, close, volume`` (float)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import pandas as pd

logger = logging.getLogger("edgelab.data")

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class DataProvider(ABC):
    """Interface every price source must implement."""

    name: str = "abstract"

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str | pd.Timestamp | None = None,
        end: str | pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Return OHLCV bars for ``symbol`` at ``timeframe`` in ``[start, end]``.

        Must satisfy :func:`_normalise` (UTC index, canonical columns). Raises
        ``FileNotFoundError``/``ValueError`` if the series cannot be produced.
        """

    @abstractmethod
    def available_symbols(self, timeframe: str) -> list[str]:
        """List symbols this provider can serve at ``timeframe``."""

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    def _normalise(
        df: pd.DataFrame,
        start: str | pd.Timestamp | None,
        end: str | pd.Timestamp | None,
    ) -> pd.DataFrame:
        """Coerce an arbitrary OHLCV frame to the canonical contract."""
        df = df.copy()
        # Lowercase columns and map common aliases.
        df.columns = [str(c).strip().lower() for c in df.columns]
        alias = {"date": "time", "datetime": "time", "vol": "volume", "tickvol": "volume"}
        df = df.rename(columns=alias)

        if "time" in df.columns:
            idx = pd.to_datetime(df["time"], utc=True)
            df = df.drop(columns=[c for c in ["time"] if c in df.columns])
            df.index = idx
        else:
            df.index = pd.to_datetime(df.index, utc=True)

        missing = [c for c in ["open", "high", "low", "close"] if c not in df.columns]
        if missing:
            raise ValueError(f"OHLCV frame missing columns: {missing}")
        if "volume" not in df.columns:
            df["volume"] = 0.0

        df = df[OHLCV_COLUMNS].astype(float)
        df = df[~df.index.duplicated(keep="last")].sort_index()

        if start is not None:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]

        # Drop bars with non-finite prices (weekend ffill artefacts etc.).
        df = df[df[["open", "high", "low", "close"]].notna().all(axis=1)]
        return df
