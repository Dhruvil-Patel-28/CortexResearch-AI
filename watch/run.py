"""
CLI entrypoint for Topic Watch tasks.

Usage:
    python -m watch.run --ingest        # fetch new items from all sources
    python -m watch.run --ingest --score  # fetch + LLM-score new items
    python -m watch.run --status        # show store stats
"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-22s | %(levelname)-7s | %(message)s",
    )

    parser = argparse.ArgumentParser(description="CortexResearch watch runner")
    parser.add_argument("--ingest", action="store_true", help="fetch new items from all enabled sources")
    parser.add_argument("--score", action="store_true", help="LLM-score unscored items against the profile")
    parser.add_argument("--status", action="store_true", help="show store stats and last ingest time")
    args = parser.parse_args()

    if args.status:
        from store import db

        db.init_db()
        print(json.dumps(db.stats(), indent=2))
        return 0

    result: dict = {}

    if args.ingest or not any([args.score, args.status]):
        from watch.ingest import run_ingest

        result["ingest"] = run_ingest()

    if args.score:
        from watch.ranker import score_unscored

        result["score"] = score_unscored()

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
