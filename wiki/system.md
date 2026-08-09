---
type: system
updated: 2026-08-09
status: frozen (in-sample; forward-test pending)
---

# The 4-Brick System — current deployable book

> The synthesis of the whole project: four **decorrelated** edges ("bricks"), each
> with mandatory SL/TP/time-exit, on liquid OHLCV, prop-firm compliant, measured in
> **R** (SL = −1 R). This page links to the code that owns each rule — it does not
> restate the parameters (they live in the files and would rot here). See
> [[exp-009-ibs-reversion-4th-brick]], [[exp-008-crypto-breakout-3rd-brick]],
> [[exp-007-turn-of-month-2nd-brick]], [[exp-005-mt5-intraday-vol-breakout]].
> Numbers below are **findings**, not config.

## The four bricks

| # | Brick | Asset(s) | Mechanism | Code (source of truth) | Standalone |
|---|-------|----------|-----------|------------------------|-----------|
| 1 | **US-open ATR breakout**, low-vol regime (ATR3<ATR20 on D1) | NAS100 (real M1) | intraday breakout | [`edgelab/intraday/atr_breakout.py`](../edgelab/intraday/atr_breakout.py) — `run_atr_breakout('NAS100', regime_mode='low', direction='both')` | +11.6 R/yr, PF 1.27 |
| 2 | **Turn-of-month**, SL = 1.5·ATR14 | XAUUSD (D1) | seasonality | [`edgelab/edges/turn_of_month.py`](../edgelab/edges/turn_of_month.py) — `run_turn_of_month('XAUUSD', sl_atr=1.5)` | +2.2 R/yr, PF 1.68 |
| 3 | **MACD(12,26,9)+RSI** ([arXiv 2206.12282](https://arxiv.org/abs/2206.12282)), exits TP 6·ATR / 30 bars (`crypto_risk:`) | BTC+ETH (D1) | crypto trend | daily `BacktestEngine(cadence='live')` + `macd_rsi`; data `data_cache_mt5/` (Pepperstone) | **+11.8 R/yr, PF 1.65, t=3.52** |
| 4 | **IBS reversion**, SL = 2.5·ATR14 (buy IBS<0.2, exit IBS>0.8 / 30-bar) | NAS100 (D1) | intraday-position reversion | [`edgelab/edges/ibs.py`](../edgelab/edges/ibs.py) — `run_ibs('NAS100', IBSParams(sl_atr=2.5))` (live cadence) | **+4.8 R/yr, PF 2.21, t=5.16** |

Brick 4 (added 2026-07-31, [[exp-009-ibs-reversion-4th-brick]]) is the first brick-4
candidate to **improve the book on every axis**. US500 IBS is the same-asset-avoiding
alternative (weaker: split-half early t=1.45, cost-fragile). It is **long equity beta** —
size ≤1R, do not over-weight (tail co-moves in a secular bear).

Coin set for brick 3 = **BTC+ETH only** (user-verified more drawdown-efficient than
adding SOL/ADA — alts add correlated crash risk, not diversification).
Breakout-20 (`VolatilityBreakoutEdge(channel=20)`) is the lower-tail **conservative
alternative** to MACD-RSI. Single-MA-50 is the fallback if crypto is not prop-tradable.

## THE TWO NAMED BOOKS (user's naming, 2026-08-08) — use these names everywhere

| Name | Composition | Where it is used | Live |
|---|---|---|---|
| **book AGRESSIF** | b1 @1R + b2 @1R + b3 @1R + b4 @1R + **KAER @0.5R** | the **CHALLENGE** phase, at 1.00 %/trade | **deployed on the demo** — magics 101-106 |
| **book FUNDED** | b1 @1R + b2 @1R + **b3 @0.5R** + b4 @1R (no KAER) | the **FUNDED** phase, at 0.50 %/trade (protection) | not deployed; a config change at funding time |

**KELT was removed from both books on 2026-08-09** (user decision) and unwired from the
live runner — see the FTMO-cost section below. It never took a live trade (magic 107 stayed
flat). `keltner_btc.py` and `KeltnerStrategy` are kept for research and `verify`.

**Net of every FTMO cost** (commission + swap, measured below), the two books are
**AGRESSIF +40.90 R/yr** (maxDD 17.4 R, RoMaD 2.36, Sharpe 1.77) and **FUNDED +22.46 R/yr**
(maxDD 12.3 R, RoMaD 1.83, Sharpe 1.63). Challenge at 1.00 %: **83.8 % in 3.0 months**;
funded at 0.50 %: **12.1 %/yr withdrawn at 1.0 % ruin**. The gross numbers below predate the
cost work and are kept because they are what the sleeve pages and the MC report reproduce.

The two-phase plan is measured in [[log]] (2026-08-08): AGRESSIF@1.00 % → FUNDED@0.50 %
withdraws **30.2 %** over two years at **1.6 % ruin**, against 27.2 % / 1.4 % for the best
single-book plan and 24.5 % / 3.2 % for the 4-brick book. The gain is *time* — the
challenge clears in 2.6 months instead of 4.5, buying ~2 extra funded months — and the
switch is what keeps ruin at 1.6 % instead of AGRESSIF's own **12.3 %**. Staying aggressive
after funding is the trap: the aggressive book earns its risk only while a failure costs a
fee rather than the account.

**Monthly profile of AGRESSIF** (96 complete months, 2018-07→2026-06 / recent half):
mean **+4.81 / +4.49 R per month**, median +4.12 / +4.41 R, σ 6.9 / 7.2 R,
**80.2 % / 72.9 % positive months**, best +21.7 R, worst −14.9 R. At 1.00 %/trade that is
**+4.81 % per month on average**, worst month −14.9 %. FUNDED: +2.99 / +3.10 R per month,
**76.0 % / 77.1 % positive months**, worst −11.4 R.

⚠️ AGRESSIF still contains **one sleeve that has never been forward-tested** (KAER), so its
numbers are in-sample for that part. Without it AGRESSIF degenerates to the frozen 4-brick
book — slower, not broken.

## Forward-test sleeves (NOT bricks) — KAER and KELT, added 2026-08-07/08

| Sleeve | Asset | Mechanism | Code | Standalone | Live |
|---|---|---|---|---|---|
| **KAER** — Kaufman efficiency-ratio intraday breakout | NAS100 (M15) | follow a 10-bar range break when ER(10)'s trailing percentile is in the top tercile; SL 2.0·ATR14, no TP, flat 15:55 ET | [`edgelab/intraday/kaer.py`](../edgelab/intraday/kaer.py) — `run_kaer('NAS100')` | +28.8 R/yr, PF 1.19, t=3.20, **RoMaD 1.13**, 8/9 +yrs | magic **106**, `enable_kaer`, **0.5R** |
| ~~**KELT** — Keltner-band breakout~~ **RETIRED 2026-08-09** | BTCUSD (H1) | EMA(20) ± 1.5·ATR(20) band break; **SL = max(3·ATR14, 25×spread)**, TP 2R, 96-bar exit | [`edgelab/intraday/keltner_btc.py`](../edgelab/intraday/keltner_btc.py) — `run_keltner()` (research + `verify` only) | +17.2 R/yr gross → **+5.04 net of FTMO cost, t=0.87** | **unwired** — never took a live trade |

KELT shared BTCUSD with brick 3 under its own magic, which **required a HEDGING account**
(verified: `margin_mode == 2`) — moot since the retirement, but it stands if the sleeve is
ever revived. Its monthly correlation to brick 3 is +0.07…+0.23, so it was a *second
crypto-trend sleeve*, not a new mechanism, and the 25×-spread floor is **part of the rule**
(without it R/yr reads +27.1 instead of +17.2). **What killed it was neither the signal nor
the floor but the cost structure**: a 2.95 % stop buys 34 % of the balance in notional, and
FTMO charges that notional a 30 %/yr swap every night it is held.

**KAER is deliberately NOT counted as a 5th brick.** corr **+0.370** to brick 1 with **40 % of
its trading days closing a brick-1 trade too** — every brick-brick pair above is ≤ 0.03 — and
it replicates on **no other index** (US500 t=1.64, GER40 1.30, US30 0.00, FRA40/US2000/UK100
negative). It is brick 1's family, so the live question is "**is this a better brick 1?**",
not "is this a 5th sleeve". Sized at **half R** because at equal risk +KAER@0.5R improves the
book on every axis (R/yr 32.0→47.4, maxDD 14.3→17.1, RoMaD 2.24→**2.78**, Sharpe 1.95→2.03,
%/yr 11.2→**13.9**) while +KAER@1R makes it worse (funded ruin at 0.50 % 1.7 %→26.3 %). A
straight **swap** at 1R is a bad trade (worst day −3.07→−5.07 R so the −5 % daily rule bites
again, challenge pass 92.3 %→80.2 % at 1 %, funded ruin →14.6 %); the swap at 0.5R
*strictly dominates* the current book (ruin 1.7 %→1.0 %) — which is exactly what the forward
test is meant to confirm or kill. In-sample and parameter-selected; brick 1 is
forward-committed and tick-validated, KAER is not. See [[ledger]] and `RESEARCH_LOG_KAUFMAN.md`.

## Why these edges (the finding — corrected 2026-07-31: three → four)

Across **9000 arXiv papers** and the full technical canon (MA/MACD/Bollinger/CCI/ADX/
SAR/Keltner/Aroon/Ichimoku, RSI2/z-score/Williams%R/Stochastic, VWAP, candlesticks,
OPR, TS/XS momentum, pairs, calendar), **every family converges to a small set of edges
or fails net of cost**. On liquid OHLCV: the trend edge exists **only in crypto** + the
**NAS opening breakout**; FX daily direction has no edge net of cost; seasonality =
turn-of-month.

⚠️ **The old claim "reversion is dead everywhere" was too strong and is CORRECTED.**
The reversion tests that failed were generic (index z-score/RSI2 t=1.23, lag-reversal =
bid-ask bounce, FX/crypto random-walk). But the **IBS** signal (where the close sits in
the day's range) **is a genuine reversion edge on US equity indices** — NAS100 t=4.68,
US500 t=3.36, US2000 t=2.70 (Europe/Asia ≈ 0), net of cost, robust to split-half + cost +
bootstrap → **brick 4** ([[exp-009-ibs-reversion-4th-brick]]). So a 4th decorrelated brick
did **not** need different data after all — it needed the *right* reversion signal on the
*right* (US-index) universe. Whether a 5th needs options-implied data (VRP/skew) is still
open. See [[ledger]] and [[lessons]].

## Decorrelation & combined backtest (equal 1 R/trade, 2018-07→2026-07, 8 yr)

Pairwise daily-P&L correlations all ≈ 0. Brick 4 (IBS NAS100) vs the others:
**−0.00 / −0.03 / −0.01** (NAS / gold / crypto) — same order as the existing
brick-brick corrs (NAS/gold +0.02, NAS/crypto −0.01, gold/crypto −0.01). Max |corr|
across the whole 4×4 matrix is **0.03**.

| Metric | 3-brick | **4-brick (+ IBS NAS100)** |
|--------|---------|-----------|
| **Total (Pepperstone + live cadence, canonical)** | — | **+258 R (+32.0 R/yr)**; NAS +12.9 + gold +2.5 + crypto +11.8 + IBS +4.8 |
| maxDD / RoMaD / Sharpe | — | **14.3 R / 2.24 / 2.57** |
| Profit factor (pooled trades) | — | **1.44** (1446 trades, 53% win); per brick NAS 1.27 / gold 1.86 / crypto 1.65 / IBS 2.21 |
| Activity | — | **~180 trades/yr**: NAS ~95, crypto ~35, IBS ~35, gold 12 |
| worst day | −4.15 R | **−3.07 R** (crypto no longer books 4 same-day stops) |
| MC median R/yr, P(profit) | — | **+31.6, 97.2%** |
| MC 5th-pct year, median maxDD | — | **+4.3 R, 9.5 R** |

Adding brick 4 **raises return AND Sharpe AND lowers maxDD** — the first candidate to do
all three (the ⭐ [[ledger]] candidates lowered Sharpe or correlated to brick 1). Combined
maxDD stays **below the worst single brick** (NAS ~16.6 R) → decorrelation empties **risk**,
not return.

**HTML reports** (self-contained, in `edgelab/reports/`): `portfolio_backtest.html` (equity
curve, per-brick, correlation, annual R) and `monte_carlo.html` (percentile fan,
distributions, prop-firm odds by sizing). Both are **regenerated by one command** —
[`edgelab/reports/build_reports.py`](../edgelab/reports/build_reports.py), which recomputes
the book and re-runs the MC through `monte_carlo_static.simulate()` (the same function the
CLI prints from, so report and printout can't disagree) and re-injects the data blobs.
Run it after adding or changing a brick. Brick 3 is priced on the Pepperstone crypto feed
(the live-realistic book).

## Monte Carlo (block-bootstrap, no compounding, 1 R = risk% of **initial** balance)

⚠️ **Corrected 2026-07-29.** The earlier MC (~+28.5 R/yr) was wrong — two stacked bugs,
both understating: (a) it used the **compounding** engine mark-to-market for the crypto
brick instead of fixed-fractional trade-R; (b) it reindexed on business days
(`freq='B'`), silently **dropping crypto weekend exits**. Fixed = fixed-fractional
trade-R on a **calendar** index. The MC median matches the historical backtest to ~0.5 R/yr
— the correctness check for a block-bootstrap. Reproducible:
[`edgelab/reports/monte_carlo_static.py`](../edgelab/reports/monte_carlo_static.py).

**4-brick, 1-year distribution (40k sims, blocks of 14 d):** P(profitable year) = **97.2%**,
mean **+31.8 R** (historical +32.0).

| Pct | annual R | maxDD R |
|-----|---------:|--------:|
| 5th | +4.3 | 5.4 |
| 25th | +20.4 | 7.4 |
| **50th** | **+31.6** | **9.5** |
| 75th | +43.2 | 12.2 |
| 95th | +59.7 | 18.0 |

maxDD tail: 99th pct 23.6 R, worst 41.6 R.

## Prop sizing — firm with STATIC drawdown (target +15% / total −10% / daily −5%)

**No daily-rule ceiling any more:** the worst historical day is **−3.07 R** (the crypto
brick no longer books four same-day stops), so the −5% daily rule is not breached at any
sizing tested up to 1.5%. The binding limit is now the **−10% static floor**.

**Challenge (time-to-pass, 4-brick):**
- **0.75%/trade = best pass rate** — **95.8%** in ~6.4 months; 1.00% = **92.3%** in **~4.5 months**.
- **0%** daily-rule breaches at every sizing; failures are now all total-DD.
- 1.25-1.5% still passes 84-88% but fails DD 12-16% — the trade-off is speed vs ruin.

**Funded (static −10% floor, monthly payout resets balance to initial):**
- **0.50%/trade** → ~**16.7%/yr** withdrawn, **1.8%** ruin/yr (keep-the-account choice).
- 0.75% → ~24.6%/yr, ~12% ruin/yr.
- **Never above 1%** — E[withdrawn] plateaus at 35–38% while ruin explodes past 47%.
- **Asymmetric plan:** pass the challenge at 1.0% (speed), drop to 0.5% once funded (protection).

### Margin on an FTMO **Swing** account (measured 2026-08-09)

The swing account is **mandatory** for this book (b2/b3/b4 hold overnight and over
weekends) and its advertised **1:30 applies to nothing here** — the book holds no forex.
The leverages that bite are **indices 1:15, metals 1:9, crypto 1:1** (crypto is 1:1 on the
*normal* account too, so **the swing downgrade is nearly free**). Measured on the real
position timeline (`scratchpad/ftmo_swing_margin.py`):

| Book | median margin | p99 | max | time > 100 % | entries refused |
|---|---|---|---|---|---|
| **AGRESSIF @1.00 %, final (no KELT)** | **19.0 %** | 49.5 % | **84.4 %** | **0 %** | **0 / 3801** |
| **FUNDED @0.50 %, final (no KELT)** | **4.8 %** | 14.7 % | **24.8 %** | 0 % | **0 / 1445** |
| *(was)* AGRESSIF with KELT, swing | 31.7 % | 77.6 % | 117.4 % | 0.10 % | 25 / 5034 |
| *(was)* AGRESSIF with KELT, normal | 30.4 % | 70.6 % | 112.6 % | 0.01 % | 2 / 5034 |

The tail saturation was **KELT's**, not the account's: at 1R it ate **33.9 %** of the balance
in margin (2.95 % median stop × crypto 1:1) vs KAER 17.5 %, brick 1 16.5 %, brick 4 1.5 %.
**Retiring it removed the margin problem outright** — the final books never come close to the
ceiling. (Had it been kept, `0.75 %/trade`, `KELT@0.25R`, or `b3@0.5R + KELT@0.25R` each took
the max under 100 %.)

⚠️ **`broker.market_order` never calls `order_calc_margin`/`order_check`**, so a 10019
refusal raises, the runner logs it, and the brick simply **re-attempts on the next pass**
at a drifted price.

### FTMO commissions (measured 2026-08-09) — one sleeve pays for all of them

**The whole thing is one formula: cost in R = `sides × rate / stop_pct`.** A commission is
proportional to *notional*, and notional/risk = 1/stop%, so **the same rate hurts in inverse
proportion to how tight the stop is**. FTMO charges **0.0325 %/side on crypto**, **0.0007 %/side
on metals**, **0 % on indices**.

| Sleeve | stop % | cost/trade | R/yr → | t → |
|---|---|---|---|---|
| **KELT** BTC | 2.95 % | **0.0220 R** | 17.35 → **13.60** | 2.99 → **2.35** |
| b3 BTC / ETH | 8.6 / 11.4 % | 0.0075 / 0.0057 R | −0.13 / −0.11 | ~flat |
| b2 XAU | 1.99 % | 0.0007 R | −0.01 | flat |
| b1 / b4 / KAER | — | 0 | 0 | — |

Book: AGRESSIF **55.97 → 53.85 R/yr** (Sharpe 2.29 → 2.20), FUNDED **34.72 → 32.72**
(2.21 → 2.08). So **−22 % of KELT's edge and ~−4 % of the book** — the tight-stop sleeve is
the only one that notices. `scratchpad/ftmo_commissions.py`.

### The swap is the real bill — and it is what retired KELT

FTMO's spec, read symbol by symbol, uses **two different MT5 swap modes**, and each needs
its own conversion:

| Symbol | MT5 mode | spec | → annual % of price |
|---|---|---|---|
| BTCUSD / ETHUSD | *percentage of current price* | −30 / −30, Fri ×3 | **−30 % both sides** |
| NAS100 | *points* | −559.07 / −56.72, Fri ×3 | **−7.23 % long**, −0.73 % short |
| XAUUSD | *points* | −78.40 / −23.55, **Wed ×3** | **−7.01 % long**, −2.10 % short |

*Percentage of current price* is `SYMBOL_SWAP_MODE_INTEREST_CURRENT` — the MQL5 doc says
**annual** interest on a **360-day** bank year, so −30 is 8.33 bps/night, not 30 points.
*Points* is a fixed cash amount per lot, so its cost as a fraction of notional **depends on
the price**; converting at today's price gives 7.23 % and 7.01 % — two nearly identical
funding rates, which is exactly what confirms **point size 0.01 on both** (at 0.1 the NAS
would read 72 %/yr, which does not exist on an index). The repo's `POINT_SIZE` says 0.1 for
NAS100 — that is **Pepperstone**; FTMO quotes it to 2 decimals.

Three consequences that do *not* fall out of a naive reading:

1. **Count swap UNITS, not nights.** The weekday factors sum to 7 per week either way, but
   they are not interchangeable: with gold's **Wednesday** triple a weekend costs **1** unit
   while crossing a Wednesday costs **3**; with NAS's Friday triple a weekend costs 3.
2. **Direction matters, because b2 and b4 are long-only** — they always pay the expensive
   side (10× the short rate on NAS).
3. **b1 and KAER pay nothing at all.** They are intraday; zero rollovers crossed.

**`cost_R = units × rate/unit / stop_pct`** — inverse in the stop's tightness, linear in the
holding time. Measured at 1R:

| Sleeve | units/trade | R/yr → | left | t → |
|---|---|---|---|---|
| **KELT** *(retired)* | 2.1 | 17.35 → **5.04** | **29 %** | 2.99 → **0.87** |
| b3 BTC / ETH | 20.3 / 17.5 | 6.41 → 3.13 / 5.50 → 3.07 | ~50 % | 1.41 / 1.25 |
| b4 NAS IBS | 3.2 | 4.81 → **4.30** | 89 % | 5.16 → 4.59 |
| b2 XAU ToM | 2.8 | 2.56 → **2.21** | 87 % | 2.35 → 2.07 |
| **b1, KAER** | **0** | **12.95 / 30.82 unchanged** | **100 %** | — |

Gold and the NAS get off lightly — wide stops, low rates, and for gold the Wednesday triple
means its month-end weekends are cheap. **Crypto carries essentially the whole bill.**

⭐ **Removing KELT is what the numbers say.** Net of every FTMO cost, with KELT the books are
AGRESSIF 43.39 R/yr at maxDD **21.92** (RoMaD 1.98, challenge @1 % 82.0 %) and FUNDED 24.96
at maxDD 14.66 (funded ruin **2.5 %**). Without it: **40.90 / maxDD 17.36 / RoMaD 2.36 /
challenge 83.8 %** and **22.46 / maxDD 12.31 / RoMaD 1.83 / ruin 1.0 %**. −2.5 R/yr buys
4.5 R of drawdown and halves ruin. A sleeve at **t = 0.87 net** has no place in a static-DD
book. Cutting brick 3 as well goes too far — its 3× wider stop absorbs the swap.

**Structural shift worth naming: b1 + KAER now carry 66 % of AGRESSIF's net R/yr** (27.1 of
40.9) because they are the only sleeves that never cross a rollover. The swing account is
still mandatory for b2/b3/b4 — but everything it costs lands on the long-hold sleeves.
`scratchpad/ftmo_swaps.py`. See [[log]] 2026-08-09.

### "Then why not go 100 % intraday?" — measured, and the answer is no

b1 and KAER keep **100 %** of their edge net of FTMO cost, so the question is natural. At
**equal risk** (each book at its own −10 % static floor, funded income under a 2 % ruin cap
— the project's admission-test metric since 2026-07-31):

| Book | R/yr | maxDD | RoMaD | **funded %/yr @ ≤2 % ruin** |
|---|---|---|---|---|
| **A — current (b1+b2+b3+b4+KAER)** | 40.90 | **17.36** | **2.36** | **15.0 %** |
| F — no gold | 38.71 | 17.86 | 2.17 | 14.3 % |
| **E — no crypto (b1+b2+b4+KAER)** | 34.79 | **17.12** | 2.03 | **14.6 %** |
| D — intraday + b4 | 32.60 | 17.47 | 1.87 | 13.8 % |
| B — intraday only, KAER@0.5R | 28.31 | 18.00 | 1.57 | 10.8 % |
| C — intraday only, KAER@1R | **43.71** | **28.76** | 1.52 | **9.6 %** |

**C is the lesson in one row: the highest gross R/yr of the lot and the lowest income at
equal risk**, because its maxDD nearly doubles. B is starker still — **maxDD 18.00 R, worse
than the whole book's 17.36, for 12.6 R/yr less**. The cause is already on this page:
**b1 and KAER correlate +0.36, same asset, same family** — which is exactly why KAER was
never counted as a 5th brick. An intraday-only book is not a cheaper diversified book, it is
**one bet on one asset**, and its drawdowns stack instead of cancelling.

⭐ **The instinct does land, one sleeve over: dropping CRYPTO costs only 0.4 pts** (E: 14.6 %
at 1.4 % ruin vs A's 15.0 % at 1.6 %) and in exchange removes all the −30 %/yr swap, the 1:1
margin that was the swing account's only saturation point, weekend gap risk, and takes the
**worst day from −4.36 R to −2.63 R**. Brick 3 nets only 6.2 R/yr now (vs 11.9 gross) and
carries most of the bad path. **Decide it explicitly — don't drift into it.**

**Do not cut b2 or b4 to "go intraday".** They are the sleeves that survive the costs best
(89 % and 87 % kept, net t 4.59 and 2.07) *and* the real decorrelators (|corr| ≤ 0.12 to
everything, against +0.36 between b1 and KAER); their swap bill is −0.51 and −0.34 R/yr.
⚠️ And **KAER is still not forward-tested** — an intraday-only book would stake its entire
result on the least-proven sleeve in the set.

**Payout cadence:** biweekly is **not** better. Annual income is ~flat across cadence,
but frequent payout strips the cushion (reset to 100% = always 10% from the static
floor) → **~2× the ruin risk** vs monthly/quarterly. Take payouts **as infrequently as
cashflow allows**; the only reason to withdraw often is **counterparty risk** (the firm
itself). If partial withdrawals are allowed, keep a **+4% cushion** (ruin 17.6% → 6.5%
for −3 pts of income). Reproducible: [`edgelab/reports/payout_frequency.py`](../edgelab/reports/payout_frequency.py).

## Independent verification (2026-07-30) — "are these good reproducible edges live?"

A full re-audit, run from scratch (not trusting these tables). Two separable claims:

**(a) Code reproducibility — PROVEN.** `python -m edgelab.live.verify` re-ran clean:
brick 1 **830/830** exact entries, brick 2 **124/126** (the only 2 misses are Good
Friday 2018-03-29 & 2024-03-28 — market closed, the live business-day calendar approx
skips them), brick 3 signal + barriers **identical**. → the live runner places the
trades the backtest predicts; no divergence.

**(b) Edge stats — reproduce to the decimal** (independently recomputed on the 2018-07+
live-realistic window; `scratchpad/verify_bricks.py`):

| Brick | n | R/yr | PF | t (per-trade) | +yrs |
|-------|---|-----:|---:|--------------:|------|
| 1 NAS ORB | 784 | +13.0 | 1.27 | **3.01** | 7/9 |
| 2 gold ToM | 96 | +2.5 | 1.86 | **2.35** | 7/9 |
| 3 crypto MACD-RSI | 721 | +17.2 | 1.57 | **5.25** | 8/9 |
| **combined** | — | **+32.5** | — | Sharpe **2.42** | 8/9 |

⚠️ **This whole table is on the LITERAL cadence and is now known to be optimistic for
brick 3** — see the cadence correction below. Live-cadence brick 3 is n=570, **+6.9 R/yr,
PF 1.27, t=2.43, 6/9 +yrs**.

Decorrelation confirmed: NAS/gold +0.02, NAS/crypto −0.01, gold/crypto −0.01.
(This audit predates brick 4; **brick 4 IBS** was added and re-run into the canonical
reports on **2026-07-31**: on the live cadence n=287, **+4.8 R/yr, t=5.16**, corrs to the
three all ≤|0.03|. Canonical live-cadence book → **+27.1 R/yr, Sharpe 2.15**.
See [[exp-009-ibs-reversion-4th-brick]].)

**(c) Robustness stress** (`scratchpad/robustness.py`) — ⚠️ **the confidence order is
REVERSED by the cadence correction: brick 4 > brick 1 > brick 2 > brick 3.**
- **Brick 3, after the exit fix, is healthy again** (but the old "strongest brick" claim
  stays withdrawn). With the framework-default exits it was 49% 2020 and **ex-2020
  t=1.30**, negative in 2024 and 2025. With the **validated** exits (TP 6·ATR / 30 bars)
  it is **+11.8 R/yr, t=3.52, 9/9 positive years**, ex-2020 t=2.60, and positive in 2024
  (+3.0) and 2025 (+0.8). The fragility was in the arbitrary defaults, not the signal.
- **Brick 1's vol-regime filter carries the edge:** regime=low t=2.80 → **regime=off
  t=1.66 (sub-threshold)** → high t=−0.46. Real, but conditional on a fitted (though
  mechanism-motivated) filter. Cost-robust to 8pt slippage on the bar model — **but**
  [[exp-005-mt5-intraday-vol-breakout]] shows bar-M1 **under-counts intrabar stops**
  (honest real-tick PF ~1.2–1.3 < 1.27) → live likely thinner.
- **Brick 2 is a thin diversifier** (~12 trades/yr, +2.5 R/yr); its value is the
  decorrelation, not the return, and it sits on the multiple-testing borderline (t=2.35).
  It is nonetheless the **2nd most efficient sleeve** (Sharpe 3.83) — do not drop it.
- **Brick 4 is now the most robust** (t=5.16 on the live cadence, PF 2.21, 8/9 +yrs,
  split-half stable) — and the only one whose t *rose* under the cadence correction.

**Bottom line (revised 2026-07-31).** The edges are genuine and decorrelated and the code
reproduces them live — but the *sizes* were not what the literal backtests said. After the
cadence correction the book is **+27.1 R/yr, not +37.3**, and the ranking is inverted:
bricks 1, 2, 4 hold up, **brick 3 is thin and 2020-dependent**. Out-of-sample persistence
remains unproven (forward test: 2 trades). Nothing in the *live* code needed changing —
the driver was already right; it was the backtest that was optimistic.

## Admission test for a 5th brick (measured 2026-07-31, `scratchpad/sleeve_swap.py`)

**Decorrelation is necessary but NOT sufficient.** Compared at *equal risk* (each config
sized to its own binding prop ceiling — the **−10% static floor**, since after the cadence
fix the daily rule never binds). Re-run 2026-07-31 on the final book:

| Config | R/yr | maxDD | RoMaD | **%/yr at equal risk** |
|---|---|---|---|---|
| **A — the book (4 bricks)** | +32.0 | 14.3 R | 2.24 | **22.4%** |
| B — A − gold | +29.5 | 13.6 | 2.17 | 21.7 (−0.6) |
| C — A − gold **+ GER40** | +38.1 | 20.5 | 1.86 | 18.6 (**−3.8**) |
| D — A **+ GER40** (add) | +40.5 | 21.1 | 1.93 | 19.3 (**−3.1**) |
| G — A − NAS **+ GER40** | +27.6 | 19.2 | 1.43 | 14.3 (**−8.0**) |
| H — A − IBS **+ GER40** | +35.8 | 22.4 | 1.60 | 16.0 (**−6.4**) |
| **E — A + IBS US500** | +34.9 | 14.2 | 2.46 | **24.6 (+2.3)** |
| F — A + an IBS-calibre independent sleeve | +36.8 | 13.5 | 2.75 | **27.5 (+5.1)** |

**Every GER40 configuration loses at equal risk**, and swapping is worse than adding. The
cause is not correlation (|corr| ≤ 0.02 to all four) but its **path**: GER40's standalone
maxDD is **22.6 R for +8.6 R/yr → RoMaD 0.38**, i.e. it carries more drawdown on its own
than the entire book (14.3 R). Note config G has the *highest* Sharpe of the lot (2.68)
yet the worst %/yr — Sharpe measures daily vol, RoMaD measures the path, and GER40's
losses cluster. **On a static-DD prop account the path is what you are paid on.**

Standalone RoMaD is the cleanest admission test: IBS **1.59**, crypto 0.95, NAS 0.79,
gold 0.73, **GER40 0.38**.

⚠️ **PARTIALLY REVERSED 2026-08-09 by the FTMO cost work — GER40 is no longer closed.**
The verdict above was measured **at 1R, on a book without KAER, and gross of FTMO cost**.
Net of cost, on the real book, and **at half size**, it becomes the first configuration ever
tested that *beats* the book at equal risk: **A + GER40@0.5R = 16.4 %/yr at 1.5 % ruin**
against A's 15.0 % at 1.6 %. At 1R it still loses the point (15.4 %, maxDD 17.4 → 26.4 R) —
same sizing lesson as KAER and KELT: **a sleeve with a poor standalone RoMaD is worth only
its decorrelation, so it is dosed at half.** And **A − crypto + GER40@1R = 15.8 % at 1.0 %
ruin**, i.e. better than today's book with **no crypto at all**.

What changed is not GER40 but its competition: it is **intraday, so its swap is zero and its
index commission is zero** — it keeps 100 % of +10.17 R/yr — while brick 3 fell from 11.9 to
6.2 R/yr. Still **in-sample, best-of-5 variants, regime filter inverted vs brick 1**, and the
same ATR-breakout *mechanism* as brick 1 on another index/session. **Forward-test it at 0.5R
alongside KAER — do not add it to the book on these numbers.** `scratchpad/dax_orb.py`,
[[log]] 2026-08-09.

| Sleeve | R/yr | daily vol | **standalone Sharpe** |
|---|---|---|---|
| IBS (b4) | +4.8 | 0.442 | **4.84** |
| gold ToM (b2) | +2.5 | 0.868 | **3.83** |
| crypto (b3) | +11.8 | 1.774 | 3.36 |
| NAS ORB (b1) | +12.9 | 1.238 | 1.71 |
| *GER40 (candidate)* | *+8.6* | *1.368* | *1.63* |

Three consequences. **Never drop brick 2 to make room** — its small R/yr is a *frequency*
artefact (12 trades/yr) and removing it costs −0.6 pts/yr at equal risk. **There is no
slot scarcity**: adding always beats swapping, and after the cadence fix there is no
daily-rule ceiling at all. And **GER40 is closed** — it lost on the old book (−1.4 pts)
and loses by more on the better one (−3.1), because the bar rose with it.

**The open candidate is [[exp-009-ibs-reversion-4th-brick|IBS on US500]]** (config E,
**+2.3 pts/yr at equal risk**, RoMaD +0.23, Sharpe +0.11, maxDD flat) — the only real
strategy tested that improves the book. It is already coded (`run_ibs('US500')`). It has
NOT had the validation battery (exp-009 flags it as weaker: split-half early t=1.45,
cost-fragile past 4pt) and it is correlated to brick 4 by construction. Validate before
adding. Admission test: **standalone RoMaD near the top of the table**, then *add*.

## Caveats (why this is "frozen candidate", not "deployed")

1. **All in-sample** on candidate bricks — no genuine forward test yet.
2. Brick 1 t≈3.0 is **regime-selected** (regime-off t=1.69); brick 2 is a **thin**
   diversifier (~12 trades/yr, t=2.18); **brick 3 is the weak link** (live cadence
   +6.9 R/yr, t=2.43, ex-2020 t=1.30, negative in 2024 and 2025) and crypto
   **prop-tradability varies by firm** — verify your firm allows it before deploying;
   brick 4 is **long equity beta** (corr ~0 understates tail co-movement in a secular bear).
2b. **The whole book is now priced on the LIVE cadence** (recut 2026-07-31, in two
   passes). Both daily-bar bricks were affected by the same defect: the loop could **close
   and re-open inside one bar**, filling the new trade at that bar's **already-past open**.
   No once-per-bar driver can do that. Brick 4: **+5.6 → +4.8 R/yr**. Brick 3: **+17.2 →
   +6.9 R/yr** (t 5.25 → 2.43). Book: **+38.2 → +27.1 R/yr**. Decisive check — letting the
   engine re-enter intraday at the *honest* price (the barrier it just filled at,
   `cadence="live_reentry"`) gives **+5.5 R/yr, WORSE than not re-entering at all**. So the
   missing +10.3 R/yr was pure stale-price artefact, not a missed opportunity, and the
   deployed driver needs no change. `cadence="live"` is the tradeable book;
   `cadence="literal"` reproduces the historical runs and is used **only**
   by `verify` to prove the live signal math matches it. The edge is *stronger* on the live
   cadence (**t 4.77 → 5.16**, PF 1.99 → 2.21) — it is the R/yr that was optimistic, not
   the edge. Bricks 1–3 were already live-cadence.
3. Block-bootstrap **understates long crypto bear regimes** → real funded ruin likely
   a bit above the numbers above → argues for the conservative sizing end.
4. ✅ **The brick-3 cadence gap is CONFIRMED, fixed and re-cut** (was "suspected" earlier
   the same day). It cost **−10.3 R/yr** — by far the largest correction in the project.
   `verify` now guards it on every run (it asserts the live cadence re-opens inside a bar
   **0** times and prints the live-vs-literal R/yr gap). The favourable side predicted
   earlier did materialise: the worst day improved **−4.43 → −3.08 R**, so the −5% daily
   rule no longer binds at any tested sizing. Bricks 1 and 2 are structurally immune (one
   trade per session / per month), so all four are now on the live cadence.

## Going live / forward-test (`edgelab/live/`)

Built 2026-07-29, **brick 4 added 2026-07-31**: **one Python process** on MT5/Pepperstone
runs all four bricks as strategy modules under **one shared risk manager** (the
architecture chosen for these low-frequency, bar-based bricks — Python reuses the exact
backtest math so live can't diverge; MQL5 was rejected to avoid re-implementation drift).
Proven with `python -m edgelab.live.verify` → brick1 **830/830** exact, brick3 identical,
brick2 ~98% (holiday-shifted month-ends), brick4 **314/314 trades exact** on signal math.
Start: `python -m edgelab.live.runner`.

**Brick 4 live wiring** (magic **105**, `NasIbsStrategy`): decides once per broker day at
the D1 rollover like bricks 2–3, long-only, **no TP** — exits are the broker-managed stop,
`IBS > 0.8` at a close, or 30 D1 bars (counted in *bars*, not calendar days, since NAS100
prints none at weekends). It shares NAS100 with brick 1 but holds a **separate position**
under its own magic. It waits for the day's bar to actually print before entering, so the
stop is never sized off a stale close. No config change was needed to deploy it
(`ibs_symbol`/`enable_ibs` default to NAS100/true).

**Time exits — the driver owns them, and they are the part `verify` used to skip.**
Every sleeve has one: b1/KAER flat at 15:55 ET (wall clock), b2 on a count of the month's
completed D1 bars, b3 at 30 D1 bars, b4 at 30 D1 bars or `IBS>0.8`, KELT at 96 H1 bars.
Two rules, both learned the hard way on 2026-08-09 (see [[log]]):

1. **Count BARS in the broker's own frame, never calendar dates or elapsed hours.** MT5
   returns `position.time` on the **server** clock (Athens) but labelled UTC —
   `broker.server_epoch_to_utc` reinterprets it. Comparing the raw stamp to a true-UTC
   clock made b3 hold **31** bars instead of 30 and KELT **99+** instead of 96
   (KELT: +17.2 → +15.0 R/yr, RoMaD 0.94 → **0.60**). And elapsed hours ≠ bars: the
   BTCUSD H1 feed has 137 two-day holes, so KELT counts index distance like b3/b4.
2. **Send every D-bar time exit `rollover_lead_min` (10 min) early** — b2, b3, b4 and
   KELT's 96-bar cap. An exit firing *at* 00:00 server lands in the daily break of any
   symbol that has one — **NAS100 and XAUUSD are both shut 00:00–01:00 server (23:00–00:00
   Paris)** — so it is rejected 10018 and fills at the reopen, which **on a Friday is
   Monday**. That is how a sleeve carries a weekend it never agreed to: **13 % of brick 2's
   exit bars and 20 % of brick 4's are Fridays.** BTCUSD/ETHUSD have no break, so on crypto
   the lead is insurance.
   ⚠️ **Not 5 minutes: on FRIDAY these symbols stop quoting at 23:55 server** (last M5 bar
   23:50), so a 5-minute lead would fire exactly on the Friday close — the one day the
   weekend is at stake. 10 min (23:50 server = **22:50 Paris**) is the last window live
   every day. Because of the lead, b2/b3/b4 evaluate their **exit on every pass** (entries
   stay once per broker day) and park `_acted_day` so an early close can never be followed
   by an early re-entry — the `cadence='live'` guarantee.
3. **A refused exit must be retried on the very next poll — see the incident below.**
   Retrying it once per broker day is not "on every pass", and the difference is days of
   unwanted exposure.

### ⚠️ Incident 2026-08-07→09 — brick 4 could not get out, and the log said it had

Brick 4 held its NAS100 long (ticket 82489480, entered 2026-08-06) for **~3 extra days**.
`NasIbsStrategy.step` set `_acted_day = bday` **before** attempting `broker.close()`, so the
first refusal of a broker day consumed that day's only exit attempt: every later pass
returned at the `first_pass_today` guard without retrying. On a weekend that is three days.
The runner then printed **`market reopened, order placed`** on the next pass — a line emitted
whenever `step()` merely returned without raising `MarketClosed`, which proves nothing
(`step()` has ~6 legitimately silent exits). It fired **six times on 2026-08-09 alone**, each
20 s after a refusal, so the log positively asserted the opposite of what happened.

Fixed 2026-08-10 in [`strategies.py`](../edgelab/live/strategies.py) /
[`runner.py`](../edgelab/live/runner.py) / [`broker.py`](../edgelab/live/broker.py):

- **Two day markers instead of one.** `_acted_day` (= don't OPEN on this bar) is still set
  the moment a position is seen, preserving the `cadence='live'` guarantee against a
  mid-pass stop fill. The new `_managed_day` (= the exit decision RESOLVED) is set only
  *after* the close attempt returns. A refusal leaves it unset → the next poll retries.
  Applied to all three rollover bricks (b2, b3, b4); b1/KAER/KELT never had the bug (their
  exit branch already runs unconditionally).
- **`Broker.orders_sent`**, a counter incremented on each executed entry/exit. The runner
  diffs it across `step()` and now says `NO order sent on this pass` when nothing went out.
- **Throttled failure logging** (`runner._log_failure`): full traceback once, then one line
  every 15 min while the *same* failure repeats. Necessary *because* exits now retry — a
  rejection persisting on an OPEN market would otherwise write a traceback every 20 s and
  rotate `runner.log`'s useful history away (the same concern that typed a missing quote as
  `MarketClosed` in `broker._tick_price`).

**Lesson, and it generalises past this repo: a log line must assert what was *observed*, not
what the code path implies.** The bug was ~3 days old and invisible precisely because the
runner reported success on a bare return. `verify` could not have caught this — it checks
signal/cadence fidelity on cached bars, and never exercises a broker that refuses.

Cost, measured: brick 2 is a **wash on mean** (tracking error vs the backtest's `c[xi]`
exit: −0.43 R at 22:50 vs −0.40 R at the current post-break fill, over 89 exits/8.5 yr) but
clearly **tighter** — σ 0.045 vs 0.066 R, worst case **0.14 vs 0.50 R**. Brick 3/KELT are
unaffected (no break). Brick 4's cap is **dormant: 0 of 287 exits** — all 262 non-stop exits
are the `IBS>0.8` signal, which deliberately keeps the rollover fill because it must be
judged on a fully *closed* bar.

**Open, not done:** moving brick 4's **IBS signal** exit onto the lead too would remove its
54 Monday fills, costs **+4.81 → +4.78 R/yr**, but means judging IBS on a bar 10 min from
final. That is a rule change, not a fix — decide it deliberately.

`python -m edgelab.live.verify` includes `verify_time_exits()` (a–e): the stamp on both DST
sides, b3 against the engine's own exit bar, KELT's `_held` across the feed's gaps, b2's
lead firing on the backtest's exit bar, and b4's lead landing exactly one bar early.

**Order sending is ENABLED (`live_trading: true`) — safe because the Pepperstone account
is a DEMO.** A hard gate (`allow_real_account: false`) refuses to send orders if the
connected account is not a demo (fails loudly rather than trading real money). The live
path attaches SL/TP to the position, picks a supported filling mode, clears the broker's
min-stop distance, clamps lots, retries on requotes, and journals every fill to
`edgelab/live/_out/trades.csv`. See `edgelab/live/README.md`.

**Lot-grid sizing: nearest-step + over-risk cap (`max_risk_R`, default 1.25).** Pepperstone
NAS100 steps by **0.1 lot** (one decimal), a coarse grid relative to the 60 k€ demo: 0.1 lot
≈ 160 € ≈ 0.27R, so 1R (600 €) sits between 0.3 lot (0.80R) and 0.4 lot (1.07R). `_snap_lots`
rounds to the **NEAREST** step (not floor) so the quantisation error centres on 1R instead of
biasing down every trade (floor gave 0.3 = 0.80R; nearest gives 0.4 = 1.07R). `lots_for_risk`
then **skips the entry past `max_risk_R`** (returns 0 lots → the brick marks the day done) and
logs any sub-cap size above **1.10R**; normal quantisation (≤1.10R) is silent. On a smaller
account where even `volume_min` overshoots the cap (e.g. NAS100 0.1 lot = 1.6R on a 10 k€ demo)
the trade is skipped outright. This keeps the uniform-1R assumption of the MC/prop model honest.
Tune the cap in `config_live.yaml`. **The grid is a hard broker limit — the only way to make it
proportionally finer is a bigger account (more lots per 1R); on this demo 60 k€ is the max.**

**Brick 3 re-validated on Pepperstone (2026-07-29): ✅ holds.** Same signal/engine on
Pepperstone BTC+ETH D1 (2018-07+): **+16.7 R/yr, PF 1.55, maxDD 9.1R, t=3.93, corr −0.02,
9/9 years positive, gate PASS** (realistic cost BTC 6 / ETH 16 bps; cost-robust — even
pessimistic 8/20 bps → +16.2 R/yr, t=3.80). Lower than Yahoo (+22–25) because of shorter
history + a different broker daily-close time (not cost). Recent (2023+) spreads are
tighter than the historical median. So the live book expectation is **~+30 R/yr**, and
brick 3 trades the exact same signal live.

**Next action:** run the live (demo) forward test on Pepperstone; confirm the first
tickets risk ~1R with the broker's real tick value, and that the prop firm allows crypto.

**See also.** [[exp-005-mt5-intraday-vol-breakout]], [[exp-007-turn-of-month-2nd-brick]],
[[exp-008-crypto-breakout-3rd-brick]], [[breadth]], [[ledger]], [[data-sources]], [[codebase-map]].
