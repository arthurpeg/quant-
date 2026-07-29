"""Triage an arXiv abstract: which signal family, and is it backtestable on the
OHLCV prop-asset data we actually have (FX / indices / metals / energy bars)?

This is a keyword heuristic, not comprehension — it routes the corpus to the finite
set of implementable strategy templates, and flags out everything that needs data we
don't have (limit-order-book, options, single-stock fundamentals, text/NLP, crypto).
"""
from __future__ import annotations

# Signal families we can implement on OHLCV bars.
FAMILY_KEYWORDS = {
    "momentum": ["momentum", "trend follow", "time series momentum", "moving average",
                 "trend-following", "continuation", "drift"],
    "reversal": ["mean reversion", "reversal", "contrarian", "overreaction", "mean-reverting"],
    "breakout": ["breakout", "opening range", "range expansion", "channel"],
    "seasonality": ["seasonal", "calendar", "day-of-week", "day of the week", "turn-of-month",
                    "turn of the month", "month-of-year", "holiday", "time-of-day",
                    "intraday pattern", "overnight return", "weekend"],
    "volatility": ["volatility timing", "volatility risk premium", "realized volatility",
                   "variance risk", "vol target", "garch", "volatility forecast", "vix"],
    "pairs_statarb": ["pairs trading", "statistical arbitrage", "cointegration",
                      "cointegrated", "spread trading", "relative value"],
    "lead_lag": ["lead-lag", "lead lag", "cross-asset predictab", "spillover", "granger"],
    "carry": ["carry", "term structure", "roll yield", "futures curve", "contango", "backwardation"],
    "regime": ["regime", "hidden markov", "markov switching", "regime-switching"],
    "cross_sectional": ["cross-section", "cross section", "factor", "ranking", "long-short portfolio"],
}

# If any of these dominate, the signal needs data we DON'T have -> not backtestable here.
EXCLUDE_KEYWORDS = {
    "order_book": ["limit order book", "order book", "order flow", "market microstructure",
                   "bid-ask", "depth", "queue", "high-frequency quotes", "tick-by-tick order"],
    "options": ["option pricing", "implied volatility surface", "greeks", "american option",
                "european option", "call option", "put option", "derivative pricing", "hedging"],
    "fundamentals": ["earnings", "balance sheet", "fundamental", "accounting", "book-to-market",
                     "dividend", "analyst", "10-k", "financial statement"],
    "textnlp": ["sentiment", "news", "text", "nlp", "language model", "llm", "twitter",
                "social media", "tweet"],
    "crypto": ["cryptocurrency", "bitcoin", "crypto", "blockchain", "defi", "token"],
    "theory": ["stochastic control", "hamilton-jacobi", "partial differential equation",
               "utility maximization", "no-arbitrage bound", "viscosity solution",
               "mean field game", "optimal execution", "market making"],
}


def _hits(text: str, kws: list[str]) -> int:
    return sum(text.count(k) for k in kws)


def classify_paper(paper: dict) -> dict:
    """Return {families, exclude_reasons, backtestable, family_score}."""
    text = f"{paper.get('title','')} {paper.get('abstract','')}".lower()

    families = {fam: _hits(text, kws) for fam, kws in FAMILY_KEYWORDS.items()}
    families = {f: n for f, n in families.items() if n > 0}

    excludes = {ex: _hits(text, kws) for ex, kws in EXCLUDE_KEYWORDS.items()}
    excludes = {e: n for e, n in excludes.items() if n > 0}

    # empirical-price signal words push toward backtestable
    empirical = _hits(text, ["return predictab", "trading strategy", "backtest", "sharpe",
                             "excess return", "abnormal return", "price", "futures", "index",
                             "commodity", "forex", "exchange rate", "profitable"])

    family_score = sum(families.values())
    exclude_score = sum(excludes.values())
    # Backtestable if it maps to an implementable family, has empirical flavour, and
    # is not dominated by data we lack.
    backtestable = bool(families) and empirical > 0 and exclude_score <= family_score

    return {
        "families": sorted(families, key=families.get, reverse=True),
        "family_score": family_score,
        "exclude_reasons": sorted(excludes, key=excludes.get, reverse=True),
        "backtestable": backtestable,
    }
