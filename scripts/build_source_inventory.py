#!/usr/bin/env python3
"""
Build a normalized source inventory from Evidence Validation v1.

Reads:
  data/evidence_validation/v1/evidence_references.csv

Writes:
  data/evidence_validation/v2/source_inventory.csv
  data/evidence_validation/v2/source_domain_summary.csv
  reports/source_inventory_report.json

The script accepts both JSON strings and Python literal representations
found in legacy CSV cells. It does not fetch URLs or mark any edge verified.
"""

import ast
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path.cwd()
INPUT = ROOT / "data/evidence_validation/v1/evidence_references.csv"
OUT_DIR = ROOT / "data/evidence_validation/v2"
REPORT_DIR = ROOT / "reports"

def parse_struct(value, expected_type=None):
    if value is None:
        return [] if expected_type is list else {}
    raw = str(value).strip()
    if not raw:
        return [] if expected_type is list else {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
            if expected_type is None or isinstance(parsed, expected_type):
                return parsed
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            pass
    return [] if expected_type is list else {}

def as_list(value):
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    return [value]

def unique_strings(values):
    result = []
    seen = set()
    for value in values:
        if isinstance(value, dict):
            continue
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result

def get_domain(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except ValueError:
        return ""

def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    inventory_fields = [
        "edge_id",
        "work_qid",
        "property_id",
        "statement_id",
        "target_qid",
        "reference_index",
        "source_urls",
        "source_domains",
        "stated_in_qids",
        "imported_from_qids",
        "source_titles",
        "publication_dates",
        "has_p854_url",
        "has_p248_stated_in",
        "has_p143_imported_from",
        "reference_fields_raw",
    ]

    domain_counts = Counter()
    stated_in_counts = Counter()
    imported_from_counts = Counter()
    source_title_counts = Counter()

    total_rows = 0
    rows_with_urls = 0
    rows_with_stated_in = 0
    rows_with_imported_from = 0
    rows_with_any_source_marker = 0
    parse_warnings = 0
    output_rows = []

    with INPUT.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"edge_id", "work_qid", "property_id", "statement_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        for row in reader:
            total_rows += 1

            nested = parse_struct(row.get("reference_fields"), dict)
            if row.get("reference_fields") and not nested:
                parse_warnings += 1

            urls = unique_strings(
                as_list(parse_struct(row.get("reference_urls"), list))
                + as_list(nested.get("reference_url"))
            )
            stated_in = unique_strings(
                as_list(parse_struct(row.get("stated_in_qids"), list))
                + as_list(nested.get("stated_in_qid"))
            )
            imported_from = unique_strings(
                as_list(parse_struct(row.get("imported_from_qids"), list))
                + as_list(nested.get("imported_from_qid"))
            )
            titles = unique_strings(as_list(nested.get("source_title")))

            pub_dates = []
            for date_item in as_list(nested.get("publication_date")):
                if isinstance(date_item, dict):
                    pub_dates.append(str(date_item.get("time", "")))
                else:
                    pub_dates.append(str(date_item))
            pub_dates = unique_strings(pub_dates)

            domains = unique_strings([get_domain(url) for url in urls])
            domains = [d for d in domains if d]

            has_url = bool(urls)
            has_stated_in = bool(stated_in)
            has_imported_from = bool(imported_from)

            rows_with_urls += int(has_url)
            rows_with_stated_in += int(has_stated_in)
            rows_with_imported_from += int(has_imported_from)
            rows_with_any_source_marker += int(
                has_url or has_stated_in or has_imported_from
            )

            for domain in domains:
                domain_counts[domain] += 1
            for qid in stated_in:
                stated_in_counts[qid] += 1
            for qid in imported_from:
                imported_from_counts[qid] += 1
            for title in titles:
                source_title_counts[title] += 1

            output_rows.append({
                "edge_id": row.get("edge_id", ""),
                "work_qid": row.get("work_qid", ""),
                "property_id": row.get("property_id", ""),
                "statement_id": row.get("statement_id", ""),
                "target_qid": row.get("target_qid", ""),
                "reference_index": row.get("reference_index", ""),
                "source_urls": json.dumps(urls, ensure_ascii=False),
                "source_domains": json.dumps(domains, ensure_ascii=False),
                "stated_in_qids": json.dumps(stated_in, ensure_ascii=False),
                "imported_from_qids": json.dumps(imported_from, ensure_ascii=False),
                "source_titles": json.dumps(titles, ensure_ascii=False),
                "publication_dates": json.dumps(pub_dates, ensure_ascii=False),
                "has_p854_url": has_url,
                "has_p248_stated_in": has_stated_in,
                "has_p143_imported_from": has_imported_from,
                "reference_fields_raw": row.get("reference_fields", ""),
            })

    inventory_path = OUT_DIR / "source_inventory.csv"
    with inventory_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=inventory_fields)
        writer.writeheader()
        writer.writerows(output_rows)

    domain_path = OUT_DIR / "source_domain_summary.csv"
    with domain_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["domain", "reference_record_count"])
        for domain, count in domain_counts.most_common():
            writer.writerow([domain, count])

    report = {
        "stage": "source_inventory_v1",
        "input": str(INPUT),
        "total_reference_records": total_rows,
        "records_with_p854_urls": rows_with_urls,
        "records_with_p248_stated_in": rows_with_stated_in,
        "records_with_p143_imported_from": rows_with_imported_from,
        "records_with_any_source_marker": rows_with_any_source_marker,
        "rows_with_no_source_marker": total_rows - rows_with_any_source_marker,
        "reference_fields_parse_warnings": parse_warnings,
        "unique_domains": len(domain_counts),
        "top_domains": [
            {"domain": domain, "reference_record_count": count}
            for domain, count in domain_counts.most_common(20)
        ],
        "top_stated_in_qids": [
            {"qid": qid, "reference_record_count": count}
            for qid, count in stated_in_counts.most_common(20)
        ],
        "top_imported_from_qids": [
            {"qid": qid, "reference_record_count": count}
            for qid, count in imported_from_counts.most_common(20)
        ],
        "top_source_titles": [
            {"title": title, "reference_record_count": count}
            for title, count in source_title_counts.most_common(20)
        ],
        "outputs": {
            "source_inventory": str(inventory_path),
            "source_domain_summary": str(domain_path),
        },
        "important": [
            "This is an inventory only; it does not fetch source pages.",
            "URL availability is not proof that a source supports an edge.",
            "P248 stated-in references and P854 URLs are kept distinct.",
            "P143 imported-from references are not treated as independent evidence.",
            "No edge is marked verified by this script.",
        ],
    }

    report_path = REPORT_DIR / "source_inventory_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
