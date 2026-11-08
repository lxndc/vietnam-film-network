from collectors.wikipedia_api import WikipediaCollector


def test_wikipedia_search_paginates_and_fetches_details_in_chunks(monkeypatch):
    calls = []

    def fake_request_json(session, endpoint, *, params, **kwargs):
        calls.append(dict(params))
        if params.get("list") == "search":
            offset = int(params.get("sroffset", 0))
            return {"query": {"search": [
                {"pageid": offset + i + 1, "title": f"Page {offset + i + 1}",
                 "snippet": "snippet", "wordcount": 100}
                for i in range(int(params["srlimit"]))
            ]}}
        page_ids = [int(value) for value in params["pageids"].split("|")]
        return {"query": {"pages": [
            {"pageid": value, "title": f"Page {value}",
             "fullurl": f"https://vi.wikipedia.org/wiki/Page_{value}",
             "extract": "extract", "pageprops": {"wikibase_item": f"Q{value}"}}
            for value in page_ids
        ]}}

    monkeypatch.setattr("collectors.wikipedia_api.request_json", fake_request_json)
    settings = {
        "sources": {"wikipedia": {"vi_api": "https://vi.wikipedia.org/w/api.php"}},
        "collection": {"maxlag_seconds": 5, "request_timeout_seconds": 10,
                       "max_retries": 1, "request_delay_seconds": 0,
                       "wikipedia_extract_chars": 1000},
    }
    collector = WikipediaCollector(object(), settings, "vi")
    matches, pages = collector.collect_query("query-1", "phim Việt Nam", "work", 120)

    search_calls = [call for call in calls if call.get("list") == "search"]
    detail_calls = [call for call in calls if call.get("pageids")]
    assert [call["sroffset"] for call in search_calls] == [0, 50, 100]
    assert [len(call["pageids"].split("|")) for call in detail_calls] == [50, 50, 20]
    assert len(matches) == 120
    assert len(pages) == 120
