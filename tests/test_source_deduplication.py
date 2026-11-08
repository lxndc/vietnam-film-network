import importlib.util
from pathlib import Path
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'source_deduplication.py'
SPEC = importlib.util.spec_from_file_location('source_deduplication', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

def test_p248_qid_normalization():
    key, canonical, qid = MODULE.normalize_p248('https://www.wikidata.org/wiki/Q3561957')
    assert key == 'WIKIDATA_PUBLICATION:Q3561957'
    assert qid == 'Q3561957'

def test_tracking_parameters_removed():
    a = MODULE.normalize_p854('https://www.imdb.com/title/tt2294629/fullcredits?utm_source=x&fbclid=abc')
    b = MODULE.normalize_p854('https://www.imdb.com/title/tt2294629/fullcredits')
    assert a[0] == b[0]
    assert a[2] == 'imdb.com'

def test_different_paths_not_merged():
    assert MODULE.normalize_p854('https://example.com/a')[0] != MODULE.normalize_p854('https://example.com/b')[0]

def test_http_https_not_merged():
    assert MODULE.normalize_p854('http://example.com/a')[0] != MODULE.normalize_p854('https://example.com/a')[0]

def test_distinct_imdb_titles_not_merged():
    assert MODULE.normalize_p854('https://imdb.com/title/tt1/fullcredits')[0] != MODULE.normalize_p854('https://imdb.com/title/tt2/fullcredits')[0]
