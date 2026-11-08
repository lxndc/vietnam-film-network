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
    stable_id,
    utc_now,
)
from collectors.wikipedia_api import WikipediaCollector, is_index_search_match
from collectors.wikidata_client import WikidataClient
from scripts.build_candidates import main as build_candidates
from scripts.validate_batch import main as validate_batch

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incremental large-scale collection expansion for Vietnam Film Network."
    )
    parser.add_argument("--sources", choices=["all", "wikipedia", "wikidata"], default="all")
    parser.add_argument("--max-works", type=int, default=4000,
                        help="Maximum unique Wikidata Work seeds to retain in this corpus (not verified Nodes).")
    parser.add_argument("--work-page-size", type=int, default=None,
                        help="Wikidata seed page size, 1-500; defaults from settings.")
    parser.add_argument("--wikipedia-limit", type=int, default=100,
                        help="Results per configured Wikipedia query (1-500, fetched in pages of 50).")
    parser.add_argument("--credit-batch-size", type=int, default=None,
                        help="Number of Work QIDs per Wikidata credit query.")
    parser.add_argument("--credit-row-limit", type=int, default=None,
                        help="Maximum relation rows per credit batch.")
    parser.add_argument("--force", action="store_true",
                        help="Repeat expansion tasks; existing JSONL rows remain deduplicated.")
    parser.add_argument("--no-rebuild", action="store_true",
                        help="Do not rebuild processed candidates after collection.")
    return parser.parse_args()


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def run_wikipedia(session, settings, checkpoint, paths, limit: int, force: bool) -> list[str]:
    query_config = yaml.safe_load((ROOT / "config" / "search_queries.yaml").read_text(encoding="utf-8"))
    tasks_run: list[str] = []
    raw_dir = ROOT / paths["raw_wikipedia"]
    for language, queries in query_config["wikipedia"].items():
        collector = WikipediaCollector(session, settings, language)
        for item in queries:
            task = f"expanded:v3:wikipedia:{language}:{item['id']}:limit{limit}"
            if checkpoint.is_completed(task) and not force:
                logging.info("Bỏ qua Wikipedia task đã checkpoint: %s", task)
                continue
            matches, pages = collector.collect_query(item["id"], item["query"], item["scope"], limit)
            added_matches = append_jsonl_unique(raw_dir / "search_matches.jsonl", matches, ("match_id",))
            added_pages = append_jsonl_unique(raw_dir / "pages.jsonl", pages, ("document_id",))
            checkpoint.mark_completed(task)
            tasks_run.append(task)
            logging.info("Wikipedia %s/%s: +%d matches, +%d pages", language, item["id"], added_matches, added_pages)
    return tasks_run



def extract_wikipedia_work_qids(matches: list[dict], pages: list[dict]) -> set[str]:
    """Return QIDs only from Wikipedia pages explicitly collected with Work scope."""
    page_by_key = {
        (row.get("language"), str(row.get("page_id"))): row for row in pages
    }
    qids: set[str] = set()
    for match in matches:
        if match.get("scope") != "work" or is_index_search_match(match):
            continue
        page = page_by_key.get((match.get("language"), str(match.get("page_id"))), {})
        qid = str(page.get("wikidata_id") or "")
        if qid.startswith("Q") and qid[1:].isdigit():
            qids.add(qid)
    return qids

