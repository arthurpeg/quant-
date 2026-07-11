---
type: index
updated: 2026-07-11
---

# Wiki Index — the catalog

> **This is the FIRST file to read at the start of every session.** It is the
> table of contents for the whole knowledge base. Skim it, then drill into the
> pages you need. After `index.md`, always also read
> [Failed Ideas/ledger.md](Failed%20Ideas/ledger.md) before starting new work —
> it is the list of dead ends we must not re-walk.
>
> This wiki is LLM-maintained. Claude reads it at session start and updates it
> before finishing. Obsidian is the human's viewer; the markdown folder is the
> real memory. See [SCHEMA.md](SCHEMA.md) for the rules and templates.

Project: **ML quantitatif** — feature engineering + labeling + ML research for an
intraday / cross-sectional systematic trading system on prop-firm assets.
Raw sources of truth are the **code** (`*.py`) and **data** (`data_cache*/`); this
wiki links to them and never copies them in as truth.

---

## Hub pages (the backbone)

| Page | Purpose |
|------|---------|
| [index.md](index.md) | This catalog. Read first. |
| [SCHEMA.md](SCHEMA.md) | The rulebook: page templates, workflows, lint checks. |
| [log.md](log.md) | Append-only chronological log of everything that happened. |
| [hot.md](hot.md) | **Auto-generated** current-state snapshot. Never hand-edit. |
| [lessons.md](lessons.md) | Cross-cutting synthesis of what we've learned. |
| [Failed Ideas/ledger.md](Failed%20Ideas/ledger.md) | Every abandoned idea + why. Read before new work. |

## Experiments (the unit of work — one page each)

| Experiment | Verdict | Summary |
|------------|---------|---------|
| [exp-001 — V1 single-TF direction baseline](experiments/exp-001-v1-single-tf-direction.md) | ❌ no edge | 1H triple-barrier direction, AUC ≈ 0.52; P&L is just drift. |
| [exp-002 — V3 MT5 four "new info" angles](experiments/exp-002-v3-mt5-four-angles.md) | ⚠️ partial | Vol target works (risk mgmt only); cross-asset / seasonality / order-flow fail. |
| [exp-003 — Cross-sectional FX + metals](experiments/exp-003-xsection-fx.md) | ❌ no edge | ~11-name prop universe too narrow; ML overfits (IC −0.03), momentum insignificant (t=1.19). |
| [exp-004 — Breadth POC (equities)](experiments/exp-004-xsection-breadth-poc.md) | ⚠️ partial | Breadth mechanism confirmed: IR +0.58 (138 bets) vs ~0 (1 bet). Survivorship-biased, not deployable. |
| [exp-005 — MT5 intraday vol breakout (Nasdaq)](experiments/exp-005-mt5-intraday-vol-breakout.md) | 🚧 open | External MQL5 EA on NAS100 (US-open breakout). Strong negative prior (single-asset direction); test rigorously OOS + costs. |

## Concepts (shared vocabulary)

| Concept | What it pins down |
|---------|-------------------|
| [Triple barrier labeling](concepts/triple-barrier.md) | How trades are labeled (TP / SL / timeout). |
| [Walk-forward & embargo](concepts/walk-forward-embargo.md) | Temporal split, no leakage across the labeling window. |
| [Information Coefficient & IR](concepts/information-coefficient-and-ir.md) | IC, Information Ratio, and IR ≈ IC·√(breadth). |
| [Breadth](concepts/breadth.md) | Number of independent bets — the lever this project now pulls. |
| [Cross-sectional vs directional](concepts/cross-sectional-vs-directional.md) | Ranking assets vs predicting one asset's direction. |
| [Leakage](concepts/leakage.md) | Every way future info can sneak into X; how we prevent it. |
| [Prop-firm universe](concepts/prop-firm-universe.md) | The allowed asset whitelist and why it constrains us. |

## Research (ingested external references)

| Page | Source |
|------|--------|
| [López de Prado — AFML](research/lopez-de-prado-afml.md) | Triple barrier, meta-labeling, purging/embargo, fractional diff. |
| [Factor investing & cross-section](research/factor-investing-cross-section.md) | Momentum/value/carry factors, fundamental law of active management. |

## Reference (router pages — link only, never restate)

| Page | Routes to |
|------|-----------|
| [Codebase map](reference/codebase-map.md) | Which `.py` file owns what. |
| [Data sources](reference/data-sources.md) | Yahoo cache vs MT5 cache vs equity panel. |
