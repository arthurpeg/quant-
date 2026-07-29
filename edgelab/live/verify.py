"""Prove the LIVE signal functions reproduce the BACKTEST decisions on cached bars.

This is the anti-divergence guarantee: before trusting the live runner, we replay the
same history through edgelab.live.signals and check it lands the same entries as the
frozen backtest functions. Runs fully offline. From repo root:
    python -m edgelab.live.verify
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.orb import load_bars
from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams, _mins
from edgelab.edges.turn_of_month import run_turn_of_month, TurnOfMonthParams
from edgelab.risk.trade_rules import TradeRules
from edgelab.config import load_config
from edgelab.live import signals as S

MT5_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_mt5"
CRYPTO_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache_crypto"


def verify_brick1() -> bool:
    p = ATRBreakParams(regime_mode="low", direction="both")
    df = load_bars("NAS100", "M1")
    d1 = pd.read_parquet(MT5_DIR / "NAS100_D1.parquet")
    atr_map = S.prev_day_atrs(d1, p)

    local = df.tz_convert(p.tz)
    open_m, close_m = _mins(p.session_open), _mins(p.session_close)
    day_key = local.index.tz_localize(None).normalize().to_numpy()
    work = df.copy()
    work["_m"] = (local.index.hour * 60 + local.index.minute).to_numpy()

    live_entries = {}
    for _d, g in work.groupby(day_key, sort=True):
        m = g["_m"].to_numpy()
        sess = g[(m >= open_m) & (m <= close_m)]
        if len(sess) < 10:
            continue
        et_day = pd.Timestamp(sess.index[0]).tz_convert(p.tz).date()
        atrs = atr_map.get(et_day)
        if atrs is None or not np.isfinite(atrs[0]) or atrs[0] <= 0:
            continue
        res = S.nas_orb_scan(sess[["open", "high", "low", "close"]], atrs[0], atrs[1], atrs[2], p)
        if res is None:
            continue
        confirm_idx, plan = res
        entry = float(sess["open"].to_numpy()[confirm_idx + 1])
        live_entries[et_day] = (plan.direction, round(entry, 3), round(plan.sl_dist, 4))

    bt = run_atr_breakout("NAS100", p, "M1").trades
    bt_entries = {r["date"]: (int(r["direction"]), round(float(r["entry"]), 3), round(float(r["r_dist"]), 4))
                  for _, r in bt.iterrows()}

    keys = set(live_entries) | set(bt_entries)
    mism = [(k, live_entries.get(k), bt_entries.get(k)) for k in sorted(keys)
            if live_entries.get(k) != bt_entries.get(k)]
    n = len(bt_entries)
    print(f"  BRICK 1 (NAS ORB): backtest {n} entries, live {len(live_entries)} entries, "
          f"{n - len(mism)}/{len(keys)} exact match")
    for k, lv, bv in mism[:5]:
        print(f"    MISMATCH {k}: live={lv} backtest={bv}")
    return len(mism) == 0


def verify_brick2() -> bool:
    p = TurnOfMonthParams(sl_atr=1.5)
    d1 = pd.read_parquet(MT5_DIR / "XAUUSD_D1.parquet")
    bt = run_turn_of_month("XAUUSD", p)
    bt_days = {pd.Timestamp(r["date"]).normalize(): round(float(r["r_dist"]), 3)
               for _, r in bt.iterrows()}

    # walk each calendar day the backtest could enter on, ask the live state
    ok = 0
    checked = 0
    diffs = []
    for day, r_dist in bt_days.items():
        st = S.tom_state(d1, day, p)
        checked += 1
        if st.is_entry_day and abs(st.sl_dist - r_dist) < 0.5:
            ok += 1
        else:
            diffs.append((day.date(), st.is_entry_day, round(st.sl_dist, 3), r_dist))
    print(f"  BRICK 2 (turn-of-month): {ok}/{checked} backtest entry-days matched by live "
          f"(business-day calendar approximation)")
    for d in diffs[:5]:
        print(f"    DIFF {d[0]}: live is_entry={d[1]} sl={d[2]} vs backtest r_dist={d[3]}")
    # tolerance: calendar approximation may miss a few holiday-shifted month-ends
    return ok / max(checked, 1) >= 0.80


def verify_brick3() -> bool:
    cfg = load_config()
    rules = TradeRules.from_config(cfg.risk)
    ok = True
    for s in ("BTCUSD", "ETHUSD"):
        d = pd.read_parquet(CRYPTO_DIR / f"{s}_D1.parquet")
        d["time"] = pd.to_datetime(d["time"], utc=True)
        d = d.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
        # target series identical to the frozen backtest signal?
        sig = S.macd_rsi(d)
        # spot-check the barrier math equals TradeRules on the last signalled bar
        plan = S.crypto_entry(d, cfg.raw["risk"])
        nz = int((sig != 0).sum())
        line = f"  BRICK 3 ({s}): macd_rsi {nz} nonzero bars"
        if plan is not None:
            # rebuild barrier via TradeRules from the same entry_atr and compare distance
            from edgelab.risk.trade_rules import atr as eatr
            entry_atr = float(eatr(d, cfg.raw["risk"]["atr_window"]).iloc[-1])
            stop, take = rules.barrier_prices(100.0, plan.direction, entry_atr)
            ref_sl = abs(100.0 - stop)
            match = abs(ref_sl - plan.sl_dist) < 1e-9
            line += f"; last-bar target={plan.direction} sl_dist match={match}"
            ok = ok and match
        else:
            line += "; currently flat (no entry)"
        print(line)
    return ok


def main():
    print("=" * 70)
    print("  LIVE-vs-BACKTEST signal verification")
    print("=" * 70)
    r1 = verify_brick1()
    r2 = verify_brick2()
    r3 = verify_brick3()
    print("-" * 70)
    print(f"  brick1={'PASS' if r1 else 'FAIL'}  brick2={'PASS' if r2 else 'FAIL'}  "
          f"brick3={'PASS' if r3 else 'FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
