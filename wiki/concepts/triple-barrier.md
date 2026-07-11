---
type: concept
updated: 2026-07-11
---

# Triple barrier labeling

**Definition.** López de Prado's labeling scheme (see
[[lopez-de-prado-afml]]). From each entry, three barriers race: an upper **take
profit** (`+X R`), a lower **stop loss** (`-1 R`), and a **vertical timeout** after
`N` bars. The label is which barrier is hit first: TP / SL / timeout.

**How we use it here.** Implemented in `labeling.py`; parameters in `config.py`
(`R_ATR_MULT`, `TP_R_MULTIPLE`, `SL_R_MULTIPLE`, `TIMEOUT_BARS`, `LABEL_MAP =
{sl:0, tp:1, timeout:2}`). **1 R = `R_ATR_MULT · ATR(14)`** in price units — the
barriers are volatility-scaled, not fixed pips. The timeout is counted in **market
bars**, never wall-clock, so weekend/holiday gaps don't shrink it. Ambiguous bars
(TP and SL both touched in one bar) resolve conservatively to SL
(`AMBIGUOUS_BAR_POLICY`).

**Pitfalls.**
- The label looks up to `TIMEOUT_BARS` into the future → it is the reason the
  train/test split needs an **embargo** of that many bars ([[walk-forward-embargo]],
  [[leakage]]).
- Overlapping labels are serially correlated; the executable backtests use
  non-overlapping trades to avoid double-counting.

**See also.** [[walk-forward-embargo]], [[leakage]], [[lopez-de-prado-afml]].
