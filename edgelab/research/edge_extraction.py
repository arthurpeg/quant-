"""Turn a scored arXiv paper into a structured *edge candidate* fiche.

CRITICAL HONESTY RULE: we never invent results. The fiche keeps two clearly
separated buckets:
  * ``from_article``    — verbatim snippets quoted from the abstract (claims the
    authors make; NOT verified by us).
  * ``our_reformulation`` — how *we* would turn the idea into a testable edge in
    THIS framework. These are hypotheses to backtest, explicitly ours, not the
    paper's findings.

Extraction is deliberately conservative and rule-based (keyword/sentence matching);
it flags what to read, it does not claim to understand the paper.
"""
from __future__ import annotations

import re

# Map indicative abstract vocabulary to an edge family we can implement.
_FAMILY_HINTS = {
    "momentum": ["momentum", "trend", "time series momentum", "drift", "continuation"],
    "mean_reversion": ["mean reversion", "reversal", "contrarian", "overreaction"],
    "volatility_breakout": ["breakout", "volatility", "range", "realized volatility"],
    "carry": ["carry", "risk premium", "term structure"],
    "statistical_arbitrage": ["pairs trading", "statistical arbitrage", "cointegration"],
    "cross_sectional": ["cross-section", "cross section", "factor", "ranking"],
}

_FREQ_HINTS = {
    "daily": ["daily", "day"],
    "weekly": ["weekly", "week"],
    "monthly": ["monthly", "month"],
    "intraday": ["intraday", "minute", "high-frequency", "high frequency"],
}

# Sentences worth quoting verbatim as author claims.
_CLAIM_TRIGGERS = ["sharpe", "return", "abnormal", "significant", "predict",
                   "profitable", "out-of-sample", "out of sample", "outperform"]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _guess_family(text: str) -> str:
    low = text.lower()
    best, best_hits = "unknown", 0
    for fam, hints in _FAMILY_HINTS.items():
        hits = sum(low.count(h) for h in hints)
        if hits > best_hits:
            best, best_hits = fam, hits
    return best


def _guess_frequency(text: str) -> str:
    low = text.lower()
    for freq, hints in _FREQ_HINTS.items():
        if any(h in low for h in hints):
            return freq
    return "unknown"


def _guess_period(text: str) -> str:
    years = re.findall(r"(19|20)\d{2}", text)
    if len(years) >= 2:
        return f"{years[0]}–{years[-1]} (as mentioned in abstract; verify in paper)"
    if years:
        return f"around {years[0]} (verify in paper)"
    return "not stated in abstract"


def extract_candidate(paper: dict) -> dict:
    """Build a structured candidate fiche from a paper dict (see module docstring)."""
    abstract = paper.get("abstract", "")
    title = paper.get("title", "")
    family = _guess_family(f"{title} {abstract}")
    freq = _guess_frequency(abstract)

    claims = [s for s in _sentences(abstract)
              if any(t in s.lower() for t in _CLAIM_TRIGGERS)][:4]

    reformulation = _REFORMULATION_TEMPLATES.get(family, _REFORMULATION_TEMPLATES["unknown"])

    return {
        "arxiv_id": paper.get("arxiv_id"),
        "title": title,
        "authors": paper.get("authors", []),
        "published": paper.get("published"),
        "pdf_url": paper.get("pdf_url"),
        "score": paper.get("score"),
        "inferred_family": family,
        "inferred_frequency": freq,
        # --- strictly the paper's own words (unverified) ---
        "from_article": {
            "claim_snippets": claims,
            "tested_period": _guess_period(abstract),
            "note": "Verbatim/near-verbatim from the abstract. NOT verified by us.",
        },
        # --- strictly our hypothesis to test ---
        "our_reformulation": {
            "hypothesis": reformulation["hypothesis"],
            "candidate_universe": "prop-firm whitelist (FX/indices/metals/energy)",
            "candidate_frequency": freq if freq != "unknown" else "daily (default)",
            "candidate_entry_rule": reformulation["entry_rule"],
            "maps_to_edge": reformulation["maps_to_edge"],
            "note": "OUR reformulation to backtest in edgelab — not the paper's result.",
        },
    }


_REFORMULATION_TEMPLATES = {
    "momentum": {
        "hypothesis": "Past N-period return sign predicts next-period return sign.",
        "entry_rule": "Long if trailing lookback return > 0, short if < 0 (optionally vol-gated).",
        "maps_to_edge": "ts_momentum",
    },
    "mean_reversion": {
        "hypothesis": "Short-horizon deviations from a rolling mean revert.",
        "entry_rule": "Fade z-score extremes: long when z <= -k, short when z >= +k.",
        "maps_to_edge": "zscore_mean_reversion",
    },
    "volatility_breakout": {
        "hypothesis": "A close beyond a prior channel by k*ATR marks a continuation.",
        "entry_rule": "Long on upside channel breakout, short on downside, buffered by ATR.",
        "maps_to_edge": "vol_breakout",
    },
    "cross_sectional": {
        "hypothesis": "Ranking assets on a signal and going long-top/short-bottom pays.",
        "entry_rule": "Cross-sectional rank; long top quantile, short bottom (needs breadth).",
        "maps_to_edge": "(not yet implemented — cross-sectional edge is future work)",
    },
    "statistical_arbitrage": {
        "hypothesis": "A cointegrated spread mean-reverts around its equilibrium.",
        "entry_rule": "Trade the spread's z-score back to zero.",
        "maps_to_edge": "(not yet implemented — pairs edge is future work)",
    },
    "carry": {
        "hypothesis": "High-carry instruments outperform low-carry ones on average.",
        "entry_rule": "Long high-carry, short low-carry (needs carry data we lack for FX).",
        "maps_to_edge": "(blocked — no historical swap/carry data, see wiki data-sources)",
    },
    "unknown": {
        "hypothesis": "Unclear from abstract; read the paper before formulating.",
        "entry_rule": "TBD after reading full text.",
        "maps_to_edge": "(unmapped)",
    },
}
