import csv
import json
from pathlib import Path
from collections import defaultdict, Counter

INPUT = Path("data/evidence_validation/v2/source_review_queue.csv")
OUT = Path("data/evidence_validation/v2/reused_source_edge_audit.csv")
SUMMARY = Path("reports/reused_source_audit_report.json")

groups = defaultdict(list)

with INPUT.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        key = (
            row.get("source_kind", ""),
            row.get("source_locator", "").strip()
        )
        groups[key].append(row)

# Chỉ xuất nguồn được sử dụng bởi ít nhất 10 Edge khác nhau.
output = []

for (kind, locator), rows in groups.items():
    edge_ids = sorted({
        r.get("edge_id", "")
        for r in rows if r.get("edge_id")
    })

    if len(edge_ids) < 10:
        continue

    for row in rows:
        output.append({
            "source_kind": kind,
            "source_locator": locator,
            "edge_id": row.get("edge_id", ""),
            "relationship_type": row.get("relationship_type", ""),
            "work_qid": row.get("work_qid", ""),
            "target_qid": row.get("target_qid", ""),
            "property_id": row.get("property_id", ""),
            "source_title": row.get("source_title", "")
        })

fields = [
    "source_kind",
    "source_locator",
    "edge_id",
    "relationship_type",
    "work_qid",
    "target_qid",
    "property_id",
    "source_title"
]

with OUT.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(output)

report = {
    "total_source_tasks": sum(map(len, groups.values())),
    "unique_source_assets": len(groups),
    "sources_reused_10_or_more_edges": sum(
        len({r.get("edge_id") for r in rows}) >= 10
        for rows in groups.values()
    ),
    "source_types": dict(Counter(
        kind for kind, locator in groups
    )),
    "output": str(OUT)
}

SUMMARY.write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, ensure_ascii=False, indent=2))
