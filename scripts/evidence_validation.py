from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from collectors.common import build_session, load_settings, request_json, setup_logging, utc_now

ROOT = Path(__file__).resolve().parents[1]
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
QID_RE = re.compile(r"^Q[1-9]\d*$")
HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)

# These are properties on the Work item. For Person -> Work edges, the
# statement value must equal relation_review.source_qid. For Work -> Organization
# edges, it must equal relation_review.target_qid.
REFERENCE_FIELDS = {
    "P854": "reference_url",
    "P248": "stated_in_qid",
    "P143": "imported_from_qid",
    "P813": "retrieved_date",
    "P577": "publication_date",
    "P1476": "source_title",
    "P1065": "archive_url",
    "P50": "author_qid",
    "P123": "publisher_qid",
    "P1683": "quotation",
    "P407": "language_qid",
    "P6954": "online_access_status_qid",
    "P304": "pages",
    "P478": "volume",
    "P356": "doi",
}


def qid_value(snak: dict[str, Any] | None) -> str:
    if not isinstance(snak, dict) or snak.get("snaktype") != "value":
        return ""
    value = (snak.get("datavalue") or {}).get("value")
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return ""


def scalar_value(snak: dict[str, Any] | None) -> Any:
    if not isinstance(snak, dict) or snak.get("snaktype") != "value":
        return None
    return (snak.get("datavalue") or {}).get("value")


def extract_reference(reference: dict[str, Any]) -> dict[str, Any]:
    snaks = reference.get("snaks") or {}
    extracted: dict[str, Any] = {
        "reference_hash": reference.get("hash"),
        "reference_urls": [],
        "stated_in_qids": [],
        "imported_from_qids": [],
        "fields": {},
    }
    for property_id, label in REFERENCE_FIELDS.items():
        values = []
        for snak in snaks.get(property_id, []) or []:
            value = scalar_value(snak)
            if value is None:
                continue
            if isinstance(value, dict):
                value = value.get("id") or value.get("text") or value
            values.append(value)
        if not values:
            continue
        extracted["fields"][label] = values
        if property_id == "P854":
            extracted["reference_urls"].extend(
                str(v).strip() for v in values if HTTP_RE.match(str(v).strip())
            )
        elif property_id == "P248":
            extracted["stated_in_qids"].extend(str(v) for v in values if QID_RE.fullmatch(str(v)))
        elif property_id == "P143":
            extracted["imported_from_qids"].extend(str(v) for v in values if QID_RE.fullmatch(str(v)))
    extracted["reference_urls"] = sorted(set(extracted["reference_urls"]))
    extracted["stated_in_qids"] = sorted(set(extracted["stated_in_qids"]))
    extracted["imported_from_qids"] = sorted(set(extracted["imported_from_qids"]))
    return extracted


def statement_target_qid(claim: dict[str, Any]) -> str:
    return qid_value(claim.get("mainsnak") or {})


def statement_role_qids(claim: dict[str, Any]) -> set[str]:
    qualifiers = claim.get("qualifiers") or {}
    return {
        qid_value(snak)
        for snak in qualifiers.get("P3831", []) or []
        if qid_value(snak)
    }


def find_matching_statements(
    entity: dict[str, Any] | None,
    property_id: str,
    expected_value_qid: str,
    expected_role_qid: str = "",
) -> list[dict[str, Any]]:
    if not entity or not property_id or not expected_value_qid:
        return []
    claims = (entity.get("claims") or {}).get(property_id, []) or []
    matches = []
    for claim in claims:
        if statement_target_qid(claim) != expected_value_qid:
            continue
        if expected_role_qid and expected_role_qid not in statement_role_qids(claim):
            continue
        matches.append(claim)
    return matches


def expected_statement_value(row: dict[str, str]) -> tuple[str, str]:
    """Return the item value stored on the Work statement and any role QID."""
    work_qid = (row.get("work_qid") or "").strip()
    source_qid = (row.get("source_qid") or "").strip()
    target_qid = (row.get("target_qid") or "").strip()
    role_qid = (row.get("role_qid") or "").strip()
    if not QID_RE.fullmatch(work_qid):
        return "", ""
    if target_qid == work_qid and QID_RE.fullmatch(source_qid):
        return source_qid, role_qid
    if source_qid == work_qid and QID_RE.fullmatch(target_qid):
        return target_qid, role_qid
    return "", role_qid


