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
    """Brick 2 parity, in two parts.

    (a) ENTRY days — the original check: does the live calendar flag the same month-ends
        the backtest enters on, with the same 1R distance?
    (b) TRADE replay — the part that was MISSING, and its absence let a real bug ship:
        ``is_exit_day`` was structurally always False (0 exit days over 2018-2026), so
        the live gold position could never time-exit and rode to its stop instead. A
        harness that only checks entries certifies half a brick. This replays
        ``GoldTomStrategy``'s real once-per-rollover cadence — the only price it can get
        is the OPEN of the day it wakes on — and compares whole trades to the backtest.
    """
    p = TurnOfMonthParams(sl_atr=1.5)
    d1 = pd.read_parquet(MT5_DIR / "XAUUSD_D1.parquet")
    bt = run_turn_of_month("XAUUSD", p)
    bt_days = {pd.Timestamp(r["date"]).normalize(): round(float(r["r_dist"]), 3)
               for _, r in bt.iterrows()}

    # ---- (a) walk each calendar day the backtest could enter on, ask the live state ----
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
    print(f"  BRICK 2 (turn-of-month) entry days: {ok}/{checked} backtest entry-days matched "
          f"by live (business-day calendar approximation)")
    for d in diffs[:5]:
        print(f"    DIFF {d[0]}: live is_entry={d[1]} sl={d[2]} vs backtest r_dist={d[3]}")

    # ---- (b) replay the driver's rollover cadence over the same D1 bars ----------------
    d = d1.copy()
    d.columns = [c.lower() for c in d.columns]
    d["t"] = pd.to_datetime(d["time"], utc=True)
    d = d.set_index("t")[["open", "high", "low", "close"]].astype(float).sort_index()
    o, lo = d["open"].to_numpy(), d["low"].to_numpy()
    days = d.index.tz_convert("UTC").tz_localize(None).normalize()
    cost_frac = 2 * p.cost_bps / 1e4

    live_trades, in_pos, entry_px, risk, stop = [], False, 0.0, 0.0, 0.0
    unexited = 0
    for i in range(len(d)):
        st = S.tom_state(d, days[i], p)          # what the driver sees at this rollover
        if in_pos and st.is_exit_day:            # close at the price the rollover offers
            live_trades.append((entry_px, o[i], "time_exit",
                                (o[i] - entry_px - cost_frac * entry_px) / risk))
            in_pos = False
        if (not in_pos) and st.is_entry_day and st.sl_dist > 0:
            entry_px, risk = o[i], st.sl_dist
            stop, in_pos = entry_px - risk, True
        if in_pos and lo[i] <= stop:             # broker-side stop, intrabar (pessimistic)
            px = stop if o[i] >= stop else o[i]
            live_trades.append((entry_px, px, "stop",
                                (px - entry_px - cost_frac * entry_px) / risk))
            in_pos = False
    if in_pos:
        unexited = 1                             # still holding at the end of the sample

    # Compare LIKE FOR LIKE: the months whose entry day the live calendar cannot flag are
    # months the market is shut on (Good Friday month-ends) — live skips them by design,
    # so charging their P&L to the exit logic would hide what this check is for.
    skipped = [d for d, _ in ((k, v) for k, v in bt_days.items()) if not S.tom_state(d1, d, p).is_entry_day]
    lv_R = sum(t[3] for t in live_trades)
    bt_R = float(bt["R"].sum())
    cmp_R = float(bt[~bt["date"].isin({s.date() for s in skipped})]["R"].sum())
    n_exit = sum(1 for t in live_trades if t[2] == "time_exit")
    print(f"  BRICK 2 (turn-of-month) trade replay: live {len(live_trades)} trades "
          f"({n_exit} time-exit, {len(live_trades)-n_exit} stopped) vs backtest {len(bt)} "
          f"| total R {lv_R:+.2f} vs {bt_R:+.2f}, and {cmp_R:+.2f} on the {len(bt)-len(skipped)} "
          f"comparable months -> exit tracking error {lv_R - cmp_R:+.2f} R "
          f"({len(skipped)} months skipped live, worth {bt_R - cmp_R:+.2f} R: market shut at that month-end)")
    if n_exit == 0:
        print("    FAIL: the live calendar never produces a time-exit -> the position can "
              "only leave on its stop (this was the 2026-08-04 bug).")

    # entry tolerance: the business-day calendar may miss a few holiday-shifted month-ends.
    # exit gate: every trade must be able to leave on time, and the replay must track the
    # comparable backtest months to within 1 R over the whole sample (measured: -0.33 R).
    entries_ok = ok / max(checked, 1) >= 0.80
    exits_ok = n_exit > 0 and unexited == 0 and abs(lv_R - cmp_R) <= 1.0
    return entries_ok and exits_ok


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


