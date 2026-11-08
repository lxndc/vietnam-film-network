from scripts.evidence_validation import (
    classify_edge_status,
    expected_statement_value,
    extract_reference,
    find_matching_statements,
    statement_role_qids,
)


def item_snak(qid):
    return {
        "snaktype": "value",
        "datavalue": {"value": {"id": qid}},
    }


def test_expected_statement_value_person_to_work():
    row = {
        "work_qid": "Q100",
        "source_qid": "Q200",
        "target_qid": "Q100",
        "role_qid": "",
    }
    assert expected_statement_value(row) == ("Q200", "")


def test_expected_statement_value_work_to_organization():
    row = {
        "work_qid": "Q100",
        "source_qid": "Q100",
        "target_qid": "Q300",
        "role_qid": "",
    }
    assert expected_statement_value(row) == ("Q300", "")


def test_expected_statement_value_rejects_wrong_orientation():
    row = {
        "work_qid": "Q100",
        "source_qid": "Q200",
        "target_qid": "Q300",
        "role_qid": "",
    }
    assert expected_statement_value(row) == ("", "")


def test_find_matching_statement_matches_property_and_target():
    entity = {
        "claims": {
            "P161": [{
                "id": "Q100$abc",
                "rank": "normal",
                "mainsnak": item_snak("Q200"),
            }]
        }
    }
    assert len(find_matching_statements(entity, "P161", "Q200")) == 1
    assert find_matching_statements(entity, "P161", "Q201") == []
    assert find_matching_statements(entity, "P57", "Q200") == []


def test_role_qualifier_is_checked_when_supplied():
    entity = {
        "claims": {
            "P3092": [{
                "id": "Q100$abc",
                "rank": "normal",
                "mainsnak": item_snak("Q200"),
                "qualifiers": {"P3831": [item_snak("Q300")]},
            }]
        }
    }
    assert len(find_matching_statements(entity, "P3092", "Q200", "Q300")) == 1
    assert find_matching_statements(entity, "P3092", "Q200", "Q301") == []
    assert statement_role_qids(entity["claims"]["P3092"][0]) == {"Q300"}


def test_extract_reference_separates_reference_url_and_stated_in():
    ref = {
        "hash": "abc",
        "snaks": {
            "P854": [{
                "snaktype": "value",
                "datavalue": {"value": "https://example.org/source"},
            }],
            "P248": [item_snak("Q400")],
        },
    }
    result = extract_reference(ref)
    assert result["reference_urls"] == ["https://example.org/source"]
    assert result["stated_in_qids"] == ["Q400"]


def test_imported_from_is_not_misclassified_as_reference_url():
    ref = {"snaks": {"P143": [item_snak("Q500")]}}
    result = extract_reference(ref)
    assert result["reference_urls"] == []
    assert result["imported_from_qids"] == ["Q500"]


def test_status_with_url_requires_source_review():
    status = classify_edge_status(
        statement_match_count=1,
        reference_url_count=1,
        stated_in_count=0,
        imported_from_count=0,
        other_reference_count=0,
    )
    assert status == "statement_matched_reference_url_needs_source_review"
    assert status != "verified"


def test_unreferenced_statement_is_not_verified():
    status = classify_edge_status(
        statement_match_count=1,
        reference_url_count=0,
        stated_in_count=0,
        imported_from_count=0,
        other_reference_count=0,
    )
    assert status == "statement_matched_unreferenced"


def test_no_statement_match_is_separate_from_unreferenced():
    status = classify_edge_status(
        statement_match_count=0,
        reference_url_count=0,
        stated_in_count=0,
        imported_from_count=0,
        other_reference_count=0,
    )
    assert status == "statement_not_found_or_endpoint_mismatch"
