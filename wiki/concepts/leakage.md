---
type: concept
updated: 2026-07-11
---

# Leakage

**Definition.** Any way information from the future (or from the test set) reaches
the model at training/feature time, inflating backtest metrics into fiction. The #1
way to fool yourself in quant ML.

**How we use it here.** Anti-leakage is a hard project constraint. Defenses in place:
- **Causal features only** — rolling windows with `center=False`, rolling z-scores;
  no look-ahead. (`features/*`.)
- **Temporal split with embargo** — [[walk-forward-embargo]]; embargo =
  `TIMEOUT_BARS` because [[triple-barrier]] labels look that far ahead.
- **Strict X/y separation** — X is everything known ≤ t; y is the future label.
  Enforced in `pipeline.run`.
- **Per-date normalization** in the cross-sectional work uses only that date's
  cross-section (no future stats).
- **Determinism check** — `dataset_hash` (double-run identical hash) guards against
  accidental order/state dependence, a cousin of leakage.

**Pitfalls / leak vectors to watch.**
- Fitting scalers / feature selection on the full series before splitting.
- Multi-timeframe features made available before the higher-TF bar *closes*
  (`ENABLE_MTF` uses `merge_asof` backward with availability = open + duration).
- Survivorship bias — using today's universe membership in the past ([[data-sources]],
  [[exp-004-xsection-breadth-poc]]).
- Overlapping labels leaking across the split boundary.

**See also.** [[walk-forward-embargo]], [[triple-barrier]],
[[cross-sectional-vs-directional]].
