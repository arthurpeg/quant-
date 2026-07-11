---
type: concept
updated: 2026-07-11
---

# Information Coefficient (IC) & Information Ratio (IR)

**Definition.**
- **IC** — the (rank/Spearman) correlation between the model's predicted scores and
  realized forward returns. A measure of *signal quality per bet*. IC ≈ 0.03–0.05 is
  already a decent equity signal; IC ≈ 0.5 is huge.
- **IR** — Information Ratio: annualized active return ÷ active risk. A measure of
  *strategy quality*.
- **The Fundamental Law of Active Management** (Grinold):
  **IR ≈ IC · √(breadth)**, where breadth = number of *independent* bets per period.

**How we use it here.** This identity is the project's current thesis. It explains
why [[exp-001-v1-single-tf-direction]] failed and how the pivot could succeed: a
tiny IC on **one** instrument (breadth = 1) yields a tiny IR — useless. The *same*
tiny IC spread over hundreds of simultaneous [[cross-sectional-vs-directional]] bets
(large [[breadth]]) yields a usable IR. Measured directly in
[[exp-004-xsection-breadth-poc]] (POC A ~200 bets vs POC B 1 bet) and applied in
[[exp-003-xsection-fx]].

**Pitfalls.**
- **"Independent" is the load-bearing word.** Correlated bets don't count as full
  breadth — 200 stocks in one sector ≈ far fewer than 200 independent bets. Overlap
  in time (holding period > rebalance) also shrinks effective N.
- A high IC on a single index (POC B) is still worthless if breadth = 1.

**See also.** [[breadth]], [[cross-sectional-vs-directional]],
[[factor-investing-cross-section]], [[walk-forward-embargo]].
