# RESEARCH LOG — the whole Kaufman canon, tested across every asset class

**Date:** 2026-08-07 · **Source:** `TSaM.pdf` (Perry J. Kaufman, *Trading Systems and
Methods*, 5th ed., Wiley 2013)
**Mandate (user):** *"reprends le livre, les stratégies qui y sont expliquées et les
stratégies que tu crées toi en prenant plein de morceaux par-ci par-là ; teste chaque
stratégie sur l'or, les indices US et EU, les cryptos et le forex — c'est comme ça qu'on a
déjà trouvé une brique."*

The premise is correct and it is the discovery mechanism this project already used once:
a rule is never scored only on the market its author had in mind.

---

## 1. What was built

**The catalogue.** The book walked chapter by chapter; every passage carrying a
reproducible rule was extracted (`scratchpad/tsam_rules.py`, with the chapter/page in the
docstring of each family):

| ch. | families implemented |
|---|---|
| 4 | Dunnigan thrust, Nofri congestion-phase, outside day with an outside close (both the original and Kaufman's reversed reading), Prathap 3-bar inside, pivot-point breakout (k=3/5/10), channel breakout, moving channel, CCI break and fade |
| 5 | swing breakout with a % swing filter (0.5/1/2/4 %), N-day breakout |
| 6 | linear-regression slope, 1-bar forecast with 2σ confidence bands |
| 7–8 | the **six systems Kaufman benchmarks** (M, MA, EXP, NDB, SWG, LRS) at 10/20/40/80, 2-MA crossovers, Bollinger break/fade, Keltner break/fade, % bands, projected crossover |
| 9 | RSI(2/14) trend and reversion, stochastic, Williams %R, MACD cross, MACD+RSI, **Kaufman's Divergence Index**, double-smoothed momentum (TSI), velocity & acceleration, ADX/DI, Parabolic SAR |
| 10 | turn-of-month, sell-in-May |
| 15 | opening-gap fade and follow, weekday reversal, IBS trend and reversion |
| 17 | **KAMA, VIDYA, FRAMA** (direction + price cross), the ER-gated breakout, **Meyers' adaptive intraday breakout**, Arrington variable-length MA |
| 19 | Elder triple screen, Pring KST |
| 20 | volatility-regime gating of a breakout |

**Excluded, with the reason stated in the code**: cycles/MEM (fitted spectra, not a rule),
volume & breadth (MT5 CFD "volume" is a tick count — the ledger's standing finding),
spreads/arbitrage (two instruments), behavioural (COT/news/astrology = external data).

**The composites** — the "morceaux par-ci par-là" half: 7 trend filters
{KAMA, VIDYA, FRAMA, ER-state, ADX, LR-slope, none} × 8 triggers
{NDB20, NDB40, MA-cross, RSI2, Bollinger, Keltner, IBS, CCI} = **56 pairings**. The filter
says which side is allowed, the trigger says when — Kaufman's own thesis in ch.8/17/19.

**153 rules → 135 distinct after de-duplicating on the SIGNAL ARRAY** (the book names the
same mechanism three times: a Donchian channel *is* an N-day breakout *is* a channel
breakout; counting it three times would inflate everything downstream).

**The grid.** 18 assets (8 FX, 2 metals, 4 US indices, 3 EU indices, 2 crypto) × D1 ×
5 stops × 5 targets × 2 time caps = **108,094 cells**, on the verified `kauf_lib` engine
(fill at the next open, one position at a time, pessimistic tie-break, gaps fill worse,
real Pepperstone cost, R = the trade's own stop).

---

## 2. The headline: the classes are NOT alike, and the placebo says which are real

Raw, the sweep looks unremarkable — median t −0.040, 48.5 % of cells with positive E[R],
7.6 % above their own random-entry null's 95th percentile against a 5 % chance rate.

That aggregate hides everything. Running the **identical funnel on matched random
signals** (same count, same long fraction, same bars, same brackets, same null lookup,
same thresholds, 3 replicates — `scratchpad/tsam_placebo.py`) gives the divisor:

| class | real above null-p95 | placebo | real median excess | placebo | real shortlist | placebo | **ratio** |
|---|---|---|---|---|---|---|---|
| **crypto** | **27.7 %** | 6.8 % | **+0.753** | +0.016 | 1,798 | 281 | **6.4×** |
| **metal** | 9.9 % | 6.4 % | +0.227 | −0.037 | 616 | 305 | **2.0×** |
| us_idx | 5.4 % | 5.6 % | −0.149 | −0.035 | 241 | 457 | 0.53× |
| eu_idx | 6.2 % | 5.8 % | −0.339 | +0.003 | 127 | 235 | 0.54× |
| **forex** | 3.0 % | 5.2 % | −0.128 | −0.009 | 98 | 477 | **0.21×** |
| all | 7.6 % | 5.9 % | −0.045 | +0.007 | 2,880 | 1,754 | 1.64× |

The placebo behaves exactly as designed (median excess ≈ 0, above-p95 ≈ 6 %), which
validates the machinery before any conclusion is drawn from it.

**Three findings, in order of importance.**

1. **The user's thesis is confirmed and quantified: cross-asset transfer works, and it
   points at crypto.** The whole canon — trend, reversion, oscillators, adaptive,
   patterns, calendar — produces **6.4× more survivors on crypto than pure noise does**,
   and a median excess over its own drift-matched null of **+0.75 versus +0.02**. This is
   the largest real/placebo ratio this project has ever measured; every prior corpus pass
   (TradingView 5,759 scripts, MQL4 1,256, MQL5 2,201, freqtrade 1,103, quantifiedstrategies,
   quantocracy, ProRealCode) ran at **1.2×**. It re-derives brick 3 blind, from a fourth
   independent source.
2. **Forex, US indices and EU indices are BELOW the noise rate.** Not "weak" — *below*.
   The Kaufman canon produces **fewer** winners on forex (0.21×) than random signals do.
   That is the friction tax measured as a leftward shift of the whole distribution, the
   same result the MQL4 corpus produced, now reproduced on the canonical technical
   literature rather than on retail code.
3. **Gold and silver sit in between at 2.0×** — real but a third of crypto's rate.

---

## 3. The trap this pass exposes: the daily-correlation illusion

The battery gave exact nulls (400 draws each) to the 369 (asset × rule) representatives:
**95.9 % beat Null A, 81.8 % beat Null B, 298 beat both.** That is not evidence — it is
circular, because the shortlist was selected on beating the null in the first place. It is
exactly why the placebo divisor exists, and it is worth recording that a per-cell null
*alone* passed 81 % of a shortlist whose true excess-over-noise is 1.6×.

The second trap is new and sharper. Ranking the crypto survivors by their **daily-P&L**
correlation to brick 3 says they are all decorrelated — median |corr| **0.049**. They are
not:

| measure | median over the 30 top crypto candidates |
|---|---|
| \|corr\| to brick 3, **daily** R | **0.049** |
| \|corr\| to brick 3, **monthly** R | **0.515** |
| share of their trading days that also close a brick-3 trade | 26 % |
| sign agreement on those shared days | 50 % |

**These sleeves fire 80–450 times over ten years, so two rules trading the same crypto
trend rarely close on the same DAY — and a daily correlation of 0.05 is then an artefact
of sparsity, not evidence of diversification.** On a portfolio of sparse sleeves the
horizon that matters is the one a drawdown is felt on. New standing rule: **for any sleeve
under ~40 trades/year, report the MONTHLY correlation; the daily one will lie.**

---

## 4. What is left after both filters

Only four crypto cells have a monthly correlation to brick 3 below 0.30. All four are
**slow** trend rules — which is the mechanism: brick 3 is MACD(12,26), a fast trend; a
40–80 bar trend turns on a different clock.

| cell (BTCUSD D1) | bracket | n | R/yr | PF | t | maxDD | RoMaD | +yrs | split-half (vs own sign-null) | monthly corr b3 |
|---|---|---|---|---|---|---|---|---|---|---|
| **EXP_dir_80** | SL 1.0×ATR, TP 2×SL, 30 bars | 77 | +5.2 | 2.15 | 3.24 | 3.1 R | **1.66** | **9/9** | early p=0.027 · late p=0.043 ✅ | +0.265 |
| **EXP_dir_40** | SL 1.5×ATR, TP 1×SL, 120 bars | 89 | +3.3 | 1.95 | 3.17 | 4.1 R | 0.82 | 8/9 | early p=0.000 · late p=0.020 ✅ | +0.015 |
| MACD_cross | SL 1.0×ATR, no TP, 30 bars | 115 | +16.1 | 2.73 | 3.15 | 12.4 R | 1.30 | **10/10** | early **p=0.697 ❌** · late 0.000 | +0.140 |
| MA_dir_40 | SL 0.75×ATR, TP 2×SL, 30 bars | 117 | +6.8 | 1.96 | 3.49 | 7.1 R | 0.95 | 9/9 | early **p=0.157 ❌** · late 0.003 | +0.005 |

All four are **cost-insensitive** (+50 broker points/side moves R/yr by <2 % — on crypto
1R is 60–120× the spread).

**`EXP_dir_80` is the cleanest thing this pass produced**: the direction of an 80-bar EMA
on BTCUSD, stop 1×ATR14, target 2R, 30-bar cap. **9/9 positive years, RoMaD 1.66 — higher
than any live brick (IBS 1.59, crypto 0.95, NAS 0.79, gold 0.73)** — and both halves of
the sample beat their own sign-permutation null. Its weakness is that it is also the most
correlated of the four to brick 3 (+0.265) and it is thin (7.3 trades/yr, +5.2 R/yr).

`MACD_cross` has the biggest number (+16.1 R/yr, 10/10 years) and the worst provenance:
its first half does not beat its own null (p=0.70), so all of its measured edge is in the
recent half.

**Book impact at equal risk** (⚠️ on the 3-brick *literal-cadence* series in
`bricks_daily.parquet`, not the canonical 4-brick live book — the levels are not
comparable to `system.md`, only the deltas are):

| config | R/yr | maxDD | RoMaD | Sharpe | %/yr |
|---|---|---|---|---|---|
| book (b1+b2+b3) | +32.5 | 15.8 | 2.06 | 1.87 | 10.3 % |
| + MACD_cross @1R | +48.7 | 17.7 | **2.75** | 2.10 | **13.8 %** |
| + MA_dir_40 @1R | +39.1 | 15.9 | 2.47 | 2.16 | 12.3 % |
| + EXP_dir_80 @1R | +37.5 | 16.8 | 2.23 | 2.08 | 11.2 % |

---

## 5. Verdict

**No brick is promoted, and the reason is not the statistics of any single cell — it is
the selection.** These four were chosen from 128 crypto survivors, themselves from 1,798
shortlisted crypto cells, themselves from 12,281. The class-level claim is solid (6.4×
placebo); the cell-level claim is selection-inflated by construction, and two of the four
already fail their own split-half.

What this pass *establishes*:

* **the cross-asset method the user asked for works, and now has a number on it** — 6.4×
  on crypto, 2.0× on metals, ≤0.54× everywhere else;
* **crypto trend is the only robust family in the entire technical canon on this
  universe**, re-derived blind for the fourth time from a fourth independent source;
* **forex is below the noise rate** — the strongest form yet of this project's FX wall;
* **the monthly-correlation rule**, which changes how every sparse sleeve in this project
  must be judged from now on — and which, applied retroactively, is the reason none of
  these crypto cells is a diversifier.

**Recommended next step, if any**: forward-test `EXP_dir_80` on BTCUSD at 0.5R alongside
brick 3 on the demo — it is the only cell that clears both halves, has 9/9 positive years
and the best RoMaD in the book. Do not size it as a brick until the forward test says so.

---

## 6. Files

| File | Role |
|---|---|
| `scratchpad/tsam_rules.py` | 153 rules (135 distinct) — the book's systems + 56 composites |
| `scratchpad/tsam_sweep.py` | the 108,094-cell cross-asset sweep + the null lookup |
| `scratchpad/tsam_battery.py` | exact Null A + Null B on the 369 representatives |
| `scratchpad/tsam_placebo.py` | the divisor: the identical funnel on matched random signals, ×3 |
| `scratchpad/tsam_crypto.py` | daily vs monthly correlation to brick 3 (the illusion) |
| `scratchpad/tsam_final.py` | full battery + book impact on the 4 decorrelated candidates |
| `scratchpad/_tsam_scored_D1.parquet` | every cell with its null and excess |
| `scratchpad/_tsam_placebo_D1.parquet` | the placebo cells |
| `scratchpad/_tsam_survivors.csv`, `_tsam_crypto_corr.csv` | the shortlists |

---

## 7. H1 — the same answer, louder, once the economic floor is applied

The H1 sweep was run in two parts. On **FX** it was stopped after three assets because the
verdict was immediate: EURUSD median t **−1.71** (5 cells of 6,899 above t=2), GBPUSD
−1.30, USDJPY −0.62 — far below chance, consistent with the ledger's standing "H1 is below
chance on all 19 assets".

On **crypto + gold** the full sweep ran: 20,898 cells, 140 distinct rules. The raw output
is a trap and it is worth spelling out, because it is the ledger's ProRealCode rule
recurring:

| | value |
|---|---|
| median t | **−2.13** |
| cells with positive E[R] | **28.3 %** |
| cells above their own null p95 | **46.0 %** (!) |
| median excess over the null | **+1.27** |
| median null t | BTCUSD **−3.51**, ETHUSD **−11.25** (floor −37), XAUUSD −0.40 |

**46 % of H1 cells "beat their null" while 72 % of them lose money.** On H1 the friction is
charged against a much smaller ATR, so a random entry is catastrophic and merely losing
less than random clears the null. *Beating a terrible null is not the same as making
money* — the standing rule, reproduced here at scale.

Applying the **economic floor** (E[R] > 0, n ≥ 60, t > 2) and then the placebo divisor
(`scratchpad/tsam_placebo_h1.py`, matched random signals through the identical funnel):

| stage | real | placebo | ratio |
|---|---:|---:|---:|
| all cells | 20,898 | 20,900 | 1.00× |
| above null p95 | 9,614 | 4,140 | 2.32× |
| **+ economic floor** | **1,313** | **241** | **5.45×** |
| — of which **crypto** | **722** | **43** | **16.8×** |
| — of which **gold** | 591 | 198 | **3.0×** |

**The H1 result agrees with D1 and is stronger: crypto at 16.8× the noise rate, gold at
3.0×.** Median excess over the matched null: crypto +1.95 real vs +0.14 placebo.

One qualification on the survivors' shape: they skew to wide stops (520 of 1,313 at
3.0×ATR, 329 at 2.0×) but not exclusively — 95 sit at 0.75×ATR. So the H1 edge is *partly*
a stop-width effect (a wider 1R dilutes the toll) and not only that. Two individual cells
worth naming, both untested beyond this screen: **BTCUSD `Keltner_break_1.5`** (SL 3×ATR,
TP 2R, 96-bar cap: n=1477, +27.1 R/yr, PF 1.28, t=4.26, RoMaD 1.54) and **XAUUSD
`Meyers_6`** — Kaufman's own adaptive intraday breakout at its published QQQ parameters,
on gold H1 (n=1972, +23.8 R/yr, t=3.91, but its null is already +2.72, so the excess is
only +1.19).

### 7b. Both were then batteried — one dies, one is the best candidate of the session

**XAUUSD `Meyers_6` — REJECTED, and the reason is legible in one number: it is 93 % long.**
Kaufman's own adaptive intraday breakout, transferred to gold H1, spends 93 % of its
signals on the long side of a market that rose through the whole sample. Its own nulls say
so: **Null A median +2.63, Null B median +2.91** — a random 93 %-long gold bracket already
scores t ≈ +2.9, so its t = 3.91 is worth about **+1.0**, not +3.9. And:
* **the recent half does not beat its own null** (late t=2.94 vs null 2.75, **p = 0.316**);
* RoMaD **0.73** — equal to gold ToM, the book's weakest sleeve — on a maxDD of **32.7 R**,
  twice the entire book's;
* cost-sensitive at 262 trades/yr (t 3.91 → 2.73 at +20 pts/side);
* **adding it makes the book worse**: 10.3 %/yr → **7.4 %** at 1R.
It is the documented gold-drift / long-bias artefact, in a new wrapper.

**BTCUSD `Keltner_break_1.5` — a genuine candidate, and it clears every gate this project
has**, including the two that kill everything else:

| gate | result |
|---|---|
| Null A (random entry, median −0.22) | **p = 0.000** |
| **Null B (sign permutation, median −0.07)** | **p = 0.000** — no drift to hide behind |
| positive years | **9 / 9** |
| split half, each vs its own sign-null | early t=3.88 **p=0.000** · late t=2.09 **p=0.012** |
| cost stress | **immune** — +20 broker pts/side moves t from 4.25 to **4.23** |
| **1R ≥ 25× spread floor** (the crypto post-mortem's own test) | **survives**: t 4.25 → **3.13**, pB still **0.000** |

At the honest floored configuration (SL 3×ATR14 with a 25×-spread floor, TP 2R, 96-bar cap):
**n=1266, +17.2 R/yr, PF 1.216, t=3.13, RoMaD 0.94**; monthly correlation brick 3 **+0.231**,
brick 1 +0.115, brick 2 −0.035. Book impact at equal risk: **10.3 %/yr → 12.6 %**,
RoMaD 2.06 → **2.51**, at either 1R or 0.5R.

Why the H1 friction wall does not bite here, when it has killed every other H1 result in
this project: **3×ATR(H1) on BTCUSD is a very large 1R relative to a crypto spread** (median
44× after flooring), so the toll is a rounding error. That is also the honest limit of the
result — it is a property of the instrument, not of the rule.

**Three caveats, all real.** (1) **Selection**: this is 1 cell of 722 crypto H1 survivors;
the 16.8× class ratio says the *class* is real, not that the maximum of a large screen is
unbiased. (2) **Decaying**: +35.8 R/yr in the early half against +18.2 in the late one,
even though both clear their null. (3) **Not a diversifier** — monthly corr +0.231 to brick 3
makes it a *second crypto trend sleeve* (a faster, H1 cousin of the daily MACD), not a new
mechanism.

**Recommendation: forward-test it on the demo at 0.5R alongside brick 3, with the 25×-spread
floor built into the sizing — the same treatment KAER got.** It is not a promoted brick.
