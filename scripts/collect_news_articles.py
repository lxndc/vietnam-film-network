#!/usr/bin/env python3
"""Collect newspaper article metadata from configured official RSS feeds.

This script discovers article candidates only. It does not fetch full article
bodies, extract entities/relations, or mark any edge as verified.
"""
from __future__ import annotations

import argparse
import csv
import calendar
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DEFAULT_SOURCE_FILE = CONFIG / "news_sources.csv"
DEFAULT_KEYWORDS_FILE = CONFIG / "film_keywords.txt"
DEFAULT_OUTPUT = ROOT / "data" / "staging" / "articles" / "articles.csv"
DEFAULT_REPORT = ROOT / "reports" / "news_collection_report.json"
USER_AGENT = (
    "VietnamFilmNetworkResearch/1.0 "
    "(academic research; contact: project maintainers)"
)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
OUTPUT_FIELDS = [
    "article_id", "outlet_id", "outlet_name", "canonical_url", "original_url",
    "title", "rss_summary", "author", "published_at", "updated_at",
    "section", "language", "feed_url", "discovered_at", "article_status",
    "syndication_group", "content_hash", "review_notes",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in TRACKING_KEYS:
            continue
        query.append((key, value))
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        urlencode(query, doseq=True),
        "",  # discard fragment
    ))


def stable_id(outlet_id: str, canonical_url: str) -> str:
    digest = hashlib.sha256(
        f"{outlet_id}|{canonical_url}".encode("utf-8")
    ).hexdigest()[:20]
    return f"NEWS_{digest}"


def parse_time(entry: dict, key: str) -> str:
    raw = entry.get(key)
    if not raw:
        return ""
    parsed = entry.get(f"{key}_parsed")
    if parsed:
        try:
            return datetime.fromtimestamp(
                calendar.timegm(parsed), tz=timezone.utc
            ).isoformat()
        except (OverflowError, OSError, TypeError, ValueError):
            pass
    return clean_text(raw)


def load_keywords(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Keyword file not found: {path}")
    return [
        line.strip().casefold()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def is_film_candidate(text: str, keywords: list[str]) -> bool:
    normalized = clean_text(text).casefold()
    return any(keyword in normalized for keyword in keywords)


def load_sources(path: Path, selected_ids: set[str] | None) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = []
    for row in rows:
        active = (row.get("active") or "").strip().lower()
        if active not in {"1", "true", "yes", "y"}:
            continue
        if (row.get("source_kind") or "").strip().lower() != "rss":
            continue
        if selected_ids and row.get("outlet_id") not in selected_ids:
            continue
        if not (row.get("rss_or_archive_url") or "").strip():
            continue
        selected.append(row)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCE_FILE)
    parser.add_argument("--keywords", type=Path, default=DEFAULT_KEYWORDS_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source", action="append", dest="source_ids",
                        help="Outlet ID to collect; can be repeated (TT, TN, VNE, VTV).")
    parser.add_argument("--max-per-feed", type=int, default=200)
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delay between feed requests, in seconds.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.max_per_feed < 1:
        parser.error("--max-per-feed must be >= 1")
    if args.delay < 0:
        parser.error("--delay must be >= 0")

    selected_ids = set(args.source_ids) if args.source_ids else None
    sources = load_sources(args.sources, selected_ids)
    keywords = load_keywords(args.keywords)
    if not sources:
        logging.error("No active RSS sources found in %s", args.sources)
        return 2

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })

    records: dict[str, dict] = {}
    feed_reports = []
    for index, source in enumerate(sources):
        feed_url = source["rss_or_archive_url"].strip()
        report = {
            "outlet_id": source.get("outlet_id", ""),
            "feed_url": feed_url,
            "status": "pending",
            "http_status": None,
            "entries_seen": 0,
            "film_candidates": 0,
            "error": "",
        }
        try:
            response = session.get(feed_url, timeout=(15, 45))
            report["http_status"] = response.status_code
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise RuntimeError(f"RSS/Atom parse error: {parsed.bozo_exception}")
            report["entries_seen"] = len(parsed.entries)

            for entry in parsed.entries[:args.max_per_feed]:
                original_url = clean_text(entry.get("link", ""))
                canonical_url = canonicalize_url(original_url)
                title = clean_text(entry.get("title", ""))
                summary = clean_text(entry.get("summary", ""))[:700]
                categories = [
                    clean_text(tag.get("term", ""))
                    for tag in entry.get("tags", [])
                    if tag.get("term")
                ]
                section = "; ".join(categories) or clean_text(source.get("section_scope", ""))
                search_text = " ".join([title, summary, section, *categories])
                if not canonical_url or not is_film_candidate(search_text, keywords):
                    continue

                article_id = stable_id(source.get("outlet_id", ""), canonical_url)
                row = {
                    "article_id": article_id,
                    "outlet_id": source.get("outlet_id", ""),
                    "outlet_name": source.get("outlet_name", ""),
                    "canonical_url": canonical_url,
                    "original_url": original_url,
                    "title": title,
                    "rss_summary": summary,
                    "author": clean_text(entry.get("author", "")),
                    "published_at": parse_time(entry, "published"),
                    "updated_at": parse_time(entry, "updated"),
                    "section": section,
                    "language": "vi",
                    "feed_url": feed_url,
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "article_status": "candidate_pending_article_review",
                    "syndication_group": "",
                    "content_hash": "",
                    "review_notes": "RSS metadata only; original article and exact-edge evidence not yet reviewed.",
                }
                records[article_id] = row
            report["film_candidates"] = sum(
                1 for row in records.values()
                if row["outlet_id"] == source.get("outlet_id")
            )
            report["status"] = "ok"
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            report["status"] = "error"
            report["error"] = str(exc)
            logging.warning("%s: %s", source.get("outlet_id"), exc)
        feed_reports.append(report)
        if index < len(sources) - 1:
            time.sleep(args.delay)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(
            records.values(),
            key=lambda row: (row["published_at"], row["outlet_id"]),
            reverse=True,
        ))

    args.report.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "stage": "newspaper_rss_discovery_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(sources),
        "successful_feeds": sum(item["status"] == "ok" for item in feed_reports),
        "failed_feeds": sum(item["status"] == "error" for item in feed_reports),
        "unique_article_candidates": len(records),
        "output_csv": str(args.output),
        "important": [
            "RSS output contains article candidates, not verified relation evidence.",
            "Original article pages must be checked before extracting or verifying edges.",
            "This collector does not fetch full article bodies or bypass publisher restrictions.",
            "Archive sources in config/news_sources.csv require separate permitted discovery.",
        ],
        "feeds": feed_reports,
    }
    args.report.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "successful_feeds": summary["successful_feeds"],
        "failed_feeds": summary["failed_feeds"],
        "unique_article_candidates": len(records),
        "output_csv": str(args.output),
        "report": str(args.report),
    }, ensure_ascii=False, indent=2))
    return 0 if summary["successful_feeds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
