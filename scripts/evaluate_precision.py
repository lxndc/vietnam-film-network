import csv
import json
from pathlib import Path
from collections import defaultdict

path = Path("data/evaluation/gold_standard_sample.csv")

with path.open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

groups = defaultdict(lambda: {
    "correct": 0,
    "incorrect": 0,
    "uncertain": 0,
    "pending": 0,
})

for row in rows:
    decision = (
        row.get("adjudicated_label")
        or ""
    ).strip().lower()

    if not decision:
        decision = "pending"

    if decision not in {
        "correct", "incorrect", "uncertain", "pending"
    }:
        raise ValueError(f"Invalid label: {decision}")

    groups[row["relationship_type"]][decision] += 1

total = {
    "correct": 0,
    "incorrect": 0,
    "uncertain": 0,
    "pending": 0,
}

for values in groups.values():
    for key in total:
        total[key] += values[key]

denominator = total["correct"] + total["incorrect"]

precision = (
    total["correct"] / denominator * 100
    if denominator else None
)

report = {
    "sample_size": len(rows),
    "overall": total,
    "edge_precision_percent": precision,
    "target_percent_exclusive_minimum": 90,
    "acceptance": (
        precision is not None
        and precision > 90
        and total["pending"] == 0
        and total["uncertain"] == 0
    ),
    "by_relationship_type": {}
}

for relation_type, counts in groups.items():
    n = counts["correct"] + counts["incorrect"]
    report["by_relationship_type"][relation_type] = {
        **counts,
        "precision_percent": (
            counts["correct"] / n * 100 if n else None
        )
    }

Path("reports").mkdir(exist_ok=True)
Path("reports/evaluation_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, ensure_ascii=False, indent=2))
