---
type: experiment
id: exp-005
updated: 2026-07-11
status: open
verdict: open
horizon: intraday (single-day) directional breakout
universe: single asset — Nasdaq (NAS100), MT5 (prop-firm whitelisted, index_us)
code: [mql5/IntradayVolatilityBreakout.mq5, backtest_breakout_us30.py]
---

# exp-005 — MT5 intraday volatility breakout (Nasdaq)

**Hypothesis.** A rules-based intraday ATR breakout on the **Nasdaq (NAS100)** —
enter when price breaks the US-open (09:30 NY) price ± `0.25·ATR(D1)` inside a fixed
entry window, fixed 2:1 R:R, filtered by a **low-volatility daily regime** (ATR(3d) <
ATR(20d)), flat before the US cash close — produces positive expectancy net of
realistic costs.

**Broker-time resolution (RESOLVED 2026-07-11).** The EA's `Entry/Exit` inputs are
in **broker server time** (`TimeCurrent()`), never local/Paris time. User's broker =
Paris + 1h = **EET/EEST (UTC+3 in summer)** — the standard MT5 server tz. With that,
the DEFAULT hours map cleanly to the US session, so **no change is needed** for the
US-open breakout intent:
| Event | Broker (default) | New York | Paris |
|---|---|---|---|
| Entry start | 16:30 | 09:30 (US open) | 15:30 |
| Latest entry | 18:05 | 11:05 | 17:05 |
| Exit (flat) | 22:55 | 15:55 (pre-close) | 21:55 |
⚠️ **DST caveat:** EU vs US DST transitions differ (~3 wks in March, ~1 wk late Oct)
→ the broker↔NY offset slips 1h in those windows. Same issue documented in
`config.py`. Verify the exact server offset in MT5 (Market Watch time vs UTC).

**Setup.** External MQL5 Expert Advisor (`IntradayVolatilityBreakout.mq5`, v2.00),
run in the MT5 Strategy Tester. NOT part of the Python pipeline. Structural params
are deliberately fixed and flagged "Do NOT optimize" (RR, regime periods 3d/20d,
spread cap). Fixed-risk sizing (500 acct-ccy/trade). Confirmation on M5/M10/M15
candle close.

**Prior (from the wiki, read before testing).** ⚠️ Strong negative prior:
- Ledger row: **single-asset intraday direction = no edge** (AUC ≈ 0.52). A breakout
  is a directional bet, and this is a single index — the row applies squarely.
- The separate short-gold-artifact ledger row is less directly applicable (this is
  NAS100, not gold) but reinforces the "single-asset intraday wins are usually
  artifacts" pattern.
- Note: NAS100 **is** prop-firm tradable ([[prop-firm-universe]], index_us) — unlike
  the equities in [[exp-004-xsection-breadth-poc]]. So a surviving edge here would be
  deployable, which raises the bar for skepticism, not lowers it.
- Counterpoint: it uses a **volatility regime filter**, and vol is the one thing the
  project found predictable ([[exp-002-v3-mt5-four-angles]], IC 0.47) — using it as a
  *filter* (not as alpha) is methodologically sound.
→ Conclusion: worth a **rigorous** test, not adoption. The bar for belief is high
because Gold intraday breakout backtests notoriously look good and die live.

**Code review (blockers found before any backtest).**
1. ✅ RESOLVED — all times are **broker server time**. Broker = EET/EEST (UTC+3
   summer), so defaults map to the US session (see table above). No change needed;
   just mind the DST windows. Ties to the project's UTC discipline ([[data-sources]]).
2. `SYMBOL_LAST` returns **0 on index CFDs (NAS100)** when `Use_Candle_Close=false` →
   `GetSignalPrice()` returns 0 → never trades. Exactly the project's
   "last=0 on MT5 CFD" finding. Keep `Use_Candle_Close=true` or use Bid.
3. `ORDER_FILLING_FOK` may be rejected on NAS100 (err 10030) → use IOC / detect mode.
4. `MathMax(lots, min_lot)` can silently risk **more** than `Fixed_Risk_Amount`.
5. `Max_Spread_Points` default 30 is captioned "~3× Gold spread" — set it to ~3× the
   **Nasdaq** typical spread instead (leftover comment from the template).
