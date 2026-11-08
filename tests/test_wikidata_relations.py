from collectors.wikidata_client import PROPERTY_RELATIONSHIPS, build_credit_candidate


def test_relationship_schema_has_twenty_populated_capable_types():
    assert len(PROPERTY_RELATIONSHIPS) >= 25
    assert len({value[0] for value in PROPERTY_RELATIONSHIPS.values()}) == len(PROPERTY_RELATIONSHIPS)


def test_person_work_statement_is_reversed_to_person_to_work_edge():
    row = {
        "work": {"value": "http://www.wikidata.org/entity/Q100"},
        "workLabel": {"value": "Vietnamese Film"},
        "property": {"value": "http://www.wikidata.org/entity/P161"},
        "target": {"value": "http://www.wikidata.org/entity/Q200"},
        "targetLabel": {"value": "Actor A"},
        "referenceUrls": {"value": "https://example.org/source"},
    }
    edge = build_credit_candidate(row, "2026-11-07T00:00:00+00:00")
    assert edge is not None
    assert edge["relationship_type"] == "ACTED_IN"
    assert edge["source_qid"] == "Q200"
    assert edge["target_node_qid"] == "Q100"
    assert edge["source_type"] == "Person"
    assert edge["target_type"] == "Work"
    assert edge["evidence_urls"] == ["https://example.org/source"]


def test_work_organization_statement_keeps_work_to_organization_orientation():
    row = {
        "work": {"value": "http://www.wikidata.org/entity/Q100"},
        "workLabel": {"value": "Vietnamese Film"},
        "property": {"value": "http://www.wikidata.org/entity/P272"},
        "target": {"value": "http://www.wikidata.org/entity/Q300"},
        "targetLabel": {"value": "Film Studio"},
        "referenceUrls": {"value": ""},
    }
    edge = build_credit_candidate(row, "2026-11-07T00:00:00+00:00")
    assert edge is not None
    assert edge["relationship_type"] == "PRODUCED_BY"
    assert edge["source_qid"] == "Q100"
    assert edge["target_node_qid"] == "Q300"
    assert edge["source_type"] == "Work"
    assert edge["target_type"] == "Organization"
    assert edge["evidence_urls"] == ["https://www.wikidata.org/wiki/Q100"]


def test_generic_film_crew_requires_an_explicit_role_qualifier():
    row = {
        "work": {"value": "http://www.wikidata.org/entity/Q100"},
        "workLabel": {"value": "Vietnamese Film"},
        "property": {"value": "http://www.wikidata.org/entity/P3092"},
        "target": {"value": "http://www.wikidata.org/entity/Q200"},
        "targetLabel": {"value": "Crew Member"},
        "role": {"value": "http://www.wikidata.org/entity/Q4220920"},
        "roleLabel": {"value": "film crew member"},
        "referenceUrls": {"value": "https://example.org/source"},
    }
    edge = build_credit_candidate(row, "2026-11-07T00:00:00+00:00")
    assert edge is not None
    assert edge["relationship_type"] == "OTHER_CREW_ROLE"
    assert edge["role_name"] == "film crew member"


def test_generic_film_crew_without_role_is_rejected():
    row = {
        "work": {"value": "http://www.wikidata.org/entity/Q100"},
        "workLabel": {"value": "Vietnamese Film"},
        "property": {"value": "http://www.wikidata.org/entity/P3092"},
        "target": {"value": "http://www.wikidata.org/entity/Q200"},
        "targetLabel": {"value": "Crew Member"},
        "referenceUrls": {"value": "https://example.org/source"},
    }
    assert build_credit_candidate(row, "2026-11-07T00:00:00+00:00") is None
