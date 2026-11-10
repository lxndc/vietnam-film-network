"""Newspaper-only Vietnam Film Network pipeline.

Usage: python -m news_pipeline.cli <command>
"""
from __future__ import annotations

import argparse
import json
import sys

from .common import prepare
from .collect import discover
from .fetch import fetch
from .extract import extract
from .quality import (audit, create_gold, evaluate, export_verified,
                      prepare_reviews, status)
from .neo4j_load import load
from .diagnostics import diagnose
from .backfill import backfill
from .progress import progress


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="Incrementally collect article metadata from RSS")
    collect.add_argument("--source", action="append", help="Outlet ID, repeatable")
    collect.add_argument("--limit", type=int, default=200)
    collect.add_argument("--delay", type=float, default=2)

    b = sub.add_parser("backfill", help="Discover historical article candidates from permitted publisher archives/sitemaps")
    b.add_argument("--source", action="append", help="Publisher ID, repeatable (BVH, BCP, TN, VTV, VNE, TT)")
    b.add_argument("--mode", choices=["archive", "sitemap", "both"], default="archive")
    b.add_argument("--limit", type=int, default=500)
    b.add_argument("--max-pages", type=int, default=10)
    b.add_argument("--max-sitemaps", type=int, default=15)
    b.add_argument("--sitemap", action="append", help="Explicit publisher-owned sitemap URL; repeatable")
    b.add_argument("--delay", type=float, default=3)
    b.add_argument("--max-sitemap-attempts", type=int, default=60,
                   help="Maximum sitemap/archive HTTP attempts per publisher, including failures")

    f = sub.add_parser("fetch", help="Fetch allowed publisher article text to private local cache")
    f.add_argument("--limit", type=int, default=200)
    f.add_argument("--delay", type=float, default=2)
    f.add_argument("--retry-failed", action="store_true",
                   help="Retry failed/blocked articles explicitly; robots policy is rechecked")

    e = sub.add_parser("extract", help="Extract explicit relation assertions from article text")
    e.add_argument("--limit", type=int, default=100000)

    d = sub.add_parser("diagnose", help="Inspect fetch/extract coverage without changing data")
    d.add_argument("--examples", type=int, default=8)

    sub.add_parser("audit", help="Audit 100% of discovered articles and relation assertions")
    sub.add_parser("prepare-reviews", help="Create/reconcile human review queue without overwriting reviews")
    g = sub.add_parser("sample", help="Make a stratified unlabelled independent Gold Standard sample")
    g.add_argument("--size", type=int, default=329)
    g.add_argument("--seed", type=int, default=20261109)
    g.add_argument("--force", action="store_true", help="Danger: overwrite sample including prior labels")
    evaluate_parser = sub.add_parser("evaluate", help="Evaluate genuine independently adjudicated Gold Standard")
    evaluate_parser.add_argument("--min-sample", type=int, default=200)
    sub.add_parser("export", help="Export human-verified edges only")
    sub.add_parser("status", help="Compute production acceptance status")
    sub.add_parser("progress", help="Report source yield, bottlenecks and target gaps")
    neo = sub.add_parser("neo4j", help="Import verified NewsV2-only graph")
    neo.add_argument("--mode", choices=["staging", "production"], default="staging")

    args = p.parse_args(argv)
    if args.command in ("collect", "fetch", "backfill") and (args.limit < 1 or args.delay < 0):
        p.error("--limit must be >=1 and --delay must be >=0")
    if args.command == "backfill" and (args.max_pages < 1 or args.max_sitemaps < 1):
        p.error("--max-pages and --max-sitemaps must be >= 1")
    if args.command == "extract" and args.limit < 1:
        p.error("--limit must be >=1")
    if args.command == "sample" and args.size < 1:
        p.error("--size must be >=1")
    if args.command == "evaluate" and args.min_sample < 1:
        p.error("--min-sample must be >=1")
    try:
        prepare()
        actions = {"diagnose": diagnose, "collect": discover, "fetch": fetch, "extract": extract,
                   "audit": audit, "prepare-reviews": prepare_reviews, "backfill": backfill, "progress": progress,
                   "sample": create_gold, "evaluate": evaluate,
                   "export": export_verified, "status": status, "neo4j": load}
        result = actions[args.command](args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (RuntimeError, ValueError, FileNotFoundError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
