from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from collectors.common import append_jsonl_unique, load_settings, read_jsonl, setup_logging, stable_id, utc_now
from collectors.wikipedia_api import is_index_search_match

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    settings = load_settings(ROOT)
    paths = settings["paths"]
    raw_wiki = ROOT / paths["raw_wikipedia"]
    raw_wd = ROOT / paths["raw_wikidata"]
    processed = ROOT / paths["processed"]
    processed.mkdir(parents=True, exist_ok=True)
    setup_logging(ROOT / paths["logs"] / "build_candidates.log")

    wiki_pages = read_jsonl(raw_wiki / "pages.jsonl")
    wiki_matches = read_jsonl(raw_wiki / "search_matches.jsonl")
    wd_works = read_jsonl(raw_wd / "work_seeds.jsonl")
    wd_credits = read_jsonl(raw_wd / "credit_candidates.jsonl")

    pages_by_key = {(p.get("language"), str(p.get("page_id"))): p for p in wiki_pages}
    wiki_candidates: dict[str, dict] = {}
    for match in wiki_matches:
        if is_index_search_match(match):
            continue
        scope = match.get("scope")
        if scope not in {"work", "person", "organization"}:
            continue
        page = pages_by_key.get((match.get("language"), str(match.get("page_id"))), {})
        candidate_type = {"work": "Work", "person": "Person", "organization": "Organization"}[scope]
        canonical_name = page.get("page_title") or match.get("page_title") or ""
        candidate_id = stable_id("wiki-candidate", match.get("language", ""), match.get("page_id", ""), candidate_type)
        candidate = wiki_candidates.setdefault(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "candidate_type": candidate_type,
                "canonical_name": canonical_name,
                "wikidata_id": page.get("wikidata_id"),
                "wikipedia_url": page.get("source_url"),
                "source_name": page.get("source_name", match.get("source_name")),
                "language": match.get("language"),
                "search_queries": [],
                "verification_status": "needs_review",
                "retrieved_at": utc_now(),
            },
        )
        if match.get("query_id") and match["query_id"] not in candidate["search_queries"]:
            candidate["search_queries"].append(match["query_id"])

    work_candidates: list[dict] = []
    work_by_qid: dict[str, dict] = {}
    for row in wd_works:
        qid = row.get("qid")
        if not qid:
            continue
        candidate = {
            "candidate_id": stable_id("wikidata-work", qid),
            "candidate_type": "Work",
            "canonical_name": row.get("canonical_title", ""),
            "wikidata_id": qid,
            "wikipedia_url": row.get("wikipedia_url"),
            "wikidata_url": row.get("wikidata_url"),
            "work_type_label": row.get("work_type_label"),
            "release_year": row.get("release_year"),
            "description": row.get("description"),
            "verification_status": "needs_review",
        }
        work_candidates.append(candidate)
        work_by_qid[qid] = candidate

    # Preserve Wikipedia-derived candidates separately; do not auto-merge by title.
    work_candidates.extend(v for v in wiki_candidates.values() if v["candidate_type"] == "Work")

    entities: dict[str, dict] = {}
    for candidate in wiki_candidates.values():
        if candidate["candidate_type"] != "Work":
            entities[candidate["candidate_id"]] = candidate
    for row in wd_credits:
        target_qid = row.get("target_qid")
        target_type = row.get("statement_target_type")
        if not target_qid or target_type not in {"Person", "Organization"}:
            continue
        key = stable_id("wikidata-entity", target_type, target_qid)
        entity = entities.setdefault(
            key,
            {
                "candidate_id": key,
                "candidate_type": target_type,
                "canonical_name": row.get("target_label", ""),
                "wikidata_id": target_qid,
                "wikidata_url": f"https://www.wikidata.org/wiki/{target_qid}",
                "related_work_qids": [],
                "verification_status": "needs_review",
            },
        )
        if row.get("work_qid") and row["work_qid"] not in entity.setdefault("related_work_qids", []):
            entity["related_work_qids"].append(row["work_qid"])

    relation_candidates = []
    for row in wd_credits:
        relation_candidates.append(
            {
                "candidate_id": row.get("candidate_id"),
                "source_qid": row.get("source_qid"),
                "source_type": row.get("source_type"),
                "source_label": row.get("source_label"),
                "target_qid": row.get("target_node_qid"),
                "target_type": row.get("target_type"),
                "target_label": row.get("target_node_label"),
                "relationship_type": row.get("relationship_type"),
                "role_name": row.get("role_name"),
                "role_qid": row.get("role_qid"),
                "work_qid": row.get("work_qid"),
                "evidence_urls": row.get("evidence_urls") or [row.get("source_url")],
                "evidence_reference_urls": row.get("evidence_reference_urls", []),
                "evidence_ids": [stable_id("wikidata-evidence", row.get("work_qid", ""), row.get("property_id", ""), row.get("target_qid", ""))],
                "property_id": row.get("property_id"),
                "extraction_method": row.get("extraction_method"),
                "derivation_method": "direct_wikidata_statement_candidate",
                "verification_status": "needs_review",
                "retrieved_at": row.get("retrieved_at"),
            }
        )

    # Replace processed candidate files as deterministic snapshots for this run.
    outputs = {
        "work_candidates.jsonl": work_candidates,
        "entity_candidates.jsonl": list(entities.values()),
        "relation_candidates.jsonl": relation_candidates,
    }
    for filename, rows in outputs.items():
        path = processed / filename
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        logging.info("Ghi %s: %d bản ghi", filename, len(rows))

    summary = {
        "work_candidates": len(work_candidates),
        "person_organization_candidates": len(entities),
        "relation_candidates": len(relation_candidates),
        "all_candidates_status": "needs_review",
        "warning": "Candidate chưa phải Node/Edge đã xác minh và không được tính vào nghiệm thu.",
    }
    (ROOT / paths["reports"] / "candidate_build_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
