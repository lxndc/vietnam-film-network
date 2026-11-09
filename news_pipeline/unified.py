"""One entrypoint, one NewsV2 Neo4j graph, fully automatic technical screening.

Usage: python -m news_pipeline.unified run --discover none
       python -m news_pipeline.unified run --discover both --sources VNE TN VTV TT

This does not produce independent Gold Standard labels or claim 90% precision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from .common import (NEWS_DATA, REPORTS, ROOT, article_path, csv_read, csv_write,
                     id_for, json_report, now, prepare, require_news_url,
                     source_index, text_key)
from .high_yield import extract_candidates, rebuild_assertions, REL_ENDPOINTS, NODE_PREFIX
from .quality import audit

TARGETS = {"nodes": 2200, "edges": 5500, "relationship_types": 11}
RELATIONS = set(REL_ENDPOINTS)
NODE_FIELDS = ["node_id", "node_type", "canonical_name", "verification_status", "dataset"]
EDGE_FIELDS = ["edge_id", "source_id", "target_id", "relationship_type", "verification_status",
               "evidence_count", "distinct_outlets", "outlet_ids", "source_urls", "article_ids", "dataset"]
EVID_FIELDS = ["edge_id", "assertion_id", "article_id", "outlet_id", "source_url", "evidence_text",
               "evidence_start", "evidence_end", "screening_status"]
CHECK_FIELDS = ["assertion_id", "article_id", "relationship_type", "screening_status", "reason"]
DATASET = "news_v2"


def _pass(r: dict, article: dict | None, doc: dict | None, audit_result: dict | None,
          source: dict | None, body: str | None, regenerated_ids: set[str]) -> str:
    if not article or not doc or body is None:
        return "missing_original_article_or_text"
    if not source:
        return "unknown_publisher"
    try:
        require_news_url(r.get("canonical_url", ""), source["base_url"])
    except ValueError:
        return "forbidden_url"
    if (r.get("canonical_url") != article.get("canonical_url")
            or r.get("canonical_url") != doc.get("canonical_url")
            or r.get("outlet_id") != article.get("outlet_id")):
        return "publisher_or_document_mismatch"
    if doc.get("fetch_status") != "fetched" or hashlib.sha256(body.encode("utf-8")).hexdigest() != doc.get("sha256"):
        return "missing_or_mutated_original_text"
    if not audit_result or audit_result.get("auto_review_status") != "auto_pass_needs_independent_review":
        return "technical_audit_failed"
    relation = r.get("relationship_type")
    if relation not in RELATIONS:
        return "unrecognized_relationship"
    expected = REL_ENDPOINTS[relation]
    if (r.get("subject_type"), r.get("object_type")) != expected:
        return "invalid_endpoint_types"
    for prefix, role, kind in (("subject", expected[0], NODE_PREFIX[expected[0]]),
                               ("object", expected[1], NODE_PREFIX[expected[1]])):
        if r.get(prefix + "_id") != id_for(kind, text_key(r.get(prefix + "_name", ""))):
            return "invalid_entity_id"
    if r.get("subject_id") == r.get("object_id"):
        return "self_edge"
    evidence = r.get("evidence_text", "")
    try:
        st, en = int(r.get("evidence_start", "")), int(r.get("evidence_end", ""))
    except (TypeError, ValueError):
        return "invalid_evidence_offset"
    if not (0 <= st < en <= len(body) and body[st:en] == evidence):
        return "evidence_not_verbatim"
    if r.get("subject_name", "") not in evidence or r.get("object_name", "") not in evidence:
        return "entity_not_in_evidence"
    if r.get("assertion_id") not in regenerated_ids:
        return "rule_cannot_be_reproduced"
    return ""


def screen_and_export() -> tuple[dict, list[dict], list[dict]]:
    """Evaluate every candidate; a machine-pass is not a Gold Standard label."""
    prepare()
    technical = audit(SimpleNamespace())
    articles = {r["article_id"]: r for r in csv_read(NEWS_DATA / "articles.csv")}
    docs = {r["article_id"]: r for r in csv_read(NEWS_DATA / "article_documents.csv")}
    assertions = csv_read(NEWS_DATA / "relation_assertions.csv")
    audits = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "edge_audit.csv")}
    outlets = source_index()
    grouped = defaultdict(list)
    screened = []
    errors = Counter()
    body_cache = {}
    regen = {}
    seen_article_triples = set()
    seen_assertion_ids = set()
    for r in assertions:
        aid = r.get("article_id", "")
        if aid not in body_cache:
            try:
                path = article_path(aid)
                body_cache[aid] = path.read_text(encoding="utf-8") if path.is_file() and not path.is_symlink() else None
            except (OSError, ValueError, UnicodeError):
                body_cache[aid] = None
        body = body_cache[aid]
        if aid not in regen:
            regen[aid] = {x["assertion_id"] for x in extract_candidates(articles[aid], body)} if aid in articles and body is not None else set()
        reason = _pass(r, articles.get(aid), docs.get(aid), audits.get(r.get("assertion_id")),
                       outlets.get(r.get("outlet_id")), body, regen[aid])
        key = (aid, r.get("subject_id"), r.get("relationship_type"), r.get("object_id"))
        if not reason and (r.get("assertion_id") in seen_assertion_ids or key in seen_article_triples):
            reason = "duplicate_assertion_or_duplicate_article_triple"
        seen_assertion_ids.add(r.get("assertion_id"))
        seen_article_triples.add(key)
        screened.append({"assertion_id": r.get("assertion_id", ""), "article_id": aid,
                         "relationship_type": r.get("relationship_type", ""),
                         "screening_status": "machine_pass" if not reason else "rejected",
                         "reason": reason})
        if reason:
            errors[reason] += 1
        else:
            grouped[(r["subject_id"], r["relationship_type"], r["object_id"])].append(r)
    # Deduplicate article assertions by triple and preserve every original source.
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    evidence: list[dict] = []
    for (sub_id, relation, obj_id), group in sorted(grouped.items()):
        r = group[0]
        for nid, name, ntype in ((sub_id, r["subject_name"], r["subject_type"]),
                                 (obj_id, r["object_name"], r["object_type"])):
            prior = nodes.get(nid)
            if prior and (prior["node_type"], text_key(prior["canonical_name"])) != (ntype, text_key(name)):
                raise RuntimeError(f"Inconsistent node identity: {nid}")
            nodes[nid] = {"node_id": nid, "node_type": ntype, "canonical_name": name,
                          "verification_status": "machine_screened", "dataset": DATASET}
        edge_id = id_for("NEWSEDGE", sub_id, relation, obj_id)
        src_urls = sorted(set(x["canonical_url"] for x in group))
        outlet_ids = sorted(set(x["outlet_id"] for x in group))
        edges.append({"edge_id": edge_id, "source_id": sub_id, "target_id": obj_id,
                      "relationship_type": relation, "verification_status": "machine_screened",
                      "evidence_count": len(group), "distinct_outlets": len(outlet_ids),
                      "outlet_ids": "|".join(outlet_ids), "source_urls": "|".join(src_urls),
                      "article_ids": "|".join(sorted(set(x["article_id"] for x in group))),
                      "dataset": DATASET})
        for x in group:
            evidence.append({"edge_id": edge_id, "assertion_id": x["assertion_id"],
                             "article_id": x["article_id"], "outlet_id": x["outlet_id"],
                             "source_url": x["canonical_url"], "evidence_text": x["evidence_text"],
                             "evidence_start": x["evidence_start"], "evidence_end": x["evidence_end"],
                             "screening_status": "machine_pass"})
    output = NEWS_DATA / "export" / "graph"
    csv_write(NEWS_DATA / "unified_screening.csv", screened, CHECK_FIELDS)
    csv_write(output / "nodes.csv", sorted(nodes.values(), key=lambda x: x["node_id"]), NODE_FIELDS)
    csv_write(output / "edges.csv", edges, EDGE_FIELDS)
    csv_write(output / "edge_evidence.csv", evidence, EVID_FIELDS)
    by_type = dict(Counter(r["relationship_type"] for r in edges))
    fetched = sum(r.get("fetch_status") == "fetched" for r in docs.values())
    stats = {
        "run_time": now(), "article_urls": len(articles), "fetched_articles": fetched,
        "candidate_assertions": len(assertions), "machine_checked_assertions": len(screened),
        "automatic_coverage_percent": 100.0 if assertions else None,
        "machine_pass_assertions": len(evidence), "machine_rejected_assertions": len(assertions) - len(evidence),
        "machine_screened_nodes": len(nodes), "machine_screened_edges": len(edges),
        "machine_screened_relationship_types": len(by_type), "edge_types": by_type,
        "edges_supported_by_two_or_more_outlets": sum(int(e["distinct_outlets"]) >= 2 for e in edges),
        "rejection_reasons": dict(errors), "targets": TARGETS,
        "machine_graph_target_gaps": {
            "nodes": max(0, TARGETS["nodes"] - len(nodes)),
            "edges": max(0, TARGETS["edges"] - len(edges)),
            "relationship_types": max(0, TARGETS["relationship_types"] - len(by_type)),
        },
        "count_targets_met_for_machine_graph": (
            len(nodes) >= TARGETS["nodes"] and len(edges) >= TARGETS["edges"] and len(by_type) >= TARGETS["relationship_types"]
        ),
        "independently_measured_precision_percent": None,
        "precision_gt_90_proven": False,
        "independent_gold_standard_labels_generated": False,
        "wiki_sources_used": 0,
        "meaning": "Automatic evidence screening, NOT validated >90% edge precision",
        "underlying_technical_audit": {
            "articles_auto_pass": technical.get("article_auto_pass"),
            "edge_auto_pass": technical.get("edge_auto_pass"),
        },
    }
    json_report("unified_graph.json", stats)
    return stats, list(nodes.values()), edges


def _connect():
    try:
        from neo4j import GraphDatabase
        from dotenv import dotenv_values
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install neo4j python-dotenv") from exc
    cfg = dotenv_values(ROOT / ".env")
    uri = os.environ.get("NEO4J_URI") or cfg.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USER") or cfg.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD") or cfg.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE") or cfg.get("NEO4J_DATABASE") or "neo4j"
    if not (uri and username and password):
        raise RuntimeError("NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD are required in .env")
    if not uri.startswith(("neo4j://", "neo4j+s://", "neo4j+ssc://", "bolt://", "bolt+s://", "bolt+ssc://")):
        raise RuntimeError("Neo4j URL scheme not supported")
    return GraphDatabase.driver(uri, auth=(username, password)), database


def import_neo4j(nodes: list[dict], edges: list[dict], *, batch_size: int, cleanup_legacy: bool = False) -> dict:
    if not nodes or not edges:
        raise RuntimeError("Zero machine-screened edges. Inspect reports/news_v2/unified_graph.json; Neo4j left unchanged.")
    driver, database = _connect()
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as s:
            s.run("CREATE CONSTRAINT news_v2_node_id IF NOT EXISTS FOR (n:NewsV2) REQUIRE n.node_id IS UNIQUE").consume()
            for ntype in NODE_PREFIX:
                group = [r for r in nodes if r["node_type"] == ntype]
                for start in range(0, len(group), batch_size):
                    batch = group[start:start + batch_size]
                    s.run(
                        f"UNWIND $rows AS row MERGE (n:NewsV2 {{node_id:row.node_id}}) SET n:NewsV2{ntype} "
                        "SET n.canonical_name=row.canonical_name, n.dataset='news_v2', "
                        "n.automated_screening='passed', n.entity_resolution='name_based_unconfirmed' "
                        "SET n.verification_status=coalesce(n.verification_status, 'machine_screened')",
                        rows=batch,
                    ).consume()
            for rel in sorted(RELATIONS):
                group = [r for r in edges if r["relationship_type"] == rel]
                for start in range(0, len(group), batch_size):
                    batch = group[start:start + batch_size]
                    prepared = [{**r,
                                 "evidence_count": int(r["evidence_count"]),
                                 "distinct_outlets": int(r["distinct_outlets"]),
                                 "source_urls": r["source_urls"].split("|"),
                                 "outlet_ids": r["outlet_ids"].split("|"),
                                 "article_ids": r["article_ids"].split("|")} for r in batch]
                    s.run(
                        f"UNWIND $rows AS row MATCH (a:NewsV2 {{node_id:row.source_id}}) "
                        f"MATCH (b:NewsV2 {{node_id:row.target_id}}) "
                        f"MERGE (a)-[r:{rel} {{edge_id:row.edge_id}}]->(b) "
                        "SET r.dataset='news_v2', r.automated_screening='passed', "
                        "r.verification_status='machine_screened', "
                        "r.precision_status='not_independently_measured', "
                        "r.source_urls=row.source_urls, r.article_ids=row.article_ids, "
                        "r.outlet_ids=row.outlet_ids, r.evidence_count=row.evidence_count, "
                        "r.distinct_outlets=row.distinct_outlets",
                        rows=prepared,
                    ).consume()
            if cleanup_legacy:
                # Only the obsolete dataset/label managed by the previous package.
                s.run("MATCH (n:NewsV2Auto {dataset:'news_v2_auto'}) "
                      "WHERE NOT n:NewsV2 DETACH DELETE n").consume()
            node_count = s.run("MATCH (n:NewsV2) WHERE n.dataset='news_v2' RETURN count(n) AS c").single()["c"]
            edge_count = s.run("MATCH (:NewsV2)-[r]->(:NewsV2) WHERE r.dataset='news_v2' RETURN count(r) AS c").single()["c"]
            type_count = s.run("MATCH (:NewsV2)-[r]->(:NewsV2) WHERE r.dataset='news_v2' RETURN count(DISTINCT type(r)) AS c").single()["c"]
    finally:
        driver.close()
    result = {"time": now(), "status": "completed", "database": database,
              "unified_graph_label": "NewsV2", "input_nodes": len(nodes), "input_edges": len(edges),
              "neo4j_nodes": node_count, "neo4j_edges": edge_count,
              "neo4j_relationship_types": type_count, "cleanup_old_auto_graph": cleanup_legacy,
              "precision_claim": "unmeasured; machine screening is not independent gold standard"}
    json_report("unified_neo4j.json", result)
    return result


def _discover(args):
    if args.discover == "none":
        return []
    reports = []
    if args.discover in ("rss", "both"):
        from .collect import discover
        reports.append(discover(SimpleNamespace(source=args.source or None, limit=args.discover_limit, delay=args.delay)))
    if args.discover in ("sitemap", "both"):
        from .backfill import backfill
        reports.append(backfill(SimpleNamespace(source=args.source or None,
                                                mode="both" if args.discover == "both" else "sitemap",
                                                limit=args.discover_limit,
                                                max_pages=args.max_pages, max_sitemaps=args.max_sitemaps,
                                                max_sitemap_attempts=args.max_attempts,
                                                sitemap=None, delay=args.delay)))
    return reports


def run(args) -> dict:
    prepare()
    discovery = _discover(args)
    fetch_report = []
    if not args.skip_fetch:
        from .fetch import fetch
        for batch_number in range(1, args.fetch_batches + 1):
            batch = fetch(SimpleNamespace(limit=args.fetch_limit, delay=args.delay,
                                          retry_failed=args.retry_failed))
            fetch_report.append(batch)
            print(f"[unified] fetch batch {batch_number}/{args.fetch_batches}: "
                  f"attempted={batch.get('attempted_this_run', 0)}, "
                  f"status={batch.get('statuses', {})}", file=sys.stderr, flush=True)
            if not batch.get("attempted_this_run", 0):
                break
    extraction = rebuild_assertions()
    screened, nodes, edges = screen_and_export()
    imported = None
    if not args.no_import:
        imported = import_neo4j(nodes, edges, batch_size=args.batch_size, cleanup_legacy=args.cleanup_legacy)
    result = {"stage": "news_v3_single_unified_automatic_run", "completed_at": now(),
              "discovery": discovery, "fetch": fetch_report,
              "extraction": extraction, "graph": screened, "neo4j": imported,
              "notice": "No manual review required to run. Counts are machine-screened, not independently Gold-verified."}
    json_report("unified_run.json", result)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    runp = sub.add_parser("run", help="Discover > fetch > extract > audit > export > one Neo4j graph")
    runp.add_argument("--discover", choices=["none", "rss", "sitemap", "both"], default="none",
                      help="Default none processes already collected publisher articles")
    runp.add_argument("--source", action="append", help="Publisher ID; repeat to select multiple sources")
    runp.add_argument("--discover-limit", type=int, default=1000)
    runp.add_argument("--max-sitemaps", type=int, default=10)
    runp.add_argument("--max-pages", type=int, default=10, help="Archive pages per publisher")
    runp.add_argument("--max-attempts", type=int, default=20)
    runp.add_argument("--fetch-limit", type=int, default=200, help="Articles attempted per checkpoint batch")
    runp.add_argument("--fetch-batches", type=int, default=5, help="Fetch batches, each saved durably by original fetch module")
    runp.add_argument("--delay", type=float, default=2)
    runp.add_argument("--batch-size", type=int, default=300)
    runp.add_argument("--retry-failed", action="store_true")
    runp.add_argument("--skip-fetch", action="store_true")
    runp.add_argument("--no-import", action="store_true")
    runp.add_argument("--cleanup-legacy", action="store_true", help="Delete only obsolete NewsV2Auto dataset nodes after successful import")
    sub.add_parser("status", help="Inspect unified graph/export/import status")
    args = p.parse_args(argv)
    if args.command == "run" and (args.discover_limit < 1 or args.fetch_limit < 1 or args.fetch_batches < 1 or args.max_sitemaps < 1 or args.max_pages < 1
                                  or args.max_attempts < 1 or args.delay < 0 or args.batch_size < 1):
        p.error("All limits and batch size must be positive; delay must be nonnegative")
    try:
        if args.command == "run":
            result = run(args)
        else:
            result = {}
            for name in ("unified_extraction.json", "unified_graph.json", "unified_neo4j.json"):
                path = REPORTS / name
                result[name] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, ValueError, FileNotFoundError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
