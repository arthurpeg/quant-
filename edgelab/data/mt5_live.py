"""Pull real bars from a live MetaTrader5 terminal (here: PepperstoneUK-Demo).

Kept separate from the offline providers because it needs the terminal running.
``copy_rates_range`` bars carry a per-bar ``spread`` (in points) which we keep for
honest cost. Pulled in monthly chunks to avoid the terminal's "max bars" cap.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("edgelab.data.mt5_live")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MT5_DIR = REPO_ROOT / "data_cache_mt5"

_TF = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M10": "TIMEFRAME_M10",
       "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
       "D1": "TIMEFRAME_D1"}


def pull_bars(symbol: str, timeframe: str, start: str, end: str | None = None,
              chunk_days: int = 30) -> pd.DataFrame:
    """Return real OHLCV+spread bars for ``symbol`` at ``timeframe`` in [start,end].

    Requires an initialised MT5 terminal. Times are broker-server time (as stored).
    """
    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select failed for {symbol}: {mt5.last_error()}")
        tf = getattr(mt5, _TF[timeframe])
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.utcnow().tz_convert("UTC")

        frames = []
        cur = start_ts
        step = pd.Timedelta(days=chunk_days)
        while cur < end_ts:
            nxt = min(cur + step, end_ts)
            rates = mt5.copy_rates_range(symbol, tf,
                                         cur.to_pydatetime(), nxt.to_pydatetime())
            if rates is not None and len(rates):
                frames.append(pd.DataFrame(rates))
            cur = nxt
        if not frames:
            raise ValueError(f"No bars returned for {symbol} {timeframe} {start}..{end}")

        df = pd.concat(frames, ignore_index=True)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = (df.drop_duplicates("time").sort_values("time").reset_index(drop=True))
        keep = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
        return df[[c for c in keep if c in df.columns]]
    finally:
        mt5.shutdown()


def pull_and_cache(symbol: str, timeframe: str, start: str, end: str | None = None,
                   out_dir: Path | None = None) -> Path:
    """Pull and save to ``data_cache_mt5/{symbol}_{timeframe}.parquet``."""
    d = Path(out_dir) if out_dir else MT5_DIR
    d.mkdir(parents=True, exist_ok=True)
    df = pull_bars(symbol, timeframe, start, end)
    path = d / f"{symbol}_{timeframe}.parquet"
    df.to_parquet(path)
    logger.info("cached %d %s %s bars -> %s", len(df), symbol, timeframe, path)
    return path
