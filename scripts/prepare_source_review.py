#!/usr/bin/env python3
"""
Prepare human source-review queues from Evidence Validation v1.

Inputs:
  data/evidence_validation/v2/source_inventory.csv
  data/evidence_validation/v1/edge_evidence_status.csv

Outputs:
  data/evidence_validation/v2/source_review_queue.csv
  data/evidence_validation/v2/edge_source_gap_queue.csv
  data/evidence_validation/v2/import_provenance_only.csv
  reports/source_review_queue_report.json

This script does not fetch pages and never marks an edge verified.
"""

import ast
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path.cwd()
INVENTORY = ROOT / "data/evidence_validation/v2/source_inventory.csv"
EDGE_STATUS = ROOT / "data/evidence_validation/v1/edge_evidence_status.csv"
OUT = ROOT / "data/evidence_validation/v2"
REPORTS = ROOT / "reports"

def parse_list(value):
    if not value:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    for parser in (json.loads, ast.literal_eval):
        try:
            result = parser(raw)
            if isinstance(result, list):
                return result
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
    return [raw]

def unique_strings(values):
    result, seen = [], set()
    for value in values:
        if value is None or isinstance(value, (dict, list)):
            continue
        item = str(value).strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result

def domain_of(locator):
    try:
        host = (urlparse(locator).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""

def stable_id(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:24]

def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required input missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    inventory_rows = read_csv(INVENTORY)
    edge_rows = read_csv(EDGE_STATUS)
    edge_meta = {row.get("edge_id", ""): row for row in edge_rows}

    queue_fields = [
        "review_item_id", "edge_id", "relationship_type", "work_qid",
        "property_id", "statement_id", "target_qid", "reference_index",
        "edge_evidence_status",
        "source_kind", "source_locator", "source_domain", "source_title",
        "publication_date", "source_accessible", "supports_relationship",
        "review_decision", "reviewer", "review_notes"
    ]
    queue = []
    provenance = []
    covered_edges = set()
    p854_records = 0
    p248_records = 0

    for row in inventory_rows:
        edge_id = row.get("edge_id", "")
        urls = unique_strings(parse_list(row.get("source_urls")))
        stated_in = unique_strings(parse_list(row.get("stated_in_qids")))
        titles = unique_strings(parse_list(row.get("source_titles")))
        dates = unique_strings(parse_list(row.get("publication_dates")))
        imported = unique_strings(parse_list(row.get("imported_from_qids")))
        ref_index = row.get("reference_index", "")

        for i, url in enumerate(urls):
            title = titles[min(i, len(titles) - 1)] if titles else ""
            date = dates[min(i, len(dates) - 1)] if dates else ""
            queue.append({
                "review_item_id": stable_id(edge_id, ref_index, "P854", url),
                "edge_id": edge_id,
                "relationship_type": edge_meta.get(edge_id, {}).get("relationship_type", ""),
                "work_qid": row.get("work_qid", ""),
                "edge_evidence_status": edge_meta.get(edge_id, {}).get("evidence_status", ""),
                "property_id": row.get("property_id", ""),
                "statement_id": row.get("statement_id", ""),
                "target_qid": row.get("target_qid", ""),
                "reference_index": ref_index,
                "source_kind": "P854_reference_url",
                "source_locator": url,
                "source_domain": domain_of(url),
                "source_title": title,
                "publication_date": date,
                "source_accessible": "pending",
                "supports_relationship": "pending",
                "review_decision": "pending",
                "reviewer": "",
                "review_notes": "",
            })
            covered_edges.add(edge_id)
            p854_records += 1

        for i, qid in enumerate(stated_in):
            title = titles[min(i, len(titles) - 1)] if titles else ""
            date = dates[min(i, len(dates) - 1)] if dates else ""
            locator = f"https://www.wikidata.org/wiki/{qid}"
            queue.append({
                "review_item_id": stable_id(edge_id, ref_index, "P248", qid),
                "edge_id": edge_id,
                "relationship_type": edge_meta.get(edge_id, {}).get("relationship_type", ""),
                "work_qid": row.get("work_qid", ""),
                "edge_evidence_status": edge_meta.get(edge_id, {}).get("evidence_status", ""),
                "property_id": row.get("property_id", ""),
                "statement_id": row.get("statement_id", ""),
                "target_qid": row.get("target_qid", ""),
                "reference_index": ref_index,
                "source_kind": "P248_publication_item",
                "source_locator": locator,
                "source_domain": "wikidata.org",
                "source_title": title,
                "publication_date": date,
                "source_accessible": "pending",
                "supports_relationship": "pending",
                "review_decision": "pending",
                "reviewer": "",
                "review_notes": "Resolve publication item to its actual publication/source; item URL alone is not proof.",
            })
            covered_edges.add(edge_id)
            p248_records += 1

        if imported:
            provenance.append({
                "edge_id": edge_id,
                "work_qid": row.get("work_qid", ""),
                "property_id": row.get("property_id", ""),
                "statement_id": row.get("statement_id", ""),
                "imported_from_qids": json.dumps(imported, ensure_ascii=False),
                "note": "P143 provenance only; do not count as independent evidence.",
            })

    # Avoid suggesting an edge is covered merely because a P143 provenance exists.
    source_supported_edges = set()
    for item in queue:
        source_supported_edges.add(item["edge_id"])

    gap_fields = [
        "edge_id", "relationship_type", "work_qid", "candidate_count",
        "statement_match_count", "evidence_status", "statement_ids",
        "source_urls", "gap_reason", "review_decision", "reviewer",
        "review_notes"
    ]
    gaps = []
    for row in edge_rows:
        edge_id = row.get("edge_id", "")
        status = row.get("evidence_status", "")
        if edge_id not in source_supported_edges:
            gaps.append({
                "edge_id": edge_id,
                "relationship_type": edge_meta.get(edge_id, {}).get("relationship_type", ""),
                "work_qid": row.get("work_qid", ""),
                "candidate_count": row.get("candidate_count", ""),
                "statement_match_count": row.get("statement_match_count", ""),
                "evidence_status": status,
                "statement_ids": row.get("statement_ids", ""),
                "source_urls": row.get("source_urls", ""),
                "gap_reason": (
                    "No P854 URL or P248 publication item in extracted reference inventory; "
                    "find independent source or retain needs_review."
                ),
                "review_decision": "pending",
                "reviewer": "",
                "review_notes": "",
            })

    write_csv(OUT / "source_review_queue.csv", queue_fields, queue)
    write_csv(OUT / "edge_source_gap_queue.csv", gap_fields, gaps)
    write_csv(
        OUT / "import_provenance_only.csv",
        ["edge_id", "work_qid", "property_id", "statement_id",
         "imported_from_qids", "note"],
        provenance,
    )

    report = {
        "stage": "source_review_queue_v1",
        "inventory_reference_rows": len(inventory_rows),
        "edge_status_rows": len(edge_rows),
        "source_review_tasks": len(queue),
        "p854_url_tasks": p854_records,
        "p248_publication_item_tasks": p248_records,
        "unique_edges_with_p854_or_p248": len(source_supported_edges),
        "edges_requiring_independent_source_search": len(gaps),
        "p143_provenance_records": len(provenance),
        "outputs": {
            "source_review_queue": str(OUT / "source_review_queue.csv"),
            "edge_source_gap_queue": str(OUT / "edge_source_gap_queue.csv"),
            "import_provenance_only": str(OUT / "import_provenance_only.csv"),
        },
        "important": [
            "All review decisions start as pending.",
            "A P854 URL must be opened and checked for support of the exact edge.",
            "A P248 item must be resolved to the actual publication and checked.",
            "P143 is provenance only and is not counted as independent evidence.",
            "An edge with no P854/P248 is queued for independent source search.",
            "No edge is marked verified by this script.",
        ],
    }
    (REPORTS / "source_review_queue_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
