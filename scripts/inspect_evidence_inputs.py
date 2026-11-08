import csv
import json
from pathlib import Path

ROOT = Path(".")

FILES = {
    "resolved_edges": (
        ROOT / "data/resolution/entity_resolution_v2/"
        / "resolved_edge_candidates.jsonl"
    ),
    "relation_review": (
        ROOT / "data/review/relation_review.csv"
    ),
}

def inspect_jsonl(path):
    print(f"\n===== {path} =====")

    count = 0

    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            count += 1

            if count <= 3:
                print(f"\nRecord {count}:")
                print(json.dumps(
                    row,
                    ensure_ascii=False,
                    indent=2,
                    default=str
                )[:3500])

    print("\nTotal records:", count)

def inspect_csv(path):
    print(f"\n===== {path} =====")

    with path.open(
        encoding="utf-8-sig",
        newline=""
    ) as f:
        reader = csv.DictReader(f)

        print("Columns:")
        print(reader.fieldnames)

        for index, row in enumerate(reader):
            if index >= 3:
                break

            selected = {
                key: value
                for key, value in row.items()
                if any(term in key.lower() for term in [
                    "evidence",
                    "reference",
                    "url",
                    "source",
                    "qid",
                    "relationship",
                    "work"
                ])
            }

            print(f"\nRecord {index + 1}:")
            print(json.dumps(
                selected,
                ensure_ascii=False,
                indent=2
            ))

inspect_jsonl(FILES["resolved_edges"])
inspect_csv(FILES["relation_review"])
