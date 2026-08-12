# edgelab.live — live / forward-test runner (4-brick book on MT5 / Pepperstone)

One Python process, four strategy modules, one shared risk manager. It reuses the
**exact** backtest signal math (see `edgelab/live/verify.py`), so live cannot silently
diverge from the backtest. **Dry-run by default** — it connects to MT5 only to pull
Pepperstone bars, logs the orders it *would* place, and paper-tallies realised R.

## The four bricks (unchanged from the frozen book — see `wiki/system.md`)
| Brick | Symbol | When it acts | Magic | Rule (source of truth) |
|-------|--------|--------------|-------|------------------------|
| 1 | NAS100 | intraday, US open | 101 | `signals.nas_orb_scan` → `intraday/atr_breakout.py` |
| 2 | XAUUSD | daily rollover | 102 | `signals.tom_state` → `edges/turn_of_month.py` |
| 3 | BTCUSD, ETHUSD | daily rollover | 103/104 | `signals.crypto_entry` → MACD-RSI + engine barriers |
| 4 | NAS100 | daily rollover | 105 | `signals.ibs_state` → `edges/ibs.py` |

Bricks 1 and 4 share the NAS100 instrument but are different mechanisms (intraday
breakout vs daily-close reversion, daily-R corr ≈ 0) and different magics, so they hold
**separate positions** and never interfere. Brick 4 is long-only with no TP: it exits on
the broker-managed stop, on `IBS > 0.8` at a close, or after 30 D1 bars.

## Before anything: verify live == backtest
```bash
python -m edgelab.live.verify
```
Expected: brick1 830/830 exact, brick3 identical, brick2 ~98% (2 holiday-shifted
month-ends — the business-day calendar approximation, see below), brick4 **314/314
trades exact** on signal math.

⚠️ **Brick 4's exploratory loop was not fully reachable by any driver** — it read
**+5.64 R/yr** where only **+4.81** can be traded. Three ordering artefacts: it ran its
entry test *after* the exit block of the same bar (so it could re-enter on the very bar a
stop fired, at that bar's open — a price already past), it never tested the exit on the
entry bar (a signal exit needed ≥2 bars; a driver can exit after one), and it resolved the
stop before the entry. The edge is *stronger* on the live cadence (t 5.16 vs 4.77, PF 2.21
vs 1.99) — only the R/yr was optimistic. **`run_ibs(cadence="live")` is now the default and
the whole book is priced on it**; `cadence="literal"` survives only so `verify` can prove
the live signal math reproduces the original loop. `verify` prints the gap on every run.

## Current mode: LIVE orders on a DEMO account
`config_live.yaml` ships with `live_trading: true` — the runner **sends real MT5
orders**, which is safe because the Pepperstone account is a **demo**. A hard safety
gate (`allow_real_account: false`) makes `connect()` **refuse to send orders if the
connected account is not a demo** — so pointing it at a real account later fails loudly
instead of trading real money. To go back to paper-only, set `live_trading: false`.

## Run it
1. Open your **Pepperstone MT5 terminal** and log in to the **demo** account (the
   runner attaches to it) and enable "Algo Trading" in the terminal.
2. Check `config_live.yaml` → `symbol_map`: the logical names (NAS100/XAUUSD/BTCUSD/
   ETHUSD) must map to *your broker's exact* Market-Watch symbols (they often carry a
   suffix, e.g. `NAS100.a`). Enable those symbols in Market Watch.
3. Start the loop:
```bash
python -m edgelab.live.runner
```
Other modes: `--once` (single pass, for cron), `--status` (print account + positions).

Live entries are sent via `mt5.order_send` with SL/TP **attached to the position** (the
broker manages the brackets); the runner only enforces the time-exits. Every entry/exit
is logged to console and appended to `edgelab/live/_out/trades.csv` (your forward-test
record). Sizing = **1R = `risk_per_trade` × `initial_balance`** (fixed-fractional, no
compounding). Recommended: **1.0%** to pass a static-DD challenge, **0.5%** once funded.

**Deux bases, à ne pas confondre.** `initial_balance` est la base de *sizing* : avec
`size_from_account:true` le runner la recale sur le solde réel à chaque démarrage et
à chaque reconnexion MT5, pour que 1R vaille bien 1 % du compte connecté. Les
**planchers prop** (DD total, perte journalière) vivent sur `risk.floor_basis`, posé
**une seule fois** au démarrage depuis `propfirm.challenge_start_balance` (ou
`_out/account_start.json`). Avant le 2026-08-12 les planchers se calculaient sur la
base de sizing : ils **descendaient avec le solde**, donc une reconnexion en plein
drawdown reposait le plancher −10 % plus bas et le halt pouvait ne jamais partir.

The live path also: picks a filling mode the symbol supports, widens SL/TP to clear the
broker's minimum stop distance, clamps lots to the symbol's min/max, and retries on
requotes.

