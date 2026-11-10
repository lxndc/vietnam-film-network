"""Offline tests for archive discovery, Wiki isolation, cast extraction and progress."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from news_pipeline.backfill import _archives, _parse_sitemap, _valid_article
from news_pipeline.common import is_wiki, require_news_url
from news_pipeline.extract import candidates_for_article

SRC = {"base_url": "https://baovanhoa.vn", "outlet_id": "BVH", "outlet_name": "Báo Văn Hóa"}
KEYS = ["phim", "đạo diễn", "diễn viên", "điện ảnh"]
ARTICLE = {"article_id": "NEWS_" + "1" * 24, "outlet_id": "TT",
           "canonical_url": "https://tuoitre.vn/mot-bai-ve-phim.htm"}


def test_archive_only_publisher_article_urls_and_pagination():
    html = '''<html><body>
       <a href="/dien-anh/phim-viet-nam-123.html">Phim Việt Nam</a>
       <a href="/dien-anh/?page=2">Trang 2</a>
       <a href="https://www.wikidata.org/wiki/Q1">Phim Wiki</a>
       <a href="https://baovanhoa.vn/tin-tuc.html">Tin tức chung</a>
       <a href="https://other.example/phim.htm">Phim ở nơi khác</a>
    </body></html>'''.encode('utf-8')
    hits, more = _archives(html, "https://baovanhoa.vn/dien-anh/", SRC, KEYS,
                           "https://baovanhoa.vn/dien-anh/")
    assert list(hits) == ["https://baovanhoa.vn/dien-anh/phim-viet-nam-123.html"]
    assert more == ["https://baovanhoa.vn/dien-anh?page=2"]


def test_xml_sitemap_selects_only_film_related_article():
    xml = '''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
    xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
    <url><loc>https://baovanhoa.vn/dien-anh/phim-123.html</loc>
    <news:news><news:title>Phim Việt Nam ra mắt</news:title></news:news></url>
    <url><loc>https://baovanhoa.vn/kinh-te/gia-xang-456.html</loc></url>
    <url><loc>https://vi.wikipedia.org/wiki/A</loc></url>
    </urlset>'''.encode('utf-8')
    subs, hits = _parse_sitemap(xml, "https://baovanhoa.vn/sitemap.xml", SRC, KEYS)
    assert not subs
    assert list(hits) == ["https://baovanhoa.vn/dien-anh/phim-123.html"]


def test_cast_list_evidence_explicit_and_name_offsets():
    text = "  Phim “Mai” quy tụ dàn diễn viên Trấn Thành, Hồng Đào và Tuấn Trần."
    # The role 'diễn viên' and explicit film are both mandatory.
    edges = candidates_for_article(ARTICLE, text)
    persons = {x["subject_name"] for x in edges if x["relationship_type"] == "ACTED_IN"}
    assert persons == {"Trấn Thành", "Hồng Đào", "Tuấn Trần"}
    for item in edges:
        assert item["subject_type"] == "Person"
        assert item["object_type"] == "Work"
        assert text[int(item["evidence_start"]):int(item["evidence_end"])] == item["evidence_text"]
    assert not candidates_for_article(ARTICLE,
        "Trấn Thành, Hồng Đào và Tuấn Trần đều được giới thiệu trong bài viết về phim “Mai”.")


def test_source_rejects_wiki_even_when_keyword_appears():
    assert is_wiki("https://www.wikidata.org/wiki/Q1")
    with pytest.raises(ValueError):
        require_news_url("https://vi.wikipedia.org/wiki/Film", "https://baovanhoa.vn")
    assert not _valid_article("https://baovanhoa.vn/index", "Phim Việt Nam", KEYS)
