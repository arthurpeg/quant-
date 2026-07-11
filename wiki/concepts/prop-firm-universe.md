---
type: concept
updated: 2026-07-11
---

# Prop-firm universe

**Definition.** The set of instruments a funded prop-firm account (FTMO / The5ers /
FundingPips style) is allowed to trade: **forex, indices, metals, energies**.
Crypto spot and individual equities are **excluded**. This is a hard constraint on
every deployable strategy in this project.

**How we use it here.** The whitelist is the source of truth in `config.py`
(`WHITELIST`, validated by `validate_symbol`) — don't restate the symbols here, link
to it. Consequences that shape experiments:
- Deployable work must stay inside FX / indices / metals / energy
  ([[exp-003-xsection-fx]]).
- The equity breadth POC ([[exp-004-xsection-breadth-poc]]) uses ~200 stocks only to
  demonstrate the [[breadth]] *mechanism* — those stocks are **not** tradable on a
  prop account. It's a proof of concept, not a strategy.
- Forex is not 24/7: Sun 22:00 → Fri 22:00 UTC. Never ffill across
  weekends/holidays/maintenance ([[data-sources]]).

**Pitfalls.**
- Don't let a nice equities/crypto result sneak into "deployable" — check it's in
  the whitelist first.
- Per-broker symbol names and specs vary; the whitelist is broker-facing.

**See also.** [[data-sources]], [[cross-sectional-vs-directional]], [[breadth]].
