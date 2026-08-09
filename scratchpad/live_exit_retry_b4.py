"""Regression test for the stuck-exit bug observed live on 2026-08-07..09.

Replays the real scenario: brick 4 holds a NAS100 long, the IBS exit signal fires, and
the broker refuses the close with MarketClosed (weekend / daily break) for several polls
before the market reopens.

BEFORE the fix, `_acted_day` was set before the close attempt, so the day's ONE exit
attempt was consumed by the first refusal and the position was carried to the next
broker day. AFTER the fix, the refusal leaves `_managed_day` unset and every poll retries.
"""
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(r"C:\Users\arthu\OneDrive\Documents\ML quantitatif")))

from edgelab.live.broker import MarketClosed, Position
from edgelab.live.strategies import NasIbsStrategy, SERVER_TZ
from edgelab.live import signals as S
from edgelab.live import runner as R

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

SERVER_DATES = [d for d in pd.date_range("2026-06-20", "2026-08-10", freq="D")
                if d.weekday() < 5]          # NAS100 prints no weekend bar


def make_bars() -> pd.DataFrame:
    """D1 frame in the broker's own clock (server time labelled UTC), like get_bars_raw."""
    rows = []
    for i, d in enumerate(SERVER_DATES):
        base = 29000.0 + 10.0 * i
        # last CLOSED bar (2026-08-07) closes on its high -> IBS = 1.0 -> exit_signal
        if d.date() == pd.Timestamp("2026-08-07").date():
            rows.append({"time": d, "open": base, "high": base + 200, "low": base - 100,
                         "close": base + 200})
        else:
            rows.append({"time": d, "open": base, "high": base + 150, "low": base - 150,
                         "close": base + 20})
    return pd.DataFrame(rows)


class FakeBroker:
    """Minimal live-mode broker: refuses `close` with MarketClosed `refusals` times."""

    def __init__(self, refusals: int):
        self.live = True
        self.orders_sent = 0
        self.refusals = refusals
        self.close_attempts = 0
        self.closed = False
        self.bar_calls = 0

    def equity(self):
        return 60000.0

    def get_bars_raw(self, logical, tf, n):
        self.bar_calls += 1
        return make_bars().copy()

    def open_position(self, magic):
        if self.closed:
            return None
        return Position(magic=magic, symbol="NAS100", direction=1, lots=0.4,
                        entry_price=29536.70, sl=27691.6, tp=None, sl_dist=1845.0,
                        open_time=pd.Timestamp("2026-08-06 03:00", tz="UTC"),
                        comment="brick4_ibs_reversion", ticket=82489480)

    def close(self, pos, px, reason, now_utc, cost_R=0.0):
        self.close_attempts += 1
        if self.close_attempts <= self.refusals:
            raise MarketClosed("NAS100 market closed")
        self.closed = True
        self.orders_sent += 1
        return 0.0


class FakeRisk:
    def __init__(self):
        self.failed = False
        self.initial_balance = 60000.0
        self.risk_per_trade = 0.01

    def on_equity(self, equity, now_utc):
        pass

    def can_enter(self):
        return True, "ok"

    def risk_budget(self):
        return 600.0


def run(refusals: int, polls: int, start: str = "2026-08-09 22:50:00"):
    R._MARKET_CLOSED_SINCE.clear()
    R._LAST_FAILURE.clear()
    broker, risk = FakeBroker(refusals), FakeRisk()
    strat = NasIbsStrategy({"ibs_symbol": "NAS100"})
    t0 = pd.Timestamp(start, tz="UTC")
    for i in range(polls):
        R.one_pass(broker, risk, [strat], t0 + pd.Timedelta(seconds=20 * i))
    return broker, strat


# --- sanity: the fixture really does fire the exit signal --------------------
raw = make_bars()
raw["time"] = pd.to_datetime(raw["time"], utc=True)
daily_all = raw.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
now = pd.Timestamp("2026-08-09 23:00", tz="UTC")
bday = now.tz_convert(SERVER_TZ).date()
assert bday == pd.Timestamp("2026-08-10").date(), bday
assert daily_all.index[-1].date() == bday, "the 2026-08-10 bar must be the forming one"
st = S.ibs_state(daily_all.iloc[:-1], NasIbsStrategy({}).p)
assert st.exit_signal, f"fixture does not trigger the exit: ibs={st.ibs}"
print(f"fixture ok: last-closed IBS = {st.ibs:.3f} -> exit_signal={st.exit_signal}")

# --- 1. the bug scenario: refused 5 times, then the market reopens -----------
broker, strat = run(refusals=5, polls=10)
print(f"\n[refused 5x] close attempts={broker.close_attempts} "
      f"closed={broker.closed} orders_sent={broker.orders_sent}")
assert broker.close_attempts == 6, (
    f"expected one attempt per poll until it goes through, got {broker.close_attempts} "
    "(1 = the old bug: the day's only attempt was consumed by the first refusal)")
assert broker.closed, "the position must be out once the market reopens"
assert broker.orders_sent == 1

# --- 2. a whole weekend of refusals: never abandoned ------------------------
broker, strat = run(refusals=10_000, polls=200)
print(f"[refused forever] close attempts={broker.close_attempts} closed={broker.closed}")
assert broker.close_attempts == 200, f"an exit must never be abandoned, got {broker.close_attempts}"
assert not broker.closed

# --- 3. no refusal: exactly one close, no repeat hammering ------------------
broker, strat = run(refusals=0, polls=10)
print(f"[open market]   close attempts={broker.close_attempts} closed={broker.closed}")
assert broker.close_attempts == 1, f"one close only, got {broker.close_attempts}"
assert broker.closed

# --- 4. the runner's message must not claim an order it did not send --------
class SilentBroker(FakeBroker):
    """Refuses once, then the strategy has nothing left to do (position already gone)."""

    def close(self, pos, px, reason, now_utc, cost_R=0.0):
        self.close_attempts += 1
        if self.close_attempts <= self.refusals:
            self.closed = True          # e.g. the broker stop filled while we were shut out
            raise MarketClosed("NAS100 market closed")
        self.orders_sent += 1
        return 0.0


R._MARKET_CLOSED_SINCE.clear()
R._LAST_FAILURE.clear()
broker, risk = SilentBroker(refusals=1), FakeRisk()
strat = NasIbsStrategy({"ibs_symbol": "NAS100"})
t0 = pd.Timestamp("2026-08-09 22:50:00", tz="UTC")
records = []
handler = logging.Handler()
handler.emit = lambda rec: records.append(rec.getMessage())
R.LOG.addHandler(handler)
for i in range(3):
    R.one_pass(broker, risk, [strat], t0 + pd.Timedelta(seconds=20 * i))
R.LOG.removeHandler(handler)
msgs = [m for m in records if "market reopened" in m]
print(f"[no order sent] {msgs}")
assert msgs and "NO order sent" in msgs[0], (
    f"the runner must not claim an order it never sent: {msgs}")
assert broker.orders_sent == 0

print("\nALL ASSERTIONS PASSED")
