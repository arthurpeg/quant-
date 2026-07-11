# CLAUDE.md — ML quantitatif

Python research project: feature engineering + labeling + ML for a systematic
trading system on **prop-firm assets** (forex, indices, metals, energies). The core
finding so far: single-asset **direction is not predictable** here (AUC ≈ 0.51–0.52);
the live thread is **cross-sectional / breadth** strategies. See the wiki.

## Wiki

This repo carries an **LLM-maintained wiki** at `wiki/` — a persistent knowledge
base that Claude reads at the start of every session and updates before finishing,
so knowledge compounds across sessions instead of being rediscovered. Obsidian is
the human's viewer; the markdown folder is the real memory.

**STANDING RULES (follow every session):**

1. **Before starting any substantive work:** read [`wiki/index.md`](wiki/index.md)
   **and** [`wiki/Failed Ideas/ledger.md`](wiki/Failed%20Ideas/ledger.md) first.
   The ledger lists dead ends we must not re-walk (e.g. predicting single-asset
   direction — already proven futile).

2. **Before finishing:** update the relevant wiki page(s), append one dated line to
   [`wiki/log.md`](wiki/log.md), and add a row to the Failed Ideas ledger on any
   abandonment. Follow the templates and workflows in
   [`wiki/SCHEMA.md`](wiki/SCHEMA.md).

**Immutability rule:** the wiki is the *synthesis* layer. It **links** to raw
sources (`*.py`, `data_cache*/`, `*.log`) and **never copies their contents in as
the source of truth**. Config values, code, and data live in their files; the wiki
points at them. If a value would rot, link it — don't paste it.

**`wiki/hot.md` is auto-generated** by `wiki/update_hot.py` (runs on session Stop).
Never hand-edit it except the `Next Actions` block, which the generator preserves.

**Obsidian note:** Obsidian rewrites `.obsidian/graph.json` while running, so only
edit that file when Obsidian is **closed**.

## Sync & automation

**Sync = OneDrive.** This repo lives inside the user's OneDrive folder, so the whole
project (wiki, code, config) syncs across the user's machines automatically — no `git
pull` needed. Discipline: **one machine at a time**, and wait for OneDrive "Up to date"
before switching. GitHub is only an occasional manual backup.

`.claude/settings.json` keeps a single fail-safe hook (PowerShell, Windows):
- **Stop:** regenerate `wiki/hot.md` via `wiki/update_hot.py`.

The git auto pull/commit/push hooks were intentionally removed: a live `.git` folder
syncing through OneDrive while hooks run git can corrupt the repo. Do NOT re-add
automated git here. To back up to GitHub, commit/push manually from one machine.
