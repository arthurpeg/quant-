"""Query the public arXiv API (no key required) for q-fin papers.

Uses only the stdlib (urllib + xml.etree) so there's no hard dependency on the
optional ``arxiv`` package. Respects arXiv's rate limit (>= 3s between requests).
Results are deduplicated by arXiv id and can be persisted to JSON + parquet.

API docs: https://info.arxiv.org/help/api/user-manual.html
"""
from __future__ import annotations

import logging
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

logger = logging.getLogger("edgelab.research.arxiv")

ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_last_request_ts = 0.0


def _ssl_context() -> ssl.SSLContext:
    """SSL context that works even when the OS cert store is unavailable.

    Prefers ``certifi``'s CA bundle (installed transitively via yfinance/requests),
    which sidesteps the common Windows ``CERTIFICATE_VERIFY_FAILED`` on stdlib
    ``urllib``. Falls back to the default context otherwise.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover - certifi missing
        return ssl.create_default_context()


def _rate_limit(min_interval: float) -> None:
    global _last_request_ts
    elapsed = time.time() - _last_request_ts
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _last_request_ts = time.time()


def _build_query(keywords: list[str], categories: list[str]) -> str:
    cat_clause = " OR ".join(f"cat:{c}" for c in categories)
    kw_clause = " AND ".join(f'all:"{k}"' for k in keywords)
    return f"({cat_clause}) AND ({kw_clause})"


def _parse_entry(entry: ET.Element) -> dict:
    def text(tag: str) -> str:
        el = entry.find(_ATOM + tag)
        return (el.text or "").strip() if el is not None else ""

    arxiv_id = text("id").rsplit("/", 1)[-1]
    base_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

    authors = [a.findtext(_ATOM + "name", default="").strip()
               for a in entry.findall(_ATOM + "author")]
    categories = [c.get("term") for c in entry.findall(_ATOM + "category")]

    pdf_url = ""
    for link in entry.findall(_ATOM + "link"):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break

    return {
        "arxiv_id": base_id,
        "title": " ".join(text("title").split()),
        "abstract": " ".join(text("summary").split()),
        "authors": authors,
        "published": text("published"),
        "updated": text("updated"),
        "pdf_url": pdf_url,
        "categories": categories,
    }


def search_arxiv(keywords: list[str], max_results: int = 40,
                 categories: list[str] | None = None,
                 rate_limit_seconds: float = 3.0) -> list[dict]:
    """Search arXiv for ``keywords`` within ``categories`` (default q-fin.*).

    Returns a list of paper dicts (title, abstract, authors, published, pdf_url,
    categories). Network errors are logged and yield an empty list rather than
    crashing the pipeline.
    """
    categories = categories or ["q-fin.TR", "q-fin.ST", "q-fin.PM", "q-fin.CP"]
    params = {
        "search_query": _build_query(keywords, categories),
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    _rate_limit(rate_limit_seconds)
    logger.info("arXiv query: %s", keywords)
    try:
        with urllib.request.urlopen(url, timeout=30, context=_ssl_context()) as resp:
            raw = resp.read()
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("arXiv request failed for %s: %s", keywords, exc)
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:  # pragma: no cover
        logger.warning("arXiv XML parse error: %s", exc)
        return []

    papers = [_parse_entry(e) for e in root.findall(_ATOM + "entry")]
    for p in papers:
        p["query"] = " ".join(keywords)
    return papers


def fetch_corpus(categories: list[str], target: int = 1000, page: int = 100,
                 rate_limit_seconds: float = 3.0, sort_by: str = "submittedDate") -> pd.DataFrame:
    """Paginate the arXiv API to pull up to ``target`` papers across ``categories``.

    Deduplicates by arXiv id. Used to build a large corpus for systematic triage.
    """
    cat_clause = " OR ".join(f"cat:{c}" for c in categories)
    seen: dict[str, dict] = {}
    start = 0
    while len(seen) < target:
        params = {
            "search_query": f"({cat_clause})",
            "start": start,
            "max_results": page,
            "sortBy": sort_by,
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
        _rate_limit(rate_limit_seconds)
        try:
            with urllib.request.urlopen(url, timeout=60, context=_ssl_context()) as resp:
                root = ET.fromstring(resp.read())
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("corpus page start=%d failed: %s", start, exc)
            break
        entries = root.findall(_ATOM + "entry")
        if not entries:
            break
        for e in entries:
            p = _parse_entry(e)
            seen.setdefault(p["arxiv_id"], p)
        logger.info("corpus: %d unique after start=%d", len(seen), start)
        start += page
    return pd.DataFrame(list(seen.values()))


def score_abstract(abstract: str, score_terms: dict[str, float]) -> float:
    """Heuristic priority score: sum term weights (x occurrences, capped)."""
    if not abstract:
        return 0.0
    low = abstract.lower()
    score = 0.0
    for term, weight in score_terms.items():
        count = low.count(term.lower())
        if count:
            score += weight * min(count, 3)
    return float(score)


def search_many(keyword_sets: list[list[str]], categories: list[str],
                max_results: int, score_terms: dict[str, float],
                rate_limit_seconds: float = 3.0) -> pd.DataFrame:
    """Run every keyword set, dedupe by arXiv id, score, and return a DataFrame."""
    seen: dict[str, dict] = {}
    for kws in keyword_sets:
        for paper in search_arxiv(kws, max_results, categories, rate_limit_seconds):
            aid = paper["arxiv_id"]
            paper["score"] = score_abstract(paper["abstract"], score_terms)
            if aid not in seen or paper["score"] > seen[aid]["score"]:
                # keep the highest-scoring record; remember which queries hit it
                prior_queries = seen.get(aid, {}).get("matched_queries", [])
                paper["matched_queries"] = sorted(set(prior_queries + [paper["query"]]))
                seen[aid] = paper
            else:
                seen[aid]["matched_queries"] = sorted(
                    set(seen[aid].get("matched_queries", []) + [paper["query"]]))

    df = pd.DataFrame(list(seen.values()))
    if df.empty:
        return df
    return df.sort_values("score", ascending=False).reset_index(drop=True)


def save_results(df: pd.DataFrame, out_dir: str | Path) -> dict[str, Path]:
    """Persist to both JSON (human-readable) and parquet (typed)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "arxiv_papers.json"
    parquet_path = out / "arxiv_papers.parquet"
    df.to_json(json_path, orient="records", indent=2)
    try:
        df.to_parquet(parquet_path)
    except Exception as exc:  # pragma: no cover - parquet engine optional
        logger.warning("parquet save skipped: %s", exc)
        parquet_path = None  # type: ignore
    return {"json": json_path, "parquet": parquet_path}
