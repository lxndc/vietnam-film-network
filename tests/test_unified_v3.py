"""Offline integration checks; no crawling, Neo4j, or claimed precision needed."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class UnifiedOfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source_package = Path(__file__).resolve().parents[1] / "news_pipeline"
        shutil.copytree(source_package, self.root / "news_pipeline")
        # The integration test deliberately uses original package modules in
        # a local installed project; test in the project after INSTALL.sh.
        (self.root / "config").mkdir()
        (self.root / "data/news_v2").mkdir(parents=True)
        (self.root / "reports/news_v2").mkdir(parents=True)
        (self.root / "config/news_sources.csv").write_text(
            "outlet_id,outlet_name,base_url,source_kind,rss_or_archive_url,active\n"
            "TT,Tuổi Trẻ,https://tuoitre.vn,rss,https://tuoitre.vn/giai-tri.rss,true\n",
            encoding="utf-8",
        )
        (self.root / "config/film_keywords.txt").write_text("phim\n", encoding="utf-8")
        self.aid = "NEWS_" + "a" * 24
        self.url = "https://tuoitre.vn/phim-mai-co-giai-thuong.htm"
        self.body = ("Bài báo về điện ảnh và tác phẩm Việt Nam.\n" * 8
            + "Phim “Mai” quy tụ dàn diễn viên Trấn Thành, Hồng Đào và Tuấn Trần.\n"
            + "Đạo diễn Trấn Thành đứng sau phim “Mai”.\n"
            + "Biên kịch Nguyễn Văn An viết kịch bản cho phim “Ngày Mới”.\n"
            + "Phim “Ngày Mới” đã công chiếu năm 2025.\n"
            + "Phim “Ngày Mới” được quay tại Ninh Bình.\n"
            + "Phim “Ngày Mới” chuyển thể từ tiểu thuyết “Mùa Lá Rụng”.\n"
            + "Phim “Ngày Mới” giành giải Cánh Diều Vàng.\n"
        )
        self._write("articles.csv", [{"article_id": self.aid, "outlet_id": "TT",
                    "canonical_url": self.url, "title": "Đội ngũ phim Mai"}])
        self._write("article_documents.csv", [{"article_id": self.aid, "outlet_id": "TT",
                    "canonical_url": self.url, "fetch_status": "fetched",
                    "content_chars": len(self.body),
                    "sha256": hashlib.sha256(self.body.encode()).hexdigest()}])
        path = self.root / f"data/news_v2/private/article_text/{self.aid}.txt"
        path.parent.mkdir(parents=True)
        path.write_text(self.body, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, rows):
        path = self.root / "data/news_v2" / name
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def _run(self):
        return subprocess.run([sys.executable, "-m", "news_pipeline.unified", "run",
                               "--discover", "none", "--skip-fetch", "--no-import"],
                              cwd=self.root, text=True, capture_output=True, timeout=45)

    def test_multiple_explicit_types_and_offsets(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / "reports/news_v2/unified_graph.json").read_text())
        self.assertEqual(report["automatic_coverage_percent"], 100)
        self.assertGreaterEqual(report["machine_screened_edges"], 9)
        self.assertEqual(report["machine_rejected_assertions"], 0)
        self.assertEqual(report["precision_gt_90_proven"], False)
        self.assertIsNone(report["independently_measured_precision_percent"])
        self.assertEqual(report["wiki_sources_used"], 0)
        with (self.root / "data/news_v2/export/graph/edges.csv").open(encoding="utf-8-sig") as f:
            edges = list(csv.DictReader(f))
        types = {r["relationship_type"] for r in edges}
        self.assertTrue({"ACTED_IN", "DIRECTED", "WROTE", "RELEASED_IN_YEAR", "FILMED_IN",
                         "ADAPTED_FROM", "WON_AWARD"}.issubset(types), types)
        with (self.root / "data/news_v2/export/graph/edge_evidence.csv").open(encoding="utf-8-sig") as f:
            evidence = list(csv.DictReader(f))
        for row in evidence:
            self.assertEqual(self.body[int(row["evidence_start"]):int(row["evidence_end"])], row["evidence_text"])

    def test_tampered_body_fails_closed(self):
        path = self.root / f"data/news_v2/private/article_text/{self.aid}.txt"
        path.write_text(self.body + "CHANGED", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / "reports/news_v2/unified_graph.json").read_text())
        self.assertEqual(report["machine_screened_edges"], 0)
        self.assertEqual(report["machine_screened_nodes"], 0)

    def test_wiki_url_is_rejected(self):
        self.url = "https://vi.wikipedia.org/wiki/Phim_Mai"
        self._write("articles.csv", [{"article_id": self.aid, "outlet_id": "TT",
                    "canonical_url": self.url, "title": "Phim Mai"}])
        self._write("article_documents.csv", [{"article_id": self.aid, "outlet_id": "TT",
                    "canonical_url": self.url, "fetch_status": "fetched",
                    "content_chars": len(self.body),
                    "sha256": hashlib.sha256(self.body.encode()).hexdigest()}])
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / "reports/news_v2/unified_graph.json").read_text())
        self.assertEqual(report["machine_screened_edges"], 0)
        self.assertGreater(report["machine_rejected_assertions"], 0)
        self.assertIn("forbidden_url", report["rejection_reasons"])


if __name__ == "__main__":
    unittest.main()
