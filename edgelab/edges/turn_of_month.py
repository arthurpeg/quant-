"""Turn-of-month seasonality edge (brick #2 candidate).

Family: calendar/seasonality (surfaced by the 1000-paper arXiv triage). Hypothesis
(a documented anomaly): index/commodity returns concentrate around the month turn —
be long from the last trading day of the month through the first few of the next.

Found on **XAUUSD** (gold): long the last trading day + first 2 of each month, with a
protective daily stop. Per-bet t≈2.3 (nominal), 9/10 years positive, plateau across
the first-N window, and **corr ≈ 0.00 to the NAS100 breakout brick** → a genuine
diversifier. Caveats: modest t (does not clear a strict multiple-testing bar on its
own), monthly/low-activity, needs forward-testing. Documented a-priori, which softens
the mining concern. Reported as daily P&L so it composes with the intraday bricks.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"


@dataclass
class TurnOfMonthParams:
    last_days: int = 1        # include the last N trading days of the month
    first_days: int = 2       # ... and the first M of the next
    daily_stop: float = 0.015 # protective per-day stop (fraction), for prop compliance
    cost_bps: float = 0.4     # round-trip cost in bps (gold ~0.4)
    # --- R-based trade rules (mandatory SL on every brick) ---
    sl_atr: float = 1.5       # stop distance = sl_atr * ATR14(prev day). R = this distance.
    tp_atr: float | None = None  # optional take-profit (ATR mult); None = ride to time-exit
    atr_p: int = 14


def _load_d1(symbol: str) -> pd.DataFrame:
    for ext in (".parquet", ".csv"):
        p = MT5_DIR / f"{symbol}_D1{ext}"
        if p.exists():
            d = pd.read_parquet(p) if ext == ".parquet" else pd.read_csv(p)
            d.columns = [c.lower() for c in d.columns]
            d["t"] = pd.to_datetime(d["time"], utc=True)
            return d.set_index("t")[["open", "high", "low", "close"]].astype(float).sort_index()
    raise FileNotFoundError(f"no D1 file for {symbol}")


def turn_of_month_daily_pnl(symbol: str = "XAUUSD",
                            params: TurnOfMonthParams | None = None) -> pd.Series:
    """Return the strategy's DAILY net P&L (long on window days, flat otherwise)."""
    p = params or TurnOfMonthParams()
    d = _load_d1(symbol)
    ret = d["close"].pct_change()
    month = pd.PeriodIndex(d.index.tz_localize(None), freq="M")
    tdom = pd.Series(np.arange(len(d)), index=d.index).groupby(month).rank().astype(int)
    size = pd.Series(month).map(pd.Series(month).value_counts().to_dict()).values
    window = (tdom.values >= size - (p.last_days - 1)) | (tdom.values <= p.first_days)

    daily = ret.where(pd.Series(window, index=d.index), 0.0).clip(lower=-p.daily_stop)
    # charge round-trip cost once per month, on the first window day
    entry_day = pd.Series(window, index=d.index) & ~pd.Series(window, index=d.index).shift(1, fill_value=False)
    daily = daily - entry_day.astype(float) * (2 * p.cost_bps / 1e4)
    daily.index = daily.index.tz_localize(None)
    daily.name = f"tom_{symbol}"
    return daily


def _wilder_atr(d: pd.DataFrame, n: int) -> pd.Series:
    h, l, c = d["high"], d["low"], d["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def run_turn_of_month(symbol: str = "XAUUSD",
                      params: TurnOfMonthParams | None = None) -> pd.DataFrame:
    """R-based backtest with a MANDATORY stop. One trade per month.

    Entry = open of the last trading day of month M. Stop = entry − sl_atr·ATR14
    (prev-day ATR); R = that distance so a full stop = −1R. Time-exit = close of the
    ``first_days``-th trading day of month M+1 (the calendar window end). Optional TP.
    Barriers resolved on the daily bars in between, stop winning ties (pessimistic).
    Returns a trades frame with an ``R`` column (net of round-trip cost).
    """
    p = params or TurnOfMonthParams()
    d = _load_d1(symbol)
    atr = _wilder_atr(d, p.atr_p).shift(1)          # prev-day ATR (causal)
    month = pd.PeriodIndex(d.index.tz_localize(None), freq="M")
    tdom = pd.Series(np.arange(len(d)), index=d.index).groupby(month).rank().astype(int)
    idx = d.index
    o, h, l, c = (d["open"].to_numpy(), d["high"].to_numpy(),
                  d["low"].to_numpy(), d["close"].to_numpy())
    atr_a = atr.to_numpy()
    months = month.to_numpy()
    tdom_a = tdom.to_numpy()
    cost_frac = 2 * p.cost_bps / 1e4

    # entry positions = last trading day of each month; exit = first_days-th day of next month
    last_pos = {}
    for i in range(len(idx)):
        last_pos[months[i]] = i          # overwritten -> ends at the month's last row
    uniq_months = list(dict.fromkeys(months))
    trades = []
    for k in range(len(uniq_months) - 1):
        m, m_next = uniq_months[k], uniq_months[k + 1]
        ei = last_pos[m]
        # exit index = row in m_next with tdom == first_days (or the last available before that)
        nxt = np.where((months == m_next) & (tdom_a <= p.first_days))[0]
        if len(nxt) == 0:
            continue
        xi = nxt[-1]
        entry_atr = atr_a[ei]
        if not np.isfinite(entry_atr) or entry_atr <= 0:
            continue
        entry = o[ei]
        sl_dist = p.sl_atr * entry_atr
        stop = entry - sl_dist
        take = entry + p.tp_atr * entry_atr if p.tp_atr else None
        exit_px, reason = None, "time_exit"
        for j in range(ei, xi + 1):
            if l[j] <= stop:                       # stop hit (pessimistic: check first)
                exit_px, reason = stop, "stop"; break
            if take is not None and h[j] >= take:
                exit_px, reason = take, "take"; break
        if exit_px is None:
            exit_px = c[xi]
        gross = exit_px - entry
        net = gross - cost_frac * entry            # round-trip cost in price
        trades.append({"date": pd.Timestamp(idx[ei]).tz_localize(None).date(),
                       "entry": entry, "exit": exit_px, "reason": reason,
                       "bars_held": xi - ei + 1, "r_dist": sl_dist,
                       "cost_R": (cost_frac * entry) / sl_dist,
                       "R": net / sl_dist})
    return pd.DataFrame(trades)


def turn_of_month_bets(symbol: str = "XAUUSD",
                       params: TurnOfMonthParams | None = None) -> pd.Series:
    """One net-return 'bet' per month (for the validation gate)."""
    p = params or TurnOfMonthParams()
    d = _load_d1(symbol)
    ret = d["close"].pct_change()
    month = pd.PeriodIndex(d.index.tz_localize(None), freq="M")
    tdom = pd.Series(np.arange(len(d)), index=d.index).groupby(month).rank().astype(int)
    size = pd.Series(month).map(pd.Series(month).value_counts().to_dict()).values
    window = (tdom.values >= size - (p.last_days - 1)) | (tdom.values <= p.first_days)
    dfm = pd.DataFrame({"m": month, "r": ret.values, "w": window}, index=d.index).dropna()
    cost = 2 * p.cost_bps / 1e4
    bets = {g.index[-1]: g[g["w"]]["r"].clip(lower=-p.daily_stop).sum() - cost
            for _, g in dfm.groupby("m") if g["w"].any()}
    return pd.Series(bets)
