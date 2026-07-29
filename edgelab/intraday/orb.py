"""Opening Range Breakout (ORB) — the classic intraday breakout family.

Covers the practitioner cluster in the user's topic list (Opening Range Breakout /
Opening Price Momentum / Intraday Range Expansion / Breakout Continuation /
First-Hour Volatility / Post-Breakout Drift): define the first-N-minutes range of a
session, trade a break of it, manage with a hard stop at the opposite side of the
range and a take-profit at a multiple of that risk, and flatten at the session close.

Everything is measured in **R**, where R = the entry-to-stop distance, so a full
stop-out = **-1R** (minus real cost). Cost uses each bar's own MT5 ``spread`` value
(in points) converted to price via the instrument's point size, plus a slippage
buffer — deliberately honest, per the wiki (exp-005): demo feeds flatter breakouts,
so we cost pessimistically and cross-check against the tick-validated exp-005 number.

NO LOOKAHEAD: the breakout is detected on a bar's CLOSE and filled at the NEXT bar's
open. Barriers are tested intrabar with the stop winning ties (pessimistic).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("edgelab.intraday.orb")

# MT5 point size (price value of 1 "point") per instrument. Inferred from the
# quoted price precision; the ``spread`` column is in these points.
POINT_SIZE = {
    "NAS100": 0.1, "US30": 0.1, "XAUUSD": 0.01,
    "XAGUSD": 0.001, "SpotCrude": 0.01, "NatGas": 0.001,
}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MT5_DIR = REPO_ROOT / "data_cache_mt5"

# MT5 bars are stamped in BROKER-SERVER time (Pepperstone = EET/EEST, ~UTC+2/+3),
# but stored/labelled as UTC. We must reinterpret them to TRUE UTC before doing any
# session (US-open) logic, otherwise the "opening range" lands on the wrong hours.
SERVER_TZ = "Europe/Athens"   # EET/EEST, DST-correct — matches Pepperstone server


def to_true_utc(idx: pd.DatetimeIndex, server_tz: str = SERVER_TZ) -> pd.DatetimeIndex:
    """Reinterpret a UTC-labelled index whose wall-clock is actually ``server_tz``.

    Returns a genuine UTC index. Bars falling in a DST gap/overlap are marked NaT
    (caller should drop them).
    """
    naive = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    localized = naive.tz_localize(server_tz, ambiguous="NaT", nonexistent="NaT")
    return localized.tz_convert("UTC")


@dataclass
class ORBParams:
    or_minutes: int = 30          # opening-range window length
    session_open: str = "09:30"   # local (exchange) session start
    session_close: str = "15:55"  # forced flat time (before the 16:00 cash close)
    tz: str = "America/New_York"  # session timezone (handles DST)
    tp_R: float = 2.0             # take-profit at tp_R * risk; use a huge value (e.g. 999) for hold-to-close
    direction: str = "both"       # "both" | "long" | "short"
    slippage_points: float = 1.0  # extra adverse points per side (on top of spread)
    min_or_frac: float = 0.0      # skip days whose OR width < this frac of price (0=off)
    # Volatility-regime filter (exp-005 / "First-Hour Volatility" topic): only trade
    # when today's opening-range width ranks in the upper part of its recent history.
    vol_lookback: int = 0         # trailing days of OR width to rank against (0 = filter off)
    vol_min_pct: float = 0.0      # require today's OR width >= this percentile of that window


@dataclass
class ORBResult:
    symbol: str
    params: ORBParams
    trades: pd.DataFrame          # one row per trade, R-multiple in column "R"
    metrics: dict = field(default_factory=dict)


def load_bars(symbol: str, timeframe: str = "M10", mt5_dir: Path | None = None,
              server_tz: str = SERVER_TZ) -> pd.DataFrame:
    """Load an intraday parquet and return it on a TRUE-UTC index.

    Columns: open/high/low/close/spread. The stored time is broker-server (EET);
    we reinterpret it to real UTC so downstream session logic is correct.
    """
    d = Path(mt5_dir) if mt5_dir else MT5_DIR
    df = pd.read_parquet(d / f"{symbol}_{timeframe}.parquet")
    df.columns = [c.lower() for c in df.columns]
    idx = pd.DatetimeIndex(pd.to_datetime(df["time"], utc=True))
    true_utc = to_true_utc(idx, server_tz)
    df = df.set_index(true_utc)
    df = df[df.index.notna()]   # drop DST-transition artefacts
    cols = [c for c in ["open", "high", "low", "close", "spread"] if c in df.columns]
    df = df[cols].astype(float)
    if "spread" not in df.columns:
        df["spread"] = 0.0
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_m10(symbol: str, mt5_dir: Path | None = None) -> pd.DataFrame:
    """Backwards-compatible M10 loader (now tz-correct via :func:`load_bars`)."""
    return load_bars(symbol, "M10", mt5_dir)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def run_orb(df: pd.DataFrame, symbol: str, params: ORBParams | None = None) -> ORBResult:
    """Backtest the ORB on one symbol's M10 bars. Returns per-trade R-multiples."""
    p = params or ORBParams()
    point = POINT_SIZE.get(symbol, 1.0)
    local = df.tz_convert(p.tz)
    open_m, close_m = _minutes(p.session_open), _minutes(p.session_close)
    or_end_m = open_m + p.or_minutes

    # cost per side in price = half the bar spread + slippage buffer, in price units
    def cost_price(spread_points: float) -> float:
        return (0.5 * spread_points + p.slippage_points) * point

    trades: list[dict] = []
    or_hist: list[float] = []   # past OR widths, for the causal vol-regime filter
    # Precompute local minute-of-day and calendar date ONCE (avoid per-day rescans).
    loc_min_all = (local.index.hour * 60 + local.index.minute).to_numpy()
    day_key = local.index.tz_localize(None).normalize()
    work = df.copy()
    work["_locmin"] = loc_min_all

    for _day, day_df in work.groupby(day_key.to_numpy(), sort=True):
        loc_min = day_df["_locmin"].to_numpy()
        sess_mask = (loc_min >= open_m) & (loc_min <= close_m)
        if sess_mask.sum() < 6:
            continue
        sess = day_df[sess_mask]
        sess_locmin = loc_min[sess_mask]
        day = pd.Timestamp(sess.index[0]).tz_convert(p.tz).normalize()

        or_mask = (sess_locmin >= open_m) & (sess_locmin < or_end_m)
        if or_mask.sum() == 0:
            continue
        or_bars = sess[or_mask]
        or_high = or_bars["high"].max()
        or_low = or_bars["low"].min()
        or_width = or_high - or_low
        if or_width <= 0:
            continue
        if p.min_or_frac > 0 and or_width < p.min_or_frac * or_bars["close"].iloc[-1]:
            continue

        # Volatility-regime filter: today's OR must rank high vs recent OR history.
        # Uses only PAST days (or_hist appended after the decision) -> causal.
        if p.vol_lookback > 0 and p.vol_min_pct > 0:
            window = or_hist[-p.vol_lookback:]
            if len(window) >= max(10, p.vol_lookback // 2):
                thresh = np.percentile(window, p.vol_min_pct)
                if or_width < thresh:
                    or_hist.append(or_width)
                    continue
            or_hist.append(or_width)
        elif p.vol_lookback > 0:
            or_hist.append(or_width)

        # bars available to trade: strictly after the OR window
        post = sess[~or_mask]
        if len(post) < 2:
            continue
        highs = post["high"].to_numpy()
        lows = post["low"].to_numpy()
        closes = post["close"].to_numpy()
        opens = post["open"].to_numpy()
        spreads = post["spread"].to_numpy()
        times = post.index

        # --- detect the first breakout on a bar CLOSE ---
        entry_idx = None
        direction = 0
        for i in range(len(post) - 1):   # need a next bar to fill on
            if p.direction in ("both", "long") and closes[i] > or_high:
                direction = 1
                entry_idx = i + 1
                break
            if p.direction in ("both", "short") and closes[i] < or_low:
                direction = -1
                entry_idx = i + 1
                break
        if entry_idx is None or entry_idx >= len(post):
            continue

        entry_price = opens[entry_idx]                    # fill at NEXT bar open
        stop = or_low if direction == 1 else or_high      # stop = opposite OR side
        r_dist = abs(entry_price - stop)
        if r_dist <= 0:
            continue
        take = entry_price + direction * p.tp_R * r_dist

        entry_cost = cost_price(spreads[entry_idx])
        exit_price = None
        reason = "time_exit"
        exit_cost = 0.0

        # --- manage the position bar by bar (intrabar first-touch, stop wins ties) ---
        for j in range(entry_idx, len(post)):
            hi, lo = highs[j], lows[j]
            hit_stop = lo <= stop if direction == 1 else hi >= stop
            hit_take = hi >= take if direction == 1 else lo <= take
            if hit_stop and hit_take:      # pessimistic: assume stop first
                exit_price, reason = stop, "stop"
            elif hit_stop:
                exit_price, reason = stop, "stop"
            elif hit_take:
                exit_price, reason = take, "take"
            if exit_price is not None:
                exit_cost = cost_price(spreads[j])
                exit_time = times[j]
                break
        if exit_price is None:             # never hit a barrier -> flat at session close
            exit_price = closes[-1]
            exit_cost = cost_price(spreads[-1])
            exit_time = times[-1]
            reason = "time_exit"

        gross_price = direction * (exit_price - entry_price)
        net_price = gross_price - entry_cost - exit_cost
        R = net_price / r_dist
        trades.append({
            "date": pd.Timestamp(day).date(),
            "direction": direction,
            "entry_time": times[entry_idx],
            "exit_time": exit_time,
            "entry": entry_price,
            "stop": stop,
            "take": take,
            "exit": exit_price,
            "reason": reason,
            "or_width": or_width,
            "r_dist": r_dist,
            "cost_R": (entry_cost + exit_cost) / r_dist,
            "R": R,
        })

    trades_df = pd.DataFrame(trades)
    res = ORBResult(symbol=symbol, params=p, trades=trades_df)
    res.metrics = orb_metrics_R(trades_df)
    return res


def orb_metrics_R(trades: pd.DataFrame) -> dict:
    """Performance in R-space. A full stop = -1R (minus cost)."""
    if trades is None or trades.empty:
        return {"n_trades": 0}
    R = trades["R"]
    wins = R[R > 0]
    losses = R[R <= 0]
    gross_win = wins.sum()
    gross_loss = -losses.sum()
    # equity curve in cumulative R for drawdown
    cum = R.cumsum()
    dd = (cum.cummax() - cum).max()
    # per-year R
    years = trades["date"].astype("datetime64[ns]")
    span_years = max((years.max() - years.min()).days / 365.25, 1e-9)

    return {
        "n_trades": int(len(R)),
        "win_rate": float((R > 0).mean()),
        "expectancy_R": float(R.mean()),          # average R per trade
        "total_R": float(R.sum()),
        "R_per_year": float(R.sum() / span_years),
        "avg_win_R": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_R": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "max_dd_R": float(dd),
        "R_std": float(R.std(ddof=0)),
        "sharpe_per_trade": float(R.mean() / R.std(ddof=0)) if R.std(ddof=0) > 0 else 0.0,
        "pct_stop": float((trades["reason"] == "stop").mean()),
        "pct_take": float((trades["reason"] == "take").mean()),
        "pct_timeexit": float((trades["reason"] == "time_exit").mean()),
        "avg_cost_R": float(trades["cost_R"].mean()),
        "first_date": str(trades["date"].min()),
        "last_date": str(trades["date"].max()),
    }
