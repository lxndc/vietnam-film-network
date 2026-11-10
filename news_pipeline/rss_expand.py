"""Additional publisher RSS discovery, checkpointing after every feed.

Usage:
  python -m news_pipeline.rss_expand register
  python -u -m news_pipeline.rss_expand collect --limit 300 --delay 2
  python -m news_pipeline.rss_expand report

All article links are validated against their own publisher. RSS metadata is not
article evidence; it is only used to discover URLs.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from .collect import ARTICLE_FIELDS, clean, keywords
from .common import (KEYWORDS, NEWS_DATA, REPORTS, SOURCES, USER_AGENT,
                     csv_read, csv_write, id_for, json_report, now, prepare,
                     require_news_url, sources)

FIELDS = ["outlet_id", "outlet_name", "base_url", "source_kind", "rss_or_archive_url", "section_scope",
          "source_tier", "discovery_method", "attribution_or_terms_note", "active"]

# Each feed path below was listed on a publisher's public RSS directory at
# packaging time. Network availability and permission are checked at runtime.
FEEDS = [
    ("TP", "Báo Tiền Phong", "https://tienphong.vn", "https://tienphong.vn/rss/phim-anh-35.rss", "Giải trí / Phim ảnh"),
    ("TP", "Báo Tiền Phong", "https://tienphong.vn", "https://tienphong.vn/rss/giai-tri-36.rss", "Giải trí"),
    ("TP", "Báo Tiền Phong", "https://tienphong.vn", "https://tienphong.vn/rss/giai-tri-hau-truong-168.rss", "Hậu trường sao"),
    ("TT", "Tuổi Trẻ Online", "https://tuoitre.vn", "https://tuoitre.vn/van-hoa.rss", "Văn hóa"),
    ("VTV", "Báo điện tử VTV", "https://vtv.vn", "https://vtv.vn/rss/truyen-hinh.rss", "Truyền hình"),
    ("VTV", "Báo điện tử VTV", "https://vtv.vn", "https://vtv.vn/rss/truyen-hinh/goc-khan-gia.rss", "Truyền hình / Góc khán giả"),
    ("VTV", "Báo điện tử VTV", "https://vtv.vn", "https://vtv.vn/rss/van-hoa-giai-tri.rss", "Văn hóa - Giải trí"),
    ("VTV", "Báo điện tử VTV", "https://vtv.vn", "https://vtv.vn/rss/van-hoa-giai-tri/sao.rss", "Sao"),
    ("TN", "Báo Thanh Niên", "https://thanhnien.vn", "https://thanhnien.vn/rss/video/giai-tri.rss", "Video / Giải trí"),
    ("TN", "Báo Thanh Niên", "https://thanhnien.vn", "https://thanhnien.vn/rss/video/phim-ngan-vietnamese.rss", "Video / Phim ngắn Vietnamese"),
    ("TN", "Báo Thanh Niên", "https://thanhnien.vn", "https://thanhnien.vn/rss/podcast/showbiz.rss", "Podcast / Showbiz"),
]

ADD_KEYWORDS = ["phim", "lồng tiếng", "bấm máy", "đóng máy", "làm phim", "đoàn phim", "điện ảnh Việt",
                "diễn xuất", "phim trường", "vai diễn", "đạo diễn", "tác phẩm điện ảnh"]


def register() -> dict:
    prepare()
    with SOURCES.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or FIELDS)
        old = list(reader)
    if not all(k in fields for k in FIELDS):
        raise RuntimeError("Publisher registry has an incompatible CSV header")
    present = {r.get("rss_or_archive_url", "").rstrip("/") for r in old}
    additions = []
    for outlet_id, outlet_name, base_url, feed, scope in FEEDS:
        require_news_url(feed, base_url)
        if feed.rstrip("/") in present:
            continue
        row = dict.fromkeys(fields, "")
        row.update({"outlet_id": outlet_id, "outlet_name": outlet_name,
                    "base_url": base_url, "source_kind": "rss", "rss_or_archive_url": feed,
                    "section_scope": scope, "source_tier": "A",
                    "discovery_method": "Publisher RSS directory; article fetched from publisher",
                    "attribution_or_terms_note": "Respect robots, RSS terms, copyright and source attribution",
                    "active": "true"})
        additions.append(row)
        present.add(feed.rstrip("/"))
    if additions:
        # Don't touch existing rows or their source configurations.
        tmp = SOURCES.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(old + additions)
        tmp.replace(SOURCES)
    all_keys = KEYWORDS.read_text(encoding="utf-8-sig").splitlines()
    present_keys = {k.strip().casefold() for k in all_keys}
    new_keys = [k for k in ADD_KEYWORDS if k.casefold() not in present_keys]
    if new_keys:
        with KEYWORDS.open("a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(new_keys) + "\n")
    result = {"new_feeds_registered": len(additions), "new_keyword_rules": len(new_keys),
              "total_active_rss": len([r for r in sources() if r.get("source_kind") == "rss"]),
              "publishers_with_new_feeds": sorted({r['outlet_id'] for r in additions}),
              "rss_availability_not_guaranteed": True}
    json_report("rss_v4_register.json", result)
    return result


def collect(limit: int = 300, delay: float = 2.0, publishers: list[str] | None = None,
            max_feeds: int | None = None) -> dict:
    try:
        import feedparser
    except ImportError as exc:
        raise RuntimeError('Missing feedparser; run pip install -r requirements-news-v2.txt') from exc
    if limit < 1 or delay < 0 or (max_feeds is not None and max_feeds < 1):
        raise ValueError("limit and max_feeds must be positive and delay nonnegative")
    prepare()
    rss_rows = [r for r in sources() if r.get("source_kind") == "rss" and
                (not publishers or r.get("outlet_id") in publishers)]
    if max_feeds is not None:
        rss_rows = rss_rows[:max_feeds]
    if not rss_rows:
        raise RuntimeError("No matching active RSS feeds")
    path = NEWS_DATA / "articles.csv"
    existing = {r["article_id"]: r for r in csv_read(path)}
    needles = keywords()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT,
                            "Accept": "application/rss+xml, application/atom+xml, text/xml, application/xml"})
    reports = []
    for i, src in enumerate(rss_rows, 1):
        feed_url = src['rss_or_archive_url']
        item = {"outlet_id": src["outlet_id"], "feed_url": feed_url,
                "ok": False, "seen": 0, "matched": 0, "new": 0, "error": ""}
        try:
            require_news_url(feed_url, src["base_url"])
            response = session.get(feed_url, timeout=(10, 25), allow_redirects=False, stream=True)
            try:
                if response.is_redirect:
                    raise ValueError("RSS redirected; not followed automatically")
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_content(chunk_size=32_768):
                    if chunk:
                        body.extend(chunk)
                        if len(body) > 2_000_000:
                            raise ValueError("RSS document exceeds 2MB")
            finally:
                response.close()
            parsed = feedparser.parse(bytes(body))
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"Unparseable RSS/Atom: {parsed.bozo_exception}")
            item["ok"] = True
            for entry in parsed.entries[:limit]:
                item["seen"] += 1
                title = clean(entry.get('title', ''))
                summary = clean(entry.get('summary', ''))[:1000]
                tags = ' '.join(clean(t.get('term', '')) for t in entry.get('tags', []))
                if not any(word in (title + ' ' + summary + ' ' + tags).casefold() for word in needles):
                    continue
                try:
                    canonical = require_news_url(entry.get('link', ''), src['base_url'])
                except ValueError:
                    continue
                item["matched"] += 1
                aid = id_for('NEWS', src['outlet_id'], canonical)
                if aid in existing:
                    continue
                published = entry.get('published', '')
                if entry.get('published_parsed'):
                    published = datetime.fromtimestamp(calendar.timegm(entry.published_parsed), timezone.utc).isoformat()
                existing[aid] = {"article_id": aid, "outlet_id": src["outlet_id"],
                                 "outlet_name": src["outlet_name"],
                                 "original_url": entry.get('link', ''), "canonical_url": canonical,
                                 "title": title, "summary": summary,
                                 "published_at": str(published), "author": clean(entry.get('author', '')),
                                 "feed_url": feed_url, "discovered_at": now(),
                                 "discovery_status": "rss_metadata_candidate", "article_status": "pending_fetch",
                                 "syndication_group": "", "article_hash": ""}
                item["new"] += 1
        except (requests.RequestException, ValueError, OSError) as exc:
            item["error"] = str(exc)[:300]
        reports.append(item)
        # DURABLE checkpoint after every feed, including errors.
        csv_write(path, sorted(existing.values(), key=lambda r: r['article_id']), ARTICLE_FIELDS)
        report = {"stage": "news_v4_rss_expansion", "updated_at": now(),
                  "feeds_attempted": len(reports), "feeds_total": len(rss_rows),
                  "feeds_successful": sum(bool(r['ok']) for r in reports),
                  "new_articles": sum(r['new'] for r in reports),
                  "all_discovered_urls": len(existing), "feed_reports": reports,
                  "note": "RSS discovery only; source articles and edges require separate examination"}
        json_report("rss_v4_collect.json", report)
        print(f"[rss-v4] {i}/{len(rss_rows)} {src['outlet_id']} "
              f"seen={item['seen']} matched={item['matched']} new={item['new']} "
              f"error={item['error'][:80]}", file=sys.stderr, flush=True)
        if i < len(rss_rows) and delay:
            time.sleep(delay)
    return report


def report() -> dict:
    prepare()
    articles = csv_read(NEWS_DATA / "articles.csv")
    docs = csv_read(NEWS_DATA / "article_documents.csv")
    assertions = csv_read(NEWS_DATA / "relation_assertions.csv")
    nodes = csv_read(NEWS_DATA / "export" / "graph" / "nodes.csv")
    edges = csv_read(NEWS_DATA / "export" / "graph" / "edges.csv")
    metrics = {"discovered_urls": len(articles),
               "fetched_articles": sum(r.get('fetch_status') == 'fetched' for r in docs),
               "candidate_assertions": len(assertions), "export_nodes": len(nodes),
               "export_edges": len(edges), "relationship_types": len({r.get('relationship_type') for r in edges}),
               "urls_by_outlet": dict(Counter(r.get('outlet_id') for r in articles)),
               "assertions_by_type": dict(Counter(r.get('relationship_type') for r in assertions)),
               "gap_to_target": {"nodes": max(0, 2200 - len(nodes)),
                                 "edges": max(0, 5500 - len(edges)),
                                 "relationship_types": max(0, 11 - len({r.get('relationship_type') for r in edges}))},
               "precision_independently_measured": False}
    json_report("rss_v4_progress.json", metrics)
    return metrics


def run_all(args) -> dict:
    """One command: RSS -> fetch -> extract -> screen -> ONE NewsV2 Neo4j graph."""
    from types import SimpleNamespace
    from .unified import run as unified_run
    discovered = collect(limit=args.limit, delay=args.delay, publishers=args.source, max_feeds=args.max_feeds)
    unified_args = SimpleNamespace(
        discover='none', source=None, discover_limit=args.limit,
        fetch_limit=args.fetch_limit, fetch_batches=args.fetch_batches,
        delay=args.delay, retry_failed=args.retry_failed,
        skip_fetch=False, no_import=args.no_import,
        batch_size=args.batch_size, cleanup_legacy=False,
    )
    unified_result = unified_run(unified_args)
    metrics = report()
    result = {'stage': 'rss_v4_single_automatic_run', 'completed_at': now(),
              'rss_discovery': {'new_articles': discovered['new_articles'],
                                'feeds_successful': discovered['feeds_successful'],
                                'feeds_attempted': discovered['feeds_attempted']},
              'graph_metrics': metrics,
              'neo4j': unified_result.get('neo4j'),
              'gold_precision': 'not_independently_measured'}
    json_report('rss_v4_full_run.json', result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest='action', required=True)
    cmds.add_parser('register')
    p = cmds.add_parser('collect')
    p.add_argument('--limit', type=int, default=300)
    p.add_argument('--delay', type=float, default=2.0)
    p.add_argument('--source', action='append', default=[])
    p.add_argument('--max-feeds', type=int)
    one = cmds.add_parser('run', help='Single automated RSS > fetch > extract > audit > Neo4j run')
    one.add_argument('--limit', type=int, default=300, help='Max RSS entries per feed')
    one.add_argument('--delay', type=float, default=2.0)
    one.add_argument('--source', action='append', default=[])
    one.add_argument('--max-feeds', type=int)
    one.add_argument('--fetch-limit', type=int, default=200)
    one.add_argument('--fetch-batches', type=int, default=30)
    one.add_argument('--batch-size', type=int, default=200)
    one.add_argument('--retry-failed', action='store_true')
    one.add_argument('--no-import', action='store_true')
    cmds.add_parser('report')
    args = parser.parse_args(argv)
    try:
        output = (register() if args.action == 'register' else
                  collect(limit=args.limit, delay=args.delay, publishers=args.source,
                          max_feeds=args.max_feeds) if args.action == 'collect' else
                  run_all(args) if args.action == 'run' else report())
    except (RuntimeError, ValueError, OSError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
