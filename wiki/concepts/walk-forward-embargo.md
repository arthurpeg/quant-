---
type: concept
updated: 2026-07-11
---

# Walk-forward & embargo

**Definition.** A **temporal** train/test split (never random): the test set is the
*end* of the series, so the model is only ever evaluated on data that came after its
training data. An **embargo** is a gap of dropped bars between train and test.

**How we use it here.** `pipeline.walk_forward_split` — test is the last
`TEST_SIZE_FRACTION` of the series; an embargo of `EMBARGO_BARS = TIMEOUT_BARS` bars
is removed from the end of train. Why exactly `TIMEOUT_BARS`: [[triple-barrier]]
labels peek up to `TIMEOUT_BARS` into the future, so without the gap the last train
labels would overlap the first test features → [[leakage]]. The cross-sectional
experiments use K-fold **walk-forward** folds instead (4 folds in
[[exp-003-xsection-fx]] / [[exp-004-xsection-breadth-poc]]).

**Pitfalls.**
- Random K-fold on time series is a classic leak — never use it here.
- Any global preprocessing fit on the whole series (scaling, feature selection)
  before splitting also leaks. Fit on train only.
- `feature_label_corr` in `pipeline.py` is diagnostic only — do **not** select
  features on the full dataset before the split.

**See also.** [[leakage]], [[triple-barrier]], [[information-coefficient-and-ir]].
