"""arXiv research CLI: scrape q-fin papers, score, and extract edge candidates.

Usage (from repo root):
    python -m edgelab.run_research                 # all keyword sets in config
    python -m edgelab.run_research --top 15        # only build fiches for top 15
    python -m edgelab.run_research --max-results 20

Network step (public arXiv API, no key, rate-limited). Offline-safe: request
failures are logged and produce an empty result rather than crashing.
"""
from __future__ import annotations

import argparse
import logging

from edgelab.config import load_config
from edgelab.reports import save_json
from edgelab.research.arxiv_search import save_results, search_many
from edgelab.research.edge_extraction import extract_candidate


def main() -> None:
    ap = argparse.ArgumentParser(description="edgelab arXiv research")
    ap.add_argument("--config", default=None)
    ap.add_argument("--max-results", type=int, default=None)
    ap.add_argument("--top", type=int, default=10, help="build fiches for top-N scored papers")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s", datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)
    r = cfg.research
    out_dir = cfg.resolve_path(r["out_dir"])

    max_results = args.max_results or int(r["max_results_per_query"])
    print(f"Querying arXiv {r['categories']} across {len(r['keyword_sets'])} keyword sets "
          f"(<= {max_results}/query, {r['rate_limit_seconds']}s rate limit)...")

    df = search_many(
        keyword_sets=[list(k) for k in r["keyword_sets"]],
        categories=list(r["categories"]),
        max_results=max_results,
        score_terms=dict(r["score_terms"]),
        rate_limit_seconds=float(r["rate_limit_seconds"]),
    )

    if df.empty:
        print("No papers returned (network blocked?). Nothing saved.")
        return

    paths = save_results(df, out_dir)
    print(f"\n{len(df)} unique papers. Saved: {paths['json']}")
    print("\nTop scored papers:")
    for _, row in df.head(args.top).iterrows():
        print(f"  [{row['score']:>4.0f}] {row['title'][:80]}  ({row['arxiv_id']})")

    candidates = [extract_candidate(row.to_dict()) for _, row in df.head(args.top).iterrows()]
    cand_path = save_json(candidates, out_dir / "edge_candidates.json")
    print(f"\n{len(candidates)} candidate fiches -> {cand_path}")
    print("  (each fiche separates article claims from OUR reformulation-to-test)")


if __name__ == "__main__":
    main()
