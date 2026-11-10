"""Conservative publisher archive / sitemap discovery for newspaper-only graph.

This *discovers metadata candidates*. It does not fetch article bodies, create
relations, or verify any claim. Publisher robots policy is checked before each
index request; no cross-publisher redirects or arbitrary web crawling.
"""
from __future__ import annotations

import calendar
import gzip
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .collect import ARTICLE_FIELDS, clean, keywords
from .common import (NEWS_DATA, USER_AGENT, csv_read, csv_write, id_for,
                     json_report, now, prepare, require_news_url, sources)
from .fetch import load_robots

MAX_RESPONSE = 4_000_000
SITEMAP_MAX_UNCOMPRESSED = 8_000_000
ARTICLE_SUFFIXES = (".htm", ".html", ".shtml")
PAGE_HINTS = re.compile(r"(?:[?&](?:page|trang|p)=\d+|/trang[-/]\d+|/page/\d+)", re.I)
PATH_HINTS = ("/dien-anh", "/phim", "/truyen-hinh", "/nghe-si", "/dao-dien", "/dien-vien", "/hau-truong")


def _request(session, url: str, src: dict, robots_cache: dict) -> bytes:
    url = require_news_url(url, src["base_url"])
    host = urlsplit(url).hostname
    if host not in robots_cache:
        robots_cache[host] = load_robots(session, f"{urlsplit(url).scheme}://{host}")
    policy = robots_cache[host]
    if policy is None or not policy.can_fetch(USER_AGENT, url):
        raise ValueError(f"robots disallowed/unavailable: {url}")
    res = session.get(url, timeout=(10, 35), stream=True, allow_redirects=False)
    try:
        if res.is_redirect:
            raise ValueError(f"Redirect requires manual review: {url}")
        res.raise_for_status()
        result = bytearray()
        for chunk in res.iter_content(chunk_size=32_768):
            if chunk:
                result.extend(chunk)
                if len(result) > MAX_RESPONSE:
                    raise ValueError("Archive/sitemap response exceeds safe size cap")
        return bytes(result)
    finally:
        res.close()


def _valid_article(url: str, title: str, needles: list[str]) -> bool:
    path = urlsplit(url).path.casefold()
    # Article-like paths only. Index/category URLs are not article candidates.
    if not path.endswith(ARTICLE_SUFFIXES):
        return False
    # Titles or URL slugs must explicitly indicate film-related content.
    slug = path.replace("-", " ").replace("_", " ")
    text = (title + " " + slug).casefold()
    return any(word in text for word in needles) or any(hint in path for hint in PATH_HINTS)


def _row(src: dict, url: str, title: str, method: str, published: str = "") -> dict:
    aid = id_for("NEWS", src["outlet_id"], url)
    return {
        "article_id": aid, "outlet_id": src["outlet_id"],
        "outlet_name": src["outlet_name"], "original_url": url,
        "canonical_url": url, "title": clean(title), "summary": "",
        "published_at": published, "author": "",
        "feed_url": method, "discovered_at": now(),
        "discovery_status": "archive_metadata_candidate", "article_status": "pending_fetch",
        "syndication_group": "", "article_hash": "",
    }


def _archives(html: bytes, parent: str, src: dict, needles: list[str], root: str):
    soup = BeautifulSoup(html, "html.parser")
    article_hits = {}
    pages = set()
    root_path = urlsplit(root).path.rstrip("/")
    for a in soup.find_all("a", href=True):
        abs_url = urljoin(parent, a["href"])
        try:
            url = require_news_url(abs_url, src["base_url"])
        except ValueError:
            continue
        title = clean(a.get("title") or a.get_text(" ", strip=True))
        if _valid_article(url, title, needles):
            article_hits[url] = title
            continue
        # Pagination is restricted to the explicit archive path. No arbitrary links.
        if PAGE_HINTS.search(url) and urlsplit(url).path.startswith(root_path):
            pages.add(url)
    return article_hits, sorted(pages)


