"""Read-only diagnosis of newspaper collection and relation extraction coverage."""
from __future__ import annotations

from collections import Counter

from .common import NEWS_DATA, article_path, csv_read, json_report, now
from .extract import candidates_for_article, sentences


def diagnose(args) -> dict:
    articles = csv_read(NEWS_DATA / 'articles.csv')
    docs = csv_read(NEWS_DATA / 'article_documents.csv')
    assertions = csv_read(NEWS_DATA / 'relation_assertions.csv')
    by_article = {row.get('article_id'): row for row in articles}
    fetch_statuses = Counter(row.get('fetch_status', 'missing') for row in docs)
    doc_by_article = {row.get('article_id'): row for row in docs}
    missing_docs = sum(a['article_id'] not in doc_by_article for a in articles)
    analyzed = 0
    no_match = []
    matching_articles = 0
    potential_matches_by_type = Counter()
    sentence_total = 0
    article_with_role_words = 0
    key_phrases = ('đạo diễn', 'diễn viên', 'phim', 'sản xuất', 'phát hành', 'biên kịch',
                   'lồng tiếng', 'tham gia', 'phát sóng')
    occurrences = Counter()

    for doc in docs:
        aid = doc.get('article_id', '')
        if doc.get('fetch_status') != 'fetched' or aid not in by_article:
            continue
        path = article_path(aid)
        if not path.is_file():
            continue
        body = path.read_text(encoding='utf-8')
        analyzed += 1
        sentence_total += sum(1 for _ in sentences(body))
        normalized = body.casefold()
        seen_role = False
        for phrase in key_phrases:
            count = normalized.count(phrase)
            occurrences[phrase] += count
            if phrase != 'phim' and count > 0:
                seen_role = True
        if seen_role:
            article_with_role_words += 1
        proposals = candidates_for_article(by_article[aid], body)
        if proposals:
            matching_articles += 1
            potential_matches_by_type.update(row['relationship_type'] for row in proposals)
        elif len(no_match) < max(0, args.examples):
            no_match.append({
                'article_id': aid,
                'outlet_id': by_article[aid].get('outlet_id', ''),
                'article_title': by_article[aid].get('title', ''),
                'reason': 'No explicit-role rule matched the locally fetched text',
            })

    existing_types = Counter(row.get('relationship_type', '') for row in assertions)
    result = {
        'stage': 'news_v2_1_coverage_diagnostics',
        'at': now(),
        'articles_total': len(articles),
        'articles_missing_document_row': missing_docs,
        'fetch_statuses': dict(fetch_statuses),
        'fetched_texts_available': analyzed,
        'eligible_sentences_parsed': sentence_total,
        'articles_containing_role_keywords': article_with_role_words,
        'articles_matching_extractor_rules': matching_articles,
        'matches_by_relationship_type_from_current_texts': dict(potential_matches_by_type),
        'existing_relation_assertions_total': len(assertions),
        'existing_relation_assertions_by_type': dict(existing_types),
        'role_keyword_occurrences': dict(occurrences),
        'example_articles_without_match': no_match,
        'wiki_files_read': 0,
        'interpretation': (
            'No fetched articles. Inspect fetch.json and article_documents.csv.' if analyzed == 0 else
            'Fetched articles exist but no relation patterns matched; inspect sentence styles and extractor rules.'
            if matching_articles == 0 else
            'Matching article text exists. Run extract, then audit, before Gold Standard sampling.'
        ),
        'note': 'Diagnostic scans cached original news texts; matches are unreviewed candidates, not verified edges.'
    }
    json_report('diagnose.json', result)
    return result
