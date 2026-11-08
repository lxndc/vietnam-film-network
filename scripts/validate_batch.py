from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from collectors.common import load_settings, read_jsonl

ROOT = Path(__file__).resolve().parents[1]


def duplicate_count(rows: list[dict], key: str) -> int:
    values = [row.get(key) for row in rows]
    return len(values) - len(set(values))


def main() -> None:
    settings = load_settings(ROOT)
    processed = ROOT / settings["paths"]["processed"]
    reports = ROOT / settings["paths"]["reports"]
    works = read_jsonl(processed / "work_candidates.jsonl")
    entities = read_jsonl(processed / "entity_candidates.jsonl")
    relations = read_jsonl(processed / "relation_candidates.jsonl")

    types = Counter(row.get("relationship_type", "UNKNOWN") for row in relations)
    settings_targets = settings.get("targets", {})
    populated_types = sum(1 for count in types.values() if count > 0)
    invalid_relations = [
        row for row in relations
        if not row.get("source_qid") or not row.get("target_qid") or not row.get("relationship_type")
    ]
    report = {
        "work_candidates": len(works),
        "person_organization_candidates": len(entities),
        "relation_candidates": len(relations),
        "relationship_candidate_counts": dict(types),
        "populated_relationship_candidate_types": populated_types,
        "target_candidate_core_nodes": settings_targets.get("core_nodes", 4000),
        "target_candidate_edges": settings_targets.get("valid_edges", 10000),
        "target_populated_relationship_types": settings_targets.get("populated_relationship_types", 20),
        "candidate_relation_type_target_met": populated_types >= int(settings_targets.get("populated_relationship_types", 20)),
        "duplicate_work_candidate_ids": duplicate_count(works, "candidate_id"),
        "duplicate_entity_candidate_ids": duplicate_count(entities, "candidate_id"),
        "duplicate_relation_candidate_ids": duplicate_count(relations, "candidate_id"),
        "relations_missing_endpoint_or_type": len(invalid_relations),
        "verified_nodes": 0,
        "verified_edges": 0,
        "acceptance_status": "NOT VERIFIED",
        "note": "Candidate totals and populated candidate relationship types are not verified Core Nodes or valid Edges. Acceptance requires manual review, evidence checks, entity resolution and graph import.",
    }
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "batch_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["relations_missing_endpoint_or_type"]:
        raise SystemExit("Batch có relation candidate thiếu endpoint hoặc relationship_type.")


if __name__ == "__main__":
    main()
