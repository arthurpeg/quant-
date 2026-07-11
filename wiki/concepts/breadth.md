---
type: concept
updated: 2026-07-11
---

# Breadth

**Definition.** The number of **independent bets** a strategy makes per period. The
second term in **IR ≈ IC · √(breadth)** (see [[information-coefficient-and-ir]]).

**How we use it here.** Breadth is the lever this project decided to pull after
direction prediction failed. Instead of one high-conviction call on one instrument
(breadth = 1), rank a whole universe and take many small simultaneous positions
(breadth = N). This is the difference between [[exp-004-xsection-breadth-poc]] POC A
(~200 stock bets/week) and POC B (1 index bet) built on identical data.

**Pitfalls.**
- **Correlation destroys breadth.** N positions that all rise and fall together are
  ~1 bet. FX pairs sharing a USD leg, stocks in one sector, etc. The FX book in
  [[exp-003-xsection-fx]] goes long/short specifically so the common USD exposure
  cancels and residual bets are more independent.
- **Overlapping holding periods** reduce effective breadth — hence non-overlapping
  5-day rebalancing.
- More instruments ≠ more breadth if they're redundant.

**See also.** [[information-coefficient-and-ir]], [[cross-sectional-vs-directional]].
