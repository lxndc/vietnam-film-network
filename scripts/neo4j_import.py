import os
import csv
import json
import re
from pathlib import Path
from collections import defaultdict, Counter

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

ROOT = Path.cwd()
EXPORT = ROOT / "data/export/verified"
REPORTS = ROOT / "reports"

STATUS = os.getenv("GRAPH_IMPORT_STATUS", "staging").lower()
BATCH_SIZE = 500

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")

if not PASSWORD:
    raise RuntimeError("NEO4J_PASSWORD is missing")

if STATUS not in {"staging", "production"}:
    raise ValueError("Invalid GRAPH_IMPORT_STATUS")

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def read_list(value):
    if not value:
        return []

    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []

def convert_value(key, value):
    if value == "" or value is None:
        return None

    if key in {
        "aliases",
        "professions",
        "property_ids",
        "evidence_ids",
        "evidence_urls",
    }:
        return read_list(value)

    if key in {"release_year", "source_count", "shared_work_count"}:
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    if key in {"confidence_score", "weight"}:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    return value

def properties(row, excluded):
    result = {}

    for key, value in row.items():
        if key in excluded:
            continue

        converted = convert_value(key, value)

        if converted is not None:
            result[key] = converted

    result["dataset_status"] = STATUS
    return result

def batches(rows):
    for i in range(0, len(rows), BATCH_SIZE):
        yield rows[i:i + BATCH_SIZE]

def write_batch(tx, query, rows):
    result = tx.run(query, rows=rows)
    summary = result.consume()
    return summary.counters

def main():
    node_file = EXPORT / "nodes.csv"
    edge_file = EXPORT / "edges.csv"

    if not node_file.exists() or not edge_file.exists():
        raise FileNotFoundError("Graph export files are missing")

    nodes = read_csv(node_file)
    edges = read_csv(edge_file)

    # Validate nodes
    allowed_labels = {"Person", "Work", "Organization"}

    node_ids = set()
    nodes_by_label = defaultdict(list)

    for row in nodes:
        node_id = row.get("node_id")
        label = row.get("label")

        if not node_id or label not in allowed_labels:
            raise ValueError(f"Invalid Node: {row}")

        if node_id in node_ids:
            raise ValueError(f"Duplicate node_id: {node_id}")

        node_ids.add(node_id)

        nodes_by_label[label].append({
            "node_id": node_id,
            "props": properties(row, {"node_id", "label"})
        })

    # Validate edges
    edges_by_type = defaultdict(list)
    edge_ids = set()

    for row in edges:
        edge_id = row.get("edge_id")
        source_id = row.get("source_id")
        target_id = row.get("target_id")
        rel_type = row.get("relationship_type")

        if not edge_id or not source_id or not target_id:
            raise ValueError(f"Invalid Edge: {row}")

        if source_id not in node_ids or target_id not in node_ids:
            raise ValueError(f"Missing Edge endpoint: {edge_id}")

        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", rel_type or ""):
            raise ValueError(f"Invalid relationship type: {rel_type}")

        if edge_id in edge_ids:
            raise ValueError(f"Duplicate edge_id: {edge_id}")

        edge_ids.add(edge_id)

        edges_by_type[rel_type].append({
            "edge_id": edge_id,
            "source_id": source_id,
            "target_id": target_id,
            "props": properties(
                row,
                {
                    "source_id",
                    "target_id",
                    "relationship_type",
                }
            )
        })

    # Production acceptance gate
    if STATUS == "production":
        evaluation_file = REPORTS / "evaluation_report.json"

        if not evaluation_file.exists():
            raise RuntimeError("Gold-standard evaluation report missing")

        evaluation = json.loads(
            evaluation_file.read_text(encoding="utf-8")
        )

        precision = evaluation.get("edge_precision_percent")

        if not evaluation.get("acceptance") or precision is None or precision <= 90:
            raise RuntimeError("Edge Precision must be >90%")

        if len(nodes) < 4000:
            raise RuntimeError("Core Node target not met")

        if len(edges) < 10000:
            raise RuntimeError("Valid Edge target not met")

        if len(edges_by_type) < 20:
            raise RuntimeError("Relationship Type target not met")

    print("Nodes:", len(nodes))
    print("Edges:", len(edges))
    print("Relationship Types:", len(edges_by_type))
    print("Import status:", STATUS)

    with GraphDatabase.driver(
        URI,
        auth=(USER, PASSWORD)
    ) as driver:

        driver.verify_connectivity()

        with driver.session(database="neo4j") as session:

            # Create unique constraints
            for label in allowed_labels:
                query = (
                    f"CREATE CONSTRAINT {label.lower()}_node_id "
                    f"IF NOT EXISTS FOR (n:{label}) "
                    "REQUIRE n.node_id IS UNIQUE"
                )
                session.run(query).consume()

            # Import Nodes
            for label, rows in nodes_by_label.items():
                query = f"""
                UNWIND $rows AS row
                MERGE (n:{label} {{node_id: row.node_id}})
                SET n += row.props
                """

                for batch in batches(rows):
                    session.execute_write(
                        write_batch,
                        query,
                        batch
                    )

                print(f"Imported {label}: {len(rows)}")

            # Import Edges
            for rel_type, rows in edges_by_type.items():
                query = f"""
                UNWIND $rows AS row

                MATCH (s {{node_id: row.source_id}})
                MATCH (t {{node_id: row.target_id}})

                MERGE (s)-[r:{rel_type} {{edge_id: row.edge_id}}]->(t)

                SET r += row.props

                RETURN count(r) AS total
                """

                for batch in batches(rows):
                    session.execute_write(
                        write_batch,
                        query,
                        batch
                    )

                print(f"Imported {rel_type}: {len(rows)}")

            # Verify actual database counts
            node_result = session.run(
                "MATCH (n) WHERE n.dataset_status = $status "
                "RETURN count(n) AS total",
                status=STATUS
            ).single()

            edge_result = session.run(
                "MATCH ()-[r]->() "
                "WHERE r.dataset_status = $status "
                "RETURN count(r) AS total",
                status=STATUS
            ).single()

            actual_nodes = node_result["total"]
            actual_edges = edge_result["total"]

    report = {
        "dataset_status": STATUS,
        "export_nodes": len(nodes),
        "export_edges": len(edges),
        "database_nodes": actual_nodes,
        "database_edges": actual_edges,
        "relationship_types": dict(Counter(
            e["relationship_type"] for e in edges
        )),
        "node_count_matches": actual_nodes >= len(nodes),
        "edge_count_matches": actual_edges >= len(edges),
    }

    REPORTS.mkdir(exist_ok=True)

    (REPORTS / "neo4j_import_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if actual_nodes < len(nodes) or actual_edges < len(edges):
        raise RuntimeError("Database count is lower than export count")

if __name__ == "__main__":
    main()
