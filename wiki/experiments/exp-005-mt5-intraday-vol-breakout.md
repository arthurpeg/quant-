---
type: experiment
id: exp-005
updated: 2026-07-11
status: open
verdict: marginal-positive
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

**EA v2.10 — backtest-duration decoupling (2026-07-27).** The EA no longer reads
`PERIOD_M1`: the only functional M1 dependency was the entry-time open in
`CalculateLevels` (anchor moved to the confirmation TF, whose bar opening at
`Entry_Time` has the identical open — behaviour unchanged for default 16:30 which is
an M5/M10/M15 boundary), plus a dead M1 `iTime` tracker in `OnTick` (removed). The
confirmation TF (M5/M10/M15) is now the smallest timeframe touched → the Strategy
Tester can run **"Open prices only" on the confirmation-TF chart** and use the
broker's full higher-TF history instead of being capped by the ~3 yr of usable M1
(the [[data-sources]] wall). **Two-file gotcha (2026-07-27):** the EA exists in TWO places — the repo copy
`mql5/IntradayVolatilityBreakout.mq5` (OneDrive, source of truth) and the MT5 copy
`AppData\Roaming\MetaQuotes\Terminal\<id>\MQL5\Experts\...` that MT5 actually
compiles & runs. Editing only the repo copy silently leaves the tester on the old
code (symptom: v2.10 edits done but the run still requests M1). Sync both, then
**F7 to rebuild the .ex5** (copying the .mq5 alone doesn't recompile).

**Tester setup (operational, learned 2026-07-27):** in "Open prices only" mode MT5
only allows price-series access (`iClose`/`iOpen`/`iTime`/`iBarShift`) on the *testing*
timeframe — so the tester **Period must be set to the confirmation TF (M10)**, not M1.
Running it on M1 throws `wrong timeframe request in Open Prices testing mode` +
`rates base receive error` and takes zero trades. (D1 ATR is fine — it's an indicator
handle, not a series request.) **Fidelity caveat:** open-prices-only resolves SL/TP at
*bar* granularity via the tester's fixed intrabar path — with SL 0.25·ATR / TP
0.5·ATR both can fall inside one confTF bar, so same-bar SL-vs-TP ordering is
approximate. Use this mode for the *long* history sweep; cross-check the surviving
years with "1 min OHLC" (M1-limited but honest intrabar) before believing any edge.

**Result — MT5 real-tick M1, 2.5 yr (2026-07-27).** First actual EA run (v2.10, real
ticks 99% modelling, 116M ticks, MetaQuotes-Demo). Window **2024.01→2026.04 = a NAS100
bull run** (balance curve ≈ the index). Risk **1000/trade** (1% of 100k). Net +38,983;
209 trades; PF 1.40; recovery 3.78; max equity DD 8.34%; expectancy +186.5/trade; win
48.8%; shorts 55% / longs 43%. **Read critically, not as a win:**
- MT5 Sharpe **6.53 is not annualised** and is inflated by fixed-risk sizing.
  Re-annualising from the trade stats (E +186.5, ~84 trades/yr, σ≈1120) → **Sharpe_ann
  ≈ 1.5** — good but nowhere near 6.5, and on the easiest possible regime.
- **Fixed-risk sizing is well-behaved** (at 1000/trade): avg loss 908 ≈ 0.9R (losers
  time-exit before full SL), avg win 1335 ≈ 1.3R, max win 2063 ≈ 2.06R (= the 2R TP
  cap), max loss 1251 ≈ 1.25R (minor stop slippage). All consistent. _(An earlier note
  here claiming "risk not fixed / 4R wins" was an arithmetic error assuming 500 risk;
  the run was at 1000 — retracted.)_
- Favorable-window + small n (209) + synthetic demo feed → consistent with the proxy's
  "long bias = bull drift, not a breakout edge," not a refutation of it.
- **Still not the test v2.10 enabled:** needs the long "Open prices only" M10 sweep over
  2000/2008/2018/2022 (non-bull regimes) + cost ×1.5, judged against the pre-set bar
  (OOS Sharpe > 0.7 AND PF > 1.2 net).

**Result — long multi-regime sweep, 2018→2026 (2026-07-27).** v2.10, M10 chart,
"Open prices only", ~8 yr incl. 2018-Q4 selloff, 2020 COVID crash, 2022 bear
(NAS100 −33%). Risk 1000/trade. **697 trades; net +75,372; PF 1.21; MT5 Sharpe 2.67;
win 44.6%; expectancy +108/trade; max equity DD 13.83%.** Widening the window degraded
everything vs the 2.5-yr bull window (PF 1.40→1.21, win 48.8→44.6, exp 186→108, DD
8.3→13.8%) — the expected favorable-window shrinkage. BUT it stayed **net positive
across 8 yr including 2020 & 2022** — better than the single-asset-direction prior
predicted. Re-annualised (E 108, ~87 trades/yr, σ≈1150) → **Sharpe_ann ≈ 0.88**. On
paper this **crosses both pre-set bars** (Sharpe > 0.7 AND PF > 1.2) — but only just.

**Two decisive tests still open before belief:**
1. **Cost optimism.** The 8-yr run is "Open prices only" → MT5 models a *fixed* (often
   optimistic) spread, not real variable spread. PF 1.21 is thin; a few pts of spread
   can push it to ~1.0. Calibrate: rerun 2024-2026 in "Open prices only" and compare its
   PF to the **1.40 from the real-tick/real-spread run** on the same window. If fast-mode
   ≈ 1.40 → cost modelling trustworthy, 8-yr 1.21 stands. If fast-mode ≫ 1.40 → fast mode
   is optimistic → true 8-yr PF is *below* 1.21 and the edge is likely eaten by cost.
2. **Drop the recent bull.** Rerun 2018-2022 only. Positive there → robust; all profit in
   2023-2026 → still bull drift.
3. Prop constraint: DD 13.83% at 1%/trade **breaches the ~10% prop-firm cap** → live
   sizing must drop (~0.6%/trade); edge is scale-invariant so this only scales returns.

**Result — the two decisive tests (2026-07-27).** BOTH pass:
1. **Cost/fast-mode optimism — VALIDATED.** 2024-2026 in "Open prices only" → PF **1.40**,
   209 trades, net +38,479 — **essentially identical** to the real-tick/real-spread run on
   the same window (PF 1.40, net +38,983). Fast mode is *not* optimistic vs real ticks →
   the 8-yr PF 1.21 is trustworthy, not a modelling artifact.
2. **Drop the recent bull — POSITIVE.** 2018-2022 only (incl. 2018 selloff, 2020 COVID
   crash, 2022 bear, NO 2023-26 bull): 397 trades, net **+38,729**, PF **1.19**, Sharpe MT5
   2.51 (**≈ 0.75 annualised**). Profit is split ~50/50 between 2018-2022 (+38.7k) and
   2024-2026 (+38.5k) — **not concentrated in the bull**; it makes money through the
   crises. Strongly weakens the "just bull drift" reading of the single-asset-direction
   prior.

**Data source — RESOLVED, and it's NOT MetaQuotes (2026-07-27).** Forensics on the MT5
terminal cache: the NAS100 data lives under `bases/PepperstoneUK-Demo/` —
`history/NAS100` = **full intraday bars 2018-2025** (2017 partial; pre-2016 ~empty/daily,
matching the user's "quality degrades before 2018"), `ticks/NAS100` = **real ticks
2024-2025 only** (hence the real-tick run was that window). **MetaQuotes-Demo has no
NAS100 cached at all** (only single US stocks). So these runs are on **Pepperstone, a real
broker** — the [[data-sources]] synthetic-feed wall does **not** apply here. This upgrades
confidence in the result. _(Caveat: the user switches brokers often — MetaQuotes /
Pepperstone / IC Markets in one day — always confirm the active server + symbol cache per
run.)_

**The remaining gate — now execution realism, not the feed.** Data is real-broker, but
it's a **demo**: idealized fills (no slippage/requotes), and "Open prices only" resolves
SL/TP at *bar* granularity — both optimistic, worst in the 2020/2022 vol spikes where the
strategy profits. Per-trade edge is thin: **~$98/trade (2018-22)**, ~$184 (2024-26) on
~$1000 risk. **Refinement test:** tester Spread field → fixed ~1.5-2× Pepperstone's
typical NAS100 spread; rerun 2018-2022. PF still > ~1.1 → thin but real edge on real data
→ then param-robustness sweep + prop-fit sizing. PF → ~1.0 → edge was in understated
execution cost → [[ledger]].

**Result — real ticks / real spread, 2024-01→2025-05 (2026-07-27).** The most realistic
test available (64.6M real Pepperstone ticks, spread widens in vol). **PF 1.31, net
+18,607, 117 trades, max equity DD 6.15%, Sharpe_ann ≈ 1.2.** Cost realism does NOT break
the edge on the recent window. Max loss 1.05R → stops did not slip on this window. (PF a
touch below the 1.40 of the longer 2024-2026 window simply because this excludes the very
bullish late-2025/2026 tail — not a cost degradation.) NB: real ticks are only cached
2024-01→2025-05, so this is cost-realistic but regime-favorable; the crisis regimes
(2018-2022) are only testable in open-prices (PF 1.19), which the fast-mode≈real-tick
equivalence says is not materially optimistic on cost.

**Scorecard — 4 independent tests passed:** long multi-regime 2018-2026 (PF 1.21) ·
no-bull 2018-2022 (PF 1.19) · fast-mode = real-tick on 2024-2026 (1.40=1.40) · real-tick
real-spread 2024-2025 (PF 1.31). Strongest external-strategy dossier in the project vs the
single-asset-direction prior.

**Still unproven before "deployable" (priority order):**
1. **Parameter robustness** (anti-overfit) — params are vendor-preset ("RobustifyTrading").
   NOT optimization: check the edge is a *plateau* not a spike. Rerun at neighbours —
   ATR_Multiplier {0.20,0.25,0.30}, Stop_ATR_Multiplier {0.20,0.25,0.30}, ATR_Regime_Factor
   {0.9,1.0,1.1}, entry 16:15/16:30/16:45. PF > ~1.1 all around → robust; collapses on a
   nudge → overfit to Nasdaq's past.
2. **Demo ≠ live slippage** — real ticks model spread but demo fills are idealized (no
   slippage/requotes). Unquantified. Optional: add a `Cost_Per_Trade` input to the EA to
   deduct X pts/trade and stress it (cushion ~$159/trade).
3. **Single asset (breadth 1)** — structural fragility, the project thesis; can't be fixed,
   it's the nature of the bet.
4. **Prop sizing** — 8-yr DD 13.8% at 1%/trade > ~10% cap → ~0.6%/trade for live.

**Independent Python replication (2026-07-27, `backtest_breakout_nas100.py`).** Pulled real
Pepperstone data via the MetaTrader5 python API (D1 2017+, M10 2023-09→2026; M10 API capped
at ~100k bars by "Max bars in chart", so pre-2023-09 not yet reachable). Built a faithful
open-prices-M10 port of the EA. **Validated vs MT5 real-tick truth** (2024-01→2025-05): my
engine PF **1.37 / win 46.4% / Sharpe_ann 1.25** vs MT5 **1.31 / 47.9% / ~1.2** — two
independent implementations agree. Doing so exposed three things the MT5 headline runs hid:
1. **Cost is ~10× the quoted spread.** Matching MT5-real-tick requires an effective
   execution cost of **~100 pts (10 price units)** at the US open, not the ~13 pts of the bar
   'spread' field. So **"Open prices only" underestimates cost** → the 2018-2022 PF 1.19 is
   **optimistic**; realistic is lower. PF is highly cost-sensitive (spread 0 → 1.9; 100 → 1.3).
   This retracts the earlier "open-prices ≈ real-tick, cost validated" claim.
2. **The edge is entirely SHORT-side; longs LOSE.** Validated window: long PF **0.72**
   (E[R] −0.15, win 38%), short PF **2.24** (E[R] +0.50, win 54%), both 1.37. MT5 concurs
   (longs 42% win, shorts 55%). "Both directions" is positive only because shorts carry the
   losing longs. (Note: this *reverses* the US30/H1 proxy's "all edge is long/bull-drift" —
   the proxy was misleading; on real NAS100 M10 the intraday long breakouts fade.)
3. **Parameter fragility (overfit signature).** Entry hour 16:20/16:30/16:40 → PF
   1.17/1.19/**0.89 (losing)** — a 10-min shift flips it negative. k_break 0.20/0.25/0.30 →
   1.10/1.19/1.07 (default is a soft peak). Regime filter off → PF 1.00 (breakeven); high-vol
   → 0.86. Spikes, not plateaus.

**Full-history replication, 2018-2026 (2026-07-27, "Max bars" raised → M10 2018-01+ pulled,
301k bars).** Entry logic validated to the trade: my n=**697** = MT5's 697 on 2018-2026
(2018-2022: 401 vs 397). On 2024-2026 my open-cost (60pt) engine PF **1.42** ≈ MT5 open
1.40. Extended to the full history at **realistic cost (100pt, the level validated vs MT5
real-tick)**:

| Window | PF (real cost) | PF (60pt ~open-prices) | MT5 open-prices |
|---|---|---|---|
| 2018-2022 (crises) | **0.82** | 0.96 | 1.19 |
| 2018-2026 | **0.93** | 1.05 | 1.21 |
| 2024-2026 | 1.28 | 1.42 | 1.40 |

Yearly PF (real cost, EA default): 2018 **0.79**, 2019 **0.44**, 2020 **0.71**, 2021 1.09,
2022 1.20, 2023 **0.75**, 2024 1.43, 2025 1.08, 2026 1.40 → **losing 5 of 9 years**, positive
mainly in 2024 (the window first tested). Direction on 2018-2022: both 0.82 / long 0.89 /
short 0.76 — **all lose**; the "short-only edge" is itself a 2023-2026 artifact (short 1.29
there, 0.76 pre-2023). Even at the optimistic 60pt cost, 2018-2022 is breakeven (0.96).

**MAJOR CORRECTION (2026-07-27, same day).** The "no-edge" verdict above was WRONG — it hinged
on an ~100pt effective-cost calibration that was mis-derived. I then **measured the real spread
tick-by-tick** (`copy_ticks_range`): it is **~13-19 pts (1.3-1.9 price units), fixed**, NOT
100pt. The 100pt was me force-fitting my engine to MT5's real-tick PF 1.31, wrongly assuming
that was ground truth. A **tick-level replay** (`scratchpad/tick_backtest.py`, real bid/ask
fills) gives PF **2.12** on 2024-2025 — *higher* than my M10 bars (1.90), so bars do NOT
overstate; MT5-real-tick's 1.31 is the unexplained pessimistic outlier (tester execution
friction? spread filter?), and I could not reproduce it. Still profitable regardless.

**Corrected results at the real ~15pt cost** (my engine now matches MT5 **open-prices**
everywhere: 2018-2022 1.17 vs 1.19; full 1.25 vs 1.21):

| Cut (2018-2026, real cost) | Result |
|---|---|
| both directions | **PF 1.25, Sharpe_ann 0.92** |
| long only / short only | 1.20 / 1.29 — **both profitable** |
| 2018-2022 (crises) both/long/short | 1.17 / 1.18 / 1.16 — **all positive** |
| k_break 0.20/0.25/0.30 | 1.23 / 1.25 / 1.22 — **plateau, not a spike** |
| entry 16:20/16:30/16:40 | 1.32 / 1.25 / 1.20 — **smooth, not fragile** |
| regime low/high/off | 1.25 / 1.04 / 1.14 — low-vol filter adds value |

So the earlier "short-only / param-fragile / loses on crises" findings were ALL artifacts of the
100pt over-penalty. At realistic cost the edge is **robust to its params, positive both
directions, and net-positive through the crises**.

**Trade-by-trade reconciliation vs the MT5 tester report** (`ReportTester-62133658.html`, the
open-prices 2018-2026 run, PF 1.21, `Max_Spread_Points=10000` so the spread filter is off).
Parsed all 697 MT5 trades and diffed against my engine:
| | MT5 | mine |
|---|---|---|
| n trades | 697 | **697** |
| TP exits | 154 | **154** |
| SL exits | **343** | 324 |
| time exits | 200 | 219 |
| common days, same side | — | **540/544 (99.3%)** |
Validated to the trade. Residuals: ~150 days differ (the `ATR3<ATR20` regime filter flips
boundary days under ewm-vs-Wilder ATR — the filter is itself noise-sensitive), and 19 trades
MT5 books as SL that I book as time (my SL level sits ~4pt further out from using a fixed 15pt
spread vs MT5's slightly wider bar spread).

**Point-3 RESOLVED — the 1.31 vs my 1.9-2.1 gap is intrabar stop-hunting.** SL-count ranking:
my M10 engine **324** (most lenient) < MT5 open-prices **343** < MT5 real-tick (more still) →
PF 1.31. Real ticks catch intrabar wicks to the stop that bar methods miss; MT5 open-prices
already catches 19 more SL than my bars on the *same* bars. My own tick replay (2.12) was
*optimistic* because `copy_ticks` returns flat-spread, over-smoothed ticks that omit the fast
wicks the tester replays — so it is NOT representative. **Therefore MT5-real-tick (1.31) is the
most trustworthy estimate; my 1.25/1.9-2.1 numbers are optimistic (under-count stops).**

**Verdict.** **marginal-positive — a thin real edge, best-estimate PF ~1.2-1.3 realistic**
(MT5 real-tick 1.31 recent; full-history real-tick ~1.1-1.2, below the open-prices 1.21 because
real ticks catch more stops). Positive across every method and window, but the finer the
execution model the thinner it gets. Reservations: (a) **thin & lumpy** — soft/negative years
2018/2019/2020/2023, carried by 2021/2022/2024-26; (b) **single asset (breadth 1)**, the
project thesis; (c) **demo≠live** — real fills likely worse still; (d) prop DD 13.8% at 1%/trade
> ~10% cap → size to ~0.6%/trade. Tradeable with caution + tight sizing, not a strong edge.
_Journey note: this verdict flip-flopped — an over-penalised 100pt cost briefly produced a wrong
"no-edge/ledger" call (retracted same day); measuring the real ~15pt spread flipped it to
"robust 1.25"; the trade-level report then settled it at "thin ~1.2-1.3, real ticks are the
honest number."_ Tooling: `backtest_breakout_nas100.py`, `data_cache_mt5/NAS100_*.parquet`.

**Follow-ups (2026-07-27).** (1) **Regime-timing to switch the brick on/off = dead end:** a
200d-trend filter *cuts* R/an 10.3→2.8 (kills the good years too), an equity-curve filter only
marginally lifts Sharpe (0.66→0.71) at a cost in return; the 4 soft years (2018/19/20/23) share
no ex-ante regime → any "off switch" overfits 9 years. The built-in ATR3<ATR20 is the only
defensible regime lever. (2) **Right move is breadth, not tuning** → built
`portfolio_backtest.py` (multi-brick monthly-R correlation + Sharpe-ceiling math). Finding:
US30 breakout is ~0.06 correlated with NAS100 at the monthly-R level even though the **indices
are 0.80 correlated** (daily returns). Decomposition (verified): only ~55% of trade-days overlap
(regime filter picks different days per asset), of common days only 68% are same-direction, and
even on same-day-same-direction trades corr(R) is just **0.44** (discrete TP/SL outcomes diverge).
A rules filter strips most of the underlying's linear correlation — real, general effect.
**BUT the 0.06 is the average; the same-direction-same-day correlation is 0.44 → tail/crisis
correlation (everyone breaks the same way) is much higher (~0.3-0.5), not 0.06.** So size the
portfolio with a conservative ρ≈0.2-0.3, not the rosy average — that pushes "N for Sharpe 2" from
~5 toward ~15-18. Param-tweak duplicate (entry16:20) is 0.84 (adds nothing). Truly robust
decorrelation needs **opposite mechanisms** (a mean-reversion brick that wins when breakout loses),
not just another index. Correlation caps Sharpe at s₁/√ρ. This brick is a valid +1, not solo.
(3) **2nd-brick search failed both natural ways (2026-07-27):** the breakout does NOT transfer
to other assets (US30 PF 1.08, gold 1.07, silver 0.92, oil 1.03, natgas 0.26 — decorrelated ~0
but no edge; the edge is NAS100-specific), and mean-reversion (fading the breakout) loses on
every asset/RR/regime. All assets show a weak momentum lean, only NAS100's is tradeable. Gold
breakout (+2R/yr, corr +0.01) is the sole marginal decorrelated positive. → real breadth needs a
**different signal** (other sessions, ML features, event setups), not OHLC breakout/fade variants.
Engine now supports point-per-asset + `reverse` flag; data added for XAUUSD/XAGUSD/SpotCrude/NatGas.
(4) **Sessions swept (London 10:00, Asian 02:00) — nothing:** London breakout/fade lose or
breakeven on all 6 assets incl. gold (LDN bk 0.97); Asian samples too small (2-7 trades/yr) →
noise. Only NAS100+breakout+US-open is an edge. (5) **Meta-labeling the breakout FAILED
(`backtest_metalabel_nas100.py`):** 16 causal features (momentum/vol/structure/breakout-strength/
entry-time/temporal), walk-forward OOS 2021-2026 → AUC 0.49 (logistic) / 0.51 (XGB) = random;
predicted-prob quartiles don't sort realized R; top-50% filter doesn't beat take-all. Winning vs
losing breakouts are **indistinguishable ex-ante** → the edge is UNCONDITIONAL, no ML lift; brick
is finished at ~10R/yr Sharpe~0.7. 3rd hit on the single-asset-outcome wall ([[exp-001-v1-single-tf-direction]]).
**Net of all follow-ups: breadth must come from a structurally different family (cross-sectional,
[[exp-003-xsection-fx]]/[[exp-004-xsection-breadth-poc]]), not more breakout variants.** See [[breadth]],
[[information-coefficient-and-ir]].

**Why it matters / next.** First *externally-sourced, rules-based* strategy tested
against the wiki's priors. If it fails OOS/cost tests → ledger row (single-asset
Gold breakout). If it survives → the vol-regime filter would be the likely reason,
reinforcing [[exp-002-v3-mt5-four-angles]]'s "vol is for risk management" lesson.

**Links.** [[exp-001-v1-single-tf-direction]], [[exp-002-v3-mt5-four-angles]],
[[triple-barrier]], [[leakage]], [[data-sources]], [[prop-firm-universe]].
