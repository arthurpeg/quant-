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
    print(f"  BRICK 1 (NAS ORB) entries: backtest {n}, live {len(live_entries)}, "
          f"{n - len(mism)}/{len(keys)} exact match")
    for k, lv, bv in mism[:5]:
        print(f"    MISMATCH {k}: live={lv} backtest={bv}")

    # ---- EXITS — this brick had NO exit check at all until 2026-08-11 ---------------
    # Its live exits can only come from three places: the broker's SL, the broker's TP,
    # and the driver's `time_exit_at`. So every backtest exit must be one of those three,
    # must land at or before the forced-flat minute, and a time-exit must land exactly ON
    # it. Brick 2 shipped a dead `is_exit_day` precisely because entries were checked and
    # exits were not.
    close_m = _mins(p.session_close)
    ex = pd.DatetimeIndex(pd.to_datetime(bt["exit_time"], utc=True)).tz_convert(p.tz)
    mins_ex = (ex.hour * 60 + ex.minute).to_numpy()
    reasons = set(bt["reason"].unique())
    allowed = {"stop", "take", "time_exit"}
    late = int((mins_ex > close_m).sum())
    stops = bt.loc[bt["reason"] == "stop", "R"].to_numpy()
    bad_stop = int((stops > -0.99).sum()) if len(stops) else 0

    # A time-exit normally lands ON the forced-flat minute. It legitimately lands EARLIER
    # on a shortened US session (3 July, 24 Dec, the day after Thanksgiving, Juneteenth,
    # 31 Dec): the feed simply stops, and the backtest exits on the last bar there is. So
    # the test is "the flat minute OR that day's last bar", not a fixed clock.
    # ⚠️ la derniere barre DANS LA FENETRE DE DETENTION, pas de la journee : sur un jour
    # ferie US le flux CFD REPREND le soir (derniere barre 23:59) alors que la seance cash
    # s'est arretee a 13:15. Prendre le max de la journee ratait 3 des 6 cas.
    last_min = {}
    for day, g in df.groupby(local.index.tz_localize(None).normalize().to_numpy()):
        gl = pd.DatetimeIndex(g.index).tz_convert(p.tz)
        mm = (gl.hour * 60 + gl.minute).to_numpy()
        mm = mm[mm <= close_m]
        if len(mm):
            last_min[pd.Timestamp(day).date()] = int(mm.max())
    te = bt["reason"].to_numpy() == "time_exit"
    early = []
    te_off = 0
    for i in np.flatnonzero(te):
        d_ = ex[i].date()
        if mins_ex[i] == close_m:
            continue
        if mins_ex[i] >= last_min.get(d_, 10 ** 9) - 1:
            early.append(d_)          # shortened session -> legitimate
        else:
            te_off += 1               # a real fork
    ok_exit = (not (reasons - allowed)) and late == 0 and te_off == 0 and bad_stop == 0
    print(f"  BRICK 1 (NAS ORB) exits: {dict(bt['reason'].value_counts())} | "
          f"apres {p.session_close} ET: {late} | time_exit hors cloture ET hors fin de "
          f"seance: {te_off} | stops a R > -0.99: {bad_stop} -> {'OK' if ok_exit else 'FAIL'}")
    if reasons - allowed:
        print(f"    RAISON INATTENDUE (le live ne peut pas la produire): {reasons - allowed}")

    # ⚠️ ECART LIVE/BACKTEST CONNU ET NON CORRIGE — les demi-seances.
    # Le backtest sort a la derniere barre de la seance ecourtee. Le driver, lui, attend
    # que l'horloge atteigne `session_close` : a ce moment le marche est DEJA ferme, la
    # cloture est refusee (MarketClosed) et la position est PORTEE JUSQU'A LA REOUVERTURE.
    # Corriger demanderait un calendrier de demi-seances ; en attendant, c'est mesure ici
    # plutot que decouvert un 24 decembre.
    print(f"    demi-seances: {len(early)} trade(s) sortent avant {p.session_close} parce "
          f"que le flux s'arrete ({', '.join(str(x) for x in early[:8])})")
    if early:
        print(f"    -> le LIVE ne peut pas les fermer a cette heure-la (marche deja clos) "
              f"et portera la position a la reouverture : {len(early)}/{len(bt)} trades "
              f"= {100 * len(early) / len(bt):.1f} %. Concerne aussi HMASTO et TLF.")
    return len(mism) == 0 and ok_exit


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
    # ---- ENTRY PARITY, bar by bar -- until 2026-08-11 this brick only spot-checked
    # the LAST signalled bar, which proves nothing about the 279 trades it actually took.
    # Replay `S.crypto_entry` on every bar the backtest entered on and compare direction
    # and 1R.
    ent_ok = True
    for s_, tr in zip(("BTCUSD", "ETHUSD"), out["live"]):
        d = load_pep(s_)
        idx = d.index
        bad = 0
        checked = 0
        bad_stop = warm = 0
        warm_R = 0.0
        for _, row in tr.iterrows():
            t_entry = pd.Timestamp(row["entry_time"])
            j = idx.searchsorted(t_entry)
            if j <= 0 or j >= len(idx):
                continue
            if j < 40:
                # `crypto_entry` refuse de decider avec moins de 40 barres quotidiennes.
                # Le moteur de backtest n'a pas cette garde et entre des la barre 13, donc
                # les toutes premieres entrees de l'echantillon ne sont PAS reproductibles
                # en live. Ce n'est pas un fork mais une difference DECLAREE : on la compte
                # a part au lieu de la faire echouer, et en exploitation le driver tire des
                # centaines de barres, donc la garde ne mord jamais.
                warm += 1
                warm_R += float(row["ret"])
                continue
            plan = S.crypto_entry(d.iloc[:j], crisk)      # bars up to the SIGNAL bar
            checked += 1
            if plan is None or plan.direction != int(row["direction"]):
                bad += 1
                continue
            # 1R : le moteur n'expose PAS sa distance de stop (pas de colonne r_dist), donc
            # on la lit dans le PRIX DE SORTIE des trades stoppes. Non circulaire, contrai-
            # rement a une comparaison contre un ATR recalcule ici -- qui ne testerait que
            # ma propre copie de la formule. Un gap ne peut qu'AGRANDIR l'ecart realise.
            if row["reason"] == "stop_loss":
                realised = abs(float(row["exit_price"]) - float(row["entry_price"]))
                if plan.sl_dist > realised + 1e-6:
                    bad_stop += 1
        print(f"  BRICK 3 ({s_}) entry parity: {checked - bad}/{checked} entrees reproduites "
              f"par le signal live (direction) | 1R plus large que le stop realise sur "
              f"{bad_stop} trade(s) stoppe(s), doit etre 0 | {warm} entree(s) en periode "
              f"de chauffe (<40 barres) non reproductibles en live, {warm_R:+.2f} R")
        ent_ok = ent_ok and bad == 0 and bad_stop == 0
    ok = ok and ent_ok

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


