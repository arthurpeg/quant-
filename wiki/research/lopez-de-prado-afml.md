---
type: research
updated: 2026-07-11
source: "Marcos López de Prado — Advances in Financial Machine Learning (2018)"
status: applied
---

# López de Prado — Advances in Financial Machine Learning

**What it is.** The methodological backbone for the labeling and validation in this
project. (Reference stub — expand with specific chapter notes as we lean on them.)

**Key takeaways (as used here).**
- **Triple-barrier labeling** — TP / SL / vertical-timeout; the basis of
  [[triple-barrier]] (`labeling.py`).
- **Meta-labeling** — a second model that decides whether to *act* on the primary
  model's signal (bet sizing / precision). Noted as a candidate next step, not yet
  tried.
- **Purging & embargo** — remove train samples whose label windows overlap the test
  set; the reason for our `EMBARGO_BARS = TIMEOUT_BARS` ([[walk-forward-embargo]]).
- **Sample uniqueness / overlapping labels** — overlapping triple-barrier labels are
  serially correlated; motivates non-overlapping execution in the backtests.
- **Fractional differentiation** — stationarity while preserving memory. Not yet
  used.

**Applied where.** [[triple-barrier]], [[walk-forward-embargo]], [[leakage]],
[[exp-001-v1-single-tf-direction]].