def _xml_payload(body: bytes) -> bytes:
    if body.startswith(b"\x1f\x8b"):
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(SITEMAP_MAX_UNCOMPRESSED + 1)
        if len(body) > SITEMAP_MAX_UNCOMPRESSED:
            raise ValueError("Decompressed sitemap exceeds safe cap")
    return body


def _parse_sitemap(body: bytes, source_url: str, src: dict, needles: list[str]):
    root = ET.fromstring(_xml_payload(body))
    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag not in ("sitemapindex", "urlset"):
        raise ValueError("Not a sitemapindex/urlset")
    sitemap_urls = []
    articles = {}
    for child in root:
        if tag == "sitemapindex":
            loc = next((x.text or "" for x in child if x.tag.rsplit("}", 1)[-1] == "loc"), "")
            try:
                sitemap_urls.append(require_news_url(loc, src["base_url"]))
            except ValueError:
                pass
        else:
            loc = next((x.text or "" for x in child if x.tag.rsplit("}", 1)[-1] == "loc"), "")
            title = ""
            pub = ""
            # News sitemaps can carry news:title and news:publication_date.
            for part in child.iter():
                name = part.tag.rsplit("}", 1)[-1]
                if name == "title" and not title:
                    title = clean(part.text or "")
                if name in ("publication_date", "lastmod") and not pub:
                    pub = clean(part.text or "")
            try:
                url = require_news_url(loc, src["base_url"])
            except ValueError:
                continue
            if _valid_article(url, title, needles):
                articles[url] = (title, pub)
    return sitemap_urls, articles


