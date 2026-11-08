from collectors.common import clean_html_text, stable_id


def test_stable_id_is_deterministic():
    assert stable_id("Work", "Q123") == stable_id("Work", "Q123")
    assert stable_id("Work", "Q123") != stable_id("Person", "Q123")


def test_clean_html_text_removes_tags_and_normalizes_spaces():
    assert clean_html_text("A <b>Vietnamese</b>   film &amp; series") == "A Vietnamese film & series"
