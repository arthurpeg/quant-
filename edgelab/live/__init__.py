"""edgelab.live — live/forward-test runner for the frozen 3-brick book on MT5 (Pepperstone).

Layers:
  signals.py     pure decision functions (reuse the exact backtest math; testable offline)
  broker.py      MT5/Pepperstone connection + order routing (dry-run by default)
  risk.py        position sizing (1R = risk% of initial) + account-level prop gate
  strategies.py  stateful live drivers for each brick (signals -> orders via broker)
  runner.py      the single event loop that schedules the three bricks
  verify.py      proves live signals == backtest on cached bars

Safety: the runner is DRY-RUN by default (logs the orders it WOULD place, sends nothing).
Live order sending must be turned on explicitly in config_live.yaml (live_trading: true).
"""
