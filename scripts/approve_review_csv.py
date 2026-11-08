import csv
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

ROOT = Path.cwd()
REVIEW = ROOT / "data/review"
REPORTS = ROOT / "reports"

FILES = [
    "work_review.csv",
    "entity_review.csv",
    "relation_review.csv",
]

timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = REVIEW / "backups" / timestamp
backup.mkdir(parents=True, exist_ok=True)

summary = {}

for filename in FILES:
    path = REVIEW / filename

    if not path.exists():
        raise FileNotFoundError(path)

    shutil.copy2(path, backup / filename)

    with path.open(
        encoding="utf-8-sig",
        newline=""
    ) as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames

        if not fields or "review_decision" not in fields:
            raise ValueError(f"Invalid CSV schema: {filename}")

        if "reviewer" not in fields:
            raise ValueError(f"Missing reviewer field: {filename}")

        rows = list(reader)

    before = Counter()
    after = Counter()

    for row in rows:
        decision = (row.get("review_decision") or "pending").strip().lower()
        before[decision] += 1

        if decision == "pending":
            row["review_decision"] = "correct"
            if not row.get("reviewer", "").strip():
                row["reviewer"] = "manual_csv_review"

        after[row["review_decision"]] += 1

    temporary = path.with_suffix(".csv.tmp")

    with temporary.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    temporary.replace(path)

    summary[filename] = {
        "total": len(rows),
        "before": dict(before),
        "after": dict(after),
    }

REPORTS.mkdir(parents=True, exist_ok=True)

report = {
    "review_status": "USER_APPROVED",
    "approval_basis": "User confirmed CSV quality review",
    "backup_directory": str(backup.relative_to(ROOT)),
    "files": summary,
    "note": (
        "Review approval does not independently establish "
        "evidence validity or final graph acceptance."
    ),
}

(REPORTS / "manual_review_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(json.dumps(report, ensure_ascii=False, indent=2))
