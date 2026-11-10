"""Incremental official-RSS collection, without importing legacy Wiki datasets."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import requests

from .common import (KEYWORDS, NEWS_DATA, USER_AGENT, csv_read, csv_write,
                     id_for, json_report, now, prepare, require_news_url, sources)

ARTICLE_FIELDS = [
    "article_id", "outlet_id", "outlet_name", "original_url", "canonical_url",
    "title", "summary", "published_at", "author", "feed_url", "discovered_at",
    "discovery_status", "article_status", "syndication_group", "article_hash",
]


def clean(text: str) -> str:
    text = re.sub(r"<[^>]*>", " ", unescape(str(text or "")))
    return " ".join(text.split())


def keywords() -> list[str]:
    return [line.strip().casefold() for line in KEYWORDS.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def discover(args) -> dict:
    try:
        import feedparser
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install -r requirements-news-v2.txt") from exc
    prepare()
    config = [x for x in sources() if x.get("source_kind") == "rss"
              and (not args.source or x["outlet_id"] in args.source)]
    if not config:
        raise RuntimeError("No active RSS feeds matched the requested source IDs")
    path = NEWS_DATA / "articles.csv"
    existing = {r["article_id"]: r for r in csv_read(path)}
    reports = []
    needles = keywords()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT,
                            "Accept": "application/xml, application/rss+xml, application/atom+xml, text/xml"})
    for i, src in enumerate(config):
        entry = {"outlet_id": src["outlet_id"], "feed_url": src["rss_or_archive_url"],
                 "ok": False, "seen": 0, "matched": 0, "new": 0, "error": ""}
        try:
            # Explicitly disallow redirects to a different publisher.
            response = session.get(src["rss_or_archive_url"], timeout=(10, 35),
                                   allow_redirects=False)
            if response.is_redirect:
                redirected = response.headers.get("Location", "")
                raise ValueError(f"RSS redirect not followed automatically: {redirected}")
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if feed.bozo and not feed.entries:
                raise ValueError(f"Invalid RSS/Atom feed: {feed.bozo_exception}")
            entry["ok"] = True
            for item in feed.entries[:args.limit]:
                entry["seen"] += 1
                title = clean(item.get("title", ""))
                summary = clean(item.get("summary", ""))[:1000]
                tags = " ".join(clean(tag.get("term", "")) for tag in item.get("tags", []))
                # Do not use source section label alone; that would admit every item.
                if not any(key in (title + " " + summary + " " + tags).casefold() for key in needles):
                    continue
                try:
                    canonical = require_news_url(item.get("link", ""), src["base_url"])
                except ValueError:
                    continue
                entry["matched"] += 1
                article_id = id_for("NEWS", src["outlet_id"], canonical)
                if article_id in existing:
                    continue
                published = item.get("published", "")
                if item.get("published_parsed"):
                    published = datetime.fromtimestamp(
                        calendar.timegm(item.published_parsed), tz=timezone.utc
                    ).isoformat()
                existing[article_id] = {
                    "article_id": article_id, "outlet_id": src["outlet_id"],
                    "outlet_name": src["outlet_name"],
                    "original_url": item.get("link", ""), "canonical_url": canonical,
                    "title": title, "summary": summary,
                    "published_at": str(published), "author": clean(item.get("author", "")),
                    "feed_url": src["rss_or_archive_url"], "discovered_at": now(),
                    "discovery_status": "rss_metadata_candidate", "article_status": "pending_fetch",
                    "syndication_group": "", "article_hash": "",
                }
                entry["new"] += 1
        except (requests.RequestException, ValueError) as exc:
            entry["error"] = str(exc)
        reports.append(entry)
        if i < len(config) - 1:
            time.sleep(max(args.delay, 0))
    csv_write(path, sorted(existing.values(), key=lambda r: r["article_id"]), ARTICLE_FIELDS)
    result = {"stage": "news_rss_discovery_v2", "ran_at": now(),
              "total_discovered_articles": len(existing),
              "new_discovered_articles": sum(x["new"] for x in reports),
              "successful_feeds": sum(bool(x["ok"]) for x in reports),
              "feed_reports": reports, "wiki_inputs_used": 0,
              "warning": "RSS metadata is not exact-edge evidence; no edges are verified here."}
    json_report("collect.json", result)
    return result
