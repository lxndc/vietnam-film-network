import csv
import json
from pathlib import Path
from collections import Counter

ROOT = Path.cwd()

BASE = ROOT / "data"
RES = BASE / "resolution/entity_resolution_v2"
DEDUP = BASE / "evidence_validation/v3_source_dedup"
SCOPE = BASE / "evidence_validation/v3_scope/work_scope_audit.csv"
GAP = BASE / "evidence_validation/v2/edge_source_gap_queue.csv"

OUT = BASE / "evidence_validation/v3"
REPORT = ROOT / "reports/verified_dataset_report.json"

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def read_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]

def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

def yes(value):
    return str(value).strip().lower() in {"yes", "true", "1"}

def correct(value):
    return str(value).strip().lower() == "correct"

OUT.mkdir(parents=True, exist_ok=True)

nodes = read_jsonl(RES / "canonical_nodes.jsonl")
edges = read_jsonl(RES / "resolved_edge_candidates.jsonl")

scopes = {
    r["work_qid"]: r["scope_decision"].strip()
    for r in read_csv(SCOPE)
}

assets = {
    r["source_asset_id"]: r
    for r in read_csv(DEDUP / "source_assets.csv")
}

supports = read_csv(
    DEDUP / "edge_source_support_review.csv"
)

gaps = read_csv(GAP)

node_ids = set()

for node in nodes:
    node_id = (
        node.get("node_id")
        or node.get("canonical_node_id")
        or node.get("canonical_id")
    )
    if node_id:
        node_ids.add(node_id)

evidence_by_edge = {}
for row in supports:
    aid = row.get("source_asset_id", "")
    asset = assets.get(aid, {})

    if not (
        correct(row.get("review_decision"))
        and yes(row.get("supports_exact_edge"))
        and correct(asset.get("asset_review_decision"))
        and yes(asset.get("source_accessible"))
    ):
        continue

    evidence = {
        "source_asset_id": aid,
        "source_kind": asset.get("source_kind", ""),
        "source_url": asset.get("canonical_locator", ""),
        "source_domain": asset.get("source_domain", ""),
        "independence_group": asset.get("independence_group", ""),
        "statement_id": row.get("statement_ids", ""),
        "review_decision": "correct",
    }

    evidence_by_edge.setdefault(row["edge_id"], []).append(evidence)

# Evidence added for edges that previously had no P854/P248 source.
for row in gaps:
    url = (row.get("supplemental_source_url") or "").strip()

    if not (
        url
        and yes(row.get("source_accessible"))
        and yes(row.get("supports_exact_edge"))
        and correct(row.get("review_decision"))
    ):
        continue

    evidence = {
        "source_asset_id": "",
        "source_kind": row.get("supplemental_source_type", ""),
        "source_url": url,
        "source_domain": "",
        "independence_group": row.get("independence_group", ""),
        "statement_id": "",
        "source_title": row.get("supplemental_source_title", ""),
        "review_decision": "correct",
    }

    evidence_by_edge.setdefault(row["edge_id"], []).append(evidence)

verified = []
needs_review = []
excluded = []

for edge in edges:
    edge_id = edge.get("edge_id", "")
    work_qid = edge.get("work_qid", "")
    scope = scopes.get(work_qid, "scope_uncertain")

    source_id = edge.get("source_id", "")
    target_id = edge.get("target_id", "")

    valid_endpoints = (
        source_id in node_ids and target_id in node_ids
    )

    evidence = evidence_by_edge.get(edge_id, [])

    output = dict(edge)
    output["scope_decision"] = scope
    output["verified_evidence"] = evidence
    output["verified_evidence_count"] = len(evidence)

    if scope == "exclude_foreign":
        output["verification_status"] = "out_of_scope"
        excluded.append(output)

    elif (
        scope in {"include_vietnam", "include_coproduction"}
        and valid_endpoints
        and len(evidence) >= 1
    ):
        output["verification_status"] = "verified"
        verified.append(output)

    else:
        output["verification_status"] = "needs_review"
        output["review_reason"] = (
            "invalid_endpoint" if not valid_endpoints
            else "missing_scope_approval" if scope not in {
                "include_vietnam", "include_coproduction"
            }
            else "insufficient_evidence"
        )
        needs_review.append(output)

write_jsonl(OUT / "verified_edges.jsonl", verified)
write_jsonl(OUT / "needs_review_edges.jsonl", needs_review)
write_jsonl(OUT / "excluded_edges.jsonl", excluded)

report = {
    "stage": "verified_dataset_v1",
    "input_edges": len(edges),
    "verified_edges": len(verified),
    "needs_review_edges": len(needs_review),
    "excluded_out_of_scope_edges": len(excluded),
    "verified_edges_by_type": dict(Counter(
        x["relationship_type"] for x in verified
    )),
    "verified_edges_with_evidence": sum(
        bool(x["verified_evidence"]) for x in verified
    ),
    "core_nodes_referenced_by_verified_edges": len({
        endpoint
        for edge in verified
        for endpoint in (edge["source_id"], edge["target_id"])
    }),
    "important": [
        "Only scope-approved edges with exact source support are verified.",
        "At least one reviewed evidence item is required.",
        "This script does not independently assess source credibility.",
        "Gold-standard precision evaluation remains mandatory.",
    ],
}

REPORT.write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, ensure_ascii=False, indent=2))