def run_wikidata(session, settings, checkpoint, paths, max_works: int,
                 page_size: int, credit_batch_size: int,
                 credit_row_limit: int, force: bool) -> tuple[list[str], int, int, int, int]:
    tasks_run: list[str] = []
    raw_dir = ROOT / paths["raw_wikidata"]
    raw_wikipedia_dir = ROOT / paths["raw_wikipedia"]
    work_path = raw_dir / "work_seeds.jsonl"
    credit_path = raw_dir / "credit_candidates.jsonl"
    client = WikidataClient(session, settings)

    if not 1 <= page_size <= 500:
        raise ValueError("--work-page-size must be between 1 and 500")
    if not 1 <= credit_batch_size <= 200:
        raise ValueError("--credit-batch-size must be between 1 and 200")
    if max_works < 1:
        raise ValueError("--max-works must be >= 1")

    # ORDER BY ?work + OFFSET creates deterministic, resumable pages for a fixed WDQS snapshot.
    for offset in range(0, max_works, page_size):
        task = f"expanded:v3:wikidata:work-seeds:offset{offset}:limit{page_size}"
        if checkpoint.is_completed(task) and not force:
            logging.info("Bỏ qua Wikidata seed page đã checkpoint: offset=%d", offset)
            continue
        rows = client.collect_work_seeds(page_size, offset=offset)
        added = append_jsonl_unique(work_path, rows, ("qid",))
        checkpoint.mark_completed(task)
        tasks_run.append(task)
        logging.info("Wikidata seeds offset=%d: fetched=%d, added=%d", offset, len(rows), added)
        if len(rows) < page_size:
            logging.info("Wikidata trả về ít hơn page_size; đã chạm cuối tập kết quả seed.")
            break

    all_work_rows = read_jsonl(work_path)
    unique_by_qid = {row.get("qid"): row for row in all_work_rows if row.get("qid")}

    # Critical coverage fix: Wikipedia Work-scope pages often have a Wikidata
    # sitelink even when they fail the narrower country/type seed query. Use
    # those QIDs to retrieve credits as well, but keep the original Work
    # candidates and their source evidence unchanged for review.
    wiki_matches = read_jsonl(raw_wikipedia_dir / "search_matches.jsonl")
    wiki_pages = read_jsonl(raw_wikipedia_dir / "pages.jsonl")
    wikipedia_work_qids = extract_wikipedia_work_qids(wiki_matches, wiki_pages)

    wikidata_seed_qids = set(unique_by_qid)
    combined_qids = sorted(wikidata_seed_qids | wikipedia_work_qids)
    selected_qids = combined_qids[:max_works]
    if not selected_qids:
        logging.warning("Không có Work QID từ Wikidata seeds hoặc Wikipedia sitelinks; bỏ qua credits.")
        return tasks_run, 0, 0, len(unique_by_qid), len(wikipedia_work_qids)

    logging.info(
        "Credit QID coverage: Wikidata seeds=%d, Wikipedia Work QIDs=%d, unique union=%d, selected=%d",
        len(wikidata_seed_qids), len(wikipedia_work_qids), len(combined_qids), len(selected_qids),
    )

    for start in range(0, len(selected_qids), credit_batch_size):
        batch = selected_qids[start:start + credit_batch_size]
        batch_id = stable_id("credit-batch-v3", *batch)
        task = f"expanded:v3:wikidata:credits:{batch_id}"
        if checkpoint.is_completed(task) and not force:
            logging.info("Bỏ qua credit batch đã checkpoint: %d/%d", start + 1, len(selected_qids))
            continue
        rows = client.collect_credits(batch, credit_row_limit)
        added = append_jsonl_unique(credit_path, rows, ("candidate_id",))
        checkpoint.mark_completed(task)
        tasks_run.append(task)
        logging.info("Credit batch %d-%d/%d: fetched=%d, added=%d", start + 1, start + len(batch), len(selected_qids), len(rows), added)
        if len(rows) >= credit_row_limit:
            logging.warning(
                "Credit batch chạm row limit (%d). Cần chạy lại batch với kích thước Work nhỏ hơn để tránh truncation.",
                credit_row_limit,
            )

    return tasks_run, len(selected_qids), line_count(credit_path), len(wikidata_seed_qids), len(wikipedia_work_qids)


def main() -> None:
    args = parse_args()
    settings = load_settings(ROOT)
    paths = settings["paths"]
    for key in ["raw_wikipedia", "raw_wikidata", "processed", "checkpoints", "reports", "logs"]:
        (ROOT / paths[key]).mkdir(parents=True, exist_ok=True)
    setup_logging(ROOT / paths["logs"] / "expansion.log")

    page_size = args.work_page_size or int(settings["collection"].get("wikidata_seed_page_size", 250))
    credit_batch_size = args.credit_batch_size or int(settings["collection"].get("wikidata_credit_batch_size", 100))
    credit_row_limit = args.credit_row_limit or int(settings["collection"].get("wikidata_credit_row_limit_per_batch", 5000))
    if not 1 <= args.wikipedia_limit <= 500:
        raise SystemExit("--wikipedia-limit must be between 1 and 500.")

    checkpoint_path = ROOT / paths["checkpoints"] / "collector_state.json"
    checkpoint = Checkpoint(checkpoint_path)
    session = build_session()
    started_at = utc_now()
    tasks_run: list[str] = []
    selected_work_count = 0
    credit_count = 0
    wikidata_seed_count = 0
    wikipedia_work_qid_count = 0

    if args.sources in {"all", "wikipedia"}:
        tasks_run.extend(run_wikipedia(session, settings, checkpoint, paths, args.wikipedia_limit, args.force))

    if args.sources in {"all", "wikidata"}:
        (wd_tasks, selected_work_count, credit_count,
         wikidata_seed_count, wikipedia_work_qid_count) = run_wikidata(
            session, settings, checkpoint, paths, args.max_works,
            page_size, credit_batch_size, credit_row_limit, args.force,
        )
        tasks_run.extend(wd_tasks)

    if not args.no_rebuild:
        build_candidates()
        validate_batch()

    processed = ROOT / paths["processed"]
    counts = {
        "work_candidates": line_count(processed / "work_candidates.jsonl"),
        "person_organization_candidates": line_count(processed / "entity_candidates.jsonl"),
        "relation_candidates": line_count(processed / "relation_candidates.jsonl"),
        "wikidata_work_seeds_selected": wikidata_seed_count,
        "wikipedia_work_qids_for_credits": wikipedia_work_qid_count,
        "unique_work_qids_for_credits_selected": selected_work_count,
        "wikidata_credit_candidates_total": credit_count,
    }
    report = {
        "started_at": started_at,
        "finished_at": utc_now(),
        "targets": settings.get("targets", {}),
        "collection_parameters": {
            "sources": args.sources,
            "max_works": args.max_works,
            "work_page_size": page_size,
            "wikipedia_limit_per_query": args.wikipedia_limit,
            "credit_batch_size": credit_batch_size,
            "credit_row_limit_per_batch": credit_row_limit,
        },
        "tasks_run_this_session": tasks_run,
        "candidate_counts": counts,
        "note": (
            "Candidate totals are not verified Core Nodes or valid Edges. Only manually reviewed, "
            "evidence-backed and deduplicated graph records count toward acceptance."
        ),
    }
    report_path = ROOT / paths["reports"] / "expansion_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Hoàn tất mở rộng. Báo cáo: %s", report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
