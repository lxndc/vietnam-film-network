from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]


def stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file review: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV không có header: {path}")
        if "candidate_id" not in reader.fieldnames:
            raise ValueError(f"Thiếu candidate_id trong {path}")
        if "review_decision" not in reader.fieldnames:
            raise ValueError(f"Thiếu review_decision trong {path}")
        return [dict(row) for row in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            })


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_json_array(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return [value.strip()] if value.strip() else []


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("Đ", "D").replace("đ", "d")
    value = value.casefold()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def source_rank(row: dict[str, str]) -> tuple[int, int, str]:
    language = (row.get("language") or "").lower()
    rank = 0 if language == "vi" else 1 if language == "en" else 2
    has_name = 0 if (row.get("canonical_name") or "").strip() else 1
    return (rank, has_name, (row.get("canonical_name") or "").casefold())


def approved_rows(rows: list[dict[str, str]], dataset: str) -> tuple[list[dict[str, str]], Counter[str]]:
    counts: Counter[str] = Counter()
    accepted: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for row in rows:
        decision = (row.get("review_decision") or "pending").strip().lower()
        counts[decision or "pending"] += 1
        if decision != "correct":
            continue
        candidate_id = (row.get("candidate_id") or "").strip()
        if not candidate_id:
            raise ValueError(f"{dataset}: dòng được đánh dấu correct nhưng thiếu candidate_id")
        if candidate_id in seen_ids:
            raise ValueError(f"{dataset}: candidate_id trùng: {candidate_id}")
        seen_ids.add(candidate_id)
        accepted.append(row)
    return accepted, counts


def build_canonical_nodes(
    work_rows: list[dict[str, str]], entity_rows: list[dict[str, str]]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    all_rows = work_rows + entity_rows
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    candidate_to_node: dict[str, str] = {}
    qid_type_labels: dict[str, set[str]] = defaultdict(set)

    for row in all_rows:
        label = (row.get("candidate_type") or "").strip()
        if label not in {"Work", "Person", "Organization"}:
            raise ValueError(f"candidate_type không hợp lệ: {label!r}, candidate={row.get('candidate_id')}")
        qid = (row.get("wikidata_id") or "").strip().upper()
        if qid and not re.fullmatch(r"Q\d+", qid):
            # Non-QID identifiers are not silently treated as Wikidata IDs.
            qid = ""
        if qid:
            qid_type_labels[qid].add(label)
            key = (label, f"QID:{qid}")
        else:
            # Without a strong identifier, retain each candidate separately.
            key = (label, f"CANDIDATE:{row['candidate_id']}")
        groups[key].append(row)

    nodes: list[dict[str, Any]] = []
    qid_index: dict[tuple[str, str], str] = {}
    candidate_map_rows: list[dict[str, Any]] = []

    for (label, identity_key), members in sorted(groups.items()):
        members_sorted = sorted(members, key=source_rank)
        canonical_row = members_sorted[0]
        canonical_name = (canonical_row.get("canonical_name") or "").strip()
        if not canonical_name:
            # Fall back to any populated label, but never invent one.
            canonical_name = next(
                ((m.get("canonical_name") or "").strip() for m in members_sorted if (m.get("canonical_name") or "").strip()),
                "",
            )
        if not canonical_name:
            raise ValueError(f"Không có canonical_name cho nhóm {identity_key}")

        qid = identity_key[4:] if identity_key.startswith("QID:") else ""
        node_id = stable_id("canonical-node-v1", label, identity_key)
        aliases = sorted({
            name for member in members
            for name in [member.get("canonical_name", "").strip(), *parse_json_array(member.get("aliases"))]
            if name and name != canonical_name
        }, key=str.casefold)
        source_urls = sorted({
            url for member in members
            for url in [member.get("wikipedia_url", "").strip(), member.get("wikidata_url", "").strip()]
            if url
        })
        source_candidate_ids = sorted({m.get("candidate_id", "") for m in members if m.get("candidate_id")})

        node = {
            "node_id": node_id,
            "label": label,
            "canonical_name": canonical_name,
            "aliases": aliases,
            "wikidata_id": qid or None,
            "source_candidate_ids": source_candidate_ids,
            "source_urls": source_urls,
            "source_count": len(source_urls),
            "identity_resolution_method": "exact_wikidata_qid" if qid else "kept_separate_no_qid",
            "candidate_count_merged": len(members),
            "review_status": "user_approved_csv",
            "verification_status": "needs_evidence_validation",
        }
        if label == "Work":
            years = sorted({m.get("release_year", "").strip() for m in members if m.get("release_year", "").strip()})
            types = sorted({m.get("work_type_label", "").strip() for m in members if m.get("work_type_label", "").strip()})
            node["release_year_values"] = years
            node["work_type_labels"] = types
        nodes.append(node)

        for member in members:
            candidate_id = member["candidate_id"]
            candidate_to_node[candidate_id] = node_id
            candidate_map_rows.append({
                "candidate_id": candidate_id,
                "candidate_type": label,
                "wikidata_id": qid,
                "node_id": node_id,
                "resolution_method": node["identity_resolution_method"],
                "candidate_count_merged": len(members),
            })
        if qid:
            qid_index[(label, qid)] = node_id

    # Exact normalized-name collisions are review signals only. They are never auto-merged.
    name_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        normalized = normalize_name(node["canonical_name"])
        if normalized:
            name_groups[(node["label"], normalized)].append(node)

    possible_duplicates: list[dict[str, Any]] = []
    for (label, normalized), members in sorted(name_groups.items()):
        distinct_ids = {m["node_id"] for m in members}
        if len(distinct_ids) > 1:
            possible_duplicates.append({
                "group_id": stable_id("possible-duplicate", label, normalized),
                "label": label,
                "normalized_name": normalized,
                "node_ids": sorted(distinct_ids),
                "canonical_names": sorted({m["canonical_name"] for m in members}),
                "wikidata_ids": sorted({m["wikidata_id"] for m in members if m.get("wikidata_id")}),
                "candidate_ids": sorted({cid for m in members for cid in m["source_candidate_ids"]}),
                "decision": "manual_review_required",
            })

    qid_conflicts = [
        {"wikidata_id": qid, "labels": sorted(labels), "decision": "manual_review_required"}
        for qid, labels in sorted(qid_type_labels.items()) if len(labels) > 1
    ]
    # A QID with conflicting candidate labels is ambiguous: do not use it to resolve any Edge endpoint.
    conflicting_qids = {qid for qid, labels in qid_type_labels.items() if len(labels) > 1}
    qid_index = {key: value for key, value in qid_index.items() if key[1] not in conflicting_qids}

    stats = {
        "input_approved_candidates": len(all_rows),
        "canonical_nodes": len(nodes),
        "nodes_by_label": dict(Counter(n["label"] for n in nodes)),
        "candidate_groups_merged_by_qid": sum(1 for n in nodes if n["wikidata_id"] and n["candidate_count_merged"] > 1),
        "candidates_without_qid_kept_separate": sum(1 for n in nodes if not n["wikidata_id"]),
        "possible_duplicate_name_groups": len(possible_duplicates),
        "qid_type_conflicts": len(qid_conflicts),
    }
    return nodes, qid_index, candidate_map_rows, possible_duplicates, {"stats": stats, "qid_conflicts": qid_conflicts, "candidate_to_node": candidate_to_node}


def build_resolved_edges(
    relation_rows: list[dict[str, str]],
    qid_index: dict[tuple[str, str], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    missing_reference_count = 0

    for row in relation_rows:
        decision = (row.get("review_decision") or "pending").strip().lower()
        status_counts[decision or "pending"] += 1
        if decision != "correct":
            unresolved.append({
                "candidate_id": row.get("candidate_id", ""),
                "reason": f"review_decision={decision or 'pending'}",
                "relationship_type": row.get("relationship_type", ""),
            })
            continue

        source_type = (row.get("source_type") or "").strip()
        target_type = (row.get("target_type") or "").strip()
        source_qid = (row.get("source_qid") or "").strip().upper()
        target_qid = (row.get("target_qid") or "").strip().upper()
        relationship_type = (row.get("relationship_type") or "").strip()

        source_id = qid_index.get((source_type, source_qid)) if source_qid else None
        target_id = qid_index.get((target_type, target_qid)) if target_qid else None
        work_qid = (row.get("work_qid") or "").strip().upper()
        work_id = qid_index.get(("Work", work_qid)) if work_qid else None

        reasons = []
        if not relationship_type:
            reasons.append("missing_relationship_type")
        if not source_id:
            reasons.append(f"unresolved_source:{source_type}:{source_qid or 'missing_qid'}")
        if not target_id:
            reasons.append(f"unresolved_target:{target_type}:{target_qid or 'missing_qid'}")
        if work_qid and not work_id:
            reasons.append(f"unresolved_work_context:{work_qid}")
        if reasons:
            unresolved.append({
                "candidate_id": row.get("candidate_id", ""),
                "reason": ";".join(reasons),
                "relationship_type": relationship_type,
                "source_qid": source_qid,
                "target_qid": target_qid,
                "work_qid": work_qid,
            })
            continue

        reference_urls = parse_json_array(row.get("evidence_reference_urls"))
        evidence_urls = parse_json_array(row.get("evidence_urls"))
        if not reference_urls:
            missing_reference_count += 1

        role_qid = (row.get("role_qid") or "").strip()
        role_name = (row.get("role_name") or "").strip()
        key = (source_id, relationship_type, target_id, work_id or "", role_qid or role_name)
        edge = grouped.setdefault(key, {
            "edge_id": stable_id("resolved-edge-candidate-v1", *key),
            "source_id": source_id,
            "source_type": source_type,
            "target_id": target_id,
            "target_type": target_type,
            "relationship_type": relationship_type,
            "work_id": work_id,
            "work_qid": work_qid or None,
            "role_name": role_name or None,
            "role_qid": role_qid or None,
            "candidate_ids": [],
            "evidence_urls": [],
            "evidence_reference_urls": [],
            "property_ids": [],
            "derivation_method": "direct_wikidata_statement_candidate",
            "review_status": "user_approved_csv",
            "verification_status": "needs_evidence_validation",
        })
        if row.get("candidate_id") and row["candidate_id"] not in edge["candidate_ids"]:
            edge["candidate_ids"].append(row["candidate_id"])
        for url in evidence_urls:
            if url not in edge["evidence_urls"]:
                edge["evidence_urls"].append(url)
        for url in reference_urls:
            if url not in edge["evidence_reference_urls"]:
                edge["evidence_reference_urls"].append(url)
        prop = (row.get("property_id") or "").strip()
        if prop and prop not in edge["property_ids"]:
            edge["property_ids"].append(prop)

    edges = list(grouped.values())
    for edge in edges:
        edge["candidate_ids"].sort()
        edge["evidence_urls"].sort()
        edge["evidence_reference_urls"].sort()
        edge["property_ids"].sort()

    stats = {
        "approved_relation_candidates": status_counts.get("correct", 0),
        "resolved_deduplicated_edge_candidates": len(edges),
        "unresolved_relation_candidates": len(unresolved),
        "candidates_without_statement_reference_urls": missing_reference_count,
        "edges_by_relationship_type": dict(Counter(e["relationship_type"] for e in edges)),
        "all_resolved_edges_need_evidence_validation": True,
    }
    return edges, unresolved, stats


def backup_existing_output(output_dir: Path) -> str | None:
    if not output_dir.exists() or not any(output_dir.iterdir()):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = output_dir.parent / f"{output_dir.name}_backup_{stamp}"
    shutil.copytree(output_dir, backup_dir)
    return str(backup_dir)


def run(project_root: Path, review_dir: Path, output_dir: Path) -> dict[str, Any]:
    work_raw = read_csv(review_dir / "work_review.csv")
    entity_raw = read_csv(review_dir / "entity_review.csv")
    relation_raw = read_csv(review_dir / "relation_review.csv")

    work_rows, work_status = approved_rows(work_raw, "work_review.csv")
    entity_rows, entity_status = approved_rows(entity_raw, "entity_review.csv")
    relation_rows, relation_status = approved_rows(relation_raw, "relation_review.csv")

    # This process intentionally does not reinterpret 'correct' as 'verified'.
    nodes, qid_index, candidate_map, possible_duplicates, resolution = build_canonical_nodes(work_rows, entity_rows)
    edges, unresolved, edge_stats = build_resolved_edges(relation_rows, qid_index)

    backup_dir = backup_existing_output(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl(output_dir / "canonical_nodes.jsonl", nodes)
    write_jsonl(output_dir / "resolved_edge_candidates.jsonl", edges)
    write_csv(
        output_dir / "candidate_node_map.csv",
        candidate_map,
        ["candidate_id", "candidate_type", "wikidata_id", "node_id", "resolution_method", "candidate_count_merged"],
    )
    write_csv(
        output_dir / "possible_duplicate_groups.csv",
        possible_duplicates,
        ["group_id", "label", "normalized_name", "node_ids", "canonical_names", "wikidata_ids", "candidate_ids", "decision"],
    )
    write_csv(
        output_dir / "qid_type_conflicts.csv",
        resolution["qid_conflicts"],
        ["wikidata_id", "labels", "decision"],
    )
    write_csv(
        output_dir / "unresolved_edge_candidates.csv",
        unresolved,
        ["candidate_id", "reason", "relationship_type", "source_qid", "target_qid", "work_qid"],
    )

    report = {
        "stage": "entity_resolution_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "work_review_rows": len(work_raw),
            "entity_review_rows": len(entity_raw),
            "relation_review_rows": len(relation_raw),
            "review_decisions": {
                "work": dict(work_status),
                "entity": dict(entity_status),
                "relation": dict(relation_status),
            },
            "approved_candidates_used": {
                "work": len(work_rows),
                "entity": len(entity_rows),
                "relation": len(relation_rows),
            },
        },
        "node_resolution": resolution["stats"],
        "edge_resolution": edge_stats,
        "output_directory": str(output_dir.relative_to(project_root) if output_dir.is_relative_to(project_root) else output_dir),
        "previous_output_backup": backup_dir,
        "important": [
            "Exact same-type Wikidata QID is the only automatic merge key.",
            "Candidates without QID are kept separate; same-name groups are review flags only.",
            "Resolved edges remain needs_evidence_validation and are not production graph edges.",
            "Wikidata item URLs are traceability links, not equivalent to statement reference URLs.",
            "No precision claim is made by this script.",
        ],
    }
    report_path = project_root / "reports" / "entity_resolution_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve reviewed candidates by exact same-type Wikidata QID and map relation endpoints."
    )
    parser.add_argument("--review-dir", default="data/review")
    parser.add_argument("--output-dir", default="data/resolution")
    args = parser.parse_args()
    review_dir = (ROOT / args.review_dir).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    report = run(ROOT, review_dir, output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nKết quả: canonical nodes và resolved edge candidates; chưa phải verified graph.")


if __name__ == "__main__":
    main()
