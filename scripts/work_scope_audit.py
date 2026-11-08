import csv
import json
import time
from pathlib import Path
from collections import defaultdict

import requests

ROOT = Path.cwd()
EDGE_FILE = ROOT / "data/resolution/entity_resolution_v2/resolved_edge_candidates.jsonl"
CACHE = ROOT / "data/raw/wikidata/work_scope_cache"
OUT = ROOT / "data/evidence_validation/v3_scope"
REPORT = ROOT / "reports/work_scope_audit_report.json"

API = "https://www.wikidata.org/w/api.php"
VIETNAM = "Q881"
BATCH_SIZE = 50

CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

def read_edges():
    rows = []
    with EDGE_FILE.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def get_claim_qids(claims, prop):
    result = []
    for statement in claims.get(prop, []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id"):
            result.append(value["id"])
    return sorted(set(result))

def fetch_batch(session, qids):
    response = session.get(
        API,
        params={
            "action": "wbgetentities",
            "ids": "|".join(qids),
            "props": "labels|descriptions|claims",
            "languages": "vi|en",
            "format": "json",
            "maxlag": 5,
        },
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return data.get("entities", {})

edges = read_edges()

qid_edges = defaultdict(list)

for edge in edges:
    qid = edge.get("work_qid", "")
    if qid:
        qid_edges[qid].append(edge["edge_id"])

qids = sorted(qid_edges)
session = requests.Session()
session.headers["User-Agent"] = "VietnamFilmNetwork/1.0"

items = {}

missing = []

for qid in qids:
    cache_file = CACHE / f"{qid}.json"

    if cache_file.exists():
        items[qid] = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        missing.append(qid)

for start in range(0, len(missing), BATCH_SIZE):
    batch = missing[start:start + BATCH_SIZE]

    try:
        fetched = fetch_batch(session, batch)
    except Exception:
        time.sleep(15)
        fetched = fetch_batch(session, batch)

    for qid, entity in fetched.items():
        if "missing" not in entity:
            items[qid] = entity
            (CACHE / f"{qid}.json").write_text(
                json.dumps(entity, ensure_ascii=False),
                encoding="utf-8"
            )

    time.sleep(2)

def classify(p495):
    if VIETNAM in p495 and len(p495) == 1:
        return "vietnam_candidate"

    if VIETNAM in p495 and len(p495) > 1:
        return "coproduction_candidate"

    if p495:
        return "foreign_candidate"

    return "scope_uncertain"

rows = []

for qid in qids:
    entity = items.get(qid, {})
    claims = entity.get("claims", {})

    p495 = get_claim_qids(claims, "P495")
    p17 = get_claim_qids(claims, "P17")
    p272 = get_claim_qids(claims, "P272")

    rows.append({
        "work_qid": qid,
        "label_vi": entity.get("labels", {}).get("vi", {}).get("value", ""),
        "label_en": entity.get("labels", {}).get("en", {}).get("value", ""),
        "country_of_origin_qids": json.dumps(p495),
        "country_qids": json.dumps(p17),
        "production_company_qids": json.dumps(p272),
        "resolved_edge_count": len(qid_edges[qid]),
        "scope_suggestion": classify(p495),
        "scope_decision": "pending",
        "reviewer": "",
        "review_notes": "",
    })

fields = list(rows[0].keys()) if rows else []

with (OUT / "work_scope_audit.csv").open(
    "w", encoding="utf-8-sig", newline=""
) as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

report = {
    "total_work_qids": len(qids),
    "work_items_fetched": len(items),
    "scope_suggestions": {},
    "output": str(OUT / "work_scope_audit.csv"),
}

for row in rows:
    key = row["scope_suggestion"]
    report["scope_suggestions"][key] = (
        report["scope_suggestions"].get(key, 0) + 1
    )

REPORT.write_text(
    json.dumps(report, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, ensure_ascii=False, indent=2))
