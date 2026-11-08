#!/usr/bin/env python3
"""Safely classify conflicting Wikidata QIDs and create review copies.

Reads:
  data/resolution/qid_type_conflict_details.csv
  data/review/work_review.csv
  data/review/entity_review.csv

Writes (without modifying inputs):
  data/resolution/type_resolved_review/work_review.csv
  data/resolution/type_resolved_review/entity_review.csv
  data/resolution/type_resolved_review/qid_type_decisions.csv
  data/resolution/type_resolved_review/qid_type_quarantine.csv
  reports/qid_type_resolution_report.json

Automatic type rules use Wikidata P31 plus transitive P279:
  Person       -> human (Q5)
  Work         -> film (Q11424), television series (Q5398426),
                  television film (Q506240)
  Organization -> organization (Q43229)

Only a unique class match is auto-applied. No match or multiple type matches
are quarantined for manual review. Original CSV files are never overwritten.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import requests

ROOT = Path.cwd()
REVIEW_DIR = ROOT / "data" / "review"
RESOLUTION_DIR = ROOT / "data" / "resolution"
OUTPUT_DIR = RESOLUTION_DIR / "type_resolved_review"
REPORT_DIR = ROOT / "reports"
CONFLICT_FILE = RESOLUTION_DIR / "qid_type_conflict_details.csv"
WDQS_URL = "https://query.wikidata.org/sparql"
USER_AGENT = os.getenv(
    "WIKIDATA_USER_AGENT",
    "VietnamFilmNetwork/1.0 (academic research; contact: configure-contact-email)"
)
BATCH_SIZE = 25
PAUSE_SECONDS = 1.2
MAX_RETRIES = 4

TYPE_ROOTS = {
    "Person": ["Q5"],
    "Work": ["Q11424", "Q5398426", "Q506240"],
    "Organization": ["Q43229"],
}


def read_csv(path: Path) -> Tuple[List[str], List[dict]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def write_csv(path: Path, fieldnames: List[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_type(value: str) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "person": "Person",
        "people": "Person",
        "human": "Person",
        "work": "Work",
        "film": "Work",
        "movie": "Work",
        "television_series": "Work",
        "television series": "Work",
        "organization": "Organization",
        "organisation": "Organization",
        "company": "Organization",
    }
    return mapping.get(raw, (value or "").strip())


def extract_qids_from_conflicts(rows: List[dict]) -> List[str]:
    qids = set()
    for row in rows:
        qid = (row.get("wikidata_id") or "").strip().upper()
        if re.fullmatch(r"Q[1-9][0-9]*", qid):
            qids.add(qid)
    return sorted(qids)


def build_query(qids: List[str]) -> str:
    values = " ".join(f"wd:{qid}" for qid in qids)
    branches = []
    for label, roots in TYPE_ROOTS.items():
        for root in roots:
            branches.append(
                "{ ?item wdt:P31/wdt:P279* wd:%s . BIND(\"%s\" AS ?kind) }"
                % (root, label)
            )
    return """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT DISTINCT ?item ?kind WHERE {
  VALUES ?item { %s }
  %s
}
""" % (values, " UNION ".join(branches))


def query_wikidata(qids: List[str]) -> Dict[str, set]:
    """Return QID -> set of matching project node labels."""
    matches: Dict[str, set] = defaultdict(set)
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    })

    chunks = [qids[i:i + BATCH_SIZE] for i in range(0, len(qids), BATCH_SIZE)]
    for index, chunk in enumerate(chunks, start=1):
        query = build_query(chunk)
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = session.get(
                    WDQS_URL,
                    params={"query": query, "format": "json"},
                    timeout=(20, 90),
                )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = RuntimeError(
                        f"WDQS returned HTTP {response.status_code}"
                    )
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else (2 ** attempt) * 3
                    except ValueError:
                        delay = (2 ** attempt) * 3
                    time.sleep(min(delay, 60))
                    continue
                response.raise_for_status()
                payload = response.json()
                for binding in payload.get("results", {}).get("bindings", []):
                    uri = binding.get("item", {}).get("value", "")
                    kind = binding.get("kind", {}).get("value", "")
                    qid = uri.rsplit("/", 1)[-1]
                    if qid in chunk and kind in TYPE_ROOTS:
                        matches[qid].add(kind)
                last_error = None
                break
            except Exception as exc:  # retry transient network/API errors
                last_error = exc
                time.sleep(min((2 ** attempt) * 2, 30))
        if last_error is not None:
            raise RuntimeError(
                f"WDQS request failed for batch {index}/{len(chunks)}: {last_error}"
            )
        print(f"Wikidata type lookup: batch {index}/{len(chunks)}", flush=True)
        if index < len(chunks):
            time.sleep(PAUSE_SECONDS)
    return matches


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    conflict_fields, conflict_rows = read_csv(CONFLICT_FILE)
    qids = extract_qids_from_conflicts(conflict_rows)
    if not qids:
        raise ValueError("No valid Wikidata QIDs found in conflict details")

    print(f"Unique conflicting QIDs: {len(qids)}")
    matches = query_wikidata(qids)

    # Make one decision per QID. Ambiguous or unsupported classes are held.
    decisions = {}
    for qid in qids:
        kinds = sorted(matches.get(qid, set()))
        if len(kinds) == 1:
            decisions[qid] = {
                "suggested_type": kinds[0],
                "status": "AUTO_RESOLVED_BY_WIKIDATA_P31_P279",
                "matched_types": kinds,
            }
        elif len(kinds) == 0:
            decisions[qid] = {
                "suggested_type": "",
                "status": "MANUAL_REVIEW_NO_SUPPORTED_CLASS_MATCH",
                "matched_types": [],
            }
        else:
            decisions[qid] = {
                "suggested_type": "",
                "status": "MANUAL_REVIEW_MULTIPLE_CLASS_MATCHES",
                "matched_types": kinds,
            }

    # Read original approved CSVs; keep them untouched.
    work_fields, work_rows = read_csv(REVIEW_DIR / "work_review.csv")
    entity_fields, entity_rows = read_csv(REVIEW_DIR / "entity_review.csv")

    kept_work, kept_entity = [], []
    quarantine = []
    action_counts = Counter()
    row_counts_by_status = Counter()

    def process_rows(rows: List[dict], source_file: str, keep_rows: list) -> None:
        for row in rows:
            qid = (row.get("wikidata_id") or "").strip().upper()
            candidate_type = normalize_type(row.get("candidate_type", ""))
            decision = decisions.get(qid)

            # Candidates without a conflicting QID are not changed by this script.
            if decision is None:
                keep_rows.append(row)
                action_counts["kept_not_in_conflict_list"] += 1
                continue

            if decision["status"] == "AUTO_RESOLVED_BY_WIKIDATA_P31_P279":
                suggested = decision["suggested_type"]
                if candidate_type == suggested:
                    keep_rows.append(row)
                    action_counts["kept_matching_wikidata_type"] += 1
                else:
                    quarantine.append({
                        "source_file": source_file,
                        "candidate_id": row.get("candidate_id", ""),
                        "wikidata_id": qid,
                        "canonical_name": row.get("canonical_name", ""),
                        "original_candidate_type": candidate_type,
                        "suggested_type": suggested,
                        "action": "QUARANTINE_TYPE_MISMATCH",
                        "reason": "Candidate label conflicts with Wikidata P31/P279 classification",
                    })
                    action_counts["quarantined_type_mismatch"] += 1
            else:
                quarantine.append({
                    "source_file": source_file,
                    "candidate_id": row.get("candidate_id", ""),
                    "wikidata_id": qid,
                    "canonical_name": row.get("canonical_name", ""),
                    "original_candidate_type": candidate_type,
                    "suggested_type": "",
                    "action": "QUARANTINE_MANUAL_REVIEW",
                    "reason": decision["status"],
                })
                action_counts["quarantined_manual_review"] += 1

    process_rows(work_rows, "work_review.csv", kept_work)
    process_rows(entity_rows, "entity_review.csv", kept_entity)

    # Preserve all original columns and add no synthetic values.
    write_csv(OUTPUT_DIR / "work_review.csv", work_fields, kept_work)
    write_csv(OUTPUT_DIR / "entity_review.csv", entity_fields, kept_entity)

    decision_rows = []
    conflict_types = defaultdict(set)
    for row in conflict_rows:
        qid = (row.get("wikidata_id") or "").strip().upper()
        typ = normalize_type(row.get("candidate_type", ""))
        if qid:
            conflict_types[qid].add(typ)

    for qid in qids:
        d = decisions[qid]
        decision_rows.append({
            "wikidata_id": qid,
            "original_candidate_types": json.dumps(sorted(conflict_types[qid]), ensure_ascii=False),
            "matched_wikidata_types": json.dumps(d["matched_types"], ensure_ascii=False),
            "suggested_type": d["suggested_type"],
            "status": d["status"],
            "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
        })
    write_csv(
        OUTPUT_DIR / "qid_type_decisions.csv",
        ["wikidata_id", "original_candidate_types", "matched_wikidata_types", "suggested_type", "status", "wikidata_url"],
        decision_rows,
    )
    write_csv(
        OUTPUT_DIR / "qid_type_quarantine.csv",
        ["source_file", "candidate_id", "wikidata_id", "canonical_name", "original_candidate_type", "suggested_type", "action", "reason"],
        quarantine,
    )

    decision_counts = Counter(d["status"] for d in decisions.values())
    report = {
        "stage": "qid_type_conflict_resolution_suggestions_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_conflicting_qids": len(qids),
        "qid_decisions": dict(decision_counts),
        "candidate_row_actions": dict(action_counts),
        "original_csvs_modified": False,
        "output_directory": str(OUTPUT_DIR.relative_to(ROOT)),
        "rules": {
            "Person": "P31/P279* reaches human (Q5)",
            "Work": "P31/P279* reaches film (Q11424), television series (Q5398426), or television film (Q506240)",
            "Organization": "P31/P279* reaches organization (Q43229)",
        },
        "important": [
            "Only unique Wikidata class matches are automatically suggested.",
            "No-match and multi-match QIDs are quarantined for manual review.",
            "Candidate rows with a type that conflicts with Wikidata are quarantined, not deleted.",
            "Original approved review CSVs are never overwritten.",
            "These are classification suggestions; they do not prove relation evidence or graph acceptance.",
        ],
    }
    (REPORT_DIR / "qid_type_resolution_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted; original review CSVs remain unchanged.", file=sys.stderr)
        raise SystemExit(130)
