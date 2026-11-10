"""Evidence-local, deterministic expansion of Vietnamese film credit patterns.

All assertions retain an exact sentence and byte-independent character offsets.
No source co-occurrence is counted as a relationship. No precision is inferred.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from . import extract as original
from .common import NEWS_DATA, article_path, csv_read, csv_write, id_for, json_report, now, text_key

PERSON = original.PERSON
QUOTED = r'["“‘«](?P<work>[^"”’»\n]{2,90})["”’»]'
ORG = original.ORG
FLAGS = re.IGNORECASE | re.UNICODE
# Each expression has an explicit, same-sentence film title, contributor and role.
# This intentionally trades some recall for fewer unsupported assertions.
PATTERNS = [
    ("u01", "DIRECTED", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:do\s+)?đạo diễn\s+(?P<person>{PERSON})\s+(?:thực hiện|đạo diễn|chỉ đạo|cầm trịch)'),
    ("u02", "DIRECTED", rf'(?:đạo diễn)\s+(?P<person>{PERSON})\s+(?:đứng sau|cầm trịch|thực hiện|chỉ đạo|đạo diễn)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u03", "DIRECTED", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:là\s+)?(?:tác phẩm\s+)?của\s+đạo diễn\s+(?P<person>{PERSON})(?=$|[.,;:!?])'),
    ("u04", "ACTED_IN", rf'(?:diễn viên)\s+(?P<person>{PERSON})\s+(?:vào vai|đảm nhận vai|thủ vai|đóng vai)[^.!?\n]{{0,65}}?\s+trong\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u05", "ACTED_IN", rf'(?:diễn viên)\s+(?P<person>{PERSON})\s+(?:tham gia|góp mặt|xuất hiện|đóng chính)\s+(?:trong\s+)?(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u06", "ACTED_IN", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:có\s+sự\s+tham\s+gia\s+của|có\s+sự\s+góp\s+mặt\s+của|với\s+sự\s+tham\s+gia\s+của)\s+(?:diễn viên\s+)?(?P<person>{PERSON})(?=$|[.,;:!?])'),
    ("u07", "VOICE_ACTED_IN", rf'(?:diễn viên|nghệ sĩ)\s+(?P<person>{PERSON})\s+lồng\s+tiếng\s+(?:cho|trong)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u08", "PRODUCED", rf'(?:nhà\s+sản\s+xuất)\s+(?P<person>{PERSON})\s+(?:đứng\s+sau|phụ\s+trách|thực\s+hiện|sản\s+xuất)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u09", "EXECUTIVE_PRODUCED", rf'(?:nhà sản xuất điều hành|giám đốc sản xuất)\s+(?P<person>{PERSON})\s+(?:điều\s+hành\s+sản\s+xuất|phụ\s+trách|thực\s+hiện)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u10", "WROTE", rf'(?:biên kịch)\s+(?P<person>{PERSON})\s+(?:chấp\s+bút|viết\s+kịch\s+bản|phụ\s+trách\s+kịch\s+bản)\s+(?:cho\s+)?(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u11", "WROTE", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:có\s+)?kịch\s+bản\s+(?:do|của)\s+(?:biên\s+kịch\s+)?(?P<person>{PERSON})\s+(?:viết|chấp\s+bút)'),
    ("u12", "COMPOSED_MUSIC_FOR", rf'(?:nhạc sĩ)\s+(?P<person>{PERSON})\s+(?:soạn\s+nhạc|sáng\s+tác\s+nhạc|viết\s+nhạc)\s+(?:cho\s+)?(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u13", "CINEMATOGRAPHED", rf'(?:đạo\s+diễn\s+hình\s+ảnh|quay\s+phim)\s+(?P<person>{PERSON})\s+(?:phụ\s+trách\s+hình\s+ảnh|quay|đảm\s+nhận\s+hình\s+ảnh)\s+(?:cho\s+)?(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u14", "EDITED", rf'(?:dựng\s+phim|biên\s+tập\s+phim)\s+(?P<person>{PERSON})\s+(?:dựng|biên\s+tập|phụ\s+trách\s+dựng)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u15", "PRODUCED_BY", rf'(?P<org>{ORG})\s+(?:đứng\s+sau|sản\s+xuất|hợp\s+tác\s+sản\s+xuất)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u16", "DISTRIBUTED_BY", rf'(?P<org>{ORG})\s+(?:phát\s+hành|phân\s+phối)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
    ("u17", "BROADCAST_BY", rf'(?P<org>{ORG})\s+(?:phát\s+sóng|trình\s+chiếu)\s+(?:bộ\s+)?phim\s+{QUOTED}'),
]
COMPILED_EXTRA = [(rid, rel, re.compile(pattern, FLAGS)) for rid, rel, pattern in PATTERNS]
SPECULATIVE = re.compile(r'\b(?:tin đồn|đồn đoán|nghi vấn|dự kiến|có thể sẽ|được cho là|chưa xác nhận)\b', FLAGS)
REL_ORG = {"PRODUCED_BY", "DISTRIBUTED_BY", "BROADCAST_BY"}

# Additional explicit, non-credit relations are semantically distinct and source-backed.
# These are not arbitrary co-occurrence links or inferred pairwise cast cliques.
YEAR = r"(?P<year>(?:19[5-9][0-9]|20[0-2][0-9]))"
AWARD = r"(?P<award>(?:giải\s+)?[A-ZĐÀÁẢÃẠÂẤẦẨẪẬĂẮẰẲẴẶ][\wÀ-ỹĐđ-]+(?:\s+[A-ZĐÀÁẢÃẠÂẤẦẨẪẬĂẮẰẲẴẶ][\wÀ-ỹĐđ-]+){1,5})"
FESTIVAL = r"(?P<festival>Liên\s+hoan\s+phim\s+[\wÀ-ỹĐđ-]+(?:\s+[\wÀ-ỹĐđ-]+){0,6})"
PLACE = r"(?P<place>[A-ZĐÀÁẢÃẠÂẤẦẨẪẬĂẮẰẲẴẶ][\wÀ-ỹĐđ-]+(?:\s+[A-ZĐÀÁẢÃẠÂẤẦẨẪẬĂẮẰẲẴẶ][\wÀ-ỹĐđ-]+){0,3})"
LITERARY = r'["“‘«](?P<literary>[^"”’»\n]{2,90})["”’»]'
MISC_PATTERNS = [
    ("u18", "RELEASED_IN_YEAR", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:đã\s+)?(?:ra\s+mắt|khởi\s+chiếu|công\s+chiếu|phát\s+hành|lên\s+sóng)\s+(?:vào\s+)?(?:năm\s+){YEAR}'),
    ("u19", "PRODUCED_IN_YEAR", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:được\s+)?sản\s+xuất\s+(?:vào\s+)?năm\s+{YEAR}'),
    ("u20", "WON_AWARD", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:đã\s+)?(?:đoạt|giành|nhận)\s+(?P<award>giải\s+[\wÀ-ỹĐđ-]+(?:\s+[\wÀ-ỹĐđ-]+){{0,5}}?)(?=$|[.,;:!?])'),
    ("u21", "NOMINATED_FOR", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:được\s+)?đề\s+cử\s+(?:cho\s+)?(?P<award>giải\s+[\wÀ-ỹĐđ-]+(?:\s+[\wÀ-ỹĐđ-]+){{0,5}}?)(?=$|[.,;:!?])'),
    ("u22", "SCREENED_AT", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:được\s+)?(?:trình\s+chiếu|công\s+chiếu|ra\s+mắt)\s+tại\s+{FESTIVAL}(?=$|[.,;:!?])'),
    ("u23", "FILMED_IN", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:được\s+)?(?:quay|ghi\s+hình)\s+tại\s+{PLACE}(?=$|[.,;:!?])'),
    ("u24", "ADAPTED_FROM", rf'(?:phim|bộ phim)\s+{QUOTED}\s+(?:được\s+)?chuyển\s+thể\s+từ\s+(?:tiểu\s+thuyết|truyện)\s+{LITERARY}'),
]
COMPILED_MISC = [(rid, rel, re.compile(expr, FLAGS)) for rid, rel, expr in MISC_PATTERNS]
# Explicit endpoint types for all relations (including the original 12 credits).
REL_ENDPOINTS = {rel: (("Work", "Organization") if rel in REL_ORG else ("Person", "Work"))
                 for _, rel, _ in PATTERNS}
REL_ENDPOINTS.update({
    "RELEASED_IN_YEAR": ("Work", "Year"), "PRODUCED_IN_YEAR": ("Work", "Year"),
    "WON_AWARD": ("Work", "Award"), "NOMINATED_FOR": ("Work", "Award"),
    "SCREENED_AT": ("Work", "Festival"), "FILMED_IN": ("Work", "Place"),
    "ADAPTED_FROM": ("Work", "LiteraryWork"),
})
MISC_TARGETS = {"RELEASED_IN_YEAR": "year", "PRODUCED_IN_YEAR": "year",
                "WON_AWARD": "award", "NOMINATED_FOR": "award", "SCREENED_AT": "festival",
                "FILMED_IN": "place", "ADAPTED_FROM": "literary"}
NODE_PREFIX = {"Person": "PERSON", "Work": "WORK", "Organization": "ORG", "Year": "YEAR",
               "Award": "AWARD", "Festival": "FESTIVAL", "Place": "PLACE", "LiteraryWork": "LITERARY"}


def extra_misc_for_sentence(article: dict, sentence_index: int, offset: int, sentence: str) -> list[dict]:
    if SPECULATIVE.search(sentence):
        return []
    out = {}
    for rid, relation, pattern in COMPILED_MISC:
        for match in pattern.finditer(sentence):
            title = original.clean_entity_name(match.group("work"))
            target = original.clean_entity_name(match.group(MISC_TARGETS[relation]))
            if not original.is_reasonable_work(title) or not original.candidate_name(title, 2):
                continue
            if not target or len(target) > 90 or len(target) < 3 or text_key(target) == text_key(title):
                continue
            if relation.endswith("_YEAR") and not (1950 <= int(target) <= 2030):
                continue
            if relation == "FILMED_IN" and len(target.split()) > 4:
                continue
            if relation in ("WON_AWARD", "NOMINATED_FOR") and (len(target.split()) > 7 or not target.casefold().startswith("giải ")):
                continue
            aid = article["article_id"]
            obj_type = REL_ENDPOINTS[relation][1]
            out.setdefault((relation, text_key(title), text_key(target)), {
                "assertion_id": id_for("ASSERT", aid, relation, title, target, sentence_index, rid),
                "article_id": aid, "outlet_id": article["outlet_id"], "canonical_url": article["canonical_url"],
                "subject_id": id_for("WORK", text_key(title)), "subject_name": title, "subject_type": "Work",
                "relationship_type": relation, "object_id": id_for(NODE_PREFIX[obj_type], text_key(target)),
                "object_name": target, "object_type": obj_type,
                "sentence_id": f"{aid}:s{sentence_index}", "evidence_text": sentence[:450],
                "evidence_start": str(offset), "evidence_end": str(offset + len(sentence)),
                "trigger_text": rid, "extraction_method": "deterministic_explicit_role_rule",
                "rule_id": rid, "auto_status": "candidate_not_verified",
                "human_review_status": "not_required_by_this_workflow", "reviewer": "", "review_notes": "",
                "scope_status": "automated_evidence_screening",
            })
    return list(out.values())


def extra_for_sentence(article: dict, sentence_index: int, offset: int, sentence: str) -> list[dict]:
    if SPECULATIVE.search(sentence):
        return []
    output = {}
    for rid, relation, pattern in COMPILED_EXTRA:
        for match in pattern.finditer(sentence):
            is_org = relation in REL_ORG
            person_or_org = original.clean_entity_name(match.group("org" if is_org else "person"))
            work = original.clean_entity_name(match.group("work"))
            if not (original.candidate_name(person_or_org) and original.candidate_name(work, 2)
                    and original.is_reasonable_work(work)):
                continue
            if not is_org and not original.is_reasonable_person(person_or_org):
                continue
            if text_key(person_or_org) == text_key(work):
                continue
            if is_org:
                sub_name, sub_type, sub_prefix = work, "Work", "WORK"
                obj_name, obj_type, obj_prefix = person_or_org, "Organization", "ORG"
            else:
                sub_name, sub_type, sub_prefix = person_or_org, "Person", "PERSON"
                obj_name, obj_type, obj_prefix = work, "Work", "WORK"
            aid = article["article_id"]
            triple = (aid, relation, text_key(sub_name), text_key(obj_name))
            output.setdefault(triple, {
                "assertion_id": id_for("ASSERT", aid, relation, sub_name, obj_name, sentence_index, rid),
                "article_id": aid, "outlet_id": article["outlet_id"],
                "canonical_url": article["canonical_url"],
                "subject_id": id_for(sub_prefix, text_key(sub_name)),
                "subject_name": sub_name, "subject_type": sub_type,
                "relationship_type": relation, "object_id": id_for(obj_prefix, text_key(obj_name)),
                "object_name": obj_name, "object_type": obj_type,
                "sentence_id": f"{aid}:s{sentence_index}",
                "evidence_text": sentence[:450],
                "evidence_start": str(offset), "evidence_end": str(offset + len(sentence)),
                "trigger_text": rid, "extraction_method": "deterministic_explicit_role_rule",
                "rule_id": rid, "auto_status": "candidate_not_verified",
                "human_review_status": "not_required_by_this_workflow",
                "reviewer": "", "review_notes": "",
                "scope_status": "automated_evidence_screening",
            })
    return list(output.values())


def extract_candidates(article: dict, body: str) -> list[dict]:
    rows = original.candidates_for_article(article, body)
    seen = {(r["article_id"], r["relationship_type"], r["subject_id"], r["object_id"]) for r in rows}
    for si, (offset, sentence) in enumerate(original.sentences(body)):
        if len(sentence) > 450:
            continue
        for row in (extra_for_sentence(article, si, offset, sentence) +
                    extra_misc_for_sentence(article, si, offset, sentence)):
            key = (row["article_id"], row["relationship_type"], row["subject_id"], row["object_id"])
            if key not in seen:
                rows.append(row)
                seen.add(key)
    # RSS V4: additional explicit role templates; preserve same-article deduplication.
    from .film_patterns_plus import candidates as v4_candidates
    for candidate in v4_candidates(article, body):
        key = (candidate["article_id"], candidate["relationship_type"],
               candidate["subject_id"], candidate["object_id"])
        if key not in seen:
            seen.add(key)
            rows.append(candidate)
    # Drop conjecture and ambiguous same-sentence speculation even in legacy rules.
    return [r for r in rows if not SPECULATIVE.search(r["evidence_text"])]


def rebuild_assertions() -> dict:
    articles = {r["article_id"]: r for r in csv_read(NEWS_DATA / "articles.csv")}
    docs = csv_read(NEWS_DATA / "article_documents.csv")
    found = {}
    per_article = []
    counts = Counter()
    scanned = 0
    mismatched_hash = 0
    for doc in docs:
        if doc.get("fetch_status") != "fetched" or doc.get("article_id") not in articles:
            continue
        aid = doc["article_id"]
        path = article_path(aid)
        if not path.is_file() or path.is_symlink():
            continue
        body = path.read_text(encoding="utf-8")
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != doc.get("sha256"):
            mismatched_hash += 1
            continue
        scanned += 1
        candidates = extract_candidates(articles[aid], body)
        per_article.append((aid, len(candidates)))
        for assertion in candidates:
            found[assertion["assertion_id"]] = assertion
            counts[assertion["relationship_type"]] += 1
    csv_write(NEWS_DATA / "relation_assertions.csv", sorted(found.values(), key=lambda r: r["assertion_id"]), original.REL_FIELDS)
    report = {"stage": "unified_evidence_extraction", "created_at": now(),
              "fetched_articles_scanned": scanned, "articles_hash_mismatch": mismatched_hash,
              "articles_with_candidates": sum(n > 0 for _, n in per_article),
              "candidate_assertions": len(found), "by_type": dict(counts),
              "no_guarantee_of_factual_precision": True}
    json_report("unified_extraction.json", report)
    return report
