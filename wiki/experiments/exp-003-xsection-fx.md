---
type: experiment
id: exp-003
updated: 2026-07-11
status: done
verdict: no-edge
horizon: 5-day cross-sectional (rebalance every 5d)
universe: ~11 USD-oriented FX pairs + metals (prop-firm), 2015-2026
code: [xsection_fx.py, fx_loader.py]
---

# exp-003 — Cross-sectional FX + metals

**Hypothesis.** Even though *absolute* direction is unpredictable ([[exp-001]],
[[exp-002]]), the **relative** ranking of assets may carry signal: go long the top
of the cross-section and short the bottom, so the common USD leg cancels in a
long/short book. See [[cross-sectional-vs-directional]].

**Setup.** `xsection_fx.py` on `fx_loader.py` data. Universe ~20 USD-oriented FX +
metals. Features (all causal, normalized per date): momentum 12-1 / 6-1 / 3-1 / 1m,
5-day reversal, volatility, distance to 52-week high, "value" (deviation from
long-term mean). **No carry** (historical swap unavailable). Target: 5-day forward
return, **excess vs the universe mean** that date. Costs: real MT5 spread per asset
× turnover, with a `COST_FLOOR_BPS=1.0` floor × `COST_MULT=1.5`. Model:
`XGBRegressor` (depth 3, heavy regularization). 4 walk-forward folds, top/bottom
quintile book. Don't restate params — see `xsection_fx.py`.

**Key question.** Does the ML ranker beat **simple factor sorts** (momentum / value
/ reversal alone)? If ML adds nothing over a momentum sort, say so plainly.

**Result** (run 2026-07-11, 395 rebalances, ~11 assets/date, 13-name universe,
walk-forward, net of MT5 spread × turnover):

| Strategy | IC | t(IC) | IC-IR | net %/yr | Sharpe net | maxDD |
|----------|-----|-------|-------|----------|------------|-------|
| **ML (XGBoost)** | **−0.0288** | −1.48 | −0.60 | **−4.81** | **−1.29** | −31.4% |
| Momentum 12-1 | +0.0254 | 1.19 | +0.48 | +0.32 | +0.08 | −8.0% |
| Value (5y) | +0.0102 | 0.46 | +0.19 | +0.21 | +0.05 | −11.7% |
| Reversal 5j | +0.0350 | 1.54 | +0.62 | −4.24 | −0.94 | −27.5% |

- **The ML ranker is actively harmful** — negative IC (−0.029), Sharpe −1.29. It
  overfits a ~11-name cross-section.
- **Best net strategy = plain Momentum 12-1**, but Sharpe 0.08, +0.32%/yr, and its
  **IC t-stat = 1.19 is NOT significant at 5%**.
- Reversal has the highest raw IC (+0.035) but its turnover eats it: net −4.24%/yr.
- **Breadth here is only ~11 names** vs ~138 in [[exp-004-xsection-breadth-poc]].

**Verdict.** ❌ **No edge.** Nothing is statistically significant. ML overfits;
simple factors are marginal-to-negative net of cost. The likely root cause is
**insufficient [[breadth]]**: ~11 correlated USD-leg instruments cannot generate the
√N that makes a weak IC usable (see [[information-coefficient-and-ir]]). This is the
mirror image of exp-004: same mechanism, far too few bets.

**Why it matters / next.** Confirms the [[breadth]] thesis by *counter-example* — the
prop-firm FX/metals universe is too narrow for cross-sectional alpha. Candidate next
steps: (a) widen the tradable universe (add indices/energy with a proper session
profile) to raise N; (b) accept these as a *risk-parity / diversification* overlay
rather than an alpha; (c) drop cross-sectional FX and pursue breadth elsewhere.

**Code note.** `xsection_fx.py` originally crashed: the hard filter
`if ok.sum() < 10` on a ~10-name universe required the latest-starting asset
(CNHUSD, whose `value_5y` needs a 5-year window) at every date → only 4 valid
rebalances → empty test folds → crash in the max-drawdown reduction. Fixed by
ranking the *available* names with a relative floor `MIN_NAMES = 6` (standard ragged-
panel handling); restored 395 rebalances. ⚠️ Universe membership depends on
`fx_loader.spreads_bps()` (10 vs 13 names seen across runs) — reproducibility
follow-up: pin the spread snapshot.

**Why it matters / next (breadth link).** Pairs with
[[exp-004-xsection-breadth-poc]], which isolates the breadth *mechanism* on equities.

**Links.** [[cross-sectional-vs-directional]], [[breadth]],
[[information-coefficient-and-ir]], [[factor-investing-cross-section]],
[[data-sources]].
