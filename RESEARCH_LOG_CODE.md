# Code harvest: TradingView + Freqtrade + MQL5 (2026-07-31)

The hypothesis was reasonable: **a paper describes, code executes**. Every strategy file has
a 100 %-mechanical entry, exit and usually an explicit stop, so it passes the "clear rules"
filter by construction — which ~19 800 screened papers and blog posts did not. Tested.

## Access reality (probed, not assumed)

| Source | Source code reachable? |
|---|---|
| **mql5.com CodeBase** | ❌ the page does not contain the source; download returns 404 without a logged-in account. No account was created. |
| **tradingview.com** | ❌ `pine-facade` serves only TradingView's **145 built-in indicators** (`STD;` ids). Community Pine needs the site's internal API. |
| **GitHub** | ✅ serves all three languages as raw files, no auth. |

So all three languages were harvested **through GitHub**, 1 API call per repo (recursive
tree) then raw files — which stays inside the unauthenticated rate limit.

## Harvest

**836 strategy files** from 25 curated repos: freqtrade 648, MQL 137, Pine 51.
A file counts as a *strategy* only if it carries `populate_entry_trend` / `strategy.entry`
/ `OrderSend`-`OnTick` — indicators and libraries are dropped.

After the user's filters: **131 files use external data** (VIX, funding rate, open interest,
on-chain, sentiment), **9 use ML** (no fixed rule) → **469 eligible**.

## The finding: 836 files contain 139 ideas, and they are the canon we already exhausted

| Family | files | | Family | files |
|---|---|---|---|---|
| bbands | ~119 | | williams | 49 |
| adx | ~60 | | sma | 41 |
| psar | 82 | | fib | 36 |
| ichimoku | 71 | | pivot | 26 |
| rsi | 52 | | supertrend | 22 |
| macd, ema, stoch, cci, donchian, keltner, vwap, obv, mfi | the rest | | **ibs** | **1** |

469 eligible files collapse to **139 distinct family combinations** (×3.4 duplication), and
those 139 are recombinations of ~20 classical primitives — precisely the canon
[[system]] already reports as exhausted: *MA/MACD/Bollinger/CCI/ADX/SAR/Keltner/Aroon/
Ichimoku, RSI2/z-score/Williams %R/Stochastic, VWAP, candlesticks*.

**The single most informative number: 1 file out of 836 mentions IBS** — the one signal that
ever produced a brick here. The corpus is dense in exactly the indicators that do not work
and empty of the one that does.

## The families NOT yet in the ledger, tested

PSAR, Ichimoku, classic pivots, Heikin-Ashi, Supertrend, Williams %R — 19 assets each
(US + EU indices, FX, gold, crypto), live cadence, mandatory 2.5·ATR stop, net of cost:

| Family | assets + | median t | max t | best | t>2 |
|---|---|---|---|---|---|
| PSAR(0.02, 0.2) | 15/19 | 0.49 | 2.63 | XAUUSD | 2 |
| Ichimoku (price > cloud) | 13/19 | 0.41 | 2.37 | XAUUSD | 1 |
| Classic pivot (close > P) | 12/19 | 0.24 | 2.26 | BTCUSD | 1 |
| Heikin-Ashi | 15/19 | 0.73 | 2.21 | BTCUSD | 3 |
| Supertrend(10, 3) | 11/19 | 0.43 | 2.07 | XAUUSD | 1 |
| Williams %R(14) | 12/19 | 1.01 | 2.01 | GER40 | 1 |

**114 tests, 9 at t>2 against 2.6 expected by chance, max t = 2.63.** The
multiple-testing-adjusted bar for 114 tests is ~3.3. Nothing passes. Per-asset median t
runs 0.24–1.01: as families, these are noise.

## Limits worth stating

* **77 % of the harvest is crypto-only.** Freqtrade is 648 of 836 files and trades nothing
  else — it covers 1 of the user's 4 asset classes.
* **Timeframe mismatch:** of the 353 freqtrade strategies that declare one, **293 are on
  5 m / 1 m / 15 m**. We hold H1/D1 for crypto. Pulling M5 crypto is feasible, but the
  families would be the same ones failing above, at a granularity where cost bites harder.
* MFI/OBV are **data-blocked**: MT5 CFD "volume" is tick count, not traded volume
  ([[ledger]], order-flow row).

## Verdict

"Code beats papers" is **half true and it was worth testing**: rule completeness goes from
~0.4 % (76 eligible out of 19 800 papers) to 100 % by construction. But completeness was
never the binding constraint — **the idea space is**. The code corpus is a re-combination
of the same twenty indicators, and screening it harder produces false positives, not edges.

Files: `scratchpad/code_harvest.py`, `code_parse.py`, `code_index.json`,
`code_specs.csv`, `code_eligible.csv`, `scratchpad/code/` (836 sources).
