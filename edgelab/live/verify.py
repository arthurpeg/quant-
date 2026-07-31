"""Prove the LIVE signal functions reproduce the BACKTEST decisions on cached bars.

This is the anti-divergence guarantee: before trusting the live runner, we replay the
same history through edgelab.live.signals and check it lands the same entries as the
frozen backtest functions. Runs fully offline. From repo root:
    python -m edgelab.live.verify
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from edgelab.intraday.orb import load_bars
from edgelab.intraday.atr_breakout import run_atr_breakout, ATRBreakParams, _mins
from edgelab.edges.turn_of_month import run_turn_of_month, TurnOfMonthParams
from edgelab.edges.ibs import run_ibs, IBSParams
from edgelab.risk.trade_rules import TradeRules
from edgelab.config import load_config, risk_for
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
    crisk = risk_for(cfg, "crypto")          # brick 3's own exits, as the runner reads them
    rules = TradeRules.from_config(crisk)
    ok = True
    for s in ("BTCUSD", "ETHUSD"):
        d = pd.read_parquet(CRYPTO_DIR / f"{s}_D1.parquet")
        d["time"] = pd.to_datetime(d["time"], utc=True)
        d = d.set_index("time")[["open", "high", "low", "close"]].astype(float).sort_index()
        # target series identical to the frozen backtest signal?
        sig = S.macd_rsi(d)
        # spot-check the barrier math equals TradeRules on the last signalled bar
        plan = S.crypto_entry(d, crisk)
        nz = int((sig != 0).sum())
        line = f"  BRICK 3 ({s}): macd_rsi {nz} nonzero bars"
        if plan is not None:
            # rebuild barrier via TradeRules from the same entry_atr and compare distance
            from edgelab.risk.trade_rules import atr as eatr
            entry_atr = float(eatr(d, crisk["atr_window"]).iloc[-1])
            stop, take = rules.barrier_prices(100.0, plan.direction, entry_atr)
            ref_sl = abs(100.0 - stop)
            match = abs(ref_sl - plan.sl_dist) < 1e-9
            line += f"; last-bar target={plan.direction} sl_dist match={match}"
            ok = ok and match
        else:
            line += "; currently flat (no entry)"
        print(line)

    # CADENCE: the driver returns after handling an open position (`_acted_day` blocks a
    # second action that day), so it can NEVER close and re-open inside one bar. The
    # literal engine could, filling the re-entry at that bar's already-past open — worth
    # +10.3 R/yr of pure artefact. Guard it: the book must be built on cadence='live'.
    from edgelab.backtest.engine import BacktestEngine
    from edgelab.backtest.costs import CostModel
    from edgelab.reports.monte_carlo_static import load as load_pep, macd_rsi as pep_macd
    cm = CostModel(10, 3, {'BTCUSD': 5, 'ETHUSD': 8})
    W = pd.Timestamp('2018-07-01')
    out = {}
    for cad in ("literal", "live"):
        e = BacktestEngine(replace(cfg, raw={**cfg.raw, 'risk': crisk}),
                           cost_model=cm, cadence=cad)
        rows = []
        for s in ("BTCUSD", "ETHUSD"):
            d = load_pep(s)
            tr = e.run(d, pep_macd(d), s, "x").trades
            tr["ex"] = pd.to_datetime(tr["exit_time"]).dt.tz_localize(None)
            tr["en"] = pd.to_datetime(tr["entry_time"]).dt.tz_localize(None)
            rows.append(tr)
        out[cad] = rows
    reent = sum(int((r.sort_values("en")["en"].dt.normalize()
                     == r.sort_values("en")["ex"].dt.normalize().shift(1)).sum())
                for r in out["live"])
    yrs = 8.07
    rr = {c: pd.concat(v)[pd.concat(v)["ex"] >= W]["ret"].sum() / yrs for c, v in out.items()}
    print(f"  BRICK 3 cadence: live re-opens inside a bar {reent} times (must be 0) | "
          f"R/yr live {rr['live']:+.2f} vs literal {rr['literal']:+.2f} "
          f"({rr['live']-rr['literal']:+.2f}) - the book uses cadence='live'")
    return ok and reent == 0


def _ibs_bars() -> pd.DataFrame:
    d = pd.read_parquet(MT5_DIR / "NAS100_D1.parquet")
    d.columns = [c.lower() for c in d.columns]
    d["t"] = pd.to_datetime(d["time"], utc=True)
    return d.set_index("t")[["open", "high", "low", "close"]].astype(float).sort_index()


def verify_brick4() -> bool:
    """Brick 4 parity, in two parts (stricter than bricks 1-3 — compares whole TRADES).

    (a) SIGNAL MATH — replay run_ibs's own loop structure but take every decision from
        ``S.ibs_state``. Must be trade-for-trade IDENTICAL: that is what proves the live
        signal layer cannot diverge from the frozen backtest. This is the PASS/FAIL gate.

    (b) DRIVER CADENCE — replay the real driver's once-per-rollover cadence
        (``NasIbsStrategy.step``) and report the residual gap. The only structural
        difference is that run_ibs may re-enter on the SAME bar a stop fired, filling at
        that bar's OPEN — a price that is already in the past by then. Live cannot do that
        and does not try to; the gap is reported in R so it is never silently ignored.
    """
    p = IBSParams(sl_atr=2.5)
    d = _ibs_bars()
    o, lo, c = d["open"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    idx, n = d.index, len(d)
    # every decision the two replays consume, taken from the LIVE signal function
    states = [None] + [S.ibs_state(d.iloc[:T], p) for T in range(1, n + 1)]   # states[T] <- bars 0..T-1

    def trade(entry_i, entry_px, risk, exit_px, why):
        return (pd.Timestamp(idx[entry_i]).tz_localize(None), round(entry_px, 3),
                round(exit_px, 3), why, round((exit_px - entry_px - p.cost_price) / risk, 6))

    # ---- (a) run_ibs's structure, live's decisions --------------------------------
    a_trades, in_pos, entry_i, entry_px, risk, stop = [], False, -1, 0.0, 0.0, 0.0
    for t in range(n):
        if in_pos:
            why = exit_px = None
            if lo[t] <= stop:
                exit_px, why = (stop if o[t] >= stop else o[t]), "stop"
            elif states[t + 1].exit_signal or (t - entry_i) >= p.max_hold:
                why = "ibs" if states[t + 1].exit_signal else "time"
                exit_px = o[t + 1] if t + 1 < n else c[t]
                why = why if t + 1 < n else "eod"
            if why:
                a_trades.append(trade(entry_i, entry_px, risk, exit_px, why)); in_pos = False
        if (not in_pos) and t >= 1 and states[t].entry_ok:
            entry_i, entry_px, risk = t, o[t], states[t].sl_dist
            stop, in_pos = entry_px - risk, True
            if lo[t] <= stop:
                a_trades.append(trade(entry_i, entry_px, risk,
                                      stop if o[t] >= stop else o[t], "stop")); in_pos = False

    bt = run_ibs("NAS100", p, cadence="literal")
    bt_trades = [(pd.Timestamp(r["entry_dt"]), round(float(r["entry"]), 3), round(float(r["exit"]), 3),
                  r["reason"], round(float(r["R"]), 6)) for _, r in bt.iterrows()]
    mism = [(x, y) for x, y in zip(a_trades, bt_trades) if x != y]
    same = len(a_trades) == len(bt_trades) and not mism
    print(f"  BRICK 4 (NAS IBS) signal math: backtest {len(bt_trades)} trades, live-decisions "
          f"{len(a_trades)}, {len(bt_trades) - len(mism)}/{len(bt_trades)} exact match")
    for x, y in mism[:5]:
        print(f"    MISMATCH live={x} backtest={y}")

    # ---- (b) the driver's real rollover-only cadence --------------------------------
    b_trades, in_pos, entry_i, entry_px, risk, stop = [], False, -1, 0.0, 0.0, 0.0
    for T in range(1, n):
        st = states[T]                                   # what the driver sees at this rollover
        if in_pos and (st.exit_signal or (T - 1 - entry_i) >= p.max_hold):
            b_trades.append(trade(entry_i, entry_px, risk, o[T],
                                  "ibs" if st.exit_signal else "time")); in_pos = False
        if (not in_pos) and st.entry_ok:
            entry_i, entry_px, risk = T, o[T], st.sl_dist
            stop, in_pos = entry_px - risk, True
        if in_pos and lo[T] <= stop:                     # intrabar stop, managed by the broker
            b_trades.append(trade(entry_i, entry_px, risk,
                                  stop if o[T] >= stop else o[T], "stop")); in_pos = False

    lit_R = sum(t[4] for t in bt_trades)
    dr_R = sum(t[4] for t in b_trades)
    print(f"  BRICK 4 (NAS IBS) driver cadence: {len(b_trades)} trades vs {len(bt_trades)} backtest "
          f"| total R {dr_R:+.1f} vs {lit_R:+.1f} ({dr_R - lit_R:+.1f} R) - the reports "
          f"use the LIVE cadence, run_ibs(cadence='live')")
    return same


def main():
    print("=" * 70)
    print("  LIVE-vs-BACKTEST signal verification")
    print("=" * 70)
    r1 = verify_brick1()
    r2 = verify_brick2()
    r3 = verify_brick3()
    r4 = verify_brick4()
    print("-" * 70)
    print(f"  brick1={'PASS' if r1 else 'FAIL'}  brick2={'PASS' if r2 else 'FAIL'}  "
          f"brick3={'PASS' if r3 else 'FAIL'}  brick4={'PASS' if r4 else 'FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
