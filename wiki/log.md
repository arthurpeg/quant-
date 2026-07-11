---
type: log
updated: 2026-07-11
---

# Log — append-only

Chronological record of everything that happened. **Append only, never edit.**
Each entry is one line:
`## [YYYY-MM-DD] <type> | <what happened> | <outcome>`
`<type>` ∈ {ingest, experiment, query, lint, setup, refactor}.
Grep the last few with: `grep "^## \[" wiki/log.md | tail -5`.

## [2026-07-11] setup | Bootstrapped the LLM-maintained wiki (hubs, experiments, concepts, research, reference, Failed Ideas ledger, update_hot.py, hooks, Obsidian) | Wiki live; seeded from project memory
## [2026-07-11] experiment | Backfilled exp-001..004 from prior sessions' findings | V1 direction = no edge; V3 vol = risk-mgmt only; cross-sectional/breadth = current open thread
## [2026-07-11] refactor | Fixed xsection_fx.py sample-degeneracy crash (hard `ok.sum()<10` on ~10-name universe → 4 rebalances → empty folds); use relative MIN_NAMES=6 | 395 rebalances restored
## [2026-07-11] experiment | Ran exp-003 (cross-sectional FX/metals, real numbers) | NO EDGE: ML IC −0.029 Sharpe −1.29; momentum best but insignificant (t=1.19); breadth ~11 too low. Added ledger row
## [2026-07-11] experiment | Ran exp-004 (breadth POC equities, real numbers) | PARTIAL: mechanism confirmed IR +0.58 (~138 bets) vs ~0 (1 bet); survivorship-biased, not deployable
## [2026-07-11] lint | Reconciled exp-003/004 verdicts across index, lessons, ledger, hot | Wiki consistent; wall = prop universe too narrow for breadth
## [2026-07-11] experiment | Filed exp-005 (external MQL5 intraday Gold breakout EA) + saved mql5/IntradayVolatilityBreakout.mq5 | Status open; strong negative prior (single-asset direction ledger); code review flagged 5 blockers (server-time, SYMBOL_LAST=0 on CFD, FOK, min_lot risk, tester mode); pending OOS/cost test
## [2026-07-11] refactor | Corrected exp-005: asset is NASDAQ (NAS100) not Gold; resolved broker-time (EET/EEST UTC+3 = Paris+1) → default hours already map to US open 09:30 NY, no change needed | Server-time blocker resolved; DST caveat noted
## [2026-07-12] experiment | exp-005 Python proxy cross-check (backtest_breakout_us30.py): US30 H1 breakout+regime, no NAS100/M1 data available | FLAT in both-directions (E[R]+0.010, PF 1.02, Sharpe~0); positive only on long = bull drift; regime filter helps marginally. Reinforces no-edge prior; MT5 NAS100 M1 still pending
## [2026-07-12] ops | Migrated 29.4GB MT5 tick cache C:->E: via directory junction (D: was ACL-locked) | C: free 4.9->48.9GB; MT5 data at E:\MetaQuotes\Terminal via junction, transparent
## [2026-07-12] lint | User flagged MT5 data quality: on MetaQuotes-Demo (synthetic feed) | Recorded 3rd data wall in data-sources + lessons + memory; exp-005 MT5 test blocked pending a real broker feed
## [2026-07-12] ops | Switched sync to OneDrive-only: removed git auto pull/commit/push hooks (kept hot.md regen), added .gitignore | Repo is in OneDrive → syncs across machines without git; one-time GitHub backup push done. Rule: one machine at a time, wait for OneDrive "Up to date"