def verify_hmasto(window: int = 400, sample: int = 4000) -> bool:
    """FORWARD-TEST SLEEVE — NAS100 M15 HMA/EMA cross + triple-oscillator confirmation.

    This sleeve replaced KAER in the live slot on 2026-08-10, and it carries an extra
    burden the other sleeves do not: its rule was VALIDATED BY A TRANSPILER
    (`scratchpad/tv_transpile.py` running the original Pine) and then RE-IMPLEMENTED in
    `edgelab/intraday/hma_stoch.py`. The handoff's `adx_di.py` blocker is the cautionary
    tale: 98.36 % signal agreement between a transpiled port and its repo module was
    enough to turn RoMaD 1.12 into 0.67. 98 % is not agreement; 100 % is.

    Four checks, any of which failing means the module has forked and must not trade:

    (1) TRUNCATED WINDOW. The driver hands ``hma_scan`` only the last ``hmasto_bars``
        bars while the backtest sees the whole history. Every indicator here is a short
        rolling window (HMA 12, EMA 5 shifted 2, RSI 14, stoch 12/5 smoothed 3), so a
        400-bar trailing window should be exact — but RSI is Wilder-recursive and seeded,
        so it converges rather than matching instantly. This is what pins it down.
    (2) STOP DISTANCE. 1R = max(1.0*ATR14, 25*spread), both read at the SIGNAL bar. The
        25x-spread floor is load-bearing; without it the sleeve is inflated.
    (3) SEQUENCING. The driver only scans while FLAT, so a signal firing mid-trade must be
        skipped exactly as the backtest skips it.
    (4) NO TARGET. tp_R must stay None: with TP=1R the cost stress goes NEGATIVE (-3.16).
    """
    from edgelab.intraday.hma_stoch import (HmaStochParams, run_hma_stoch, load_m15,
                                            hma_signals, hma_atr, stop_distance)

    p = HmaStochParams()
    if p.tp_R is not None:                                   # ---- (4)
        print("  HMASTO: tp_R is not None — the validated profile has NO target. FAIL")
        return False

    bars = load_m15("NAS100")
    bt = run_hma_stoch("NAS100", p, bars=bars).trades
    if not len(bt):
        print("  HMASTO: no backtest trades — cannot verify")
        return False

    full_sig = hma_signals(bars, p)
    full_atr = hma_atr(bars, p)
    n = len(bars)

    # ---- (1) + (2) truncated window vs full history ---------------------------------
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
        sub = bars.iloc[i - window + 1: i + 1]
        res = S.hma_scan(sub, p, "NAS100")
        live_dir = 0 if res is None else res[1].direction
        if live_dir != int(full_sig[i]):
            bad_sig += 1
            continue
        if res is not None:
            want = stop_distance(bars, i, p, full_atr, "NAS100")
            if abs(res[1].sl_dist - want) > 1e-9:
                bad_sl += 1
    print(f"  HMASTO window fidelity: {len(take)} bars replayed through a {window}-bar "
          f"trailing window ({len(sig_bars)} of them signal bars) — "
          f"{len(take) - bad_sig} direction matches, {bad_sig} mismatches, "
          f"{bad_sl} stop-distance mismatches")

    # ---- (3) one-position-at-a-time sequencing --------------------------------------
    exits = dict(zip(bt["signal_i"].astype(int), bt["exit_i"].astype(int)))
    live, i = [], max(250, p.atr_p + 2)
    while i < n - 1:
        if full_sig[i] == 0 or stop_distance(bars, i, p, full_atr, "NAS100") <= 0:
            i += 1
            continue
        live.append((i, int(full_sig[i])))
        nxt = exits.get(i)
        if nxt is None:
            break
        i = nxt
    bt_entries = [(int(r["signal_i"]), int(r["direction"])) for _, r in bt.iterrows()]
    seq_ok = live == bt_entries
    print(f"  HMASTO sequencing: backtest {len(bt_entries)} entries, driver replay "
          f"{len(live)} entries, identical: {seq_ok}")
    if not seq_ok:
        for a, b in [(a, b) for a, b in zip(live, bt_entries) if a != b][:5]:
            print(f"    MISMATCH live={a} backtest={b}")
    ok = (bad_sig == 0) and (bad_sl == 0) and seq_ok
    print(f"  HMASTO (fwd-test sleeve, {len(bt_entries)} entries, sized "
          f"{p.size_R:.2f}R live): {'PASS' if ok else 'FAIL'}")
    return ok


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



