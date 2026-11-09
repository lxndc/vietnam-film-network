#!/usr/bin/env python3
"""100% *technical* screening and isolated Neo4j import for News V2.

Never writes fabricated Gold Standard reviewer labels, never marks a machine
verdict as independently verified and never disables the production gate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import random
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_pipeline.common import (
    NEWS_DATA, REPORTS, ROOT, article_path, csv_read, csv_write,
    id_for, is_wiki, json_report, now, prepare, require_news_url,
    source_index, text_key,
)
from news_pipeline.extract import COMPILED, CAST_LIST_RULES, clean_entity_name
from news_pipeline.quality import audit, evaluate, GOLD_FIELDS

NODE_TYPES = {"Person": "PERSON_", "Work": "WORK_", "Organization": "ORG_"}
REL_TYPES = {
    "ACTED_IN", "VOICE_ACTED_IN", "DIRECTED", "PRODUCED", "EXECUTIVE_PRODUCED",
    "WROTE", "COMPOSED_MUSIC_FOR", "CINEMATOGRAPHED", "EDITED",
    "DISTRIBUTED_BY", "BROADCAST_BY", "PRODUCED_BY",
}
WORK_TO_ORG = {"DISTRIBUTED_BY", "BROADCAST_BY", "PRODUCED_BY"}
SPECULATIVE = re.compile(r"\b(?:dự kiến|tin đồn|đồn đoán|nghi vấn|được cho là|có thể sẽ)\b", re.I)
VERDICT_FIELDS = [
    "assertion_id", "article_id", "outlet_id", "relationship_type", "subject_id",
    "object_id", "canonical_url", "machine_status", "failure_reasons", "rule_id",
    "checked_at", "precision_certified", "human_review_claimed",
]
NODE_FIELDS = ["node_id", "node_type", "canonical_name", "verification_status", "dataset"]
EDGE_FIELDS = [
    "edge_id", "source_id", "target_id", "relationship_type", "verification_status",
    "precision_status", "evidence_count", "article_ids", "source_urls", "dataset",
]
EVIDENCE_FIELDS = [
    "edge_id", "assertion_id", "article_id", "source_url", "evidence_text",
    "evidence_start", "evidence_end", "machine_status",
]
GOLD_SCREEN_FIELDS = [
    "assertion_id", "article_id", "relationship_type", "canonical_url",
    "machine_status", "failure_reasons", "gold_standard_label", "precision_certified",
]
AUTO_DATASET = "news_v2_auto"


def _rule_supports(assertion: dict) -> bool:
    """Re-match the asserted entities, relation, and rule in the exact evidence."""
    evidence = assertion.get("evidence_text", "")
    rule_id = assertion.get("rule_id", "")
    relation = assertion.get("relationship_type", "")
    source_name = clean_entity_name(assertion.get("subject_name", ""))
    target_name = clean_entity_name(assertion.get("object_name", ""))
    expected_person = source_name if relation not in WORK_TO_ORG else ""
    expected_org = target_name if relation in WORK_TO_ORG else ""
    expected_work = target_name if relation not in WORK_TO_ORG else source_name

    for rid, pattern, kind, _ in COMPILED:
        if rid != rule_id or kind != relation:
            continue
        for match in pattern.finditer(evidence):
            try:
                work = clean_entity_name(match.group("work"))
                if text_key(work) != text_key(expected_work):
                    continue
                if relation in WORK_TO_ORG:
                    org = clean_entity_name(match.group("org"))
                    if text_key(org) == text_key(expected_org):
                        return True
                else:
                    person = clean_entity_name(match.group("person"))
                    if text_key(person) == text_key(expected_person):
                        return True
            except (IndexError, AttributeError):
                continue
        return False

    if relation != "ACTED_IN":
        return False
    for rid, pattern in CAST_LIST_RULES:
        if rid != rule_id:
            continue
        for match in pattern.finditer(evidence):
            if text_key(clean_entity_name(match.group("work"))) != text_key(expected_work):
                continue
            names = re.split(r"\s*,\s*|\s+và\s+|\s+cùng\s+", match.group("cast"))
            for name in names:
                cleaned = re.sub(r"^(?:NSND|NSƯT)\s+", "", clean_entity_name(name))
                if text_key(cleaned) == text_key(expected_person):
                    return True
        return False
    return False


def _check_assertion(r, article, doc, source, audit_row, duplicate: bool) -> list[str]:
    errors: list[str] = []
    if duplicate:
        errors.append("duplicate_assertion_id")
    if not article or not doc:
        errors.append("article_or_document_missing")
    if not source:
        errors.append("outlet_not_allowlisted")
    else:
        try:
            require_news_url(r.get("canonical_url", ""), source["base_url"])
        except (KeyError, ValueError):
            errors.append("nonpublisher_or_wiki_url")
    if not audit_row or audit_row.get("auto_review_status") != "auto_pass_needs_independent_review":
        errors.append("previous_full_audit_not_passed")
    if article:
        for field in ("canonical_url", "outlet_id"):
            if r.get(field) != article.get(field):
                errors.append(f"{field}_article_mismatch")
        if is_wiki(article.get("canonical_url", "")):
            errors.append("wiki_article_forbidden")
    if r.get("relationship_type") not in REL_TYPES:
        errors.append("unrecognized_relationship")
    relation = r.get("relationship_type", "")
    expected_types = ("Work", "Organization") if relation in WORK_TO_ORG else ("Person", "Work")
    if (r.get("subject_type"), r.get("object_type")) != expected_types:
        errors.append("wrong_relationship_direction_or_types")
    for role, node_type in (("subject", expected_types[0]), ("object", expected_types[1])):
        nid = r.get(role + "_id", "")
        name = r.get(role + "_name", "")
        if not nid or not nid.startswith(NODE_TYPES[node_type]):
            errors.append(f"{role}_id_invalid")
        if not name or len(name.strip()) < 2:
            errors.append(f"{role}_name_invalid")
        if nid != id_for(NODE_TYPES[node_type][:-1], text_key(name)):
            errors.append(f"{role}_id_name_mismatch")
    if r.get("subject_id") == r.get("object_id"):
        errors.append("self_edge")
    if r.get("extraction_method") != "deterministic_explicit_role_rule":
        errors.append("unsupported_extraction_method")
    evidence = r.get("evidence_text", "")
    if SPECULATIVE.search(evidence):
        errors.append("speculative_evidence")
    if not _rule_supports(r):
        errors.append("original_rule_cannot_be_replayed")
    if not doc or doc.get("fetch_status") != "fetched":
        errors.append("original_article_not_fetched")
    if doc and r.get("article_id") != doc.get("article_id"):
        errors.append("document_id_mismatch")
    if article and doc and doc.get("canonical_url") != article.get("canonical_url"):
        errors.append("document_url_mismatch")
    if doc:
        try:
            path = article_path(r.get("article_id", ""))
            if path.is_symlink() or not path.is_file():
                errors.append("article_text_missing_or_symlink")
            else:
                body = path.read_text(encoding="utf-8")
                if hashlib.sha256(body.encode("utf-8")).hexdigest() != doc.get("sha256"):
                    errors.append("article_hash_mismatch")
                if len(body) < 250:
                    errors.append("article_body_too_short")
                try:
                    start = int(r.get("evidence_start", ""))
                    end = int(r.get("evidence_end", ""))
                    if start < 0 or end <= start or end > len(body) or body[start:end] != evidence:
                        errors.append("evidence_offsets_or_content_mismatch")
                except ValueError:
                    errors.append("invalid_evidence_offsets")
        except (OSError, UnicodeError, ValueError):
            errors.append("article_text_unreadable")
    return sorted(set(errors))


def _read_current_inputs():
    articles = csv_read(NEWS_DATA / "articles.csv")
    docs = csv_read(NEWS_DATA / "article_documents.csv")
    candidates = csv_read(NEWS_DATA / "relation_assertions.csv")
    article_index = {r["article_id"]: r for r in articles}
    doc_index = {r["article_id"]: r for r in docs}
    audit_index = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "edge_audit.csv")}
    if len(article_index) != len(articles) or len(doc_index) != len(docs):
        raise RuntimeError("Duplicate news article/document IDs; inspect inputs before auto screening")
    return articles, docs, candidates, article_index, doc_index, audit_index


def screen(sample_size: int = 329, create_sample: bool = True) -> dict:
    prepare()
    # Force a *fresh* full technical audit to avoid trusting stale prior JSON.
    audit(SimpleNamespace())
    articles, docs, candidates, articles_by_id, docs_by_id, audits = _read_current_inputs()
    if len(audits) != len(candidates):
        raise RuntimeError("Edge audit count differs from assertion count; duplicate IDs suspected")
    outlets = source_index()
    seen_assertions: set[str] = set()
    statuses = []
    passed: list[dict] = []
    seen_triples_article: set[tuple] = set()
    for r in candidates:
        aid = r.get("assertion_id", "")
        duplicate_id = aid in seen_assertions
        seen_assertions.add(aid)
        triple = (r.get("article_id"), r.get("subject_id"), r.get("relationship_type"), r.get("object_id"))
        duplicate_triple = triple in seen_triples_article
        seen_triples_article.add(triple)
        errors = _check_assertion(
            r, articles_by_id.get(r.get("article_id")), docs_by_id.get(r.get("article_id")),
            outlets.get(r.get("outlet_id")), audits.get(aid), duplicate_id or duplicate_triple,
        )
        machine_status = "machine_screened" if not errors else "machine_rejected"
        if not errors:
            passed.append(r)
        statuses.append({
            "assertion_id": aid, "article_id": r.get("article_id", ""), "outlet_id": r.get("outlet_id", ""),
            "relationship_type": r.get("relationship_type", ""), "subject_id": r.get("subject_id", ""),
            "object_id": r.get("object_id", ""), "canonical_url": r.get("canonical_url", ""),
            "machine_status": machine_status, "failure_reasons": ";".join(errors),
            "rule_id": r.get("rule_id", ""), "checked_at": now(),
            "precision_certified": "no", "human_review_claimed": "no",
        })
    csv_write(NEWS_DATA / "auto_screening.csv", statuses, VERDICT_FIELDS)
    # Build a disjoint *machine-screened* export. Never write the verified export.
    by_triple = defaultdict(list)
    for r in passed:
        by_triple[(r["subject_id"], r["relationship_type"], r["object_id"])].append(r)
    nodes, edges, evidences = {}, [], []
    for (source_id, relation, target_id), group in sorted(by_triple.items()):
        r = group[0]
        n1 = {
            "node_id": source_id, "node_type": r["subject_type"],
            "canonical_name": r["subject_name"], "verification_status": "machine_screened",
            "dataset": AUTO_DATASET,
        }
        n2 = {
            "node_id": target_id, "node_type": r["object_type"],
            "canonical_name": r["object_name"], "verification_status": "machine_screened",
            "dataset": AUTO_DATASET,
        }
        for n in (n1, n2):
            prior = nodes.get(n["node_id"])
            if prior and (prior["node_type"], prior["canonical_name"]) != (n["node_type"], n["canonical_name"]):
                raise RuntimeError("Entity ID collision with incompatible names or types")
            nodes[n["node_id"]] = n
        edge_id = id_for("AUTOEDGE", source_id, relation, target_id)
        urls = sorted({x["canonical_url"] for x in group})
        article_ids = sorted({x["article_id"] for x in group})
        edges.append({
            "edge_id": edge_id, "source_id": source_id, "target_id": target_id,
            "relationship_type": relation, "verification_status": "machine_screened",
            "precision_status": "not_independently_measured", "evidence_count": len(group),
            "article_ids": "|".join(article_ids), "source_urls": "|".join(urls),
            "dataset": AUTO_DATASET,
        })
        for assertion in group:
            evidences.append({
                "edge_id": edge_id, "assertion_id": assertion["assertion_id"],
                "article_id": assertion["article_id"], "source_url": assertion["canonical_url"],
                "evidence_text": assertion["evidence_text"],
                "evidence_start": assertion["evidence_start"],
                "evidence_end": assertion["evidence_end"],
                "machine_status": "machine_screened",
            })
    target = NEWS_DATA / "export" / "auto_staging"
    csv_write(target / "nodes.csv", sorted(nodes.values(), key=lambda n: n["node_id"]), NODE_FIELDS)
    csv_write(target / "edges.csv", edges, EDGE_FIELDS)
    csv_write(target / "edge_evidence.csv", evidences, EVIDENCE_FIELDS)

    sample_path = NEWS_DATA / "gold_standard_sample.csv"
    created = False
    if create_sample and not sample_path.exists() and passed:
        # Stratified sampling of THIS machine-screened population. The Gold
        # labels remain blank; neither precision nor reviewer names are forged.
        strata = defaultdict(list)
        for row in passed:
            strata[(row["relationship_type"], row["outlet_id"])].append(row)
        rng = random.Random(20261109)
        for subset in strata.values():
            rng.shuffle(subset)
        chosen = []
        while len(chosen) < min(sample_size, len(passed)):
            progressed = False
            for key in sorted(strata):
                if strata[key] and len(chosen) < min(sample_size, len(passed)):
                    chosen.append(strata[key].pop())
                    progressed = True
            if not progressed:
                break
        sample_rows = []
        for row in chosen:
            sample_rows.append({
                "assertion_id": row["assertion_id"], "article_id": row["article_id"],
                "outlet_id": row["outlet_id"], "relationship_type": row["relationship_type"],
                "subject_name": row["subject_name"], "object_name": row["object_name"],
                "evidence_text": row["evidence_text"], "canonical_url": row["canonical_url"],
                "reviewer_a": "", "reviewer_a_label": "", "reviewer_b": "",
                "reviewer_b_label": "", "adjudicator": "", "adjudicated_label": "",
                "evidence_checked_url": "", "review_notes": "",
            })
        csv_write(sample_path, sample_rows, GOLD_FIELDS)
        json_report("gold_auto_population_sampling.json", {
            "stage": "unlabelled_sample_of_machine_screened_population",
            "created_at": now(), "requested_sample_size": sample_size,
            "sample_size": len(sample_rows), "population_assertions": len(passed),
            "random_seed": 20261109,
            "no_reviewer_labels_created": True,
            "precision_calculable": False,
        })
        created = True
    statuses_by_id = {r["assertion_id"]: r for r in statuses}
    sample_rows = csv_read(sample_path) if sample_path.exists() else []
    if any(is_wiki(r.get("canonical_url", "")) or is_wiki(r.get("evidence_checked_url", ""))
           for r in sample_rows):
        raise RuntimeError("Gold sample inside news_v2 contains Wiki URL; move it to a legacy archive and regenerate")
    machine_gold = []
    for r in sample_rows:
        v = statuses_by_id.get(r.get("assertion_id", ""), {})
        machine_gold.append({
            "assertion_id": r.get("assertion_id", ""), "article_id": r.get("article_id", ""),
            "relationship_type": r.get("relationship_type", ""), "canonical_url": r.get("canonical_url", ""),
            "machine_status": v.get("machine_status", "missing_from_current_population"),
            "failure_reasons": v.get("failure_reasons", ""),
            "gold_standard_label": "UNASSESSED", "precision_certified": "no",
        })
    csv_write(NEWS_DATA / "auto_gold_screening.csv", machine_gold, GOLD_SCREEN_FIELDS)
    independent_eval = (evaluate(SimpleNamespace(min_sample=200)) if sample_rows else None)
    reasons = Counter(x for row in statuses if row["failure_reasons"] for x in row["failure_reasons"].split(";"))
    count = len(candidates)
    output = {
        "stage": "automated_newspaper_technical_screening_v1", "created_at": now(),
        "candidate_edges": count, "candidates_machine_audited": len(statuses),
        "machine_audit_coverage_percent": 100.0 if count else None,
        "machine_pass_assertions": len(passed), "machine_rejected_assertions": count - len(passed),
        "machine_screened_unique_edges": len(edges), "machine_screened_nodes": len(nodes),
        "machine_populated_types": len({r["relationship_type"] for r in edges}),
        "reject_reasons": dict(reasons),
        "sample_created": created, "gold_sample_rows": len(sample_rows),
        "gold_standard_evaluation_status": independent_eval.get("status") if independent_eval else "missing",
        "independently_measured_precision_percent": independent_eval.get("precision_percent") if independent_eval else None,
        "gold_standard_precision_above_90": (
            independent_eval.get("precision_above_90") if independent_eval and
            independent_eval.get("status") == "calculable" else None
        ),
        "qualified_as_verified_for_production": False,
        "wiki_sources_used": 0,
        "export_dir": str(target.relative_to(ROOT)),
        "explanation": "Full machine-check coverage and rule replay are not factual precision. Gold Standard labels were NOT populated.",
    }
    json_report("auto_screening.json", output)
    return output


def _load_auto_export():
    target = NEWS_DATA / "export" / "auto_staging"
    nodes = csv_read(target / "nodes.csv")
    edges = csv_read(target / "edges.csv")
    evidence = csv_read(target / "edge_evidence.csv")
    if not nodes or not edges:
        raise RuntimeError("No machine-screened graph; first run prepare and inspect auto_screening.json")
    if len({n["node_id"] for n in nodes}) != len(nodes) or len({e["edge_id"] for e in edges}) != len(edges):
        raise RuntimeError("Duplicate export node/edge IDs")
    node_ids = {n["node_id"] for n in nodes}
    outlets = source_index()
    for n in nodes:
        if (n.get("node_type") not in NODE_TYPES or n.get("dataset") != AUTO_DATASET
                or n.get("verification_status") != "machine_screened"):
            raise RuntimeError("Unexpected auto node type/status/dataset")
    for e in edges:
        if (e.get("dataset") != AUTO_DATASET or e.get("verification_status") != "machine_screened"
                or e.get("precision_status") != "not_independently_measured"
                or e.get("relationship_type") not in REL_TYPES
                or e.get("source_id") not in node_ids or e.get("target_id") not in node_ids):
            raise RuntimeError("Unexpected auto edge type/status/endpoints")
        try:
            if int(e["evidence_count"]) < 1:
                raise ValueError("no evidence")
        except ValueError as exc:
            raise RuntimeError("Invalid edge evidence count") from exc
    for ev in evidence:
        if ev.get("machine_status") != "machine_screened" or is_wiki(ev.get("source_url", "")):
            raise RuntimeError("Invalid or Wiki evidence source in auto export")
    return nodes, edges, evidence


def import_staging(batch_size=300) -> dict:
    prepare()
    # Re-run full screening in the same invocation: never trust stale export files.
    screened = screen()
    nodes, edges, _ = _load_auto_export()
    try:
        from neo4j import GraphDatabase
        from dotenv import dotenv_values
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install neo4j python-dotenv") from exc
    cfg = dotenv_values(ROOT / ".env")
    uri = os.environ.get("NEO4J_URI") or cfg.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER") or cfg.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD") or cfg.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE") or cfg.get("NEO4J_DATABASE") or "neo4j"
    if not (uri and user and password):
        raise RuntimeError("Set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD in local .env")
    if not (uri.startswith("bolt://") or uri.startswith("bolt+s://") or uri.startswith("neo4j://") or uri.startswith("neo4j+s://") or uri.startswith("neo4j+ssc://") or uri.startswith("bolt+ssc://")):
        raise RuntimeError("Unsupported Neo4j URI scheme")

    def chunks(items):
        for i in range(0, len(items), batch_size):
            yield items[i:i+batch_size]

    # Separate label and relationship ID space from Wiki and manually verified graph.
    # Existing NewsV2Auto nodes from a prior run are not deleted.
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            session.run("CREATE CONSTRAINT news_v2_auto_id IF NOT EXISTS FOR (n:NewsV2Auto) REQUIRE n.node_id IS UNIQUE").consume()
            for node_type in NODE_TYPES:
                group = [n for n in nodes if n["node_type"] == node_type]
                for batch in chunks(group):
                    session.run(
                        f"UNWIND $rows AS row MERGE (n:NewsV2Auto:{node_type} {{node_id: row.node_id}}) "
                        "SET n.canonical_name = row.canonical_name, n.dataset='news_v2_auto', "
                        "n.verification_status='machine_screened', n.precision_status='not_independently_measured'",
                        rows=batch,
                    ).consume()
            for rel in REL_TYPES:
                group = [e for e in edges if e["relationship_type"] == rel]
                for batch in chunks(group):
                    prepared = [{**e, "source_urls": e["source_urls"].split("|"),
                                 "article_ids": e["article_ids"].split("|"),
                                 "evidence_count": int(e["evidence_count"])} for e in batch]
                    session.run(
                        f"UNWIND $rows AS row MATCH (a:NewsV2Auto {{node_id: row.source_id}}) "
                        f"MATCH (b:NewsV2Auto {{node_id: row.target_id}}) "
                        f"MERGE (a)-[r:{rel} {{edge_id: row.edge_id}}]->(b) "
                        "SET r.dataset='news_v2_auto', r.verification_status='machine_screened', "
                        "r.precision_status='not_independently_measured', "
                        "r.source_urls=row.source_urls, r.article_ids=row.article_ids, "
                        "r.evidence_count=row.evidence_count",
                        rows=prepared,
                    ).consume()
            db_node_count = session.run(
                "MATCH (n:NewsV2Auto {dataset:'news_v2_auto'}) RETURN count(n) AS n"
            ).single()["n"]
            db_edge_count = session.run(
                "MATCH (:NewsV2Auto)-[r]->(:NewsV2Auto) "
                "WHERE r.dataset='news_v2_auto' RETURN count(r) AS n"
            ).single()["n"]
    report = {
        "stage": "news_v2_auto_neo4j_staging_import", "status": "completed", "date": now(),
        "mode": "machine_screened_staging", "database": database,
        "input_nodes": len(nodes), "input_edges": len(edges),
        "neo4j_auto_nodes_total": db_node_count, "neo4j_auto_edges_total": db_edge_count,
        "wiki_data_imported": False, "gold_standard_certification": False,
        "independently_measured_precision_percent": None,
        "warning": "Neo4j staging import is NOT an academic precision pass, and is not production acceptance.",
    }
    json_report("neo4j_auto_staging.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="100% automated technical screening and create independent sample with empty labels")
    prep.add_argument("--sample-size", type=int, default=329)
    prep.add_argument("--no-sample", action="store_true")
    imp = sub.add_parser("import", help="Rebuild screen and import machine-screened graph into Neo4j staging")
    imp.add_argument("--batch-size", type=int, default=300)
    sub.add_parser("status", help="Print latest automated screening and import status")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.sample_size < 1:
                parser.error("--sample-size must be positive")
            result = screen(args.sample_size, not args.no_sample)
        elif args.command == "import":
            if args.batch_size < 1:
                parser.error("--batch-size must be positive")
            result = import_staging(args.batch_size)
        else:
            report_path = REPORTS / "auto_screening.json"
            import_path = REPORTS / "neo4j_auto_staging.json"
            result = {
                "auto_screening": json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None,
                "neo4j_staging_import": json.loads(import_path.read_text(encoding="utf-8")) if import_path.exists() else None,
            }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (RuntimeError, ValueError, FileNotFoundError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
