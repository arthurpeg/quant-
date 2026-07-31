# Quantocracy screen (2026-07-31) — 7 606 links, 0 new brick

Same user filter as the quantifiedstrategies pass: clear entry/SL/TP rules, no external
data, US & EU indices / forex / gold / crypto only, then backtest the survivors to the letter.

## The funnel

| Step | Count |
|---|---|
| Links on the 154 index pages | **7 606** (409 source blogs) |
| On an allowed asset | 1 013 |
| Minus external-data / wrong-asset markers | 662 |
| With a hint of a mechanical rule | 254 |
| Minus noise (podcasts, tutorials, reviews, jobs) | **231 fetched** |
| Fetched with usable text (87 dead / blocked / paywalled) | **144** |
| Fully specified **and** in scope | **4** |

Quantocracy is a link aggregator, not a strategy site: **87 % of its links are things the
user excluded** — single-stock factor research (Alpha Architect alone is 837 + 239 links),
asset allocation / risk parity / TAA, ML methodology, options and vol surface, fixed
income, macro commentary. It aggregates quantitative *research*, not executable rules.

Rejected at the read stage: DTR Trading (RUT iron condors = options), Alvarez Quant Trading
(country-ETF rotation, dividend screens, Hi-Lo breadth index), Black Arbs (2-asset
allocation), Allocate Smartly (monthly TSM — already ledger-killed), Rulyfi (meta-research
on backtest overfitting — worth reading, not a strategy), Quantpedia MACD-on-Bitcoin
(= brick 3's family, already in the book).

## The 4 testable strategies

| # | Rule (verbatim) | Source | Result |
|---|---|---|---|
| Q1 | "buy Bitcoin at 21:00 (UTC+0) and sell it at 23:00 (UTC+0)" | Quantpedia | **t = −7.19**, PF 0.65, 3/9 +yrs |
| Q2 | "Short at GMT 09:15, Wednesday/Thursday/Friday, close after 5 hours" | Quant Journey | **all 7 majors negative**, t −0.14 → −5.20 |
| Q3 | long on a new 10-day high, exit when the close is no longer a 10-day high | Quantpedia | ETH t=2.69 (+3.1 R/yr), BTC t=0.87 |
| Q4 | buy BTC at the NYSE close when on a local X-day high, sell at the NYSE open | Quantpedia | **t ≈ 2.1–2.2**, +1.3 → +1.7 R/yr |

**Q1** fails and its whole neighbourhood fails (19→23, 20→22, 21→22 all t between −5.3 and
−13.1). **Q2** fails on every pair, and the article's own comment section objection ("it is
just the post-2008 EURUSD downtrend") turns out to be wrong in an informative way: the
**symmetric long loses too** (t=−3.58), so it is not a directional bias, it is the spread.
Split-half on EURUSD: +0.71 then −0.77.

**Q3** is one asset out of two, sub-threshold after multiple testing, and it is the
Donchian/trend-on-crypto family that brick 3 already covers. **Q4** is real but tiny —
smaller than brick 2, the book's thinnest sleeve — and below the project's bar.

## ⚠️ The find that matters: a look-ahead that read t = 17.4

Q4 first came out at **+11.8 R/yr, t = 17.43, PF 10.51, 9/9 positive years**. That is not
an edge, it is a bug, and the tell was the profit factor: an overnight crypto trade does
not have PF 10.

Cause: after `to_true_utc`, a **D1 bar stamped day D covers D 21:00 UTC → D+1 21:00 UTC**.
The "on a local X-day high" condition was evaluated on that bar's *close* — which is only
known 24 h later — while the entry was at 21:00 UTC on day D. The filter was therefore
selecting nights that *ended* at a high: it was reading the very move it claimed to trade.

Fixed by giving every daily value an explicit `known_at = timestamp + 1 day` and taking
only bars with `known_at <= entry time`. The effect collapses **t 17.43 → 2.23**.

For calibration, the unconditional version of the same window (buy 21:00 UTC, sell at the
next NYSE open, no filter) is **−1.81 R/yr, t = −1.33** net of cost, i.e. the raw overnight
window does not pay; the filter adds a little, but only a little.

**Lesson (now the third variant of the same lesson this month):** on a broker feed, a daily
bar's timestamp is the *start* of its session, not a date. Any rule that mixes daily
conditions with intraday entries needs an explicit "known at" time, or it will read the
future. Cf. the tz bug in the ledger and the two cadence corrections in `wiki/log.md`.

## Files
`scratchpad/qc_index.py` (154 index pages), `qc_triage.py` (the 3 filters),
`qc_fetch.py` (231 articles from 83 blogs), `qc_rules.py` (rule extraction),
`qc_run.py` (the 4 backtests), `qc_links.csv`, `qc_shortlist.csv`, `qc_rules.csv`,
`qc/` + `qc_pages/` (raw pages).