6. Must run tester in **"Every tick based on real ticks"** with **real spread**.
No blatant look-ahead: ATR and confirmation candle are read at `shift 1` (closed
bar) — clean.

**Test protocol (success criteria set in advance).**
- Compile (MetaEditor F7) → Strategy Tester, XAUUSD, real ticks, real spread.
- Walk-forward: any optimization on 2018-2022, **judge only blind OOS 2023-2026**.
- Do NOT optimize the structural params.
- Cost sensitivity: rerun at spread ×1.5 + slippage; if the edge dies → [[ledger]].
- Believe it only if OOS Sharpe > 0.7 AND profit factor > 1.2 net of costs.
- Optional cross-check: reimplement the breakout in Python (`mt5_loader.py`,
  `backtest_exec.py`) and walk-forward with the project's honest costs, independent
  of the optimistic MT5 tester.

**Result — Python proxy cross-check** (`backtest_breakout_us30.py`, run 2026-07-12).
⚠️ Proxy only: **US30 not NAS100, H1 not M1** — tests the *concept*, not the EA. Data
caps at H1 in `data_cache_mt5/`; a faithful M1 NAS100 port isn't possible without
pulling intraday data from MT5. Same logic: open±0.25·ATR(D1) breakout, RR 2, ATR(3d)<
ATR(20d) low-vol regime, flat by session end, 6 pt round-trip cost. US30 2019-2026:

| Variant (net) | n | win% | E[R] | totR | PF | Sharpe_ann |
|---|---|---|---|---|---|---|
| **regime-low / both** (EA default) | 590 | 42.9% | +0.010 | +5.8 | 1.02 | +0.07 |
| regime-low / long | 292 | 46.9% | +0.067 | +19.5 | 1.14 | +0.36 |
| regime-low / short | 305 | 39.0% | −0.039 | −12.0 | 0.93 | −0.21 |
| no-regime / both | 1127 | 41.6% | −0.007 | −7.9 | 0.99 | −0.07 |
| regime-high / both | 537 | 40.2% | −0.025 | −13.7 | 0.96 | −0.17 |

- **In "both directions" (the EA default) → flat** (PF 1.02, Sharpe ≈ 0). +5.8 R over 7
  years = nothing.
- **All the positivity is on the LONG side; short loses everywhere** → this is the
  ledger's "long bias = bull-market drift, not an edge," not a breakout edge.
- The low-vol regime filter helps marginally (both: +0.010 vs no-regime −0.007;
  regime-high −0.025) → consistent with [[exp-002-v3-mt5-four-angles]]: vol is a
  *filter*, not alpha. But it doesn't create an edge.
- Caveats: H1 coarseness + conservative same-bar-SL rule bias results DOWN; US30 ≠
  NAS100 (Nasdaq more bull-trendy → long-only would look even better but for the same
  drift reason). So the proxy **reinforces the negative prior** but does not settle the
  NAS100-M1 case.

**Result — MT5 (real NAS100, M1).** 🚧 Blocked on **data quality**. User is on
**MetaQuotes-Demo**, a synthetic/aggregated feed — unreliable for M1 index backtests
(see [[data-sources]]). A tester run on it would not be trustworthy either way. The
definitive test needs the **actual prop-firm broker's M1 feed** (or research-grade
futures/tick data). (Aside: spread filter default 30 was blocking all trades on
Nasdaq, real spread ~90 pts → raise `Max_Spread_Points`.)

**Verdict.** open — leaning **no-edge** on the proxy evidence; awaiting the MT5 NAS100
M1 run for the definitive call.

**Why it matters / next.** First *externally-sourced, rules-based* strategy tested
against the wiki's priors. If it fails OOS/cost tests → ledger row (single-asset
Gold breakout). If it survives → the vol-regime filter would be the likely reason,
reinforcing [[exp-002-v3-mt5-four-angles]]'s "vol is for risk management" lesson.

**Links.** [[exp-001-v1-single-tf-direction]], [[exp-002-v3-mt5-four-angles]],
[[triple-barrier]], [[leakage]], [[data-sources]], [[prop-firm-universe]].
