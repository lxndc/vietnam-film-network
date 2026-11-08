import csv
import json
import random
from pathlib import Path
from collections import defaultdict

INPUT = Path("data/evidence_validation/v3/verified_edges.jsonl")
OUTPUT = Path("data/evaluation/gold_standard_sample.csv")

SAMPLE_SIZE = 30
SEED = 42

groups = defaultdict(list)

with INPUT.open(encoding="utf-8") as f:
    for line in f:
        if line.strip():
            row = json.loads(line)
            groups[row["relationship_type"]].append(row)

random.seed(SEED)
sample = []

for relation_type, rows in sorted(groups.items()):
    selected = random.sample(rows, min(SAMPLE_SIZE, len(rows)))

    for row in selected:
        evidence = row.get("verified_evidence", [])

        sample.append({
            "edge_id": row.get("edge_id", ""),
            "source_id": row.get("source_id", ""),
            "target_id": row.get("target_id", ""),
            "relationship_type": relation_type,
            "work_qid": row.get("work_qid", ""),
            "evidence_urls": json.dumps([
                x.get("source_url", "") for x in evidence
            ], ensure_ascii=False),
            "reviewer_a": "",
            "reviewer_b": "",
            "adjudicated_label": "",
            "review_notes": "",
        })

OUTPUT.parent.mkdir(parents=True, exist_ok=True)

fields = list(sample[0].keys()) if sample else [
    "edge_id", "source_id", "target_id", "relationship_type",
    "work_qid", "evidence_urls", "reviewer_a", "reviewer_b",
    "adjudicated_label", "review_notes"
]

with OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(sample)

print("Relationship types:", len(groups))
print("Gold standard sample:", len(sample))
print("Output:", OUTPUT)
