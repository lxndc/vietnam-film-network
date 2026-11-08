import csv
import json
from pathlib import Path

ROOT = Path.cwd()

NODE_FILE = ROOT / "data/resolution/entity_resolution_v2/canonical_nodes.jsonl"
EDGE_FILE = ROOT / "data/evidence_validation/v3/verified_edges.jsonl"
OUT = ROOT / "data/export/verified"

OUT.mkdir(parents=True, exist_ok=True)

def read_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]

def first(row, keys):
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None

def json_cell(value):
    if value is None:
        return "[]"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
        return json.dumps([value], ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)

nodes_raw = read_jsonl(NODE_FILE)
edges = read_jsonl(EDGE_FILE)

# Map all canonical nodes.
node_map = {}

for row in nodes_raw:
    node_id = first(row, [
        "node_id",
        "canonical_node_id",
        "canonical_id",
        "id",
    ])

    label = first(row, [
        "label",
        "node_type",
        "canonical_type",
        "candidate_type",
    ])

    name = first(row, [
        "canonical_name",
        "name",
        "title",
    ])

    if not node_id or label not in {
        "Person", "Work", "Organization"
    } or not name:
        raise ValueError(
            "Invalid canonical node schema. "
            f"Available fields: {list(row.keys())}"
        )

    if node_id in node_map:
        raise ValueError(f"Duplicate canonical node_id: {node_id}")

    node_map[node_id] = row

used_ids = set()

for edge in edges:
    used_ids.add(edge.get("source_id"))
    used_ids.add(edge.get("target_id"))

missing = used_ids - set(node_map)

if missing:
    raise ValueError(
        f"Edges reference {len(missing)} missing canonical nodes"
    )

node_fields = [
    "node_id", "label", "canonical_name", "aliases",
    "professions", "work_type", "release_year",
    "organization_type", "wikidata_id", "wikipedia_url",
    "verification_status", "source_count"
]

node_rows = []

for node_id in sorted(used_ids):
    row = node_map[node_id]

    node_rows.append({
        "node_id": node_id,
        "label": first(row, [
            "label", "node_type", "canonical_type", "candidate_type"
        ]),
        "canonical_name": first(row, [
            "canonical_name", "name", "title"
        ]),
        "aliases": json_cell(row.get("aliases")),
        "professions": json_cell(row.get("professions")),
        "work_type": first(row, ["work_type", "work_type_label"]) or "",
        "release_year": first(row, ["release_year", "year"]) or "",
        "organization_type": row.get("organization_type") or "",
        "wikidata_id": row.get("wikidata_id") or "",
        "wikipedia_url": row.get("wikipedia_url") or "",
        "verification_status": "scope_and_edge_approved",
        "source_count": first(row, [
            "source_count", "primary_source_count"
        ]) or 0,
    })

edge_fields = [
    "edge_id", "source_id", "target_id",
    "relationship_type", "role_name", "work_id", "work_qid",
    "property_ids", "derivation_method",
    "verification_status", "evidence_ids", "evidence_urls",
    "source_count"
]

edge_rows = []
evidence_rows = []

for edge in edges:
    evidence = edge.get("verified_evidence", [])

    if not evidence:
        raise ValueError(
            f"Verified edge without evidence: {edge.get('edge_id')}"
        )

    urls = sorted({
        item.get("source_url", "")
        for item in evidence
        if item.get("source_url")
    })

    asset_ids = sorted({
        item.get("source_asset_id", "")
        for item in evidence
        if item.get("source_asset_id")
    })

    edge_rows.append({
        "edge_id": edge["edge_id"],
        "source_id": edge["source_id"],
        "target_id": edge["target_id"],
        "relationship_type": edge["relationship_type"],
        "role_name": edge.get("role_name") or "",
        "work_id": edge.get("work_id") or "",
        "work_qid": edge.get("work_qid") or "",
        "property_ids": json_cell(edge.get("property_ids")),
        "derivation_method": edge.get("derivation_method") or "",
        "verification_status": "verified",
        "evidence_ids": json.dumps(asset_ids),
        "evidence_urls": json.dumps(urls, ensure_ascii=False),
        "source_count": len(evidence),
    })

    for item in evidence:
        evidence_rows.append({
            "edge_id": edge["edge_id"],
            "source_asset_id": item.get("source_asset_id", ""),
            "source_kind": item.get("source_kind", ""),
            "source_url": item.get("source_url", ""),
            "source_domain": item.get("source_domain", ""),
            "independence_group": item.get("independence_group", ""),
            "review_decision": "correct",
        })

def write_csv(name, fields, rows):
    path = OUT / name
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(path, len(rows), "records")

write_csv("nodes.csv", node_fields, node_rows)
write_csv("edges.csv", edge_fields, edge_rows)

write_csv(
    "edge_evidence.csv",
    [
        "edge_id", "source_asset_id", "source_kind",
        "source_url", "source_domain",
        "independence_group", "review_decision"
    ],
    evidence_rows
)

print("Core Nodes:", len(node_rows))
print("Verified Edges:", len(edge_rows))
print("Relationship Types:", len({
    x["relationship_type"] for x in edge_rows
}))
print("Graph export:", OUT)
