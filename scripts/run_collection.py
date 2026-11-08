from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import yaml

from collectors.common import (
    Checkpoint,
    append_jsonl_unique,
    build_session,
    load_settings,
    read_jsonl,
    setup_logging,
    utc_now,
)
from collectors.wikipedia_api import WikipediaCollector
from collectors.wikidata_client import WikidataClient


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect a small, restartable Vietnam-film data batch.")
    parser.add_argument("--limit", type=int, default=None, help="Số kết quả tối đa cho mỗi Wikipedia query và Work seed")
    parser.add_argument("--sources", choices=["all", "wikipedia", "wikidata"], default="all")
    parser.add_argument("--force", action="store_true", help="Chạy lại task đã có checkpoint; dữ liệu vẫn được deduplicate")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Xóa checkpoint trước khi chạy")
    return parser.parse_args()


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def main() -> None:
    args = parse_args()
    settings = load_settings(ROOT)
    paths = settings["paths"]
    for key in ["raw_wikipedia", "raw_wikidata", "processed", "checkpoints", "reports", "logs"]:
        (ROOT / paths[key]).mkdir(parents=True, exist_ok=True)
    setup_logging(ROOT / paths["logs"] / "collection.log")
    limit = args.limit or int(settings["collection"]["batch_size"])
    if limit < 1 or limit > 50:
        raise SystemExit("--limit phải nằm trong khoảng 1–50 cho batch thăm dò.")

    checkpoint_path = ROOT / paths["checkpoints"] / "collector_state.json"
    if args.reset_checkpoint and checkpoint_path.exists():
        checkpoint_path.unlink()
    checkpoint = Checkpoint(checkpoint_path)
    session = build_session()
    started_at = utc_now()
    tasks_run: list[str] = []

    if args.sources in {"all", "wikipedia"}:
        query_config = yaml.safe_load((ROOT / "config" / "search_queries.yaml").read_text(encoding="utf-8"))
        for language, queries in query_config["wikipedia"].items():
            collector = WikipediaCollector(session, settings, language)
            for item in queries:
                task = f"wikipedia:{language}:{item['id']}"
                if checkpoint.is_completed(task) and not args.force:
                    logging.info("Bỏ qua task đã hoàn tất: %s", task)
                    continue
                matches, pages = collector.collect_query(
                    item["id"], item["query"], item["scope"], limit
                )
                raw_wiki = ROOT / paths["raw_wikipedia"]
                added_matches = append_jsonl_unique(
                    raw_wiki / "search_matches.jsonl", matches, ("match_id",)
                )
                added_pages = append_jsonl_unique(
                    raw_wiki / "pages.jsonl", pages, ("document_id",)
                )
                checkpoint.mark_completed(task)
                tasks_run.append(task)
                logging.info("Lưu mới: %d match, %d page", added_matches, added_pages)

    if args.sources in {"all", "wikidata"}:
        client = WikidataClient(session, settings)
        raw_wd = ROOT / paths["raw_wikidata"]
        work_path = raw_wd / "work_seeds.jsonl"
        work_task = "wikidata:work_seeds"
        if not checkpoint.is_completed(work_task) or args.force:
            work_rows = client.collect_work_seeds(limit)
            append_jsonl_unique(work_path, work_rows, ("qid",))
            checkpoint.mark_completed(work_task)
            tasks_run.append(work_task)
        all_works = read_jsonl(work_path)
        work_qids = [row.get("qid", "") for row in all_works if row.get("qid")]
        credit_task = "wikidata:credits"
        if work_qids and (not checkpoint.is_completed(credit_task) or args.force):
            credit_rows = client.collect_credits(
                work_qids,
                int(settings["collection"]["wikidata_credit_row_limit"]),
            )
            append_jsonl_unique(
                raw_wd / "credit_candidates.jsonl",
                credit_rows,
                ("candidate_id",),
            )
            checkpoint.mark_completed(credit_task)
            tasks_run.append(credit_task)
        elif not work_qids:
            logging.warning("Không có Work QID để truy vấn credit; bỏ qua task credits.")

    report = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "batch_limit_per_search": limit,
        "tasks_run_this_session": tasks_run,
        "raw_counts": {
            "wikipedia_search_matches": line_count(ROOT / paths["raw_wikipedia"] / "search_matches.jsonl"),
            "wikipedia_pages": line_count(ROOT / paths["raw_wikipedia"] / "pages.jsonl"),
            "wikidata_work_seeds": line_count(ROOT / paths["raw_wikidata"] / "work_seeds.jsonl"),
            "wikidata_credit_candidates": line_count(ROOT / paths["raw_wikidata"] / "credit_candidates.jsonl"),
        },
        "note": "Đây là số liệu thu thập thô/ứng viên, không phải số Node hoặc Edge đã xác minh.",
    }
    report_path = ROOT / paths["reports"] / "collection_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Hoàn tất batch. Báo cáo: %s", report_path)
    logging.info("Raw counts: %s", report["raw_counts"])


if __name__ == "__main__":
    main()