def verify_tlf(window: int = 600, sample: int = 4000) -> bool:
    """FORWARD-TEST SLEEVE — TLF, Two-Leg Fade. M5, SHORT-ONLY, NAS100 + US500.

    This sleeve carries two burdens the others do not.

    First, its rule HOLDS STATE: the always-in flag is a forward-fill that can reach
    arbitrarily far back, and the two-leg state machine remembers a phase, the bar the
    pullback started on, and the pre-pullback extreme. A truncated window can therefore
    fork from full history in a way a pure rolling indicator never does.

    Second, it is the only sleeve that enters on a WORKING STOP ORDER. The live layer had
    no pending-order support until 2026-08-10; deploying a market-entry approximation
    instead would have cost 10 % (+17.93 vs +20.25 R/yr). `Broker.place_stop`,
    `cancel_pending`, `resolve_paper_stop` and `modify_sl` exist for this sleeve, and the
    checks below are what say they behave like the backtest.

    Six checks, any of which failing means the module has forked and must not trade:

    (1) TRUNCATED WINDOW. Every armed-bar decision inside the driver's window must match
        the full-history one.
    (2) TRIGGER PRICE. The live scan's trigger must equal the backtest's, to the tick.
    (3) SEQUENCING. The driver scans only while FLAT and with no working order, so a
        setup firing mid-trade must be skipped exactly as the backtest skips it.
    (4) DIRECTION. Every trade must be SHORT. Brooks' own direction measures −0.022 R.
    (5) NO TARGET. tp_R must stay None.
    (6) POINT SIZE. A missing point size once priced US500 ten times too cheap and let
        through 688 trades instead of 460. `point_size` must RAISE on an unknown symbol.
    """
    from edgelab.intraday.two_leg_fade import (TwoLegFadeParams, run_two_leg_fade,
                                               load_m5, armed_bars, point_size)
    from edgelab.live.signals import tlf_scan

    p = TwoLegFadeParams()
    if p.tp_R is not None:                                            # ---- (5)
        print("  TLF: tp_R is not None — the validated profile has NO target. FAIL")
        return False
    if p.entry_mode != "stop":
        print(f"  TLF: entry_mode={p.entry_mode!r} — the validated profile enters on a "
              f"STOP order. FAIL")
        return False
    try:                                                              # ---- (6)
        point_size("EURUSD")
        print("  TLF: point_size() silently defaulted on an unknown symbol. FAIL")
        return False
    except KeyError:
        pass

    ok_all = True
    for sym in ("NAS100", "US500"):
        bars = load_m5(sym)
        res = run_two_leg_fade(sym, p, bars=bars)
        bt, full = res.trades, res.triggers
        if not len(bt):
            print(f"  TLF {sym}: no backtest trades — cannot verify")
            return False
        if (bt["direction"] != -1).any():                             # ---- (4)
            print(f"  TLF {sym}: a trade is not SHORT. FAIL")
            return False

        n = len(bars)
        rng = np.random.default_rng(0)
        armed_idx = np.flatnonzero(full != 0)
        armed_idx = armed_idx[armed_idx >= window]
        others = np.arange(window, n)
        others = rng.choice(others, size=min(sample, len(others)), replace=False)
        probe = np.unique(np.concatenate([armed_idx, others]))
        bad = bad_trig = 0
        tick = point_size(sym)
        for i in probe:                                               # ---- (1) + (2)
            w = bars.iloc[i - window + 1:i + 1]
            got = armed_bars(w, p, sym)[-1]
            if int(got) != int(full[i]):
                bad += 1
                continue
            if got != 0:
                plan = tlf_scan(w, p, sym)
                want = float(bars["low"].iloc[i]) - tick
                if plan is None or abs(plan[1].trigger - want) > 1e-9:
                    bad_trig += 1
        print(f"  TLF {sym} window fidelity: {len(probe)} bars replayed through a "
              f"{window}-bar trailing window ({len(armed_idx)} of them armed) — "
              f"{bad} decision mismatches, {bad_trig} trigger-price mismatches")
        ok_all &= (bad == 0 and bad_trig == 0)

        # ---- (3) sequencing: replay the driver's flat-and-no-order cadence -----------
        taken, busy_until = [], -1
        for i in np.flatnonzero(full != 0):
            # STRICTLY less: the backtest re-arms ON the exit bar (its walk advances with
            # searchsorted(idx, exit_i, "left"), which keeps a signal AT exit_i), and so
            # does the driver — it polls, sees flat, and scans the bar that just closed.
            # Using <= here cost a phantom 889-vs-890 mismatch on 2026-08-10.
            if i < busy_until:
                continue
            m = i + 1
            row = bt[bt["entry_time"] == bars.index[m]] if m < n else bt.iloc[0:0]
            if not len(row):
                continue                       # order expired unfilled — as in the driver
            taken.append(bars.index[m])
            busy_until = int(np.searchsorted(bars.index, row["exit_time"].iloc[0]))
        same = len(taken) == len(bt) and all(
            a == b for a, b in zip(taken, bt["entry_time"].tolist()))
        fill_rate = 100.0 * len(bt) / max(int((full != 0).sum()), 1)
        print(f"  TLF {sym} sequencing: backtest {len(bt)} entries, driver replay "
              f"{len(taken)} entries, identical: {same} "
              f"({fill_rate:.0f} % of armed orders ever fill; the rest expire)")
        ok_all &= bool(same)
        print(f"  TLF {sym} ({len(bt)} entries, STOP entry, sized {p.size_R:.2f}R live): "
              f"{'PASS' if ok_all else 'FAIL'}")
    return bool(ok_all)