def verify_kaer(window: int = 2600, sample: int = 4000) -> bool:
    """FORWARD-TEST SLEEVE — NAS100 M15 Kaufman ER breakout.

    Two things can make this sleeve diverge live, and neither is the rule itself (the
    driver calls ``kaer_signals``, the same function the backtest calls):

    (1) THE TRUNCATED WINDOW. The driver hands ``kaer_scan`` only the last
        ``kaer_bars`` bars, while the backtest sees the whole history. The ER gate is a
        *rolling percentile over 1820 bars*, so a window shorter than that would silently
        change every decision — and it would do so quietly, not by crashing. We therefore
        replay a large sample of bars through a trailing window of exactly the size the
        config uses and require the decision to be identical to the full-history one.

    (2) SEQUENCING. The driver only scans while FLAT, so a signal firing mid-trade must be
        skipped exactly as the backtest skips it. Replayed here on the precomputed signal
        array against the backtest's own entry bars.
    """
    from edgelab.intraday.kaer import KaerParams, run_kaer, load_m15, kaer_signals, kaer_atr

    p = KaerParams()
    bars = load_m15("NAS100")
    bt = run_kaer("NAS100", p, bars=bars).trades
    if not len(bt):
        print("  KAER: no backtest trades — cannot verify")
        return False

    full_sig = kaer_signals(bars, p)
    full_atr = kaer_atr(bars, p)
    n = len(bars)

    # ---- (1) truncated window vs full history --------------------------------------
    rng = np.random.default_rng(0)
    sig_bars = np.flatnonzero(full_sig != 0)
    sig_bars = sig_bars[sig_bars >= window]
    others = np.arange(window, n)
    others = others[full_sig[others] == 0]
    take = np.concatenate([
        sig_bars,
        rng.choice(others, min(sample, len(others)), replace=False)])
    bad_sig = bad_sl = 0
    for i in take:
        res = S.kaer_scan(bars.iloc[i - window + 1: i + 1], p)
        live_dir = 0 if res is None else res[1].direction
        if live_dir != int(full_sig[i]):
            bad_sig += 1
            continue
        if res is not None:
            if abs(res[1].sl_dist - p.k_stop * full_atr[i]) > 1e-9:
                bad_sl += 1
    print(f"  KAER window fidelity: {len(take)} bars replayed through a {window}-bar "
          f"trailing window ({len(sig_bars)} of them signal bars) — "
          f"{len(take) - bad_sig} direction matches, {bad_sig} mismatches, "
          f"{bad_sl} stop-distance mismatches")

    # ---- (2) one-position-at-a-time sequencing --------------------------------------
    exits = dict(zip(bt["signal_bar"].astype(int), bt["exit_bar"].astype(int)))
    live, i, warm = [], 250, 250
    while i < n - 1:
        if full_sig[i] == 0 or not np.isfinite(full_atr[i]) or full_atr[i] <= 0:
            i += 1
            continue
        live.append((i, int(full_sig[i])))
        nxt = exits.get(i)
        if nxt is None:
            break
        i = nxt
    bt_entries = [(int(r["signal_bar"]), int(r["direction"])) for _, r in bt.iterrows()]
    seq_ok = live == bt_entries
    print(f"  KAER sequencing: backtest {len(bt_entries)} entries, driver replay "
          f"{len(live)} entries, identical: {seq_ok}")
    if not seq_ok:
        for a, b in [(a, b) for a, b in zip(live, bt_entries) if a != b][:5]:
            print(f"    MISMATCH live={a} backtest={b}")
    ok = (bad_sig == 0) and (bad_sl == 0) and seq_ok
    print(f"  KAER (fwd-test sleeve, {len(bt_entries)} entries, sized "
          f"{p.size_R:.2f}R live): {'PASS' if ok else 'FAIL'}")
    return ok