## Keep it running 24/7
The runner only enforces **time-exits and new entries while it is alive** (SL/TP are
broker-side and survive an outage, so risk is always capped). It self-heals a dropped
MT5 connection (health-check + reconnect every cycle) and logs to `_out/runner.log`
(rotating). To survive a **process crash** or reboot, use the supervisor:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File edgelab\live\run_forever.ps1
```
It relaunches the runner if it crashes; it **stops** (does not restart) on a clean
interrupt or a blown account (exit 42). Stop it anytime by creating `edgelab\live\_out\STOP`
or closing the window. Logs to `_out/supervisor.log`.

**Track the forward-test** — a one-command readout of the trade journal (realised R
total / per brick / per month, win rate, profit factor, open positions):
```powershell
py -3 -m edgelab.live.summary
```

**Daily Discord heartbeat (dead-man's switch)** — set `discord_webhook_url` (+ optional
`daily_report_et`) in config_live.yaml. The runner posts a summary once a day; its
ABSENCE is the alert (no report today => the runner is down). Test the webhook now:
```powershell
py -3 -m edgelab.live.summary --discord "https://discord.com/api/webhooks/XXXX/YYYY"
```

**Auto-start at logon** (optional, run once, no admin):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File edgelab\live\install_task.ps1
```
Registers a Scheduled Task `edgelab-live`. For headless restarts, leave the MT5 terminal
running (or set `mt5_path:` in `config_live.yaml` so `mt5.initialize()` can launch it) and
enable "save account/password" in the terminal so it reconnects on its own.

**Best of all: a VPS** with the terminal always up — the runner must be alive to enforce
time-exits (brick 1 flat at 15:55 ET, brick 2 at the window end, brick 3 after 10 days,
brick 4 on `IBS > 0.8` or 30 bars). Brick 4's **stop** is attached to the position, so the
broker still protects it if the runner is down; only its signal/time exits need the runner.

## Auto-update from GitHub (no more manual file copies)
With `auto_update: true` and the VPS folder as a **git clone**, the runner checks
`origin/main` every `update_check_min` minutes; when a new commit exists it exits and the
supervisor `git pull`s + relaunches — so a `git push` propagates to the VPS on its own. If
the pulled code fails to import, the supervisor **rolls back** to the last-good commit
(trading continues). `config_live.yaml` is gitignored → never overwritten. One-time VPS
bootstrap (needs `git`): from the runner folder,
```powershell
git init; git remote add origin https://github.com/arthurpeg/quant-.git; git fetch origin; git reset --hard origin/main
```
then run under `run_forever.ps1`. Edit only `config_live.yaml` (untracked) on the VPS —
never tracked files, or the next sync discards them.

## Deploy on a VPS that already runs another MT5 (e.g. a MetaQuotes algo)
The `MetaTrader5` Python package connects to **one terminal per process**, chosen by the
`path` you pass. So this Pepperstone runner and your existing MetaQuotes algo coexist —
each is its own process pointing at its own terminal. Steps (Windows VPS, e.g. Contabo):

1. **Install a second MT5 terminal for Pepperstone** (its own folder — the MetaQuotes and
   Pepperstone terminals are separate installs). Log into the Pepperstone **demo**, enable
   *Tools → Options → Expert Advisors → Allow algorithmic trading*, and enable the symbols
   (NAS100/XAUUSD/BTCUSD/ETHUSD) in Market Watch. Leave it running. Tick "save account
   information" so it reconnects on its own.
2. **Copy this repo** to the VPS (git clone or copy the `edgelab/` package + `config.yaml`).
   The live runner does **not** need the parquet data caches (it pulls bars from the
   terminal); only `verify.py` needs them, and you already ran that on your PC.
3. **Install Python deps:** `pip install MetaTrader5 pandas numpy pyarrow pyyaml`.
4. **Point the runner at the Pepperstone terminal** in `config_live.yaml`:
   ```yaml
   mt5_path: "C:/Program Files/Pepperstone MetaTrader 5/terminal64.exe"
   expect_server: Pepperstone        # refuses to trade if it lands on the MetaQuotes terminal
   # mt5_login / mt5_server / mt5_password  -> optional, for deterministic unattended reconnect
   ```
   `expect_server` is the key safety net: if the runner ever attaches to the wrong terminal,
   it **refuses to trade** instead of firing orders into your MetaQuotes account.
5. **Confirm the wiring:** `python -m edgelab.live.runner --status` — the log must show
   `server=PepperstoneUK-Demo type=DEMO` and your Pepperstone balance (not MetaQuotes).
6. **Run under the supervisor** (`run_forever.ps1`) or auto-start at logon (`install_task.ps1`).

Your MetaQuotes algo is unaffected — keep it pointed at its own terminal. If it's also a
Python `MetaTrader5` script, make sure IT also passes its own `path` so the two never cross.

## Known live-vs-backtest gaps (read these)
1. **Brick 3 data source.** The backtest used **Yahoo daily spot**; live uses
   Pepperstone's **crypto CFD** daily bars, whose daily *close time* (broker-defined)
   and spread differ → MACD/RSI values differ slightly. **Re-validate brick 3 on
   Pepperstone crypto bars** before trusting it, and confirm your prop firm even allows
   crypto. If not, drop brick 3 (or run it elsewhere — but then it loses the shared-account
   DD netting).
2. **Brick 2 calendar.** The entry day (last trading day of the month) uses a
   business-day calendar; exchange **holidays** can shift it ±1 day a few times a year.
3. **Fill price.** Paper/live enter at ~market on breakout confirmation; the backtest
   fills at the next bar's open. Difference is a few points, logged.
4. **Sizing inputs.** Lots use the broker's `symbol_info` tick value; verify the first
   few live tickets risk ~1R as intended.

## Files
`signals.py` (pure decisions) · `broker.py` (MT5 + paper book) · `risk.py` (sizing +
prop gate) · `strategies.py` (per-brick drivers) · `runner.py` (event loop) ·
`verify.py` (live==backtest proof) · `config_live.yaml` (all settings).
