# QuantifiedStrategies.com — "200+ free strategies" screen (2026-07-31)

User request: take every strategy on <https://www.quantifiedstrategies.com/trading-strategies-free/>,
keep only those with **clear entry / SL / TP rules**, **no external data** (VIX, macro…),
on **US & EU indices, forex, gold, crypto**, then backtest the survivors **to the letter**.

## The funnel

| Step | Count |
|---|---|
| Article URLs on the index | **338** |
| Fetched with usable text | 337 |
| **Explicitly paywalled rules** ("THIS SECTION IS FOR MEMBERS ONLY" / "you find the trading rules at the bottom of the article") | **174** |
| ≥2 rule sentences stated in the running prose | 125 |
| After the 3 user filters (mechanical / no external data / allowed assets) | **55 read in detail** |
| **Fully specified → backtested** | **22** |
| (strategy × asset) tests run | **381** |

### The structural blocker
The site gates its formal *Trading Rules* box behind MemberPress. **174 of 338 articles say
so explicitly.** Those cannot be reproduced to the letter at any effort — e.g. Larry
Connors Double Seven: *"THIS SECTION IS FOR MEMBERS ONLY … BECOME A MEMBER TO GET ACCESS
TO TRADING RULES IN ALL ARTICLES"*. A minority of articles nevertheless state the rule in
prose (IBS, turn-of-month, the overnight family, the crossovers) — those are what got tested.

Also dropped by the asset/external filters: bonds & TLT, NIFTY/China/Brazil/India/Italy,
sector ETFs, single stocks, penny stocks, silver/platinum/corn/cocoa/sugar/oil/lumber/copper,
portfolios & asset allocation, pairs/merger-arb/long-short (need a stock universe), and
everything VIX / put-call / NAAIM / AAII / TRIN / advance-decline / CPI / PMI / NFP /
interest-rate / short-interest / fundamentals.

## Method
`scratchpad/qs_backtest.py` — one generic daily-bar runner in R, on the **live cadence**
(wiki/system.md), gap-aware intrabar stop, stop wins ties, Pepperstone-realistic cost per
instrument. The articles are long-only and mostly carry **no stop**, so a **mandatory
2.5·ATR14 stop** is added (project rule — R is defined by the stop). Validation: the runner
reproduces brick 4 exactly (IBS NAS100 +4.81 R/yr, t=5.16, 287 trades).

## Result — nothing new passes

381 tests. Expected by chance alone: ~9 at t>2, ~0.7 at t>2.9, ~0.09 at t>3.5.
Observed: **23 / 2 / 1**. A mild excess at t>2, and the two that clear the
multiple-testing-adjusted bar are **the IBS strategy we already trade**.

| Strategy × asset | n | R/yr | t | PF | +yrs |
|---|---|---|---|---|---|
| **IBS <0.2 → >0.8 — NAS100** | 287 | +4.81 | **5.16** | 2.21 | 8/9 |
| **IBS <0.2 → >0.8 — US500** | 273 | +3.32 | **3.48** | 1.74 | 7/9 |
| Turnaround Tuesday — NAS100 | 63 | +0.80 | 2.88 | 2.54 | 9/9 |
| Keltner lower-band — NETH25 | 25 | +2.39 | 2.61 | 3.12 | 6/6 |
| ROC(12) zero-cross — US30 | 122 | +2.22 | 2.54 | 1.94 | 8/9 |
| Overnight + MA200 — XAUUSD | 1564 | +3.74 | 2.52 | 1.19 | 7/9 |
| MACD(12,26,9) — BTCUSD | 99 | +4.93 | 2.46 | 2.34 | 6/9 |

**The site's single best strategy is the one already in the book.** IBS is brick 4
([[exp-009]]); US500 IBS is its known, weaker sibling. Everything else is at or below the
noise floor once 381 tests are accounted for.

### Pooled t-stats are inflated — do not read the summary table
`qs_results.csv` shows pooled t of 3.4–4.2 for the crossover families (ROC, MACD, 20/9 EMA).
That is the [[ledger]]'s **basket lesson** again: the assets co-fire, so pooling ~19
correlated series inflates t. Per asset, the same families have a **median t of 0.5–0.9**
and **1 asset out of 19 above t=2**.

## What it independently confirms
Run blind against 338 outside articles, the screen re-derives the project's own conclusions:

* **Trend/crossovers work on crypto and nowhere else.** Best MACD asset = BTCUSD (+4.9 R/yr)
  — that is brick 3. Best 20-EMA/Donchian assets = BTC/ETH. Every crossover family has a
  per-asset median t below 1.
* **Reversion works through IBS on US indices, and only there** — exactly the correction
  recorded in [[ledger]] on 2026-07-31.
* **The overnight family fails**, and it is the site's flagship. Unconditional overnight:
  pooled t = **−1.21**; 3-days-down: **−0.43**; MA200-filtered: **−0.03**. Only gold is
  positive (t=2.52) — consistent with our own overnight-drift test (ledger: Sharpe −0.10).
* **Seasonality is thin**: expiration week best asset t=2.29, turn-of-month pooled t=1.50
  (our gold turn-of-month brick 2 is the one member of that family that survives).

## Not testable on our data
* **"5-day low overnight"** (open at a 5-day low & close > open): **0 trades** on CFD daily
  bars — the article uses SPY, where the cash open can gap below a 5-day low. On 24h CFD
  bars the open ≈ the previous close, so the condition never fires. Untestable, not failed.
* **London breakout** (Asian-session range) needs intraday; we have M1 only for
  EURUSD/USDJPY/EURJPY — left for a later pass.
* Anything gated (174 articles).

## Files
`scratchpad/qs_fetch.py` (fetch + pass-1 triage), `qs_triage2.py` (rule extraction +
the 3 user filters), `qs_backtest.py` (generic R runner), `qs_run.py` (the 22 strategies),
`qs_pages/` (338 article texts), `qs_shortlist.csv`, `qs_results.csv`, `qs_out_*.csv`.
