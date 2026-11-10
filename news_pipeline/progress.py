"""Read-only progress telemetry; counts verified data separately from candidates."""
from __future__ import annotations

from collections import Counter

from .common import NEWS_DATA, csv_read, json_report, now

TARGETS = {"verified_nodes": 2200, "verified_edges": 5500, "populated_types": 11,
           "precision_strictly_above": 90}


def progress(args) -> dict:
    articles = csv_read(NEWS_DATA / "articles.csv")
    documents = csv_read(NEWS_DATA / "article_documents.csv")
    assertions = csv_read(NEWS_DATA / "relation_assertions.csv")
    audited = csv_read(NEWS_DATA / "edge_audit.csv")
    reviews = csv_read(NEWS_DATA / "edge_review.csv")
    nodes = csv_read(NEWS_DATA / "export" / "verified" / "nodes.csv")
    edges = csv_read(NEWS_DATA / "export" / "verified" / "edges.csv")
    gold = csv_read(NEWS_DATA / "gold_standard_sample.csv")
    fetched = [r for r in documents if r.get("fetch_status") == "fetched"]
    auto_pass = [r for r in audited if r.get("auto_review_status") == "auto_pass_needs_independent_review"]
    review_accepted = [r for r in reviews if r.get("review_decision") == "correct"]
    populated = len({r.get("relationship_type") for r in edges})
    verified = {"verified_nodes": len(nodes), "verified_edges": len(edges),
                "populated_types": populated}
    gaps = {k: max(0, TARGETS[k] - verified[k]) for k in verified}
    candidate_per_fetched = round(len(assertions) / len(fetched), 3) if fetched else None
    auto_pass_per_fetched = round(len(auto_pass) / len(fetched), 3) if fetched else None
    estimated_additional_fetched_for_eligible_5500 = (
        max(0, int((TARGETS["verified_edges"] - len(auto_pass)) / auto_pass_per_fetched + 0.999))
        if auto_pass_per_fetched and auto_pass_per_fetched > 0 else None
    )
    # Estimate is about audit-passing candidates, NOT verified relations.
    result = {
        "stage": "newspaper_pipeline_progress_v2_2", "generated_at": now(),
        "targets": TARGETS, "verified_outputs": verified, "verified_gaps": gaps,
        "articles_discovered": len(articles), "articles_fetched": len(fetched),
        "articles_by_outlet": dict(Counter(a.get("outlet_id") for a in articles)),
        "fetch_status_distribution": dict(Counter(x.get("fetch_status") for x in documents)),
        "candidate_assertions": len(assertions),
        "candidate_relation_types": dict(Counter(x.get("relationship_type") for x in assertions)),
        "automatically_audited_assertions": len(audited),
        "auto_pass_needs_independent_review": len(auto_pass),
        "human_review_rows": len(reviews), "human_accepted_assertions": len(review_accepted),
        "gold_standard_sample_size": len(gold),
        "candidate_assertions_per_fetched_article": candidate_per_fetched,
        "audit_pass_candidates_per_fetched_article": auto_pass_per_fetched,
        "estimated_additional_fetched_articles_to_get_5500_audit_pass_candidates": estimated_additional_fetched_for_eligible_5500,
        "estimate_warning": "This is a volume projection at current extract+audit yield, not predicted verified edges or precision.",
        "next_actions": [],
        "wiki_inputs_used": 0,
    }
    if len(articles) <= len(fetched):
        result["next_actions"].append("Expand publisher RSS sources or run bounded archive/sitemap backfill")
    else:
        result["next_actions"].append("Fetch more discovered original publisher articles")
    if not assertions and fetched:
        result["next_actions"].append("Run diagnose + extract; review real sentence patterns if zero candidate edges")
    elif len(audited) != len(assertions):
        result["next_actions"].append("Run audit for 100% candidate coverage")
    elif auto_pass:
        result["next_actions"].append("Prepare independent edge review and Gold Standard labels")
    json_report("progress.json", result)
    return result
