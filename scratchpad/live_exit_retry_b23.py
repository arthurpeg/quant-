"""Same stuck-exit regression, for bricks 2 (gold turn-of-month) and 3 (crypto MACD)."""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(r"C:\Users\arthu\OneDrive\Documents\ML quantitatif")))

from edgelab.live.broker import MarketClosed, Position
from edgelab.live import strategies as ST
from edgelab.live import runner as R

logging.basicConfig(level=logging.WARNING)

DATES = list(pd.date_range("2026-06-01", "2026-08-10", freq="D"))   # crypto: 7d/7


def bars(dates):
    return pd.DataFrame([{"time": d, "open": 60000.0 + 10 * i, "high": 60200.0 + 10 * i,
                          "low": 59800.0 + 10 * i, "close": 60100.0 + 10 * i}
                         for i, d in enumerate(dates)])


class FakeBroker:
    def __init__(self, refusals, symbol, dates):
        self.live = True
        self.orders_sent = 0
        self.refusals = refusals
        self.close_attempts = 0
        self.closed = False
        self.symbol = symbol
        self.dates = dates

    def equity(self):
        return 60000.0

    def get_bars_raw(self, logical, tf, n):
        return bars(self.dates).copy()

    def open_position(self, magic):
        if self.closed:
            return None
        return Position(magic=magic, symbol=self.symbol, direction=1, lots=0.1,
                        entry_price=60000.0, sl=59000.0, tp=None, sl_dist=1000.0,
                        open_time=pd.Timestamp("2026-08-01 03:00", tz="UTC"),
                        comment="x", ticket=1)

    def close(self, pos, px, reason, now_utc, cost_R=0.0):
        self.close_attempts += 1
        if self.close_attempts <= self.refusals:
            raise MarketClosed(f"{self.symbol} market closed")
        self.closed = True
        self.orders_sent += 1
        return 0.0


class FakeRisk:
    failed = False
    initial_balance = 60000.0
    risk_per_trade = 0.01

    def on_equity(self, e, t):
        pass

    def can_enter(self):
        return True, "ok"

    def risk_budget(self):
        return 600.0


def drive(strat, broker, polls, start="2026-08-09 22:50:00"):
    R._MARKET_CLOSED_SINCE.clear()
    R._LAST_FAILURE.clear()
    t0 = pd.Timestamp(start, tz="UTC")
    for i in range(polls):
        R.one_pass(broker, FakeRisk(), [strat], t0 + pd.Timedelta(seconds=20 * i))


# ---- brick 2: gold turn-of-month -------------------------------------------
ST.S.tom_state = lambda d1, day, p: SimpleNamespace(
    is_exit_day=True, is_entry_day=False, bars_done=99, sl_dist=10.0)

for refusals, expected in ((5, 6), (10_000, 40)):
    b = FakeBroker(refusals, "XAUUSD", DATES)
    drive(ST.GoldTomStrategy({"gold_symbol": "XAUUSD"}), b, polls=40)
    print(f"brick2 refusals={refusals:>5} -> close attempts={b.close_attempts} closed={b.closed}")
    assert b.close_attempts == expected, b.close_attempts

b = FakeBroker(0, "XAUUSD", DATES)
drive(ST.GoldTomStrategy({"gold_symbol": "XAUUSD"}), b, polls=10)
print(f"brick2 open market   -> close attempts={b.close_attempts} closed={b.closed}")
assert b.close_attempts == 1 and b.closed

# ---- brick 3: crypto MACD (time_exit_bars=1 => the exit is always due) ------
risk_cfg = {"time_exit_bars": 1}
for refusals, expected in ((5, 6), (10_000, 40)):
    b = FakeBroker(refusals, "BTCUSD", DATES)
    drive(ST.CryptoMacdStrategy({}, "BTCUSD", risk_cfg), b, polls=40)
    print(f"brick3 refusals={refusals:>5} -> close attempts={b.close_attempts} closed={b.closed}")
    assert b.close_attempts == expected, b.close_attempts

b = FakeBroker(0, "BTCUSD", DATES)
drive(ST.CryptoMacdStrategy({}, "BTCUSD", risk_cfg), b, polls=10)
print(f"brick3 open market   -> close attempts={b.close_attempts} closed={b.closed}")
assert b.close_attempts == 1 and b.closed

print("\nBRICKS 2 & 3 OK")