def backfill(args) -> dict:
    """Sitemap/archive discovery with bounded attempts and durable checkpoints.

    Every 5 attempted sitemap/archive pages we persist article candidates to
    data/news_v2/articles.csv and a live report. Ctrl+C also checkpoints.
    """
    prepare()
    selected = [s for s in sources() if not args.source or s["outlet_id"] in args.source]
    # Config may contain several RSS feeds per publisher: traverse its sitemap
    # only once per outlet, not once per feed (avoids multi-hour duplicate work).
    srcs = list({s["outlet_id"]: s for s in selected}.values())
    if args.mode == "archive":
        srcs = [s for s in srcs if s.get("source_kind") == "archive"]
    if not srcs:
        raise RuntimeError("No eligible sources; check --mode/--source")
    needles = keywords()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html, application/xml, text/xml, application/rss+xml"})
    path = NEWS_DATA / "articles.csv"
    existing = {r["article_id"]: r for r in csv_read(path)}
    reports = []
    robots_cache = {}
    discovered = 0
    attempts = 0
    interrupted = False
    status = "in_progress"
    max_attempts = getattr(args, "max_sitemap_attempts", 60)
    if max_attempts < 1:
        raise ValueError("--max-sitemap-attempts must be >=1")

    def save_checkpoint():
        # csv_write uses an atomic temp-file replacement; a repeat run can resume
        # without producing duplicate article IDs.
        csv_write(path, sorted(existing.values(), key=lambda r: r["article_id"]), ARTICLE_FIELDS)
        output = {
            "stage": "news_backfill_v2_2_hotfix",
            "date": now(),
            "status": status,
            "mode": args.mode,
            "articles_total": len(existing),
            "new_article_candidates": discovered,
            "pages_attempted_total": attempts,
            "max_articles": args.limit,
            "max_sitemap_attempts_per_source": max_attempts,
            "outlets": reports,
            "wiki_source_files_read": 0,
            "note": "Only discovers publisher URLs; never verifies an edge. Progress is checkpointed.",
        }
        json_report("backfill.json", output)
        return output

    try:
        for src in srcs:
            report = {
                "outlet_id": src["outlet_id"], "method": args.mode,
                "index_pages_read": 0, "pages_attempted": 0,
                "sitemap_attempted": 0, "archive_attempted": 0,
                "new_articles": 0, "errors": [], "latest_url": "",
            }
            reports.append(report)

            if args.mode in ("archive", "both") and src.get("source_kind") == "archive":
                root = src["rss_or_archive_url"]
                pending = deque([root])
                visited = set()
                while (pending and report["index_pages_read"] < args.max_pages
                       and report["archive_attempted"] < max_attempts
                       and discovered < args.limit):
                    url = pending.popleft()
                    if url in visited:
                        continue
                    visited.add(url)
                    report["archive_attempted"] += 1
                    report["pages_attempted"] += 1
                    report["latest_url"] = url
                    attempts += 1
                    try:
                        page = _request(session, url, src, robots_cache)
                        article_hits, more_pages = _archives(page, url, src, needles, root)
                        report["index_pages_read"] += 1
                        for article_url, title in article_hits.items():
                            record = _row(src, article_url, title, url)
                            if record["article_id"] not in existing:
                                existing[record["article_id"]] = record
                                report["new_articles"] += 1
                                discovered += 1
                                if discovered >= args.limit:
                                    break
                        for next_page in more_pages:
                            if next_page not in visited:
                                pending.append(next_page)
                        outcome = "ok"
                    except (requests.RequestException, ValueError, ET.ParseError) as exc:
                        report["errors"].append(str(exc)[:240])
                        outcome = "error"
                    print(f"[{src['outlet_id']}] archive {report['archive_attempted']}/{max_attempts} "
                          f"({outcome}) +{report['new_articles']} articles; total new={discovered}", flush=True)
                    if attempts % 5 == 0:
                        save_checkpoint()
                    if pending and discovered < args.limit:
                        time.sleep(max(args.delay, 0))

            if args.mode in ("sitemap", "both") and discovered < args.limit:
                robots = load_robots(session, src["base_url"])
                seeds = list(robots.site_maps() or []) if robots else []
                if args.sitemap:
                    seeds.extend(args.sitemap)
                if not seeds:
                    report["errors"].append("No publisher sitemap seeds available from robots.txt")
                    print(f"[{src['outlet_id']}] no sitemap seeds from robots.txt; skipped", flush=True)
                pending = deque(seeds)
                seen = set()
                while (pending and report["index_pages_read"] < args.max_sitemaps
                       and report["sitemap_attempted"] < max_attempts
                       and discovered < args.limit):
                    url = pending.popleft()
                    if url in seen:
                        continue
                    seen.add(url)
                    report["sitemap_attempted"] += 1
                    report["pages_attempted"] += 1
                    report["latest_url"] = url
                    attempts += 1
                    try:
                        body = _request(session, url, src, robots_cache)
                        subs, article_hits = _parse_sitemap(body, url, src, needles)
                        report["index_pages_read"] += 1
                        for next_url in subs:
                            if next_url not in seen:
                                pending.append(next_url)
                        for article_url, (title, pub) in article_hits.items():
                            record = _row(src, article_url, title, url, pub)
                            if record["article_id"] not in existing:
                                existing[record["article_id"]] = record
                                discovered += 1
                                report["new_articles"] += 1
                                if discovered >= args.limit:
                                    break
                        outcome = "ok"
                    except (requests.RequestException, ValueError, ET.ParseError) as exc:
                        report["errors"].append(str(exc)[:240])
                        outcome = "error"
                    print(f"[{src['outlet_id']}] sitemap {report['sitemap_attempted']}/{max_attempts} "
                          f"({outcome}) +{report['new_articles']} articles; total new={discovered}", flush=True)
                    if attempts % 5 == 0:
                        save_checkpoint()
                    if pending and discovered < args.limit:
                        time.sleep(max(args.delay, 0))
            # Save after finishing each publisher even with <5 attempts.
            save_checkpoint()
        status = "completed"
    except KeyboardInterrupt:
        status = "interrupted_checkpoint_saved"
        interrupted = True
        print("Interrupted: saving discovered article URLs and report before exit...", flush=True)
    finally:
        output = save_checkpoint()
        session.close()
    if interrupted:
        return output
    return output
