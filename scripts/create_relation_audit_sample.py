import csv
import random
from collections import defaultdict
from pathlib import Path

SOURCE = Path("data/review/relation_review.csv")
OUTPUT = Path("data/review/relation_audit_sample.csv")

SAMPLE_SIZE = 30
RANDOM_SEED = 42

random.seed(RANDOM_SEED)

groups = defaultdict(list)

with SOURCE.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as file:
    reader = csv.DictReader(file)
    fieldnames = reader.fieldnames

    if not fieldnames or "relationship_type" not in fieldnames:
        raise ValueError(
            "Missing relationship_type column"
        )

    for row in reader:
        groups[row["relationship_type"]].append(row)

selected = []

for relationship_type, rows in sorted(groups.items()):
    sample = random.sample(
        rows,
        min(SAMPLE_SIZE, len(rows))
    )

    for row in sample:
        row["audit_group"] = relationship_type
        selected.append(row)

output_fields = list(fieldnames) + ["audit_group"]

with OUTPUT.open(
    "w",
    encoding="utf-8-sig",
    newline=""
) as file:
    writer = csv.DictWriter(
        file,
        fieldnames=output_fields
    )
    writer.writeheader()
    writer.writerows(selected)

print(f"Relationship types: {len(groups)}")
print(f"Audit records: {len(selected)}")
print(f"Output: {OUTPUT}")