def verify_keltner(window: int = 600, sample: int = 4000) -> bool:
    """FORWARD-TEST SLEEVE — BTCUSD H1 Keltner-band breakout.

    Same two failure modes as KAER, and neither is the rule itself (the driver calls
    `keltner_signals`, the function the backtest calls):

    (1) THE TRUNCATED WINDOW. The driver hands `keltner_scan` only the last `kelt_bars`
        (600) bars while the backtest sees 66k. EMA(20) is an infinite-memory filter, so a
        short window changes it — quietly, never by crashing. Replayed here through a
        window of exactly the configured size.
    (2) THE FLOORED STOP. 1R = max(3*ATR14, 25*spread) and the floor is part of the RULE.
        A live driver computing the unfloored stop would risk 57% more R/yr on paper and
        place stops inside the spread on the thin tail. Checked to the last decimal.

    Plus the one-position-at-a-time sequencing, replayed against the backtest's own entries.
    """
    from edgelab.intraday.keltner_btc import (KeltParams, run_keltner, load_h1,
                                              keltner_signals, stop_distance)

    p = KeltParams()
    bars = load_h1("BTCUSD")
    bt = run_keltner("BTCUSD", p, bars=bars).trades
    if not len(bt):
        print("  KELT: no backtest trades — cannot verify")
        return False

    full = keltner_signals(bars, p)
    n = len(bars)

    rng = np.random.default_rng(0)
    sig_bars = np.flatnonzero(full != 0)
    sig_bars = sig_bars[sig_bars >= window]
    others = np.arange(window, n)
    others = others[full[others] == 0]
    take = np.concatenate([rng.choice(sig_bars, min(sample, len(sig_bars)), replace=False),
                           rng.choice(others, min(sample, len(others)), replace=False)])
    bad_sig = bad_sl = 0
    for i in take:
        w = bars.iloc[i - window + 1: i + 1]
        res = S.keltner_scan(w, p)
        live_dir = 0 if res is None else res[1].direction
        if live_dir != int(full[i]):
            bad_sig += 1
            continue
        if res is not None:
            ref = stop_distance(bars, i, p)
            if abs(res[1].sl_dist - ref) > 1e-9:
                bad_sl += 1
    print(f"  KELT window fidelity: {len(take)} bars replayed through a {window}-bar "
          f"trailing window — {bad_sig} direction mismatches, {bad_sl} floored-stop "
          f"mismatches")

    exits = dict(zip(bt["signal_bar"].astype(int), bt["exit_bar"].astype(int)))
    live, i = [], 250
    while i < n - 1:
        if full[i] == 0 or stop_distance(bars, i, p) <= 0:
            i += 1
            continue
        live.append((i, int(full[i])))
        nxt = exits.get(i)
        if nxt is None:
            break
        i = nxt
    bt_entries = [(int(r["signal_bar"]), int(r["direction"])) for _, r in bt.iterrows()]
    seq_ok = live == bt_entries
    print(f"  KELT sequencing: backtest {len(bt_entries)} entries, driver replay "
          f"{len(live)} entries, identical: {seq_ok}")
    ok = (bad_sig == 0) and (bad_sl == 0) and seq_ok
    print(f"  KELT (fwd-test sleeve, {len(bt_entries)} entries, sized {p.size_R:.2f}R "
          f"live): {'PASS' if ok else 'FAIL'}")
    return ok


