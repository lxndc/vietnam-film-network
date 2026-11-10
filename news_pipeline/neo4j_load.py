"""Load exclusively reviewed newspaper graph into separate :NewsV2 nodes.

Never reads legacy Wiki artifacts. Production mode is gated on independent Gold Standard
acceptance and size thresholds. Staging mode does not represent acceptance.
"""
from __future__ import annotations

import os
import re

from .common import NEWS_DATA, ROOT, csv_read, json_report, now
from .quality import status as compute_status, export_verified

ALLOWED_NODE_TYPES = {"Person", "Work", "Organization"}
ALLOWED_REL_TYPES = {
    "ACTED_IN", "VOICE_ACTED_IN", "DIRECTED", "PRODUCED", "EXECUTIVE_PRODUCED",
    "WROTE", "COMPOSED_MUSIC_FOR", "CINEMATOGRAPHED", "EDITED",
    "DISTRIBUTED_BY", "BROADCAST_BY", "PRODUCED_BY",
}


def load(args) -> dict:
    # Import is entirely self-contained in the newspaper namespace.
    # Rebuild the export only from current human reviews before every import.
    export_verified(args)
    checks = compute_status(args)
    mode = args.mode
    if mode == "production" and not checks["production_import_permitted"]:
        raise RuntimeError("NewsV2 production import BLOCKED: acceptance targets/independent precision not met")
    nodes = csv_read(NEWS_DATA / "export" / "verified" / "nodes.csv")
    edges = csv_read(NEWS_DATA / "export" / "verified" / "edges.csv")
    if not nodes or not edges:
        raise RuntimeError("No verified NewsV2 nodes/edges to import")
    if len({n["node_id"] for n in nodes}) != len(nodes):
        raise RuntimeError("Duplicate Node IDs")
    if len({e["edge_id"] for e in edges}) != len(edges):
        raise RuntimeError("Duplicate Edge IDs")
    ids = {x["node_id"] for x in nodes}
    for n in nodes:
        if n["node_type"] not in ALLOWED_NODE_TYPES or n["verification_status"] != "verified":
            raise RuntimeError("Non-NewsV2 node type or unverified node")
        if not (n["node_id"].startswith("PERSON_") or
                n["node_id"].startswith("WORK_") or n["node_id"].startswith("ORG_")):
            raise RuntimeError("Non-NewsV2 ID namespace")
    for e in edges:
        if (e["relationship_type"] not in ALLOWED_REL_TYPES
                or e["verification_status"] != "verified"
                or e["source_id"] not in ids or e["target_id"] not in ids
                or e["dataset"] != "news_v2"
                or int(e["evidence_count"]) < 1):
            raise RuntimeError("Invalid/unsupported NewsV2 edge")
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("pip install neo4j") from exc
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise RuntimeError("pip install python-dotenv") from exc
    cfg = dotenv_values(ROOT / ".env")
    uri = os.environ.get("NEO4J_URI") or cfg.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER") or cfg.get("NEO4J_USER")
    passwd = os.environ.get("NEO4J_PASSWORD") or cfg.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE") or cfg.get("NEO4J_DATABASE") or "neo4j"
    if not uri or not user or not passwd:
        raise RuntimeError("Missing NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD")
    driver = GraphDatabase.driver(uri, auth=(user, passwd))
    try:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            session.run("CREATE CONSTRAINT news_v2_id IF NOT EXISTS FOR (n:NewsV2) REQUIRE n.node_id IS UNIQUE").consume()
            for n in nodes:
                label = n["node_type"]  # strictly allowlisted above
                session.run(
                    f"MERGE (n:NewsV2:{label} {{node_id: $nid}}) "
                    "SET n.canonical_name = $name, n.dataset = 'news_v2', "
                    "n.dataset_status = $mode, n.verification_status = 'verified'",
                    nid=n["node_id"], name=n["canonical_name"], mode=mode,
                ).consume()
            for e in edges:
                rel = e["relationship_type"]  # strictly allowlisted above
                session.run(
                    f"MATCH (a:NewsV2 {{node_id:$sid}}), (b:NewsV2 {{node_id:$tid}}) "
                    f"MERGE (a)-[r:{rel} {{edge_id:$eid}}]->(b) "
                    "SET r.dataset = 'news_v2', r.dataset_status = $mode, "
                    "r.verification_status = 'verified', r.source_urls = $urls, "
                    "r.evidence_count = $evidence_count, r.article_ids = $article_ids",
                    sid=e["source_id"], tid=e["target_id"], eid=e["edge_id"], mode=mode,
                    urls=e["source_urls"].split("|"), article_ids=e["article_ids"].split("|"),
                    evidence_count=int(e["evidence_count"]),
                ).consume()
            db_nodes = session.run(
                "MATCH (n:NewsV2 {dataset_status:$mode}) RETURN count(n) AS c",
                mode=mode,
            ).single()["c"]
            db_edges = session.run(
                "MATCH (:NewsV2)-[r]->(:NewsV2) WHERE r.dataset='news_v2' "
                "AND r.dataset_status=$mode RETURN count(r) AS c",
                mode=mode,
            ).single()["c"]
    finally:
        driver.close()
    result = {"stage": "news_v2_neo4j_import", "mode": mode,
              "export_nodes": len(nodes), "export_edges": len(edges),
              "neo4j_mode_nodes": db_nodes, "neo4j_mode_edges": db_edges,
              "dataset": "news_v2", "legacy_wiki_read_or_merged": False, "completed_at": now()}
    json_report(f"neo4j_{mode}.json", result)
    return result
