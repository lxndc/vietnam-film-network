"""Offline checkpoint + evidence offset regression tests; run after installation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_pipeline import backfill, extract


class GrowthFixTest(unittest.TestCase):
    def test_frontier_persists_child_urls_without_restarting_root(self):
        with tempfile.TemporaryDirectory() as td, patch.object(backfill, 'NEWS_DATA', Path(td)):
            seed = 'https://publisher.example/sitemap.xml'
            child1 = 'https://publisher.example/sitemap-older-1.xml'
            child2 = 'https://publisher.example/sitemap-older-2.xml'
            pending, seen = backfill._vfn_load_sitemap_frontier('TP', [seed])
            self.assertEqual(list(pending), [seed])
            pending.popleft()
            seen.add(seed)
            pending.extend([child1, child2])
            backfill._vfn_save_sitemap_frontier('TP', pending, seen)
            resumed, visited = backfill._vfn_load_sitemap_frontier('TP', [seed])
            self.assertEqual(list(resumed), [child1, child2])
            self.assertEqual(visited, {seed})
            # Resume and complete the two children.
            for child in list(resumed):
                resumed.popleft()
                visited.add(child)
            backfill._vfn_save_sitemap_frontier('TP', resumed, visited)
            rescan, _ = backfill._vfn_load_sitemap_frontier('TP', [seed])
            self.assertEqual(list(rescan), [seed])

    def test_source_sentence_offset_after_leading_whitespace(self):
        body = '  Đạo diễn Trấn Thành thực hiện phim “Mai”.\n  Phim “Mai” ra mắt trên toàn quốc năm 2026.'
        matches = list(extract.sentences(body))
        self.assertEqual(len(matches), 2)
        for index, sentence in matches:
            self.assertEqual(body[index:index + len(sentence)], sentence)

    def test_frontier_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as td, patch.object(backfill, 'NEWS_DATA', Path(td)):
            path = Path(td) / 'state' / 'sitemap_frontier_TP.json'
            path.parent.mkdir()
            outside = Path(td) / 'source.json'
            outside.write_text('{}')
            path.symlink_to(outside)
            with self.assertRaises(ValueError):
                backfill._vfn_load_sitemap_frontier('TP', ['https://publisher.example/sitemap.xml'])


if __name__ == '__main__':
    unittest.main()
