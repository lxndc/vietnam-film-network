#!/usr/bin/env python3
"""Inspect actual V4 funnel and why same-sentence credit rules rarely match."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from news_pipeline.common import NEWS_DATA, REPORTS, article_path
from news_pipeline import extract, high_yield


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))

articles = {r['article_id']: r for r in rows(NEWS_DATA / 'articles.csv')}
docs = rows(NEWS_DATA / 'article_documents.csv')
assertions = rows(NEWS_DATA / 'relation_assertions.csv')
edge_rows = rows(NEWS_DATA / 'export/graph/edges.csv')
screening = rows(NEWS_DATA / 'unified_screening.csv')
counts = Counter()
examples = []
role_re = re.compile(r'\b(?:đạo diễn|diễn viên|biên kịch|nhà sản xuất|lồng tiếng|phát hành|phát sóng|quay phim|chuyển thể|công chiếu|giành giải)\b', re.I)
film_re = re.compile(r'\b(?:bộ phim|phim|tác phẩm điện ảnh|phim truyền hình)\b', re.I)
quote_re = re.compile(r'[“”"‘’«»]')
for doc in docs:
    if doc.get('fetch_status') != 'fetched':
        continue
    counts['fetched'] += 1
    aid = doc['article_id']
    article = articles.get(aid)
    if not article:
        counts['without_article_row'] += 1
        continue
    path = article_path(aid)
    if not path.exists() or path.is_symlink():
        counts['missing_body_file'] += 1
        continue
    body = path.read_text(encoding='utf-8')
    if hashlib.sha256(body.encode()).hexdigest() != doc.get('sha256'):
        counts['bad_sha256'] += 1
        continue
    counts['valid_articles'] += 1
    if quote_re.search(body):
        counts['article_with_quotes'] += 1
    if role_re.search(body):
        counts['article_with_role_words'] += 1
    if film_re.search(body):
        counts['article_with_film_words'] += 1
    role_and_film = 0
    ignored_long = 0
    for pos, sent in extract.sentences(body):
        counts['sentences_total'] += 1
        if role_re.search(sent):
            counts['sentences_role'] += 1
        if film_re.search(sent):
            counts['sentences_film'] += 1
        if role_re.search(sent) and film_re.search(sent):
            counts['sentences_role_and_film'] += 1
            role_and_film += 1
            if len(sent) > 450:
                ignored_long += 1
                counts['role_film_sentences_over_450'] += 1
            elif len(examples) < 12:
                examples.append({'url': article.get('canonical_url', ''),
                                 'sample': sent[:240], 'quoted': bool(quote_re.search(sent))})
    if role_and_film:
        counts['articles_with_same_sentence_role_film'] += 1
    if ignored_long:
        counts['articles_with_long_role_film_sentences'] += 1
    candidates = high_yield.extract_candidates(article, body)
    if candidates:
        counts['articles_with_extracted_relations'] += 1
        counts['recomputed_assertions'] += len(candidates)

counts['discovered_articles'] = len(articles)
counts['stored_candidate_assertions'] = len(assertions)
counts['machine_pass'] = sum(r.get('screening_status') == 'machine_pass' for r in screening)
counts['exported_unique_edges'] = len(edge_rows)
counts['exported_nodes'] = len(rows(NEWS_DATA / 'export/graph/nodes.csv'))
report = {'stage': 'news_v4_growth_diagnosis', 'counts': dict(counts),
          'exported_by_type': dict(Counter(e.get('relationship_type', '') for e in edge_rows)),
          'rejections': dict(Counter(r.get('reason', '') for r in screening if r.get('reason'))),
          'sample_sentences': examples,
          'notes': [
              'RSS captures recent links, not a historical film-credit dataset.',
              'Same-sentence patterns currently reject many unquoted or indirect references.',
              'Repeated archive/sitemap runs used to restart from the same seeds; install growth fix to resume.',
              'This is a coverage diagnostic, not a Gold Standard precision estimate.',
          ]}
REPORTS.mkdir(parents=True, exist_ok=True)
path = REPORTS / 'growth_diagnosis.json'
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
for key, value in counts.most_common():
    print(f'{key:42} {value}')
print('exported_by_type:', report['exported_by_type'])
print('rejections:', report['rejections'])
print('Saved:', path)
