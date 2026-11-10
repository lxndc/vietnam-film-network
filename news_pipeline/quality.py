"""Full-coverage automated audit and independent Gold Standard workflow."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import hashlib
import math
import random

from .common import (NEWS_DATA, article_path, assert_no_wiki, csv_read, csv_write,
                     id_for, json_report, now, require_news_url, source_index)

ARTICLE_AUDIT_FIELDS = ["article_id", "outlet_id", "canonical_url", "audit_status", "audit_reason",
                        "original_article_fetched", "wiki_contamination", "checked_at"]
EDGE_AUDIT_FIELDS = ["assertion_id", "article_id", "outlet_id", "relationship_type", "subject_id",
                     "object_id", "canonical_url", "auto_review_status", "checks_passed", "checks_failed",
                     "human_review_required", "checked_at"]
REVIEW_FIELDS = ["assertion_id", "article_id", "outlet_id", "relationship_type", "subject_name",
                 "object_name", "evidence_text", "canonical_url", "auto_review_status",
                 "supports_exact_edge", "scope_decision", "reviewer", "review_notes", "source_independence", "identity_confirmed",
                 "review_decision"]
GOLD_FIELDS = ["assertion_id", "article_id", "outlet_id", "relationship_type", "subject_name",
               "object_name", "evidence_text", "canonical_url", "reviewer_a", "reviewer_a_label",
               "reviewer_b", "reviewer_b_label", "adjudicator", "adjudicated_label",
               "evidence_checked_url", "review_notes"]
NODE_FIELDS = ["node_id", "node_type", "canonical_name", "verification_status", "source"]
EDGE_FIELDS = ["edge_id", "source_id", "target_id", "relationship_type", "verification_status",
               "evidence_count", "article_ids", "source_urls", "dataset"]
EVIDENCE_FIELDS = ["edge_id", "assertion_id", "article_id", "source_url", "evidence_text", "reviewer"]


def audit(args) -> dict:
    src = source_index()
    articles = csv_read(NEWS_DATA / "articles.csv")
    docs = {x["article_id"]: x for x in csv_read(NEWS_DATA / "article_documents.csv")}
    candidates = csv_read(NEWS_DATA / "relation_assertions.csv")
    article_by_id = {x["article_id"]: x for x in articles}
    article_checks = []
    for article in articles:
        checks = []
        source = src.get(article.get("outlet_id"))
        if not source:
            checks.append("unknown_publisher")
        else:
            try:
                require_news_url(article.get("canonical_url", ""), source["base_url"])
            except ValueError:
                checks.append("forbidden_url_or_cross_publisher")
        doc = docs.get(article["article_id"])
        if not doc or doc.get("fetch_status") != "fetched":
            checks.append("original_article_not_fetched")
        elif not article_path(article["article_id"]).is_file():
            checks.append("article_text_not_found")
        elif int(doc.get("content_chars") or 0) < 250:
            checks.append("too_short")
        else:
            body = article_path(article["article_id"]).read_text(encoding="utf-8")
            if hashlib.sha256(body.encode()).hexdigest() != doc.get("sha256"):
                checks.append("body_hash_mismatch")
        article_checks.append({
            "article_id": article["article_id"], "outlet_id": article.get("outlet_id", ""),
            "canonical_url": article.get("canonical_url", ""),
            "audit_status": "auto_pass" if not checks else "needs_review",
            "audit_reason": ";".join(checks),
            "original_article_fetched": "yes" if doc and doc.get("fetch_status") == "fetched" else "no",
            "wiki_contamination": "no" if "forbidden_url_or_cross_publisher" not in checks else "possible",
            "checked_at": now(),
        })
    csv_write(NEWS_DATA / "article_audit.csv", article_checks, ARTICLE_AUDIT_FIELDS)
    passed_articles = {r["article_id"] for r in article_checks if r["audit_status"] == "auto_pass"}
    seen = set()
    edge_checks = []
    for assertion in candidates:
        failures = []
        aid = assertion.get("article_id")
        article = article_by_id.get(aid)
        if not article or aid not in passed_articles:
            failures.append("article_failed_audit")
        if not assertion.get("evidence_text", "").strip():
            failures.append("evidence_empty")
        if not assertion.get("subject_name") or not assertion.get("object_name"):
            failures.append("entity_name_missing")
        if not assertion.get("subject_id") or not assertion.get("object_id"):
            failures.append("endpoint_missing")
        if assertion.get("subject_id") == assertion.get("object_id"):
            failures.append("self_edge")
        source = src.get(assertion.get("outlet_id"))
        if not source:
            failures.append("unknown_outlet")
        else:
            try:
                require_news_url(assertion.get("canonical_url", ""), source["base_url"])
            except ValueError:
                failures.append("wiki_or_wrong_publisher")
        if article and assertion.get("canonical_url") != article.get("canonical_url"):
            failures.append("article_url_mismatch")
        if aid and aid in passed_articles:
            body = article_path(aid).read_text(encoding="utf-8")
            evidence = assertion.get("evidence_text", "")
            if evidence not in body:
                failures.append("evidence_not_in_original_body")
            try:
                start = int(assertion.get("evidence_start", ""))
                end = int(assertion.get("evidence_end", ""))
                if start < 0 or end <= start or body[start:end] != evidence:
                    failures.append("evidence_offsets_do_not_match_original_body")
            except (TypeError, ValueError):
                failures.append("invalid_evidence_offsets")
            if not (assertion.get("subject_name", "") in evidence and
                    assertion.get("object_name", "") in evidence):
                failures.append("subject_or_object_not_in_sentence")
            if assertion.get("extraction_method") != "deterministic_explicit_role_rule":
                failures.append("unrecognized_extractor")
        key = (aid, assertion.get("subject_id"), assertion.get("relationship_type"), assertion.get("object_id"))
        if key in seen:
            failures.append("duplicate_assertion_same_article")
        seen.add(key)
        checks_passed = [
            "publisher_whitelist", "no_wiki_url", "fetched_original",
            "body_integrity_hash", "evidence_verbatim", "explicit_role_rule",
            "nonempty_endpoints", "no_article_duplicate",
        ] if not failures else []
        edge_checks.append({
            "assertion_id": assertion["assertion_id"], "article_id": aid or "",
            "outlet_id": assertion.get("outlet_id", ""),
            "relationship_type": assertion.get("relationship_type", ""),
            "subject_id": assertion.get("subject_id", ""),
            "object_id": assertion.get("object_id", ""),
            "canonical_url": assertion.get("canonical_url", ""),
            "auto_review_status": "auto_pass_needs_independent_review" if not failures else "needs_review",
            "checks_passed": ";".join(checks_passed), "checks_failed": ";".join(failures),
            "human_review_required": "yes", "checked_at": now(),
        })
    csv_write(NEWS_DATA / "edge_audit.csv", edge_checks, EDGE_AUDIT_FIELDS)
    result = {
        "stage": "news_100pct_automated_audit", "date": now(),
        "articles_total": len(articles), "articles_audited": len(article_checks),
        "article_auto_pass": sum(x["audit_status"] == "auto_pass" for x in article_checks),
        "candidate_edges_total": len(candidates), "edges_audited": len(edge_checks),
        "edge_auto_pass": sum(x["auto_review_status"].startswith("auto_pass") for x in edge_checks),
        "automatic_audit_coverage_percent": (100.0 if len(candidates) == len(edge_checks)
                                              else 0.0) if candidates else None,
        "article_audit_coverage_percent": (100.0 if len(articles) == len(article_checks)
                                           else 0.0) if articles else None,
        "edges_independently_verified": 0, "wiki_sources_used": 0,
        "IMPORTANT": "100% machine-check coverage is NOT 100% factual accuracy or Gold Standard validation.",
    }
    json_report("audit.json", result)
    return result


def prepare_reviews(args) -> dict:
    assertions = csv_read(NEWS_DATA / "relation_assertions.csv")
    audits = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "edge_audit.csv")}
    if len(audits) != len(assertions):
        raise RuntimeError("Run audit before preparing reviews; audit must cover every assertion")
    path = NEWS_DATA / "edge_review.csv"
    old = {r["assertion_id"]: r for r in csv_read(path)}
    rows = []
    for r in assertions:
        audit_row = audits.get(r["assertion_id"], {})
        existing = old.get(r["assertion_id"], {})
        row = {
            "assertion_id": r["assertion_id"], "article_id": r["article_id"],
            "outlet_id": r["outlet_id"], "relationship_type": r["relationship_type"],
            "subject_name": r["subject_name"], "object_name": r["object_name"],
            "evidence_text": r["evidence_text"], "canonical_url": r["canonical_url"],
            "auto_review_status": audit_row.get("auto_review_status", "needs_review"),
            "supports_exact_edge": existing.get("supports_exact_edge", "pending"),
            "scope_decision": existing.get("scope_decision", "scope_uncertain"),
            "reviewer": existing.get("reviewer", ""), "review_notes": existing.get("review_notes", ""),
            "source_independence": existing.get("source_independence", "not_assessed"),
            "identity_confirmed": existing.get("identity_confirmed", "pending"),
            "review_decision": existing.get("review_decision", "pending"),
        }
        rows.append(row)
    csv_write(path, rows, REVIEW_FIELDS)
    result = {"stage": "news_human_review_queue", "rows": len(rows), "existing_reviews_retained": len(old),
              "note": "No automatic yes/correct assignments."}
    json_report("reviews.json", result)
    return result


def create_gold(args) -> dict:
    path = NEWS_DATA / "gold_standard_sample.csv"
    if path.exists() and not args.force:
        raise RuntimeError("Gold Standard already exists; refusing to overwrite independent reviews")
    audits = csv_read(NEWS_DATA / "edge_audit.csv")
    good_ids = {r["assertion_id"] for r in audits if r["auto_review_status"] == "auto_pass_needs_independent_review"}
    assertions = [r for r in csv_read(NEWS_DATA / "relation_assertions.csv")
                  if r["assertion_id"] in good_ids]
    if not assertions:
        raise RuntimeError("No automatically eligible assertions; cannot create Gold Standard")
    by_group = defaultdict(list)
    for r in assertions:
        by_group[(r["relationship_type"], r["outlet_id"])].append(r)
    rng = random.Random(args.seed)
    for subset in by_group.values():
        rng.shuffle(subset)
    chosen = []
    # Round-robin groups, one per non-empty stratum before adding extras.
    while len(chosen) < min(args.size, len(assertions)) and any(by_group.values()):
        for group in sorted(by_group):
            if by_group[group] and len(chosen) < min(args.size, len(assertions)):
                chosen.append(by_group[group].pop())
    sample = []
    for r in chosen:
        sample.append({
            "assertion_id": r["assertion_id"], "article_id": r["article_id"],
            "outlet_id": r["outlet_id"], "relationship_type": r["relationship_type"],
            "subject_name": r["subject_name"], "object_name": r["object_name"],
            "evidence_text": r["evidence_text"], "canonical_url": r["canonical_url"],
            "reviewer_a": "", "reviewer_a_label": "", "reviewer_b": "",
            "reviewer_b_label": "", "adjudicator": "", "adjudicated_label": "",
            "evidence_checked_url": "", "review_notes": "",
        })
    csv_write(path, sample, GOLD_FIELDS)
    result = {"stage": "news_gold_standard_sampling", "sample_size": len(sample),
              "seed": args.seed, "stratification": "relation_type_and_outlet_round_robin",
              "unreviewed": len(sample), "wiki_sample_reused": False,
              "notice": "Sample labels are deliberately blank until two independent reviews and adjudication."}
    json_report("gold_sample.json", result)
    return result


def wilson_lower(success: int, total: int, z=1.9599639845) -> float:
    if total == 0:
        return 0.0
    p = success / total
    denom = 1 + z*z/total
    center = p + z*z/(2*total)
    radius = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))
    return (center-radius)/denom


def evaluate(args) -> dict:
    samples = csv_read(NEWS_DATA / "gold_standard_sample.csv")
    if not samples:
        raise RuntimeError("Gold Standard sample missing")
    assert_no_wiki(samples, ("canonical_url", "evidence_checked_url"))
    audits = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "edge_audit.csv")}
    assertions = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "relation_assertions.csv")}
    allowed = {"correct", "incorrect", "uncertain"}
    errors = []
    if len({x.get("assertion_id") for x in samples}) != len(samples):
        errors.append("Duplicate Gold Standard assertion IDs")
    for r in samples:
        source_assertion = assertions.get(r.get("assertion_id"))
        audit_row = audits.get(r.get("assertion_id"))
        if not source_assertion or not audit_row or audit_row.get("auto_review_status") != "auto_pass_needs_independent_review":
            errors.append(f"{r.get('assertion_id')}: not a news-v2 audited candidate")
        elif (r.get("article_id") != source_assertion.get("article_id")
              or r.get("canonical_url") != source_assertion.get("canonical_url")
              or r.get("relationship_type") != source_assertion.get("relationship_type")):
            errors.append(f"{r.get('assertion_id')}: sample provenance mismatch")
        a, b, final = (str(r.get(k, "")).lower().strip() for k in
                       ("reviewer_a_label", "reviewer_b_label", "adjudicated_label"))
        name_a, name_b = (str(r.get(k, "")).strip() for k in ("reviewer_a", "reviewer_b"))
        if a not in allowed or b not in allowed or final not in allowed:
            errors.append(f"{r['assertion_id']}: labels pending/invalid")
        if not name_a or not name_b or name_a.casefold() == name_b.casefold():
            errors.append(f"{r['assertion_id']}: two distinct reviewers required")
        if not r.get("evidence_checked_url") or not r.get("review_notes"):
            errors.append(f"{r['assertion_id']}: evidence verification and notes required")
        if a != b and not r.get("adjudicator"):
            errors.append(f"{r['assertion_id']}: adjudicator required for disagreement")
        if r.get("evidence_checked_url") != r.get("canonical_url"):
            errors.append(f"{r['assertion_id']}: original article URL mismatch")
    correct = sum(r.get("adjudicated_label", "").lower().strip() == "correct" for r in samples)
    total = len(samples)
    status = "calculable" if not errors and total >= args.min_sample else "not_calculable"
    precision = correct/total*100 if status == "calculable" else None
    wilson = wilson_lower(correct, total)*100 if status == "calculable" else None
    per_type, per_outlet = {}, {}
    reviewer_agreement = None
    if status == "calculable":
        for field, output in (("relationship_type", per_type), ("outlet_id", per_outlet)):
            for value in sorted({r.get(field, "") for r in samples}):
                subset = [r for r in samples if r.get(field, "") == value]
                successes = sum(r["adjudicated_label"].lower().strip() == "correct" for r in subset)
                output[value] = {"sample_size": len(subset), "correct": successes,
                                 "precision_percent": round(successes/len(subset)*100, 2)}
        reviewer_agreement = round(
            sum(r["reviewer_a_label"].lower().strip() == r["reviewer_b_label"].lower().strip()
                for r in samples) / total * 100, 2)
    result = {"stage": "independent_gold_standard_evaluation", "status": status,
              "sample_size": total, "required_min_sample": args.min_sample,
              "correct_count": correct if status == "calculable" else None,
              "precision_percent": precision, "wilson_lower_95_percent": wilson,
              "precision_above_90": precision > 90 if precision is not None else False,
              "gold_standard_complete": bool(status == "calculable"),
              "per_relationship_type": per_type,
              "per_outlet": per_outlet,
              "raw_reviewer_agreement_percent": reviewer_agreement,
              "acceptance": bool(status == "calculable" and precision > 90),
              "errors_count": len(errors), "error_examples": errors[:15],
              "note": "Labels are not generated by the pipeline. Review must be genuinely independent."}
    json_report("evaluation.json", result)
    return result


def export_verified(args) -> dict:
    audits = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "edge_audit.csv")}
    reviews = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "edge_review.csv")}
    assertions = csv_read(NEWS_DATA / "relation_assertions.csv")
    src = source_index()
    accepted = []
    seen = set()
    for r in assertions:
        k = r["assertion_id"]
        audit = audits.get(k)
        human = reviews.get(k)
        if not audit or not human or audit["auto_review_status"] != "auto_pass_needs_independent_review":
            continue
        if not (human.get("supports_exact_edge") == "yes"
                and human.get("scope_decision") in {"include_vietnam", "include_coproduction"}
                and human.get("source_independence") == "independent"
                and human.get("identity_confirmed") == "yes"
                and human.get("review_decision") == "correct"
                and human.get("reviewer", "").strip()
                and human.get("review_notes", "").strip()):
            continue
        require_news_url(r["canonical_url"], src[r["outlet_id"]]["base_url"])
        edge_key = (r["subject_id"], r["relationship_type"], r["object_id"])
        # Assertions about same edge in multiple news articles are merged; evidence is preserved.
        accepted.append(r)
    by_edge = defaultdict(list)
    for r in accepted:
        by_edge[(r["subject_id"], r["relationship_type"], r["object_id"])].append(r)
    nodes = {}
    edges, evidence = [], []
    for (sub_id, relation, obj_id), group in sorted(by_edge.items()):
        row = group[0]
        nodes[sub_id] = {"node_id": sub_id, "node_type": row["subject_type"],
                         "canonical_name": row["subject_name"], "verification_status": "verified",
                         "source": "newspaper_only"}
        nodes[obj_id] = {"node_id": obj_id, "node_type": row["object_type"],
                         "canonical_name": row["object_name"], "verification_status": "verified",
                         "source": "newspaper_only"}
        edge_id = id_for("EDGE", sub_id, relation, obj_id)
        urls = sorted({r["canonical_url"] for r in group})
        aids = sorted({r["article_id"] for r in group})
        edges.append({"edge_id": edge_id, "source_id": sub_id, "target_id": obj_id,
                      "relationship_type": relation, "verification_status": "verified",
                      "evidence_count": len(group), "article_ids": "|".join(aids),
                      "source_urls": "|".join(urls), "dataset": "news_v2"})
        for r in group:
            evidence.append({"edge_id": edge_id, "assertion_id": r["assertion_id"],
                             "article_id": r["article_id"], "source_url": r["canonical_url"],
                             "evidence_text": r["evidence_text"],
                             "reviewer": reviews[r["assertion_id"]]["reviewer"]})
    base = NEWS_DATA / "export" / "verified"
    csv_write(base / "nodes.csv", sorted(nodes.values(), key=lambda x:x["node_id"]), NODE_FIELDS)
    csv_write(base / "edges.csv", edges, EDGE_FIELDS)
    csv_write(base / "edge_evidence.csv", evidence, EVIDENCE_FIELDS)
    result = {"stage": "news_only_verified_export", "verified_nodes": len(nodes),
              "verified_edges": len(edges), "populated_types": len(set(r["relationship_type"] for r in edges)),
              "reviewed_evidence_rows": len(evidence), "wiki_edges_counted": 0,
              "status": "exported_not_production_approved"}
    json_report("export.json", result)
    return result


def status(args) -> dict:
    exported = csv_read(NEWS_DATA / "export" / "verified" / "edges.csv")
    nodes = csv_read(NEWS_DATA / "export" / "verified" / "nodes.csv")
    audits = csv_read(NEWS_DATA / "edge_audit.csv")
    # Never trust a saved evaluation JSON if the sample has since been modified.
    from types import SimpleNamespace
    ev = (evaluate(SimpleNamespace(min_sample=200))
          if (NEWS_DATA / "gold_standard_sample.csv").exists() else {})
    targets = {"core_nodes": 2200, "valid_edges": 5500, "relationship_types": 11,
               "precision_percent_exclusive_min": 90}
    actual = {"core_nodes": len(nodes), "valid_edges": len(exported),
              "relationship_types": len(set(x["relationship_type"] for x in exported)),
              "edge_precision": ev.get("precision_percent")}
    accepted = bool(actual["core_nodes"] >= 2200 and actual["valid_edges"] >= 5500
                    and actual["relationship_types"] >= 11
                    and ev.get("status") == "calculable" and ev.get("precision_above_90") is True)
    result = {"targets": targets, "actual_verified": actual, "auto_audited_candidates": len(audits),
              "all_acceptance_criteria_met": accepted,
              "production_import_permitted": accepted,
              "warnings": ["Old Wiki pipeline's neo4j_import.py has independent guards and MUST NOT be invoked for this dataset.",
                           "This status is diagnostic, not permission to bypass manual evidence review."]}
    json_report("acceptance.json", result)
    return result
