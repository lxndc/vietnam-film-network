#!/usr/bin/env python3
"""Make a truthful CSV/Neo4j progress snapshot without modifying graph data."""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TARGET = {"nodes": 2200, "edges": 5500, "relationship_types": 11}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def neo4j_counts(project: Path) -> dict:
    try:
        from dotenv import load_dotenv
        from neo4j import GraphDatabase
        load_dotenv(project / ".env", override=False)
        uri = os.getenv("NEO4J_URI", "").strip()
        user = os.getenv("NEO4J_USER", "").strip()
        password = os.getenv("NEO4J_PASSWORD", "")
        database = os.getenv("NEO4J_DATABASE", "neo4j").strip() or "neo4j"
        if not (uri and user and password):
            return {"connected": False, "error": "Neo4j environment variables not configured"}
        with GraphDatabase.driver(uri, auth=(user, password), connection_timeout=6) as driver:
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                nodes = session.run(
                    "MATCH (n:NewsV2) WHERE n.dataset = 'news_v2' RETURN count(n) AS n"
                ).single()["n"]
                edges = session.run(
                    "MATCH (:NewsV2)-[r]->(:NewsV2) WHERE r.dataset = 'news_v2' "
                    "RETURN count(r) AS e, count(DISTINCT type(r)) AS t"
                ).single()
        return {"connected": True, "database": database, "nodes": nodes,
                "edges": edges["e"], "relationship_types": edges["t"]}
    except Exception as exc:
        return {"connected": False, "error": f"{type(exc).__name__}: {str(exc)[:250]}"}


def create_report(project: Path) -> dict:
    folder = project / "data" / "news_v2"
    articles = read_csv(folder / "articles.csv")
    docs = read_csv(folder / "article_documents.csv")
    nodes = read_csv(folder / "export" / "graph" / "nodes.csv")
    edges = read_csv(folder / "export" / "graph" / "edges.csv")
    relations = Counter(e.get("relationship_type", "") for e in edges if e.get("relationship_type"))
    csv_metrics = {"nodes": len(nodes), "edges": len(edges),
                   "relationship_types": len(relations),
                   "relationship_distribution": dict(sorted(relations.items())),
                   "node_ids_unique": len({n.get("node_id") for n in nodes if n.get("node_id")}),
                   "edge_ids_unique": len({e.get("edge_id") for e in edges if e.get("edge_id")})}
    db = neo4j_counts(project)
    csv_ok = all(csv_metrics[k] >= v for k, v in TARGET.items())
    db_ok = db.get("connected") and all(db[k] >= v for k, v in TARGET.items())
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project": "vietnam-film-network",
        "target": TARGET,
        "discovered_urls": len(articles),
        "fetched_articles": sum(x.get("fetch_status") == "fetched" for x in docs),
        "export_csv": csv_metrics,
        "neo4j": db,
        "counts_pass_in_csv": bool(csv_ok),
        "counts_pass_in_neo4j": bool(db_ok),
        "counts_pass_both": bool(csv_ok and db_ok),
        "precision_status": "not_independently_established",
        "automated_screening_is_not_gold_standard_precision": True,
        "overall_academic_acceptance_claimed": False,
        "missing_from_csv": {k: max(0, v - csv_metrics[k]) for k, v in TARGET.items()},
        "missing_from_neo4j": ({k: max(0, v - db[k]) for k, v in TARGET.items()} if db.get("connected") else None),
    }
    return report


def display(value: object) -> str:
    return str(value) if value is not None else "Chưa kiểm tra được"


def write_report(project: Path, report: dict) -> None:
    outfile = project / "reports" / "news_v2" / "final_status.json"
    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = project / "docs" / "RESULTS_LATEST.md"
    latest.parent.mkdir(parents=True, exist_ok=True)
    a, b = report["export_csv"], report["neo4j"]
    rows = [
        ("Nodes", "nodes"),
        ("Edges", "edges"),
        ("Loại quan hệ", "relationship_types"),
    ]
    table = "\n".join(
        f"| {name} | {a[key]} | {display(b.get(key)) if b.get('connected') else 'Chưa kiểm tra được'} | {TARGET[key]} |"
        for name, key in rows
    )
    note = "ĐẠT 3 NGƯỠNG SỐ LƯỢNG (chưa xác nhận Precision)" if report["counts_pass_both"] else "CHƯA XÁC NHẬN ĐẠT 3 NGƯỠNG SỐ LƯỢNG"
    latest.write_text(
        "# Kết quả gần nhất – Vietnam Film Network\n\n"
        f"Cập nhật (UTC): `{report['timestamp_utc']}`\n\n"
        f"**Trạng thái:** {note}.\n\n"
        "| Chỉ số | CSV sau lọc máy | Neo4j | Mục tiêu |\n"
        "|---|---:|---:|---:|\n" + table + "\n\n"
        f"- URL đã phát hiện: **{report['discovered_urls']}**\n"
        f"- Bài báo tải thành công: **{report['fetched_articles']}**\n"
        f"- Kiểm tra kết nối Neo4j: **{'thành công' if b.get('connected') else 'không khả dụng'}**\n"
        "- Precision >90%: **chưa được chứng minh bằng đánh giá tham chiếu độc lập**.\n"
        "- Dữ liệu được sàng lọc bằng máy; không tự gán nhãn Gold Standard.\n\n"
        "Số liệu được ghi tự động từ CSV hiện có và truy vấn trực tiếp Neo4j, "
        "không phải dữ liệu giả lập hay kết quả mục tiêu.\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Wrote: {outfile.relative_to(project)}, {latest.relative_to(project)}")


def main() -> int:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not (project / "news_pipeline" / "unified.py").is_file():
        print("ERROR: Cannot locate unified.py in the project root", file=sys.stderr)
        return 2
    write_report(project, create_report(project))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
