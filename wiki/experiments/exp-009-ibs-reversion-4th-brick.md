---
type: experiment
status: candidate
verdict: "✅ candidate 4th brick (decorrelated, book-improving)"
updated: 2026-07-31
---

# exp-009 — IBS reversion: 4th decorrelated brick

**Origin.** User-supplied Pine v5 strategy "ES NIBBA" (daily **IBS** mean-reversion on
the S&P 500). IBS = Internal Bar Strength = `(close − low) / (high − low)` — where the
close sits in the day's range. This is the first idea in the whole brick-4 hunt that
**clears the bar**: decorrelated *and* improves the book on every axis. It also
**partially reverses** the project thesis that "reversion is dead everywhere" (see
[[ledger]], [[system]]) — reversion is alive as a **US-equity-index** effect.

**Rule (Pine base + mandatory stop, measured in R).**
- entry: `IBS < 0.2` & flat → fill next bar open
- **stop: `entry − k·ATR14`** (set at entry, ATR known through the signal bar); **1R = k·ATR**
- exits (first of): STOP (intrabar low ≤ stop, gap-aware) / `IBS > 0.8` at close → next open / 30-bar timeout
- `capital`/`risk_money` inputs in the Pine are **dead** (never referenced); real Pine
  sizing was `percent_of_equity=10` (a low-exposure artefact that undersells the edge).

**Method.** Faithful event-driven replica on `data_cache_mt5/*_D1.parquet` (Pepperstone,
2018-2026), next-open fills, intrabar stop on daily lows, ~2pt round-trip cost. Reported
in **R** to match the book. k-ATR sweep, all-prop-index generalization, correlation to the
3 bricks via the exact `scratchpad/verify_bricks.py` daily-R construction, then the
canonical block-bootstrap MC (`monte_carlo_static.py` methodology).

**Result 1 — the IBS edge is a US-index phenomenon.** k=2.5·ATR, net of ~2pt:

| Asset | t | E[R] | R/yr | +yrs | | Asset | t |
|---|---|---|---|---|---|---|---|
| **NAS100** | **4.68** | +0.143 | +5.2 | 8/9 | | GER40 | 1.19 |
| **US500** | **3.36** | +0.110 | +3.9 | 8/9 | | FRA40 | 0.59 |
| **US2000** | **2.70** | +0.076 | +2.6 | 10/11 | | UK100 | 0.69 |
| US30 | 1.63 | +0.057 | +2.0 | 7/9 | | NETH25/HK50/SWI20/AUS200 | ~0–1.9 |

US indices pass strongly; **Europe/Asia ≈ 0**. The pooled t (5.58) is **inflated** — the
US indices co-fire on risk-off days (no true √N [[breadth]], the [[ledger|basket lesson]]).
The honest signal is NAS100 / US500 / US2000 individually.

**Result 2 — total decorrelation from the 3 bricks** (daily-R Pearson, calendar index):

| IBS variant | vs NAS(b1) | vs gold(b2) | vs crypto(b3) | max\|corr\| |
|---|---|---|---|---|
| **IBS NAS100** | **+0.001** | +0.016 | −0.008 | **0.016** |
| IBS US500 | +0.005 | −0.013 | −0.030 | 0.030 |

Same order as the existing brick-brick corrs (~0.02). Elegant: IBS NAS100 is on the **same
asset as brick 1** yet corr ≈ 0 — intraday breakout and daily-close reversion are
orthogonal mechanisms on one instrument. (Canonical re-run on the report's daily-R
construction: **+0.024 / −0.017 / −0.035**, max |corr| **0.035** — same verdict.)

**Result 3 — robustness (the tests that killed GER40 / Forecast-to-Fill).**
NAS100 IBS k=2.5: cost-robust to **6pt → t=4.44**; **split-half early t=3.32 / late t=3.30**
(stable, unlike GER40); bootstrap **P(E[R]≤0)=0.0000**; 8/9 +years. US500 is weaker
(early-half t=1.45, cost-fragile past 4pt); US2000 dies on Russell spread by 4pt.
→ **NAS100 IBS k=2.5 is the lead**; US500 the same-asset-avoiding alternative.

