from __future__ import annotations

import logging
from typing import Any

from collectors.common import clean_html_text, content_hash, request_json, stable_id, utc_now


def is_index_search_match(match: dict) -> bool:
    """Identify index/list pages that must not become a core Work node."""
    query_id = str(match.get("query_id") or "")
    title = str(match.get("page_title") or "").strip().casefold()
    known_index_queries = {
        "vi_exp_vietnamese_film_lists",
        "vi_exp_filmography_vietnam",
        "en_exp_film_lists",
    }
    title_prefixes = ("list of ", "danh sách ", "danh sach ")
    return (
        match.get("scope") == "index"
        or query_id in known_index_queries
        or title.startswith(title_prefixes)
    )


class WikipediaCollector:
    def __init__(self, session, settings: dict[str, Any], language: str) -> None:
        self.session = session
        self.settings = settings
        self.language = language
        self.endpoint = settings["sources"]["wikipedia"][f"{language}_api"]
        self.collection = settings["collection"]

    def collect_query(self, query_id: str, query: str, scope: str, limit: int) -> tuple[list[dict], list[dict]]:
        if not 1 <= int(limit) <= 500:
            raise ValueError("Wikipedia query limit must be between 1 and 500")

        results: list[dict] = []
        for offset in range(0, int(limit), 50):
            page_limit = min(50, int(limit) - offset)
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srnamespace": 0,
                "srlimit": page_limit,
                "sroffset": offset,
                "srprop": "snippet|timestamp|wordcount",
                "format": "json",
                "formatversion": 2,
                "maxlag": self.collection["maxlag_seconds"],
            }
            search_payload = request_json(
                self.session, self.endpoint, params=params,
                timeout=self.collection["request_timeout_seconds"],
                max_retries=self.collection["max_retries"],
                delay_seconds=self.collection["request_delay_seconds"],
                source_name=f"Wikipedia-{self.language}-search",
            )
            page_results = search_payload.get("query", {}).get("search", [])
            results.extend(page_results)
            logging.info(
                "Wikipedia %s / %s: search offset=%d fetched=%d",
                self.language, query_id, offset, len(page_results),
            )
            if len(page_results) < page_limit:
                break

        if not results:
            logging.info("Wikipedia %s / %s: không có kết quả", self.language, query_id)
            return [], []

        retrieved_at = utc_now()
        matches: list[dict] = []
        pages: list[dict] = []

        # Fetch page details in chunks of at most 50 page IDs.
        for start in range(0, len(results), 50):
            result_chunk = results[start:start + 50]
            page_ids = [str(item["pageid"]) for item in result_chunk if item.get("pageid")]
            detail_params = {
                "action": "query",
                "pageids": "|".join(page_ids),
                "prop": "extracts|info|pageprops",
                "explaintext": 1,
                "exchars": self.collection["wikipedia_extract_chars"],
                "inprop": "url",
                "ppprop": "wikibase_item",
                "format": "json",
                "formatversion": 2,
                "maxlag": self.collection["maxlag_seconds"],
            }
            detail_payload = request_json(
                self.session, self.endpoint, params=detail_params,
                timeout=self.collection["request_timeout_seconds"],
                max_retries=self.collection["max_retries"],
                delay_seconds=self.collection["request_delay_seconds"],
                source_name=f"Wikipedia-{self.language}-page-details",
            )
            detail_pages = detail_payload.get("query", {}).get("pages", [])
            detail_by_id = {str(page.get("pageid")): page for page in detail_pages}

            for result in result_chunk:
                page_id = str(result.get("pageid", ""))
                page = detail_by_id.get(page_id, {})
                snippet = clean_html_text(result.get("snippet", ""))
                matches.append(
                    {
                        "match_id": stable_id("wikipedia-match", self.language, page_id, query_id),
                        "language": self.language,
                        "page_id": page_id,
                        "page_title": result.get("title", ""),
                        "query_id": query_id,
                        "query": query,
                        "scope": scope,
                        "search_snippet": snippet,
                        "search_timestamp": result.get("timestamp"),
                        "word_count": result.get("wordcount"),
                        "retrieved_at": retrieved_at,
                        "source_name": f"Wikipedia-{self.language}",
                    }
                )
                extract = page.get("extract", "")
                pageprops = page.get("pageprops", {}) or {}
                pages.append(
                    {
                        "document_id": stable_id("wikipedia-page", self.language, page_id),
                        "source_name": f"Wikipedia-{self.language}",
                        "source_type": "wikipedia_action_api",
                        "language": self.language,
                        "page_id": page_id,
                        "page_title": page.get("title", result.get("title", "")),
                        "source_url": page.get("fullurl"),
                        "wikidata_id": pageprops.get("wikibase_item"),
                        "content_excerpt": extract,
                        "content_hash": content_hash(extract),
                        "retrieved_at": retrieved_at,
                        "collection_method": "action=query;list=search;continue=sroffset;prop=extracts|info|pageprops",
                    }
                )

        logging.info("Wikipedia %s / %s: %d kết quả", self.language, query_id, len(matches))
        return matches, pages