def classify_edge_status(
    *,
    statement_match_count: int,
    reference_url_count: int,
    stated_in_count: int,
    imported_from_count: int,
    other_reference_count: int,
    deprecated_only: bool = False,
) -> str:
    if deprecated_only and statement_match_count:
        return "deprecated_statement_only_needs_review"
    if statement_match_count == 0:
        return "statement_not_found_or_endpoint_mismatch"
    if reference_url_count:
        return "statement_matched_reference_url_needs_source_review"
    if stated_in_count:
        return "statement_matched_publication_reference_needs_source_lookup"
    if imported_from_count:
        return "statement_matched_imported_from_only_needs_review"
    if other_reference_count:
        return "statement_matched_other_reference_needs_review"
    return "statement_matched_unreferenced"


class WikidataClaimsClient:
    def __init__(self, session, settings: dict[str, Any], root: Path, cache_dir: Path) -> None:
        self.session = session
        self.settings = settings
        self.root = root
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        collection = settings.get("collection", {})
        self.timeout = int(collection.get("request_timeout_seconds", 45))
        self.max_retries = int(collection.get("max_retries", 5))
        self.delay = max(2.0, float(collection.get("request_delay_seconds", 1.5)))
        self.maxlag = int(collection.get("maxlag_seconds", 5))

    def _cache_path(self, qid: str) -> Path:
        return self.cache_dir / f"{qid}.json"

    def load_cached(self, qid: str) -> dict[str, Any] | None:
        path = self._cache_path(qid)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def fetch_many(self, qids: list[str]) -> dict[str, dict[str, Any]]:
        unique = sorted({qid for qid in qids if QID_RE.fullmatch(qid)})
        results: dict[str, dict[str, Any]] = {}
        missing = []
        for qid in unique:
            cached = self.load_cached(qid)
            if cached is not None:
                results[qid] = cached
            else:
                missing.append(qid)

        for start in range(0, len(missing), 50):
            batch = missing[start:start + 50]
            payload = request_json(
                self.session,
                WIKIDATA_API,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "claims",
                    "format": "json",
                    "maxlag": self.maxlag,
                },
                timeout=self.timeout,
                max_retries=self.max_retries,
                delay_seconds=self.delay,
                source_name=f"Wikidata claims {start // 50 + 1}",
            )
            entities = payload.get("entities", {}) or {}
            for qid in batch:
                entity = entities.get(qid)
                if not isinstance(entity, dict) or entity.get("missing") is not None:
                    record = {"id": qid, "missing": True, "claims": {}}
                else:
                    record = {
                        "id": qid,
                        "lastrevid": entity.get("lastrevid"),
                        "modified": entity.get("modified"),
                        "claims": entity.get("claims", {}) or {},
                    }
                temporary = self._cache_path(qid).with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(record, ensure_ascii=False), encoding="utf-8"
                )
                temporary.replace(self._cache_path(qid))
                results[qid] = record
            logging.info(
                "Wikidata claims: batch %d/%d (%d items)",
                start // 50 + 1,
                (len(missing) + 49) // 50,
                len(batch),
            )
        return results


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    temporary.replace(path)
    return count


