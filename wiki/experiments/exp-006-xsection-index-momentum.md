---
type: experiment
id: exp-006
updated: 2026-07-27
status: open
verdict: weak — earlier "promising" retracted (data-alignment bug)
horizon: 5-day (weekly rebalance), 12-month momentum signal (6m also works; 12m strongest t 3.13)
universe: liquid prop indices (US + Europe), Pepperstone
code: [xsection_indices.py, xsection_wide.py]
---

# exp-006 — Cross-sectional index momentum (US + Europe)

**Hypothesis.** After single-asset direction ([[exp-001-v1-single-tf-direction]]) and
cross-sectional FX ([[exp-003-xsection-fx]]) both failed, the one untested cheap-to-trade
breadth source is the **liquid equity indices**: tight spreads (unlike EM FX), momentum
that trends (unlike FX crosses), multi-region. Rank the indices, go long the strongest /
short the weakest — a documented factor ("momentum everywhere", Asness et al.).

**Setup.** `xsection_indices.py` on the cached Pepperstone D1 panel. Signal = **6-month
momentum** (log P[t-5]/P[t-126], causal), weekly rebalance, long/short top/bottom tercile,
**net of each index's real spread** (bps × turnover). Compared against 3m/1m momentum and
5d/1d reversal (momentum 6m was the clear winner; the others are flat/negative).

**Result (2026-07-27, 2015-2026).**
| Universe | IC | t(IC) | net %/yr | Sharpe |
|---|---|---|---|---|
| US only (4, synchronous) | +0.028 | 0.91 | +3.2 | 0.23 |
| **US + Europe (7, ~synchronous)** | **+0.046** | **2.02** | **+7.5** | **0.61** |
| all US+EU+Asia (9, non-sync) | +0.032 | 1.55 | +5.8 | 0.50 |

**Why it's credible (survived scrutiny):**
- **Not a non-sync artifact.** Non-synchronous regional closes (Asia 14h off US) are the main
  risk for an index cross-section (lead-lag fake edge). But adding the most non-sync names
  (Asia) *dilutes* the edge (0.61→0.50) rather than inflating it; the cleanest ~synchronous
  subset (US+Europe, afternoon-overlap closes) is the strongest and **significant (t 2.02)**.
- **Stable across sub-periods:** Sharpe 2015-2020 +0.62, 2021-2026 +0.52 (all-index run).
- **9/12 years positive**, mean +5%/yr, worst year −2.1% — smooth, unlike the lumpy breakout.
- **Standard, non-fitted signal** (6-12m momentum is THE documented horizon, not cherry-picked).
- **Decorrelated from the NAS100 breakout: monthly-R corr −0.03** → a genuine 2nd brick.

**Lookback robustness (2026-07-27) — STRENGTHENS the result.** US+Europe, net of cost, across
lookbacks: 1m t+0.10, 2m t+0.76, 3m t−0.66 (neg!), 6m t+2.02, 9m t+1.33, **12m t+3.13 (Sharpe
0.70, positive in 90% of years)**; 12-1 skip variant t+2.42. This is the **canonical momentum
pattern**: long-horizon (6-12m) works and is strongest at the standard **12-month** horizon,
while short-term (1-3m) doesn't (3m even reverses) — exactly the documented short-term-reversal /
long-term-momentum shape (Jegadeesh-Titman, Asness). The edge being maximal at the *standard*
horizon (not a cherry-picked one) and following the known momentum shape **largely defuses the
multiple-testing concern.** → reference lookback updated to **12 months (t 3.13)**.

**Reservations (kept honest, given exp-005's earlier over-claims).** Thin breadth (N_eff of the
9-index set is only ~1.7; ρ≈0.71 — equity indices are one big beta, the L/S cancels it, leaving a
low-breadth relative bet); 3m-lookback is negative (non-monotonic across horizons, though this
matches the literature); demo data + estimated spreads + weekly turnover (real slippage may exceed
the model). Needs: a proper walk-forward / forward test before sizing.

**Portfolio impact.** First decorrelated 2nd brick. Two bricks (breakout Sharpe ~0.7 + index
momentum ~0.6, corr −0.03) → combined ≈ √(0.7²+0.6²) ≈ **0.9**. The breadth engine finally turns
from 1 → 2 bricks (see [[breadth]], [[information-coefficient-and-ir]]). Contrast with the FAILED
wide-FX widening ([[exp-003-xsection-fx]] follow-up): indices work where FX crosses didn't because
momentum *generalizes* to indices and they're *cheap* — the two things widening FX lacked.

**⚠️ MAJOR CORRECTION (2026-07-27, same day) — the strong result was a DATA-ALIGNMENT BUG.**
All the above (t 2.02/3.13, Sharpe 0.61-0.70, 90% years positive) was computed on
`prop_universe_D1.parquet`, whose index is the **union of all 107 instruments' daily timestamps**
(FX/metals/indices have different holidays/hours). On that panel `shift(5)`/`shift(252)` are NOT
clean 1-week / 1-year offsets for the indices → the momentum signal was computed on a misaligned
grid, inflating the result. Prompted by the prop **stop-loss requirement**, re-pulled clean index
**OHLC** (`indices_OHLC_D1.parquet`) and recomputed on the **common-date grid** (dates where all 7
US+EU indices have a real observation):

| 12m momentum, clean grid | Net/yr | Sharpe | years+ | worst yr |
|---|---|---|---|---|
| no SL | +5.1% | **0.40** | 58% | **−11.6%** |
| SL 3×ATR20 | +4.2% | 0.32 | 58% | −14.3% |
| SL 2×ATR20 | +3.0% | 0.22 | 58% | −13.6% |

Corrected reality: **Sharpe ~0.40, NOT significant** (t ~1.3), worst year **−12%** (not −2.9%).
And the mandatory prop **per-position SL makes it WORSE** (0.40→0.32) and the worst year *grows*
(−11.6%→−14.3%): momentum + stops = whipsaw (stop exits at the low, position recovers without
you); the drawdown is a **book-level** phenomenon (many positions losing together over weeks), which
a per-position stop doesn't fix.

**Verdict.** open → **WEAK / not a confirmed brick.** The "promising 2nd brick" was a
data-alignment artifact (2nd retracted over-claim this session, after exp-005's 100pt cost).
Cleanly aligned it is a thin, statistically-insignificant Sharpe ~0.4 that the required prop SL
degrades further. Effectively the project is back to **one solid brick (the NAS100 breakout)**.
Not deployable as-is. (Process note: re-checking — here forced by the SL requirement — is what
caught it; always align a cross-sectional panel to a clean common calendar before trusting shifts.)

**Links.** [[exp-003-xsection-fx]], [[exp-004-xsection-breadth-poc]], [[exp-005-mt5-intraday-vol-breakout]],
[[breadth]], [[information-coefficient-and-ir]], [[factor-investing-cross-section]], [[cross-sectional-vs-directional]].
