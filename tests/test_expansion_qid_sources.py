from scripts.run_expansion import extract_wikipedia_work_qids


def test_only_work_scope_pages_contribute_credit_qids():
    matches = [
        {"language": "vi", "page_id": "1", "scope": "work"},
        {"language": "en", "page_id": "2", "scope": "person"},
        {"language": "vi", "page_id": "3", "scope": "index"},
        {"language": "vi", "page_id": "4", "scope": "work"},
        {"language": "en", "page_id": "5", "scope": "work", "query_id": "en_exp_film_lists", "page_title": "A Vietnamese Film"},
    ]
    pages = [
        {"language": "vi", "page_id": "1", "wikidata_id": "Q100"},
        {"language": "en", "page_id": "2", "wikidata_id": "Q200"},
        {"language": "vi", "page_id": "3", "wikidata_id": "Q300"},
        {"language": "vi", "page_id": "4", "wikidata_id": "not-a-qid"},
        {"language": "en", "page_id": "5", "wikidata_id": "Q500"},
    ]
    assert extract_wikipedia_work_qids(matches, pages) == {"Q100"}
