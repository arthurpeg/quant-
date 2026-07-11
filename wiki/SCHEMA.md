---
type: schema
updated: 2026-07-11
---

# SCHEMA — the rulebook

This file tells Claude how the wiki is structured and how to maintain it. It has
three parts: **(1) page templates**, **(2) workflows**, **(3) lint**.

Golden rule (immutability): the wiki is the *synthesis* layer. It **links** to raw
sources (`*.py`, `data_cache*/`, `*.log`) and **never copies their contents in as
the source of truth**. If you need a config value, link to `config.py`; do not
paste the constant and let it rot. Findings, verdicts, and cross-references are
what live here.

Dates are `YYYY-MM-DD`. Wikilinks use Obsidian style `[[page-name]]` inside prose
and normal markdown links in tables/index. Prefer `[[wikilinks]]` liberally — a
link to a page that doesn't exist yet is a fine TODO marker, not an error.

---

## 1. Page templates

### 1a. Experiment page — `experiments/<slug>.md`
The main unit of work. One page per hypothesis tested.

```markdown
---
type: experiment
id: exp-NNN
updated: YYYY-MM-DD
status: open | done | abandoned
verdict: no-edge | edge | partial | risk-mgmt-only | open
horizon: <e.g. 1H direction, 5d cross-sectional>
universe: <assets>
code: [file1.py, file2.py]        # raw sources this experiment lives in
---

# exp-NNN — <title>

**Hypothesis.** <the one-sentence claim being tested>

**Setup.** <data, features, target, split, costs — link to code, don't restate it>

**Result.** <the numbers: AUC / IC / R² / net P&L, with the walk-forward caveat>

**Verdict.** <what we now believe; be blunt about no-edge>

**Why it matters / next.** <what this unlocks or kills>

**Links.** [[related-concept]], [[related-experiment]]. If abandoned, add a row to
[[ledger]] (Failed Ideas).
```

### 1b. Concept page — `concepts/<slug>.md`
Vocabulary so the human and Claude mean the same thing by a term.

```markdown
---
type: concept
updated: YYYY-MM-DD
---

# <Concept name>

**Definition.** <tight, project-specific definition>

**How we use it here.** <where it shows up in this project / code>

**Pitfalls.** <the traps — e.g. leakage vectors, misread metrics>

**See also.** [[…]]
```

### 1c. Research page — `research/<slug>.md`
An ingested external reference (paper, book, article).

```markdown
---
type: research
updated: YYYY-MM-DD
source: <author / title / URL — the citation>
status: skim | read | applied
---

# <Source title>

**What it is.** <one line>

**Key takeaways.** <bullets — the parts relevant to us>

**Applied where.** <which experiment/concept uses it — [[links]]>
```

### 1d. Reference (router) page — `reference/<slug>.md`
A page that ONLY links to the authoritative source. Never restates details.

```markdown
---
type: reference
updated: YYYY-MM-DD
---

# <Topic> — router

> Router page: links to the authoritative source; does not restate it.

- <thing> → `path/to/file.py`  — <one-line what-it-owns>
```

### 1e. Index entry
One row in [index.md](index.md): a link, plus a one-line summary (and a verdict
emoji for experiments). Nothing else.

### 1f. Log entry — `log.md`
One dated line, append-only, never edited:
`## [YYYY-MM-DD] <type> | <what happened> | <outcome>`
where `<type>` ∈ {ingest, experiment, query, lint, setup, refactor}.

### 1g. Failed Ideas row — `Failed Ideas/ledger.md`
One table row: `| idea | when | why it failed | evidence/link |`.

---

## 2. Workflows

### After completing an experiment (or any unit of work)
1. Create/update `experiments/<slug>.md` from template 1a; set `status`/`verdict`.
2. Add/refresh its row in [index.md](index.md).
3. Append one line to [log.md](log.md) (template 1f).
4. If it was abandoned or produced a dead end, add a row to
   [Failed Ideas/ledger.md](Failed%20Ideas/ledger.md) (template 1g).
5. If it changed the overall picture, update [lessons.md](lessons.md).
6. Touch related [[concepts]] if a term's meaning sharpened.

### When ingesting an external source (paper/article)
1. Create `research/<slug>.md` (template 1c).
2. Link it from [index.md](index.md) and from any experiment/concept it informs.
3. Append an `ingest` line to [log.md](log.md).

### When answering a substantive query
1. Read [index.md](index.md) + [Failed Ideas/ledger.md](Failed%20Ideas/ledger.md) first.
2. Answer. If the answer is durable knowledge, file it back as a page (don't let
   it die in chat) and log a `query` line.

### Session start / session end
- **Start:** read [index.md](index.md) and [ledger](Failed%20Ideas/ledger.md).
- **End:** update the relevant page, append to [log.md](log.md), add a Failed Ideas
  row on any abandonment. `hot.md` regenerates automatically (do not hand-edit it).

---

## 3. Lint (periodic self-check)

Run this pass every so often (or when asked to "lint the wiki"):

- **Orphans.** Pages linked from nowhere. Every page should be reachable from
  [index.md](index.md) or another page. Fix by linking or deleting.
- **Stale entries.** A page whose verdict a newer experiment has superseded. Mark
  it and cross-link forward.
- **Contradictions.** Two pages that disagree. Reconcile; the log timeline says
  which is newer.
- **Missing concepts.** A term used across ≥2 pages with no `concepts/` page of
  its own → create one.
- **Missing Failed-Ideas rows.** An experiment with `verdict: no-edge` /
  `status: abandoned` that isn't in the ledger → add it.
- **Immutability drift.** A wiki page that pasted a config value / code block as
  truth instead of linking → replace with a link.
- **Index accuracy.** Every content page appears in [index.md](index.md) exactly
  once; no dead links.

Log each lint pass with a `lint` line in [log.md](log.md).
