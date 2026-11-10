"""Run: python -m unittest discover -s tests -p test_rss_v4.py -v"""
import unittest
from unittest.mock import patch
from pathlib import Path
from news_pipeline import film_patterns_plus as f
from news_pipeline import rss_expand as r
from news_pipeline.common import id_for


class TestFilmCandidates(unittest.TestCase):
    def setUp(self):
        self.article = {"article_id": id_for("NEWS", "TT", "https://tuoitre.vn/example.htm"),
                        "outlet_id": "TT", "canonical_url": "https://tuoitre.vn/example.htm"}

    def test_director_and_cast_with_evidence_offset(self):
        text = ('Phim “Mai” do Trấn Thành đạo diễn.\n'
                'Phim “Mai” quy tụ Tuấn Trần, Phương Anh Đào và Hồng Đào.')
        rows = f.candidates(self.article, text)
        triples = {(x['relationship_type'], x['subject_name'], x['object_name']) for x in rows}
        self.assertIn(('DIRECTED', 'Trấn Thành', 'Mai'), triples)
        self.assertIn(('ACTED_IN', 'Tuấn Trần', 'Mai'), triples)
        self.assertIn(('ACTED_IN', 'Phương Anh Đào', 'Mai'), triples)
        self.assertIn(('ACTED_IN', 'Hồng Đào', 'Mai'), triples)
        for row in rows:
            self.assertEqual(text[int(row['evidence_start']):int(row['evidence_end'])], row['evidence_text'])

    def test_no_speculative_relationship(self):
        text = 'Tin đồn phim “Mai” do Trấn Thành đạo diễn là chưa xác nhận.'
        self.assertEqual(f.candidates(self.article, text), [])

    def test_no_simple_cooccurrence(self):
        text = 'Trấn Thành và Tuấn Trần cùng đến buổi công chiếu phim “Mai”.'
        self.assertEqual(f.candidates(self.article, text), [])


class TestRSSRegistry(unittest.TestCase):
    def test_no_wiki_urls(self):
        from news_pipeline.common import require_news_url
        for _, _, base, url, _ in r.FEEDS:
            self.assertEqual(require_news_url(url, base), url)

    def test_unique_feeds(self):
        self.assertEqual(len(r.FEEDS), len(set(x[3] for x in r.FEEDS)))


class TestRSSCollector(unittest.TestCase):
    def test_checkpoint_and_publisher_url_filter(self):
        from unittest.mock import Mock
        import tempfile
        xml = """<?xml version='1.0' encoding='utf-8'?>
        <rss version='2.0'><channel><title>Film</title>
        <item><title>Phim Việt mới do đạo diễn thực hiện</title><link>https://tienphong.vn/phim-viet-moi-post123.html</link></item>
        <item><title>Phim Việt ngoài nguồn</title><link>https://wikipedia.org/phim-post123.html</link></item>
        </channel></rss>""".encode("utf-8")
        class Response:
            is_redirect = False
            def raise_for_status(self): return None
            def iter_content(self, chunk_size): yield xml
            def close(self): return None
        class Session:
            def __init__(self): self.headers = {}
            def get(self, *a, **k): return Response()
        import sys
        from types import SimpleNamespace
        from xml.etree import ElementTree as ET
        def parse_feed(body):
            root = ET.fromstring(body)
            entries = []
            for item in root.findall('.//item'):
                entries.append({'title': item.findtext('title', ''), 'link': item.findtext('link', '')})
            return SimpleNamespace(entries=entries, bozo=False)
        rows = []
        written = []
        reports = []
        feed = dict(outlet_id='TP', outlet_name='Báo Tiền Phong',
                    base_url='https://tienphong.vn', source_kind='rss',
                    rss_or_archive_url='https://tienphong.vn/rss/phim-anh-35.rss')
        with (patch.dict(sys.modules, {'feedparser': SimpleNamespace(parse=parse_feed)}),
              patch.object(r, 'prepare', return_value=None),
              patch.object(r, 'sources', return_value=[feed]),
              patch.object(r, 'csv_read', side_effect=lambda path: list(rows)),
              patch.object(r, 'csv_write', side_effect=lambda path, new, fields: (rows.clear(), rows.extend(new), written.append(len(new)))),
              patch.object(r, 'json_report', side_effect=lambda name, body: reports.append(body)),
              patch.object(r.requests, 'Session', Session),
              patch.object(r, 'keywords', return_value=['phim'])):
            result = r.collect(limit=10, delay=0)
            self.assertEqual(result['new_articles'], 1)
            self.assertEqual(result['feeds_successful'], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(written, [1])
            self.assertEqual(len(reports), 1)
            self.assertTrue(rows[0]['canonical_url'].startswith('https://tienphong.vn/'))



class TestOneCommand(unittest.TestCase):
    def test_run_calls_unified_once(self):
        from types import SimpleNamespace
        from news_pipeline import unified
        opts = SimpleNamespace(limit=30, delay=0, source=[], max_feeds=2,
                               fetch_limit=100, fetch_batches=3,
                               retry_failed=False, no_import=False, batch_size=25)
        with (patch.object(r, 'collect', return_value={
                  'new_articles': 2, 'feeds_successful': 2, 'feeds_attempted': 2}),
              patch.object(unified, 'run', return_value={'neo4j': {'status': 'completed'}}) as run_mock,
              patch.object(r, 'report', return_value={'export_nodes': 4}),
              patch.object(r, 'json_report', return_value=None)):
            output = r.run_all(opts)
            self.assertEqual(output['neo4j']['status'], 'completed')
            self.assertEqual(run_mock.call_count, 1)
            self.assertEqual(run_mock.call_args.args[0].discover, 'none')
            self.assertFalse(run_mock.call_args.args[0].no_import)



if __name__ == '__main__':
    unittest.main()
