---
type: experiment
id: exp-004
updated: 2026-07-11
status: done
verdict: partial
horizon: 5-day (weekly rebalance)
universe: 145 US equities (panel) — POC only, survivorship-biased
code: [xsection_poc.py, equity_loader.py]
---

# exp-004 — Breadth POC (equities)

**Hypothesis.** The lever is **breadth**, not signal strength. The fundamental law:
**IR ≈ IC · √(number of independent bets)** (see
[[information-coefficient-and-ir]]). A weak IC over hundreds of simultaneous bets
beats the same IC over one bet.

**Setup.** `xsection_poc.py` on `equity_loader.py`, two contrasting POCs on the
*same* data:
- **POC A — cross-sectional stocks (~200 bets/week).** Features normalized per date
  (rank stocks against each other); target = 5-day excess return vs universe mean.
  Metrics: Spearman IC, IR, and a net-of-cost long/short **decile** portfolio.
- **POC B — same data → predict ONE index (breadth = 1 bet).** Aggregate the stock
  panel into market-breadth features (% above 200-day MA, advance/decline ratio,
  cross-sectional dispersion…) to predict US30's 5-day return. Rich information, but
  a **single** bet.

The two POCs are built to have *comparable IC*; only the number of bets differs —
making IR ≈ IC·√N visible. Costs: 5 bps/side (10 bps round-trip).

**⚠️ Caveat.** Survivorship bias is present (see `equity_loader.py`). This POC
demonstrates a **mechanism**, not a deployable strategy.

**Result** (run 2026-07-11, 145 US stocks, 2015-2026, net of 5 bps/side):

| | POC A — cross-sectional (~138 bets/wk) | POC B — predict US30 (1 bet) |
|---|---|---|
| Rebalances / dates | 416 | 526 |
| Mean IC | **+0.0107** | +0.0005 |
| IC-IR (annual) | **+0.58** | ~0.00 |
| Direction AUC | — | 0.4736 |
| Gross / Sharpe | +6.63%/yr · 0.77 | — |
| **Net / Sharpe** | **+3.48%/yr · 0.40** | — |
| Max DD · win rate | −21.0% · 51.0% | — |

- **Same signal-quality region, opposite outcomes.** POC A's per-bet IC (+0.011) is
  tiny — but spread over ~138 weekly bets it compounds to **IR +0.58** and a net
  +3.48%/yr (Sharpe 0.40). POC B's single index bet yields **IR ≈ 0** (and AUC 0.47,
  i.e. no directional signal) despite using the *same underlying data*.
- This is **IR ≈ IC·√(breadth)** made visible: breadth, not signal strength, is the
  differentiator. See [[information-coefficient-and-ir]].

**Verdict.** ⚠️ **Partial — mechanism confirmed, not deployable.** The breadth effect
is real and measurable. BUT: (1) **survivorship bias** is present (`equity_loader.py`
uses still-listed symbols) — the +3.48%/yr is inflated; (2) these 145 US stocks are
**not prop-firm tradable** ([[prop-firm-universe]]). This proves *why* to pursue
breadth, not a strategy to deploy.

**Why it matters / next.** Justifies orienting the project toward wide cross-sections
rather than single-instrument prediction — and, read together with
[[exp-003-xsection-fx]], exposes the core tension: the mechanism needs many
independent names, but the **prop-firm universe only offers ~11**. The strategic
question is now "how do we get breadth inside the tradable universe?" Open
follow-ups: (a) rerun with a survivorship-bias-free panel; (b) find a prop-tradable
universe wide enough for real breadth.

**Links.** [[breadth]], [[information-coefficient-and-ir]],
[[cross-sectional-vs-directional]], [[exp-003-xsection-fx]], [[data-sources]].