**Result 4 — the book improves on every axis** (add NAS100 IBS @1R):

| | R/yr | maxDD | RoMaD | Sharpe |
|---|---|---|---|---|
| 3-brick | +32.5 | 15.8R | 2.06 | 2.42 |
| **4-brick (+IBS)** | **+38.2** | **13.4R** | **2.85** | **2.63** |

First candidate ever to **raise Sharpe AND lower maxDD AND add return** — the ⭐ ledger
candidates (GER40, US500-ORB) *lowered* Sharpe or were correlated to brick 1.

**Result 5 — Monte Carlo** (block-bootstrap B=14, 40k sims, canonical methodology):
P(profit yr) **96.5%→98.2%**, median **+32.1→+37.6 R/yr**, **5th-pct year +2.6→+7.7 R**
(the diversification signature — the bad-luck floor lifts), median maxDD 10.5→10.0 R,
Sharpe 2.42→2.63. Challenge pass @1%/trade **90.0%→92.8%**, median time 4.2→3.8 mo; worst
day unchanged −4.15R (IBS never trades the book's worst day) so the ~1.2% ceiling holds.

⚠️ Results 4–5 are the **canonical re-run** (2026-07-31, `edgelab/reports/build_reports.py`
→ `monte_carlo_static.build_daily_R` + `simulate`). The first pass from the exploratory
scratchpad scripts read marginally higher (+38.3 R/yr, maxDD 13.3 R, MC median +37.8,
5th-pct +8.0) — same conclusion, ±0.1–0.6 R of construction/seed noise. The canonical
numbers are the ones in [[system]] and the two HTML reports.

**Verdict.** ✅ **Candidate 4th brick = NAS100 IBS reversion, k=2.5·ATR.** Genuine,
decorrelated, robust (cost + split-half + bootstrap), and it improves the book on every
metric. **Caveats / not-yet-deployed:**
1. **Long equity beta.** The whole IBS family is long-only reversion on US indices →
   structurally long equity. The daily-R corr ~0 **understates tail co-movement in a
   secular bear** (2018 −6R, 2022 −3.7R here, stop-bounded but real); a 2000-02-type
   regime would bleed more than the 2018-26 bootstrap suggests. Reason to size it ≤1R,
   not over-weight. (Same "MC understates long bear regimes" caveat as brick 3.)
2. **In-sample**, like the whole book — no forward test.
3. NAS100 variant = **single-instrument concentration** with brick 1 (signals distinct,
   but shared feed/regime risk); US500 variant avoids it but is more fragile.
4. **DEPLOYED live 2026-07-31** ([`edgelab/edges/ibs.py`](../../edgelab/edges/ibs.py) +
   `edgelab/live/` `NasIbsStrategy`, magic 105). `verify` proves the live signal layer
   reproduces **314/314 trades exactly**. But the deployable version earns
   **+4.81 R/yr, not +5.64**: `run_ibs` can re-enter on the *same daily bar* a stop fired,
   filling at that bar's **open** — a price already past by then. 13 such trades over
   2018-07→2026-07 = **−6.8 R** that no live driver can capture. The edge is unharmed
   (live-cadence **t=5.16 / PF 2.21 / 8-9 +yrs** vs backtest 4.77 / 1.99), but the book's
   canonical +38.2 R/yr is **~0.8 R/yr optimistic** because the reports use `run_ibs`.

**Code.** [`edgelab/edges/ibs.py`](../../edgelab/edges/ibs.py) (the rule, R-based, canonical)
and [`edgelab/reports/build_reports.py`](../../edgelab/reports/build_reports.py) (rebuilds
the 4-brick backtest + MC + both HTML reports in one command). Exploratory originals:
`scratchpad/es_nibba_ibs*.py`, `ibs_multi.py`, `ibs_corr.py`, `mc_4brick.py`.
Data `data_cache_mt5/*_D1.parquet`.

**See also.** [[system]], [[exp-005-mt5-intraday-vol-breakout]] (#1),
[[exp-007-turn-of-month-2nd-brick]] (#2), [[exp-008-crypto-breakout-3rd-brick]] (#3),
[[breadth]], [[ledger]].
