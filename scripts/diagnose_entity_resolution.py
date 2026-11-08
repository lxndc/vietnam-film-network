import csv
import json
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path.cwd()
REVIEW = ROOT / "data/review"
RESOLUTION = ROOT / "data/resolution"
REPORTS = ROOT / "reports"

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

# 1. QID conflicts
nodes = (
    read_csv(REVIEW / "work_review.csv")
    + read_csv(REVIEW / "entity_review.csv")
)

qid_groups = defaultdict(list)

for row in nodes:
    qid = (row.get("wikidata_id") or "").strip().upper()
    label = (row.get("candidate_type") or "").strip()

    if qid.startswith("Q") and label:
        qid_groups[qid].append(row)

conflicts = {
    qid: rows
    for qid, rows in qid_groups.items()
    if len({r.get("candidate_type") for r in rows}) > 1
}

fields = [
    "wikidata_id",
    "candidate_type",
    "candidate_id",
    "canonical_name",
    "aliases",
    "wikipedia_url",
    "wikidata_url",
]

details = []

for qid, rows in sorted(conflicts.items()):
    for row in rows:
        details.append({
            field: row.get(field, "")
            for field in fields
        })

with (RESOLUTION / "qid_type_conflict_details.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(details)

# 2. Unresolved relations
unresolved = read_csv(
    RESOLUTION / "unresolved_edge_candidates.csv"
)

reason_counts = Counter()
relationship_counts = Counter()

for row in unresolved:
    relationship_counts[
        row.get("relationship_type") or "UNKNOWN"
    ] += 1

    for reason in (row.get("reason") or "").split(";"):
        if reason:
            reason_counts[reason.split(":")[0]] += 1

# 3. Reference coverage
relations = read_csv(REVIEW / "relation_review.csv")

with_references = 0

for row in relations:
    raw = row.get("evidence_reference_urls", "")

    try:
        value = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        value = [raw] if raw else []

    if isinstance(value, list) and any(value):
        with_references += 1

report = {
    "qid_conflicts": len(conflicts),
    "qid_conflict_candidate_rows": len(details),
    "unresolved_relations": len(unresolved),
    "unresolved_reason_counts": dict(reason_counts),
    "unresolved_relationship_counts": dict(relationship_counts),
    "reference_coverage": {
        "total": len(relations),
        "with_references": with_references,
        "without_references": len(relations) - with_references
    }
}

(REPORTS / "entity_resolution_diagnostic.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, ensure_ascii=False, indent=2))
