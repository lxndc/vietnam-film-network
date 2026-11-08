from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from collectors.common import load_settings, read_jsonl

ROOT = Path(__file__).resolve().parents[1]
REVIEW_FIELDS = {
    "review_decision": "pending",
    "review_notes": "",
    "reviewer": "",
}


def csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def load_previous(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            row["candidate_id"]: row
            for row in csv.DictReader(handle)
            if row.get("candidate_id")
        }


def write_review_csv(path: Path, rows: list[dict], key: str = "candidate_id") -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = load_previous(path)
    columns = sorted({field for row in rows for field in row})
    columns = [key] + [column for column in columns if column != key]
    for field in REVIEW_FIELDS:
        if field not in columns:
            columns.append(field)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for source_row in rows:
            candidate_id = str(source_row.get(key, ""))
            old_row = previous.get(candidate_id, {})
            row = {field: csv_value(value) for field, value in source_row.items()}
            for field, default in REVIEW_FIELDS.items():
                row[field] = old_row.get(field, default)
            writer.writerow(row)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export unverified candidate JSONL files to human-review CSV queues."
    )
    parser.add_argument(
        "--output-dir", default="data/review", help="Review output directory relative to project root."
    )
    args = parser.parse_args()

    settings = load_settings(ROOT)
    processed = ROOT / settings["paths"]["processed"]
    output_dir = ROOT / args.output_dir

    datasets = {
        "work_candidates.jsonl": "work_review.csv",
        "entity_candidates.jsonl": "entity_review.csv",
        "relation_candidates.jsonl": "relation_review.csv",
    }
    summary: dict[str, int] = {}
    for input_name, output_name in datasets.items():
        source_path = processed / input_name
        if not source_path.exists():
            raise FileNotFoundError(f"Missing candidate file: {source_path}")
        rows = read_jsonl(source_path)
        output_path = output_dir / output_name
        summary[output_name] = write_review_csv(output_path, rows)
        print(f"{output_path.relative_to(ROOT)}: {len(rows)} rows")

    print(json.dumps({"review_rows": summary}, ensure_ascii=False, indent=2))
    print("Review fields: review_decision=pending|correct|incorrect|uncertain; review_notes; reviewer")
    print("Existing review decisions and notes are preserved when this script is run again.")


if __name__ == "__main__":
    main()
