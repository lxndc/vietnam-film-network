from scripts.entity_resolution import build_canonical_nodes, build_resolved_edges, normalize_name


def test_same_type_qid_merges_but_different_qid_same_name_does_not():
    works = [
        {"candidate_id": "w1", "candidate_type": "Work", "canonical_name": "Phim A", "wikidata_id": "Q10", "language": "vi"},
        {"candidate_id": "w2", "candidate_type": "Work", "canonical_name": "Film A", "wikidata_id": "Q10", "language": "en"},
        {"candidate_id": "w3", "candidate_type": "Work", "canonical_name": "Phim A", "wikidata_id": "Q11", "language": "vi"},
        {"candidate_id": "w4", "candidate_type": "Work", "canonical_name": "Phim B", "wikidata_id": "", "language": "vi"},
    ]
    nodes, qid_index, candidate_map, duplicates, meta = build_canonical_nodes(works, [])
    assert len(nodes) == 3
    assert qid_index[("Work", "Q10")] == next(r["node_id"] for r in candidate_map if r["candidate_id"] == "w1")
    assert len([r for r in candidate_map if r["candidate_id"] in {"w1", "w2"}]) == 2
    assert any("w1" in group["candidate_ids"] and "w3" in group["candidate_ids"] for group in duplicates)


def test_qid_cross_type_conflict_flagged_not_merged():
    rows = [
        {"candidate_id": "w1", "candidate_type": "Work", "canonical_name": "A", "wikidata_id": "Q5"},
        {"candidate_id": "p1", "candidate_type": "Person", "canonical_name": "A", "wikidata_id": "Q5"},
    ]
    nodes, *_rest, meta = build_canonical_nodes(rows, [])
    assert len(nodes) == 2
    assert meta["qid_conflicts"] == [{"wikidata_id": "Q5", "labels": ["Person", "Work"], "decision": "manual_review_required"}]


def test_relation_resolves_endpoints_and_remains_unverified():
    works = [{"candidate_id": "w1", "candidate_type": "Work", "canonical_name": "Film", "wikidata_id": "Q100"}]
    people = [{"candidate_id": "p1", "candidate_type": "Person", "canonical_name": "Actor", "wikidata_id": "Q200"}]
    nodes, qid_index, *_ = build_canonical_nodes(works, people)
    relations = [{
        "candidate_id": "r1", "review_decision": "correct", "source_type": "Person", "target_type": "Work",
        "source_qid": "Q200", "target_qid": "Q100", "work_qid": "Q100", "relationship_type": "ACTED_IN",
        "evidence_urls": '["https://www.wikidata.org/wiki/Q100"]', "evidence_reference_urls": "[]",
        "property_id": "P161", "role_name": "Actor", "role_qid": "",
    }]
    edges, unresolved, stats = build_resolved_edges(relations, qid_index)
    assert len(edges) == 1
    assert not unresolved
    assert edges[0]["verification_status"] == "needs_evidence_validation"
    assert stats["candidates_without_statement_reference_urls"] == 1


def test_name_normalization_is_only_a_collision_signal():
    assert normalize_name("Đạo diễn A!") == normalize_name("dao dien a")