def audit_edges(
    edges: list[dict[str, Any]],
    relation_rows: list[dict[str, str]],
    entities: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows_by_candidate = {
        (row.get("candidate_id") or "").strip(): row
        for row in relation_rows
        if (row.get("candidate_id") or "").strip()
    }
    audit_rows = []
    reference_rows = []
    unmatched_rows = []

    for edge in edges:
        candidate_ids = edge.get("candidate_ids") or []
        candidates = [rows_by_candidate[cid] for cid in candidate_ids if cid in rows_by_candidate]
        if not candidates:
            audit_rows.append({
                "edge_id": edge.get("edge_id", ""),
                "relationship_type": edge.get("relationship_type", ""),
                "work_qid": edge.get("work_qid", ""),
                "candidate_count": len(candidate_ids),
                "matched_candidate_count": 0,
                "statement_match_count": 0,
                "reference_url_count": 0,
                "stated_in_count": 0,
                "imported_from_count": 0,
                "evidence_status": "candidate_mapping_missing",
                "statement_ids": "[]",
                "source_urls": "[]",
                "note": "No relation_review rows matched candidate_ids.",
            })
            continue

        matched_candidate_ids = []
        statement_records: dict[tuple[str, str], dict[str, Any]] = {}
        invalid_candidates = []
        work_qids = set()

        for candidate in candidates:
            candidate_id = (candidate.get("candidate_id") or "").strip()
            work_qid = (candidate.get("work_qid") or edge.get("work_qid") or "").strip()
            property_id = (candidate.get("property_id") or "").strip()
            expected_qid, expected_role_qid = expected_statement_value(candidate)
            if not expected_qid:
                invalid_candidates.append({
                    "candidate_id": candidate_id,
                    "reason": "qid_orientation_invalid",
                    "source_qid": candidate.get("source_qid", ""),
                    "target_qid": candidate.get("target_qid", ""),
                    "work_qid": work_qid,
                })
                continue
            if not QID_RE.fullmatch(work_qid) or not re.fullmatch(r"P\d+", property_id):
                invalid_candidates.append({
                    "candidate_id": candidate_id,
                    "reason": "missing_or_invalid_work_qid_or_property_id",
                    "work_qid": work_qid,
                    "property_id": property_id,
                })
                continue
            work_qids.add(work_qid)
            entity = entities.get(work_qid)
            matches = find_matching_statements(
                entity, property_id, expected_qid, expected_role_qid
            )
            if not matches:
                invalid_candidates.append({
                    "candidate_id": candidate_id,
                    "reason": "statement_not_found_or_endpoint_mismatch",
                    "work_qid": work_qid,
                    "property_id": property_id,
                    "expected_statement_value_qid": expected_qid,
                    "expected_role_qid": expected_role_qid,
                })
                continue

            matched_candidate_ids.append(candidate_id)
            for claim in matches:
                statement_id = str(claim.get("id") or "")
                key = (work_qid, statement_id or f"{property_id}:{expected_qid}")
                references = [extract_reference(ref) for ref in claim.get("references", []) or []]
                statement_records[key] = {
                    "work_qid": work_qid,
                    "property_id": property_id,
                    "statement_id": statement_id,
                    "target_qid": expected_qid,
                    "rank": claim.get("rank", "normal"),
                    "role_qids": sorted(statement_role_qids(claim)),
                    "references": references,
                }

        statements = list(statement_records.values())
        all_refs = [ref for statement in statements for ref in statement["references"]]
        source_urls = sorted({
            url
            for ref in all_refs
            for url in ref.get("reference_urls", [])
        })
        stated_in_qids = sorted({
            qid
            for ref in all_refs
            for qid in ref.get("stated_in_qids", [])
        })
        imported_from_qids = sorted({
            qid
            for ref in all_refs
            for qid in ref.get("imported_from_qids", [])
        })
        other_ref_count = sum(
            1 for ref in all_refs
            if not ref.get("reference_urls")
            and not ref.get("stated_in_qids")
            and not ref.get("imported_from_qids")
        )
        non_deprecated = [s for s in statements if s.get("rank") != "deprecated"]
        deprecated_only = bool(statements) and not non_deprecated
        usable_statements = non_deprecated or statements
        evidence_status = classify_edge_status(
            statement_match_count=len(usable_statements),
            reference_url_count=len(source_urls),
            stated_in_count=len(stated_in_qids),
            imported_from_count=len(imported_from_qids),
            other_reference_count=other_ref_count,
            deprecated_only=deprecated_only,
        )

        edge_id = edge.get("edge_id", "")
        for statement in statements:
            for index, reference in enumerate(statement["references"]):
                if not any((
                    reference.get("reference_urls"),
                    reference.get("stated_in_qids"),
                    reference.get("imported_from_qids"),
                    reference.get("fields"),
                )):
                    continue
                reference_rows.append({
                    "edge_id": edge_id,
                    "work_qid": statement["work_qid"],
                    "property_id": statement["property_id"],
                    "statement_id": statement["statement_id"],
                    "target_qid": statement["target_qid"],
                    "reference_index": index,
                    "reference_urls": reference.get("reference_urls", []),
                    "stated_in_qids": reference.get("stated_in_qids", []),
                    "imported_from_qids": reference.get("imported_from_qids", []),
                    "reference_fields": reference.get("fields", {}),
                })

        for invalid in invalid_candidates:
            invalid["edge_id"] = edge_id
            unmatched_rows.append(invalid)

        notes = []
        if not statements:
            notes.append("No exact Work/property/statement-value match found in Wikidata claims.")
        if source_urls:
            notes.append("Reference URLs found; source content and reliability still require review.")
        if stated_in_qids and not source_urls:
            notes.append("P248 publication item found; resolve and inspect the publication.")
        if imported_from_qids and not source_urls and not stated_in_qids:
            notes.append("Only P143 imported-from references found; not treated as independent evidence.")
        if deprecated_only:
            notes.append("Only deprecated statement rank matched.")

        audit_rows.append({
            "edge_id": edge_id,
            "relationship_type": edge.get("relationship_type", ""),
            "work_qid": edge.get("work_qid", ""),
            "candidate_count": len(candidate_ids),
            "matched_candidate_count": len(set(matched_candidate_ids)),
            "statement_match_count": len(usable_statements),
            "reference_url_count": len(source_urls),
            "stated_in_count": len(stated_in_qids),
            "imported_from_count": len(imported_from_qids),
            "evidence_status": evidence_status,
            "statement_ids": json.dumps(sorted({s["statement_id"] for s in statements if s["statement_id"]})),
            "source_urls": json.dumps(source_urls, ensure_ascii=False),
            "note": " ".join(notes),
        })

    return audit_rows, reference_rows, unmatched_rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit Wikidata statements and extract statement references for resolved film-network edges."
    )
    parser.add_argument(
        "--edge-file",
        default="data/resolution/entity_resolution_v2/resolved_edge_candidates.jsonl",
    )
    parser.add_argument(
        "--relation-file",
        default="data/review/relation_review.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="data/evidence_validation/v1",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/raw/wikidata/statement_audit_cache",
    )
    parser.add_argument("--force-output", action="store_true")
    args = parser.parse_args()

    edge_path = ROOT / args.edge_file
    relation_path = ROOT / args.relation_file
    output_dir = ROOT / args.output_dir
    cache_dir = ROOT / args.cache_dir

    if not edge_path.exists():
        raise FileNotFoundError(edge_path)
    if not relation_path.exists():
        raise FileNotFoundError(relation_path)
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force_output:
        raise FileExistsError(
            f"Output directory is not empty: {output_dir}. Use a new --output-dir "
            "or --force-output only after backing up existing results."
        )

    settings = load_settings(ROOT)
    log_path = ROOT / settings.get("paths", {}).get("logs", "logs") / "evidence_validation.log"
    setup_logging(log_path)

    edges = read_jsonl(edge_path)
    relation_rows = read_csv(relation_path)
    work_qids = sorted({
        str(row.get("work_qid") or "").strip()
        for row in relation_rows
        if QID_RE.fullmatch(str(row.get("work_qid") or "").strip())
    })
    # Limit claims fetch to Works actually used by the resolved edge candidates.
    edge_work_qids = {
        str(edge.get("work_qid") or "").strip()
        for edge in edges
        if QID_RE.fullmatch(str(edge.get("work_qid") or "").strip())
    }
    requested_work_qids = sorted(edge_work_qids)
    contact = os.getenv("CONTACT_EMAIL", "").strip()
    if not contact or "@" not in contact or "your_email" in contact.lower():
        raise RuntimeError(
            "Set CONTACT_EMAIL in .env before calling Wikidata. Use a real contact email."
        )

    logging.info("Resolved edges: %d", len(edges))
    logging.info("Relation review rows: %d", len(relation_rows))
    logging.info("Unique Work QIDs to inspect: %d", len(requested_work_qids))

    session = build_session()
    client = WikidataClaimsClient(session, settings, ROOT, cache_dir)
    entities = client.fetch_many(requested_work_qids)
    session.close()

    audit_rows, reference_rows, unmatched_rows = audit_edges(
        edges, relation_rows, entities
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    audit_fields = [
        "edge_id", "relationship_type", "work_qid", "candidate_count",
        "matched_candidate_count", "statement_match_count", "reference_url_count",
        "stated_in_count", "imported_from_count", "evidence_status",
        "statement_ids", "source_urls", "note",
    ]
    reference_fields = [
        "edge_id", "work_qid", "property_id", "statement_id", "target_qid",
        "reference_index", "reference_urls", "stated_in_qids",
        "imported_from_qids", "reference_fields",
    ]
    unmatched_fields = [
        "edge_id", "candidate_id", "reason", "source_qid", "target_qid",
        "work_qid", "property_id", "expected_statement_value_qid", "expected_role_qid",
    ]

    write_csv(output_dir / "edge_evidence_status.csv", audit_rows, audit_fields)
    write_csv(output_dir / "evidence_references.csv", reference_rows, reference_fields)
    write_csv(output_dir / "unmatched_statement_candidates.csv", unmatched_rows, unmatched_fields)

    # Machine-readable statement audit retains claim IDs, rank, roles and references.
    statement_audit_rows = []
    for edge, audit in zip(edges, audit_rows):
        statement_audit_rows.append({
            "edge_id": edge.get("edge_id"),
            "work_qid": edge.get("work_qid"),
            "relationship_type": edge.get("relationship_type"),
            "candidate_ids": edge.get("candidate_ids", []),
            "evidence_status": audit["evidence_status"],
            "statement_ids": json.loads(audit["statement_ids"]),
            "source_urls": json.loads(audit["source_urls"]),
            "matched_candidate_count": audit["matched_candidate_count"],
        })
    atomic_write_jsonl(output_dir / "statement_audit.jsonl", statement_audit_rows)

    status_counts = Counter(row["evidence_status"] for row in audit_rows)
    report = {
        "stage": "wikidata_statement_and_reference_audit_v1",
        "generated_at": utc_now(),
        "inputs": {
            "resolved_edge_candidates": len(edges),
            "relation_review_rows": len(relation_rows),
            "unique_work_qids_requested": len(requested_work_qids),
            "work_qids_cached_or_fetched": len(entities),
        },
        "edge_audit": {
            "total_edges_audited": len(audit_rows),
            "status_counts": dict(status_counts),
            "edges_with_statement_reference_urls": sum(
                1 for row in audit_rows if row["reference_url_count"] > 0
            ),
            "edges_with_publication_item_references": sum(
                1 for row in audit_rows if row["stated_in_count"] > 0
            ),
            "edges_without_any_statement_match": sum(
                1 for row in audit_rows
                if row["evidence_status"] == "statement_not_found_or_endpoint_mismatch"
            ),
            "candidate_mappings_unmatched_or_invalid": len(unmatched_rows),
            "reference_records_extracted": len(reference_rows),
        },
        "outputs": {
            "directory": str(output_dir.relative_to(ROOT)),
            "edge_status_csv": str((output_dir / "edge_evidence_status.csv").relative_to(ROOT)),
            "references_csv": str((output_dir / "evidence_references.csv").relative_to(ROOT)),
            "statement_audit_jsonl": str((output_dir / "statement_audit.jsonl").relative_to(ROOT)),
            "unmatched_csv": str((output_dir / "unmatched_statement_candidates.csv").relative_to(ROOT)),
            "claim_cache": str(cache_dir.relative_to(ROOT)),
        },
        "important": [
            "A matching Wikidata statement is not by itself proof that the real-world claim is accurate.",
            "P854 URLs and P248 publication items are extracted for source review; they are not auto-approved.",
            "P143 imported-from references are not treated as independent evidence.",
            "No Edge is assigned verification_status=verified by this stage.",
            "Original review CSVs and Entity Resolution outputs are not modified.",
        ],
    }
    report_path = ROOT / "reports" / "evidence_validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
