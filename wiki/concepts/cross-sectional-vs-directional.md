---
type: concept
updated: 2026-07-11
---

# Cross-sectional vs directional

**Definition.**
- **Directional** — predict the *absolute* future move of one instrument ("will
  EURUSD go up?"). Requires being right about the market's overall direction.
- **Cross-sectional** — predict the *relative* ranking of many instruments at a
  point in time ("which of these 20 will out/under-perform the basket?"). Trade
  long the top, short the bottom; the common component (market beta, shared USD leg)
  cancels in the long/short book.

**How we use it here.** The whole project pivoted from directional
([[exp-001-v1-single-tf-direction]], [[exp-002-v3-mt5-four-angles]] — both
**no-edge**) to cross-sectional ([[exp-003-xsection-fx]],
[[exp-004-xsection-breadth-poc]]). Cross-sectional is attractive here for two
reasons: (1) it doesn't require predicting direction, which we showed is
unpredictable in this universe; (2) it naturally creates [[breadth]] — many
simultaneous bets — which is what makes a weak IC usable via
[[information-coefficient-and-ir]].

**Pitfalls.**
- Features must be normalized **per date** (rank/z-score across the cross-section),
  not per asset over time — otherwise you're back to a directional signal.
- The target is **excess** return vs the universe mean, not raw return.
- Still needs honest costs (per-asset spread × turnover) and survivorship-bias
  awareness ([[data-sources]]).

**See also.** [[breadth]], [[information-coefficient-and-ir]],
[[factor-investing-cross-section]].
