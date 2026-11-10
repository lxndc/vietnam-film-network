"""Fetch original publisher articles only when robots policy allows it.

Any cached article text is private/local; never public in the repo.
"""
from __future__ import annotations

import hashlib
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .common import (NEWS_DATA, USER_AGENT, article_path, csv_read, csv_write,
                     json_report, now, prepare, require_news_url, source_index)

DOCUMENT_FIELDS = [
    "article_id", "outlet_id", "canonical_url", "final_url", "fetch_status",
    "http_status", "content_chars", "sha256", "text_file", "fetched_at", "reason",
]


def normalize_paragraphs(text: str) -> str:
    # Keep article paragraph boundaries so relation extraction cannot join
    # unrelated credits into a fictitious single sentence.
    return "\n".join(
        line for part in text.splitlines()
        if (line := re.sub(r"[ \t]+", " ", part).strip())
    )


def extract_body(html: str) -> str:
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False,
                                  favor_precision=True, output_format="txt")
        if text and len(text.strip()) >= 200:
            return normalize_paragraphs(text)
    except (ImportError, ValueError, TypeError):
        pass
    soup = BeautifulSoup(html, "html.parser")
    for elt in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "form"]):
        elt.decompose()
    # Only use article-like elements; never treat the entire news portal page as body.
    main = (soup.find("article") or soup.find(attrs={"itemprop": "articleBody"})
            or soup.find("main"))
    if main is None:
        return ""
    paragraphs = [p.get_text(" ", strip=True) for p in main.find_all(["p", "h2", "h3"])]
    return normalize_paragraphs("\n".join(p for p in paragraphs if len(p) >= 30))


def load_robots(session: requests.Session, base_url: str) -> RobotFileParser | None:
    parts = urlsplit(base_url)
    url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        res = session.get(url, timeout=(8, 20), allow_redirects=False)
        if res.status_code in (404, 410):
            parser = RobotFileParser()
            parser.parse([])
            return parser
        if not res.ok or res.is_redirect:
            return None
        if len(res.content) > 512_000:
            return None
        parser = RobotFileParser()
        parser.parse(res.text.splitlines())
        return parser
    except requests.RequestException:
        return None  # fail closed; don't crawl if policy can't be checked


def safe_get(session: requests.Session, url: str, publisher: str) -> requests.Response:
    for _ in range(4):
        response = session.get(url, timeout=(10, 35), stream=True, allow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("Location", "")
            response.close()
            new_url = require_news_url(urljoin(url, location), publisher)
            if urlsplit(new_url).hostname != urlsplit(url).hostname:
                raise ValueError("Cross-host redirect requires separate robots review")
            url = new_url
            continue
        return response
    raise ValueError("Too many redirects")


def fetch(args) -> dict:
    prepare()
    source_by_id = source_index()
    articles = csv_read(NEWS_DATA / "articles.csv")
    if not articles:
        raise RuntimeError("No RSS articles; run collect first")
    rows = {r["article_id"]: r for r in csv_read(NEWS_DATA / "article_documents.csv")}
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html, application/xhtml+xml"})
    robots = {}
    done = 0
    for article in articles:
        aid = article["article_id"]
        if aid in rows:
            previous = rows[aid].get("fetch_status", "")
            if previous == "fetched" and article_path(aid).exists():
                continue
            # Failed URLs otherwise monopolize --limit on every run.
            if previous not in ("", "pending") and not getattr(args, "retry_failed", False):
                continue
        if done >= args.limit:
            break
        src = source_by_id.get(article.get("outlet_id"))
        if not src:
            continue
        publisher = src["base_url"]
        status = {"article_id": aid, "outlet_id": src["outlet_id"],
                  "canonical_url": article.get("canonical_url", ""), "final_url": "",
                  "fetch_status": "pending", "http_status": "", "content_chars": "0",
                  "sha256": "", "text_file": "", "fetched_at": now(), "reason": ""}
        try:
            url = require_news_url(article["canonical_url"], publisher)
            domain = urlsplit(url).hostname
            if domain not in robots:
                robots[domain] = load_robots(session, f"https://{domain}")
            policy = robots[domain]
            if policy is None or not policy.can_fetch(USER_AGENT, url):
                status.update(fetch_status="blocked_by_robots_or_policy",
                              reason="robots rules unavailable or disallow path")
            else:
                result = safe_get(session, url, publisher)
                status["http_status"] = str(result.status_code)
                status["final_url"] = require_news_url(result.url, publisher)
                content_type = result.headers.get("Content-Type", "").lower()
                if not result.ok or not ("html" in content_type):
                    status.update(fetch_status="http_or_mime_rejected",
                                  reason=f"status={result.status_code}; type={content_type}")
                    result.close()
                else:
                    chunks = []
                    bytes_seen = 0
                    too_big = False
                    for chunk in result.iter_content(chunk_size=16_384):
                        if chunk:
                            bytes_seen += len(chunk)
                            if bytes_seen > 2_500_000:
                                too_big = True
                                break
                            chunks.append(chunk)
                    result.close()
                    if too_big:
                        status.update(fetch_status="too_large", reason="2.5MB response limit")
                    else:
                        html = b"".join(chunks).decode(result.encoding or "utf-8", errors="replace")
                        text = extract_body(html)
                        status["content_chars"] = str(len(text))
                        if len(text) < 250:
                            status.update(fetch_status="insufficient_content",
                                          reason="article body absent or shorter than 250 characters")
                        else:
                            body_path = article_path(aid)
                            body_path.parent.mkdir(parents=True, exist_ok=True)
                            body_path.write_text(text, encoding="utf-8")
                            status.update(fetch_status="fetched",
                                          sha256=hashlib.sha256(text.encode()).hexdigest(),
                                          text_file=str(body_path.relative_to(NEWS_DATA)),
                                          reason="fetched original public article; not yet evidence-verified")
        except (requests.RequestException, ValueError, OSError) as exc:
            status.update(fetch_status="error", reason=str(exc)[:400])
        rows[aid] = status
        done += 1
        if done < args.limit:
            time.sleep(max(args.delay, 0))
    result_rows = sorted(rows.values(), key=lambda x: x["article_id"])
    csv_write(NEWS_DATA / "article_documents.csv", result_rows, DOCUMENT_FIELDS)
    from collections import Counter
    counts = dict(Counter(r["fetch_status"] for r in result_rows))
    result = {"stage": "news_article_fetch_v2", "date": now(), "attempted_this_run": done,
              "statuses": counts, "wiki_inputs_used": 0,
              "warning": "Fetched body is locally cached, not accepted as an accurate relationship."}
    json_report("fetch.json", result)
    return result