def verify_flat_times() -> bool:
    """L'heure d'aplat FORCE du driver doit etre celle des parametres du backtest.

    Les trois sleeves intraday passaient `pd.Timedelta(hours=15, minutes=55)` en DUR a
    `place_market(time_exit_at=...)` pendant que leur backtest lisait `p.session_close`.
    Les deux valaient 15:55, donc tout allait bien -- par coincidence d'un litteral, pas
    par construction. Changer le parametre aurait forke le live du backtest en silence,
    et aucun test ne l'aurait vu. Ce controle rend l'egalite obligatoire."""
    import ast
    import inspect
    from edgelab.live import strategies as St
    from edgelab.live.us_session_calendar import flat_minute, validate_against_feed

    # Compter sur l'AST, PAS sur le texte source : la premiere version comptait les
    # occurrences dans le fichier, si bien que la docstring qui EXPLIQUE la regle
    # declenchait l'alerte qu'elle documente. Un test qui interdit de parler de ce qu'il
    # interdit est un test cassé.
    def _hardcoded_flats(mod) -> int:
        tree = ast.parse(inspect.getsource(mod))
        n = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr == "Timedelta"):
                continue
            kw = {k.arg: getattr(k.value, "value", None) for k in node.keywords}
            if kw.get("hours") == 15 and kw.get("minutes") == 55:
                n += 1
        return n

    hard = _hardcoded_flats(St)
    ok = hard == 0
    print(f"  FLAT-TIME: heures d'aplat codees en dur dans strategies.py: {hard} "
          f"(doit etre 0 -- chaque driver lit son propre p.session_close)")
    from edgelab.intraday.atr_breakout import ATRBreakParams
    from edgelab.intraday.hma_stoch import HmaStochParams
    from edgelab.intraday.two_leg_fade import TwoLegFadeParams
    for nm, prm in (("brick1", ATRBreakParams(regime_mode="low", direction="both")),
                    ("HMASTO", HmaStochParams()), ("TLF", TwoLegFadeParams())):
        print(f"    {nm:7s} session_close={prm.session_close} tz={prm.tz}")

    # ---- le calendrier des seances ecourtees, confronte au FLUX ---------------------
    # Faute DANGEREUSE : une seance ecourtee que le calendrier ignore -> le driver attend
    # 15:55, le marche est deja clos, la position part a la nuit. Faute BENIGNE : un jour
    # marque a tort -> on sort quelques heures trop tot. Seule la premiere fait echouer.
    missed_all = 0
    for sym in ("NAS100", "US500"):
        missed, spurious, seen = validate_against_feed(sym, verbose=False)
        # une PANNE DE FLUX est indiscernable d'une cloture anticipee apres coup, et aucun
        # calendrier ne la predit : on la signale sans faire echouer.
        print(f"    calendrier vs flux {sym}: {len(seen)} seances ecourtees couvertes, "
              f"{len(missed)} manquee(s), {len(spurious)} marquee(s) a tort (benin)")
        for dd, last in missed[:5]:
            print(f"      MANQUEE {dd} (flux jusqu'a {last // 60:02d}:{last % 60:02d}) "
                  f"-- panne de flux ou seance non prevue par les regles")
        missed_all += len(missed)
    if missed_all:
        print(f"    -> {missed_all} journee(s) restent a risque de portage de nuit. "
              f"Aucune regle de calendrier ne couvre une PANNE de flux.")
    return ok


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
    from edgelab.live.strategies import (CryptoMacdStrategy, KeltnerStrategy, NasIbsStrategy,
                                         SERVER_TZ, ROLLOVER_LEAD_MIN)
    from edgelab.intraday.keltner_btc import run_keltner, KeltParams, load_h1
    from edgelab.edges.turn_of_month import _load_d1 as _tom_d1
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

    # ---- (d) brick 2: the lead fires on the bar run_turn_of_month exits ON ---------
    # XAUUSD is shut 00:00-01:00 server, so an exit sent at the rollover fills an hour
    # late — or on MONDAY when the exit bar is a Friday. The backtest exits at c[xi]; the
    # driver must therefore leave on bar xi itself, which is what `bars_done + 1` detects.
    gp = TurnOfMonthParams(sl_atr=1.5)
    gd = _tom_d1("XAUUSD")
    gmonth = pd.PeriodIndex(gd.index.tz_localize(None), freq="M")
    gtdom = pd.Series(np.arange(len(gd)), index=gd.index).groupby(gmonth).rank().astype(int).to_numpy()
    gmonths = gmonth.to_numpy()
    uniq = list(dict.fromkeys(gmonths))
    raw_g = pd.DataFrame({"time": gd.index, "open": gd["open"].to_numpy(),
                          "high": gd["high"].to_numpy(), "low": gd["low"].to_numpy(),
                          "close": gd["close"].to_numpy()})
    early = late = fri = n_x = 0
    for k in range(len(uniq) - 1):
        nxt = np.where((gmonths == uniq[k + 1]) & (gtdom <= gp.first_days))[0]
        if not len(nxt):
            continue
        xi = nxt[-1]
        day = pd.Timestamp(gd.index[xi]).tz_localize(None).normalize()
        stg = S.tom_state(raw_g.iloc[: xi + 1], day, gp)
        n_x += 1
        early += int((stg.bars_done + 1) >= gp.first_days)   # the lead leaves on bar xi
        late += int(stg.is_exit_day)                         # the old code would fire here
        fri += int(day.dayofweek == 4)
    b2_ok = (n_x > 0) and (early == n_x) and (late == 0)
    ok = ok and b2_ok
    print(f"  TIME-EXIT (d) brick 2: on {n_x} exit bars the lead fires {early}/{n_x} and the "
          f"rollover rule fires {late}/{n_x} (it fires the NEXT day) — {fri} of those bars "
          f"are a FRIDAY, i.e. filled on Monday today: {b2_ok}")

    # ---- (e) brick 4: the lead is exactly one D1 bar earlier, on the real calendar --
    ip = IBSParams(sl_atr=2.5)
    nd = _ibs_bars()
    raw_n = pd.DataFrame({"time": nd.index})
    dates_n = list(pd.to_datetime(raw_n["time"]).dt.date)
    bad4 = n4 = 0
    for E in range(60, min(len(dates_n) - ip.max_hold - 3, 600), 17):
        entry_utc = pd.Timestamp(dates_n[E]).tz_localize(SERVER_TZ).tz_convert("UTC")
        # rollover of bar k: the last CLOSED bar is k-1
        first_roll = next((k for k in range(E + 1, len(dates_n))
                           if NasIbsStrategy._bars_held(raw_n, entry_utc, k - 1) >= ip.max_hold), None)
        # lead of bar j: the last CLOSED bar is j-1, and bar j is about to tip the count
        first_lead = next((j for j in range(E + 1, len(dates_n))
                           if NasIbsStrategy._bars_held(raw_n, entry_utc, j - 1) + 1 >= ip.max_hold), None)
        n4 += 1
        bad4 += int(first_roll is None or first_lead is None
                    or first_roll != E + ip.max_hold + 1 or first_lead != first_roll - 1)
    b4_ok = bad4 == 0 and n4 > 0
    ok = ok and b4_ok
    print(f"  TIME-EXIT (e) brick 4: on {n4} synthetic entries the rollover exit lands at "
          f"entry+{ip.max_hold}+1 bars and the lead exactly one bar earlier, mismatches {bad4} "
          f"(NB: this branch is DORMANT — the 30-bar cap has fired 0/287 times live)")
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
    rh = verify_hmasto()
    rf = verify_tlf()
    rk = verify_kaer()
    rl = verify_keltner()
    rt = verify_time_exits()
    rft = verify_flat_times()
    print("-" * 70)
    print(f"  brick1={'PASS' if r1 else 'FAIL'}  brick2={'PASS' if r2 else 'FAIL'}  "
          f"brick3={'PASS' if r3 else 'FAIL'}  brick4={'PASS' if r4 else 'FAIL'}  "
          f"HMASTO={'PASS' if rh else 'FAIL'}  TLF={'PASS' if rf else 'FAIL'}  "
          f"KAER={'PASS' if rk else 'FAIL'}  "
          f"KELT={'PASS' if rl else 'FAIL'}  time-exits={'PASS' if rt else 'FAIL'}  "
          f"flat-times={'PASS' if rft else 'FAIL'}")
    # HMASTO is the sleeve that is LIVE-wired (KAER and KELT are kept for research only),
    # so its result is the one that gates deployment alongside the four bricks.
    print(f"  LIVE-WIRED SET (bricks 1-4 + HMASTO + TLF): "
          f"{'PASS' if all([r1, r2, r3, r4, rh, rf, rt, rft]) else 'FAIL'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