class _FakeBroker:
    """Broker stand-in for the time-exit replay: serves a fixed D1 frame, records closes."""

    live = True

    def __init__(self, raw: pd.DataFrame):
        self._raw = raw
        self.closed_at: pd.Timestamp | None = None
        self.closed_why: str | None = None

    def get_bars_raw(self, logical, timeframe, count=90):
        return self._raw.tail(count).reset_index(drop=True).copy()

    def open_position(self, magic):          # driven explicitly by the replay
        raise NotImplementedError

    def close(self, pos, price, reason, now_utc):
        self.closed_at, self.closed_why = now_utc, reason
        return 0.0


def verify_time_exits() -> bool:
    """The DRIVER's clock arithmetic — the layer the other checks never touch.

    verify_brick3/verify_keltner prove the signal and the engine cadence. Neither ever
    looked at how the running driver converts an MT5 position timestamp into a bar count,
    and that is exactly where two silent one-sided errors lived: MT5 hands back the SERVER
    wall clock labelled as UTC, and it was compared against true-UTC clocks. Brick 3 held
    31 D1 bars instead of 30; KELT held 99+ H1 bars instead of 96.

    Three assertions, all against the frozen backtests' own convention:
      (a) server_epoch_to_utc reinterprets the stamp (summer +3 h, winter +2 h);
      (b) brick 3 closes on the bar the engine closes on — at the rollover if that is the
          first pass it gets, and ROLLOVER_LEAD_MIN early when it is watching;
      (c) KELT's completed-bar count hits max_bars exactly on run_keltner's own exit bar.
    """
    from edgelab.live.broker import server_epoch_to_utc
    from edgelab.live.strategies import (CryptoMacdStrategy, KeltnerStrategy, SERVER_TZ,
                                         ROLLOVER_LEAD_MIN)
    from edgelab.intraday.keltner_btc import run_keltner, KeltParams, load_h1
    ok = True

    # ---- (a) the stamp -----------------------------------------------------------
    def _epoch(naive: str) -> int:
        return int((pd.Timestamp(naive) - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s"))

    cases = [("2026-07-29 19:29:09", "2026-07-29 16:29:09"),    # EEST, +3
             ("2026-01-15 12:00:00", "2026-01-15 10:00:00")]    # EET,  +2
    stamp_ok = all(server_epoch_to_utc(_epoch(s)) == pd.Timestamp(e, tz="UTC")
                   for s, e in cases)
    ok = ok and stamp_ok
    print(f"  TIME-EXIT (a) server stamp -> true UTC on both DST sides: {stamp_ok}")

    # ---- (b) brick 3: 30 D1 bars, counted off the broker's own frame -------------
    n_bars = 30
    days = pd.date_range("2026-06-01", periods=120, freq="D")           # server midnights
    raw = pd.DataFrame({"time": days, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    strat = CryptoMacdStrategy({}, "BTCUSD", {"time_exit_bars": n_bars})

    class _Pos:
        magic, symbol, direction, sl_dist = 103, "BTCUSD", -1, 1.0
        open_time = None

    E = 20                                                   # entry bar index
    entry_srv = pd.Timestamp(days[E]).tz_localize(SERVER_TZ)  # this bar's rollover
    _Pos.open_time = (entry_srv + pd.Timedelta(seconds=20)).tz_convert("UTC")
    engine_exit_bar = E + n_bars          # engine: exit at the OPEN of entry_i + 30

    def _replay(watch_lead: bool):
        """Walk the broker days; return (bar_index, server_time) of the close."""
        for k in range(E, E + n_bars + 5):
            srv_day = pd.Timestamp(days[k])
            stamps = [srv_day.tz_localize(SERVER_TZ)]                       # 00:00 rollover
            if watch_lead:
                stamps.append((srv_day + pd.Timedelta(days=1)
                               - pd.Timedelta(minutes=ROLLOVER_LEAD_MIN)).tz_localize(SERVER_TZ))
            for srv in stamps:
                fb = _FakeBroker(raw[raw["time"] <= srv_day])   # bars up to the forming one
                strat._manage(fb, _Pos, srv.tz_convert("UTC"), srv.date())
                if fb.closed_at is not None:
                    return k, srv, fb.closed_why
        return None, None, None

    k_roll, srv_roll, why_roll = _replay(watch_lead=False)
    k_lead, srv_lead, why_lead = _replay(watch_lead=True)
    # rollover-only runner: closes on the engine's own exit bar, at its open
    b_roll = (k_roll == engine_exit_bar and why_roll == "time_exit")
    # watching runner: closes ROLLOVER_LEAD_MIN before that same rollover
    want_lead = (pd.Timestamp(days[engine_exit_bar]) - pd.Timedelta(minutes=ROLLOVER_LEAD_MIN))
    b_lead = (srv_lead is not None
              and srv_lead.tz_localize(None) == want_lead and why_lead == "time_exit")
    ok = ok and b_roll and b_lead
    print(f"  TIME-EXIT (b) brick 3: engine exits at bar {engine_exit_bar}; driver at "
          f"rollover {k_roll} ({b_roll}), early at {srv_lead} "
          f"= {ROLLOVER_LEAD_MIN:.0f} min before it ({b_lead})")

    # ---- (c) KELT: bars, not elapsed hours --------------------------------------
    # Replayed on the REAL cached H1 index, gaps and all — the BTCUSD feed has 137 two-day
    # holes, and run_keltner caps on an INDEX distance (exit_bar - entry_bar). An
    # elapsed-hours count disagreed with it on 155 of the first 200 time-exit trades.
    p = KeltParams()
    te = run_keltner(p=p).trades.query("reason == 'time_exit'")
    idx = load_h1("BTCUSD").index
    bad = holed = n_ck = 0
    for _, t in te.iterrows():
        m, end = int(t["entry_bar"]), int(t["exit_bar"])
        if end >= len(idx) - 1:
            continue          # last trade: run_keltner clips `end` at the data edge, not a cap
        frame = pd.DataFrame(index=idx[: end + 1])            # bars completed at the exit
        fill = idx[m] + pd.Timedelta(minutes=3)               # the live fill, a few min in
        n_ck += 1
        bad += int(KeltnerStrategy._held(frame, fill) != p.max_bars)
        holed += int((idx[end] - idx[m]) != pd.Timedelta(hours=end - m))
    kelt_ok = bad == 0 and n_ck > 0
    ok = ok and kelt_ok
    print(f"  TIME-EXIT (c) KELT: _held == max_bars ({p.max_bars}) on {n_ck} time-exit "
          f"trades ({holed} of them span a gap in the feed), mismatches {bad}")
    print(f"  TIME-EXIT: {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print("=" * 70)
    print("  LIVE-vs-BACKTEST signal verification")
    print("=" * 70)
    r1 = verify_brick1()
    r2 = verify_brick2()
    r3 = verify_brick3()
    r4 = verify_brick4()
    rk = verify_kaer()
    rl = verify_keltner()
    rt = verify_time_exits()
    print("-" * 70)
    print(f"  brick1={'PASS' if r1 else 'FAIL'}  brick2={'PASS' if r2 else 'FAIL'}  "
          f"brick3={'PASS' if r3 else 'FAIL'}  brick4={'PASS' if r4 else 'FAIL'}  "
          f"KAER={'PASS' if rk else 'FAIL'}  KELT={'PASS' if rl else 'FAIL'}  "
          f"time-exits={'PASS' if rt else 'FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
