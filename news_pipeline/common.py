"""Project-scoped I/O, validation, and source isolation for newspaper-only SNA."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path.cwd().resolve()
NEWS_DATA = ROOT / "data" / "news_v2"
REPORTS = ROOT / "reports" / "news_v2"
SOURCES = ROOT / "config" / "news_sources.csv"
KEYWORDS = ROOT / "config" / "film_keywords.txt"
USER_AGENT = "VietnamFilmNetworkAcademicResearch/2.0 (+https://github.com/lxndc/vietnam-film-network)"
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid"}
BAD_DOMAINS = {
    "wikipedia.org", "wikidata.org", "wikimedia.org", "mediawiki.org",
    "dbpedia.org", "wikiquote.org", "wikinews.org",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def id_for(prefix: str, *parts: str) -> str:
    key = "\x1f".join(str(x).strip() for x in parts)
    return prefix + "_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def normalize(s: str) -> str:
    return " ".join((s or "").strip().split())


def url_canonical(url: str) -> str:
    try:
        p = urlsplit((url or "").strip())
        if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
            return ""
        host = p.hostname.lower().strip(".")
        if p.port and p.port not in (80, 443):
            return ""
        params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                  if not k.lower().startswith("utm_") and k.lower() not in TRACKING]
        return urlunsplit((p.scheme.lower(), host, p.path.rstrip("/") or "/", urlencode(params), ""))
    except ValueError:
        return ""


def is_wiki(url: str) -> bool:
    try:
        hostname = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return True
    return any(hostname == domain or hostname.endswith("." + domain) for domain in BAD_DOMAINS)


def same_publisher(url: str, base: str) -> bool:
    try:
        hostname = (urlsplit(url).hostname or "").lower()
        publisher = (urlsplit(base).hostname or "").lower()
    except ValueError:
        return False
    if not hostname or not publisher:
        return False
    return hostname == publisher or hostname.endswith("." + publisher)


def require_news_url(url: str, base: str) -> str:
    canonical = url_canonical(url)
    if not canonical or is_wiki(canonical) or not same_publisher(canonical, base):
        raise ValueError(f"Rejected external, nonpublisher, or Wiki URL: {url!r}")
    return canonical


def prepare() -> None:
    # Data source and output namespaces are hard-coded. Do not follow symlinks outside the repo.
    for target in (NEWS_DATA, REPORTS):
        if target.is_symlink():
            raise RuntimeError(f"Refusing symbolic-link output: {target}")
        if not target.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"Refusing output outside project: {target}")
        target.mkdir(parents=True, exist_ok=True)
    # Prevent reads/writes through symlinked child directories in the data namespace.
    if any(path.is_symlink() for path in NEWS_DATA.rglob("*")):
        raise RuntimeError("Symlinks inside data/news_v2 are forbidden")
    if not SOURCES.is_file():
        raise FileNotFoundError(f"Missing news source registry: {SOURCES}")


def csv_read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    if not path.resolve().is_relative_to(NEWS_DATA) and path != SOURCES:
        raise RuntimeError(f"Reader blocked outside newspaper-only namespace: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def csv_write(path: Path, rows: list[dict], fields: list[str]) -> None:
    if not path.resolve().is_relative_to(NEWS_DATA):
        raise RuntimeError(f"Writer blocked outside newspaper-only namespace: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def json_report(name: str, payload: dict) -> Path:
    if "/" in name or ".." in name:
        raise ValueError("Invalid report name")
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def sources() -> list[dict]:
    rows = csv_read(SOURCES)
    active = []
    for r in rows:
        if str(r.get("active", "")).lower() not in ("true", "yes", "1"):
            continue
        base = str(r.get("base_url", ""))
        rss = str(r.get("rss_or_archive_url", ""))
        if is_wiki(base) or is_wiki(rss):
            raise RuntimeError("Wiki source forbidden in news registry")
        active.append(r)
    if not active:
        raise RuntimeError("No active news sources")
    return active


def source_index() -> dict[str, dict]:
    return {row["outlet_id"]: row for row in sources()}


def text_key(s: str) -> str:
    return re.sub(r"\W+", " ", normalize(s).casefold(), flags=re.UNICODE).strip()


def article_path(article_id: str) -> Path:
    if not re.fullmatch(r"NEWS_[0-9a-f]{24}", article_id):
        raise ValueError("Invalid news article ID")
    return NEWS_DATA / "private" / "article_text" / f"{article_id}.txt"


def assert_no_wiki(rows: list[dict], url_fields: tuple[str, ...]) -> None:
    for row in rows:
        for key in url_fields:
            value = str(row.get(key, ""))
            if value and is_wiki(value):
                raise RuntimeError(f"Wiki contamination found in {key}: {value}")
