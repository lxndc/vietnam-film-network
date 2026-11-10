"""Version 2.1: conservative explicit-role extraction, with additional
newspaper word orders and unquoted film titles.

No auto-extracted assertion is factually verified. Every relation is subject to
an article-based technical audit followed by independent evidence review.
"""
from __future__ import annotations

import re

from .common import NEWS_DATA, article_path, csv_read, csv_write, id_for, json_report, normalize, now, text_key

REL_FIELDS = [
    "assertion_id", "article_id", "outlet_id", "canonical_url", "subject_id",
    "subject_name", "subject_type", "relationship_type", "object_id",
    "object_name", "object_type", "sentence_id", "evidence_text", "evidence_start",
    "evidence_end", "trigger_text", "extraction_method", "rule_id", "auto_status",
    "human_review_status", "reviewer", "review_notes", "scope_status",
]

PERSON = r"(?:[A-ZĐÀÁẢÃẠÂẤẦẨẪẬĂẮẰẲẴẶÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ][\wÀ-ỹĐđ-]+(?:\s+[A-ZĐÀÁẢÃẠÂẤẦẨẪẬĂẮẰẲẴẶÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ][\wÀ-ỹĐđ-]+){1,3})"
WORK_QUOTED = r'[\"“‘«](?P<work>[^\"”’»]{2,90})[\"”’»]'
ORG = r"(?:Hãng phim|Công ty|Đài truyền hình)\s+[A-ZĐ\wÀ-ỹ][\wÀ-ỹ &-]{2,55}?"

# Subjects and Works are required to occur in the SAME sentence with an explicit role trigger.
RULES: list[tuple[str, str, str, str, str, int]] = [
    ("r01", rf"(?:đạo diễn)\s+(?P<person>{PERSON})\s+(?:thực hiện|đạo diễn|cầm trịch)\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "DIRECTED", "Person", "Work", 0),
    ("r02", rf"(?:bộ\s+)?phim\s+{WORK_QUOTED}\s+do\s+(?:đạo diễn)\s+(?P<person>{PERSON})\s+(?:thực hiện|chỉ đạo|đạo diễn)", "DIRECTED", "Person", "Work", 1),
    ("r03", rf"(?:diễn viên)\s+(?P<person>{PERSON})\s+(?:đóng|đảm nhận|tham gia|góp mặt)[^.!?]{{0,60}}?\s+trong\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "ACTED_IN", "Person", "Work", 0),
    ("r04", rf"(?:diễn viên)\s+(?P<person>{PERSON})\s+(?:lồng tiếng)\s+(?:cho|trong)[^.!?]{{0,35}}?\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "VOICE_ACTED_IN", "Person", "Work", 0),
    ("r05", rf"(?:nhà sản xuất)\s+(?P<person>{PERSON})\s+(?:sản xuất|thực hiện)[^.!?]{{0,24}}?\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "PRODUCED", "Person", "Work", 0),
    ("r06", rf"(?:biên kịch)\s+(?P<person>{PERSON})\s+(?:viết|chấp bút|phụ trách kịch bản)[^.!?]{{0,24}}?\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "WROTE", "Person", "Work", 0),
    ("r07", rf"(?:nhạc sĩ)\s+(?P<person>{PERSON})\s+(?:soạn nhạc|sáng tác nhạc)[^.!?]{{0,24}}?\s+(?:cho\s+)?(?:bộ\s+)?phim\s+{WORK_QUOTED}", "COMPOSED_MUSIC_FOR", "Person", "Work", 0),
    ("r08", rf"(?:quay phim|đạo diễn hình ảnh)\s+(?P<person>{PERSON})\s+(?:quay|phụ trách hình ảnh)[^.!?]{{0,28}}?\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "CINEMATOGRAPHED", "Person", "Work", 0),
    ("r09", rf"(?:dựng phim|biên tập phim)\s+(?P<person>{PERSON})\s+(?:dựng|biên tập)[^.!?]{{0,20}}?\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "EDITED", "Person", "Work", 0),
    ("r10", rf"(?:giám đốc sản xuất|nhà sản xuất điều hành)\s+(?P<person>{PERSON})\s+(?:điều hành sản xuất|sản xuất)[^.!?]{{0,24}}?\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "EXECUTIVE_PRODUCED", "Person", "Work", 0),
    ("r11", rf"(?P<org>{ORG})\s+(?:phát hành|phân phối)\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "DISTRIBUTED_BY", "Organization", "Work", 0),
    ("r12", rf"(?P<org>{ORG})\s+(?:phát sóng|chiếu)\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "BROADCAST_BY", "Organization", "Work", 0),
    ("r13", rf"(?P<org>{ORG})\s+(?:sản xuất)\s+(?:bộ\s+)?phim\s+{WORK_QUOTED}", "PRODUCED_BY", "Organization", "Work", 0),
    # Newsroom order variations. A film marker, an explicit role, and both
    # named endpoints are mandatory. Unquoted titles need a bounded delimiter.
    ("r14", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:do|được)\s+(?:đạo diễn\s+)?(?P<person>{PERSON})\s+(?:đạo diễn|chỉ đạo|thực hiện)", "DIRECTED", "Person", "Work", 0),
    ("r15", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:của\s+)?đạo diễn\s+(?P<person>{PERSON})(?=$|[.,;:!?])", "DIRECTED", "Person", "Work", 0),
    ("r16", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:có\s+sự\s+tham\s+gia\s+của|với\s+sự\s+tham\s+gia\s+của)\s+(?:diễn viên\s+)?(?P<person>{PERSON})", "ACTED_IN", "Person", "Work", 0),
    ("r17", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:do|được)\s+(?P<org>{ORG})\s+(?:sản xuất)", "PRODUCED_BY", "Organization", "Work", 0),
    ("r18", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:do|được)\s+(?P<org>{ORG})\s+(?:phát hành|phân phối)", "DISTRIBUTED_BY", "Organization", "Work", 0),
    ("r19", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:do|được)\s+(?P<org>{ORG})\s+(?:phát sóng)", "BROADCAST_BY", "Organization", "Work", 0),
    ("r20", rf"(?:[Dd]iễn viên\s+)?(?P<person>{PERSON})\s+(?:đóng vai|tham gia diễn xuất|góp mặt|tham gia|đóng)\s+(?:trong|ở)\s+(?:bộ\s+)?phim\s+(?P<work>[A-ZĐ0-9][^.!?;:,\n]{{1,60}}?)(?=$|[.,;:!?])", "ACTED_IN", "Person", "Work", 0),
    ("r21", rf"(?:[Đđ]ạo diễn\s+)(?P<person>{PERSON})\s+(?:đạo diễn|thực hiện|cầm trịch)\s+(?:bộ\s+)?phim\s+(?P<work>[A-ZĐ0-9][^.!?;:,\n]{{1,60}}?)(?=$|[.,;:!?])", "DIRECTED", "Person", "Work", 0),
    ("r22", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:có\s+kịch\s+bản\s+do|do)\s+(?:biên kịch\s+)(?P<person>{PERSON})\s+(?:chấp bút|viết)", "WROTE", "Person", "Work", 0),
    ("r23", rf"(?:[Pp]him|[Bb]ộ phim)\s+(?P<work>[\wÀ-ỹĐđ][^.!?;:,\n]{{1,72}}?)\s+(?:có\s+phần\s+âm\s+nhạc\s+do|có\s+nhạc\s+do)\s+(?:nhạc sĩ\s+)?(?P<person>{PERSON})\s+(?:sáng tác|thực hiện)", "COMPOSED_MUSIC_FOR", "Person", "Work", 0),
    ("r24", rf"(?P<org>{ORG})\s+(?:sản xuất)\s+(?:bộ\s+)?phim\s+(?P<work>[A-ZĐ0-9][^.!?;:,\n]{{1,60}}?)(?=$|[.,;:!?])", "PRODUCED_BY", "Organization", "Work", 0),

]

# A cast list must explicitly name actors and a titled Work in one sentence.
# Individual names are accepted only when they independently match PERSON.
CAST_LIST_RULES = [
    ("cast01", re.compile(
        rf"(?:[Pp]him|[Bb]ộ phim)\s+{WORK_QUOTED}\s+"
        rf"(?:quy tụ|có sự tham gia của|có dàn diễn viên gồm|với dàn diễn viên gồm)\s+"
        rf"(?:(?:dàn|các|những)\s+)?diễn viên\s+(?P<cast>[^.!?;:]{{8,170}})",
        re.I | re.UNICODE)),
    ("cast02", re.compile(
        rf"[Dd]àn diễn viên\s+(?:của\s+)?(?:bộ\s+)?phim\s+{WORK_QUOTED}\s+"
        rf"(?:gồm|bao gồm|có)\s+(?P<cast>[^.!?;:]{{8,170}})",
        re.I | re.UNICODE)),
    ("cast03", re.compile(
        rf"(?:[Cc]ác|[Nn]hững)\s+diễn viên\s+(?P<cast>[^.!?;:]{{8,170}}?)\s+"
        rf"(?:cùng tham gia|cùng đóng|góp mặt|tham gia diễn xuất)\s+"
        rf"(?:trong\s+)?(?:bộ\s+)?phim\s+{WORK_QUOTED}",
        re.I | re.UNICODE)),
]

# Work title groups are numbered because PERSON contributes one capture group.
COMPILED = [(rid, re.compile(expr, re.UNICODE | re.IGNORECASE), kind, flip)
            for rid, expr, kind, _, _, flip in RULES]


def clean_entity_name(value: str) -> str:
    value = normalize(value).strip(' \"“”‘’«».,:;!?')
    return normalize(value)


def is_reasonable_person(value: str) -> bool:
    words = normalize(value).split()
    if not 2 <= len(words) <= 5:
        return False
    if any(not word[0].isupper() for word in words):
        return False
    if any(word.casefold() in {"đạo", "diễn", "phim", "bộ", "nhà", "sản", "đã", "việt", "nam"}
           for word in words):
        return False
    return True


def is_reasonable_work(value: str) -> bool:
    words = normalize(value).split()
    if not 1 <= len(words) <= 9:
        return False
    if not words[0][0].isupper() and not words[0][0].isdigit():
        return False
    if any(word.casefold() in {"có", "được", "do", "nhưng", "cùng", "khi", "và", "rằng"}
           for word in words):
        return False
    return True


def candidate_name(value: str, min_length: int = 5) -> bool:
    value = normalize(value)
    bad = {"Việt Nam", "Hà Nội", "TP HCM", "Năm 2025", "Năm 2026"}
    return min_length <= len(value) <= 90 and value not in bad and not value.isnumeric()


def sentences(text: str):
    # Keep stable offsets. Punctuation splitting is conservative, not a linguistic parser.
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", text):
        raw = match.group(0)
        sentence = raw.strip()
        if 20 <= len(sentence) <= 800:
            # Offsets refer to exact characters in the locally cached article body.
            yield match.start() + (len(raw) - len(raw.lstrip())), sentence


def candidates_for_article(article: dict, text: str) -> list[dict]:
    out: dict[tuple[str, str, str, str], dict] = {}
    for sentence_index, (offset, sentence) in enumerate(sentences(text)):
        if len(sentence) > 450:
            continue
        for rid, pattern, kind, flipped in COMPILED:
            for match in pattern.finditer(sentence):
                is_org = match.groupdict().get("org") is not None
                subject = clean_entity_name(match.group("org") if is_org else match.group("person"))
                title = clean_entity_name(match.group("work"))
                if not candidate_name(subject) or not candidate_name(title, min_length=2):
                    continue
                if (not is_org and not is_reasonable_person(subject)) or not is_reasonable_work(title):
                    continue
                if text_key(subject) == text_key(title):
                    continue
                aid = article["article_id"]
                rid_hash = id_for("ASSERT", aid, kind, subject, title, sentence_index, rid)
                # *_BY predicates originate from Work and point to Organization.
                source_name, source_type = (title, "Work") if is_org else (subject, "Person")
                object_name, object_type = (subject, "Organization") if is_org else (title, "Work")
                source_prefix = "WORK" if is_org else "PERSON"
                object_prefix = "ORG" if is_org else "WORK"
                dedup_key = (aid, kind, source_name.casefold(), object_name.casefold())
                if dedup_key in out:
                    continue
                out[dedup_key] = {
                    "assertion_id": rid_hash, "article_id": aid,
                    "outlet_id": article["outlet_id"],
                    "canonical_url": article["canonical_url"],
                    "subject_id": id_for(source_prefix, text_key(source_name)),
                    "subject_name": source_name, "subject_type": source_type,
                    "relationship_type": kind,
                    "object_id": id_for(object_prefix, text_key(object_name)),
                    "object_name": object_name, "object_type": object_type,
                    "sentence_id": f"{aid}:s{sentence_index}",
                    "evidence_text": sentence[:450],
                    "evidence_start": str(offset),
                    "evidence_end": str(offset + len(sentence)),
                    "trigger_text": rid, "extraction_method": "deterministic_explicit_role_rule",
                    "rule_id": rid, "auto_status": "candidate_not_verified",
                    "human_review_status": "pending", "reviewer": "", "review_notes": "",
                    "scope_status": "scope_uncertain_pending_review",
                }
        # Multiple named actors credited for a single Work in one explicit sentence.
        # This expands high-yield cast statements without inventing co-occurrence edges.
        for cast_rule_id, cast_pattern in CAST_LIST_RULES:
            for match in cast_pattern.finditer(sentence):
                title = clean_entity_name(match.group("work"))
                if not candidate_name(title, min_length=2) or not is_reasonable_work(title):
                    continue
                group = match.group("cast")
                # Only ordinary cast-list separators. Clauses/roles are not accepted.
                names = re.split(r"\s*,\s*|\s+và\s+|\s+cùng\s+", group)
                for part in names:
                    person = clean_entity_name(part)
                    person = re.sub(r"^(?:NSND|NSƯT)\s+", "", person)
                    if not candidate_name(person) or not is_reasonable_person(person):
                        continue
                    if not re.fullmatch(PERSON, person, re.UNICODE):
                        continue
                    if text_key(person) == text_key(title):
                        continue
                    aid = article["article_id"]
                    dedup_key = (aid, "ACTED_IN", person.casefold(), title.casefold())
                    if dedup_key in out:
                        continue
                    out[dedup_key] = {
                        "assertion_id": id_for("ASSERT", aid, "ACTED_IN", person, title,
                                               sentence_index, cast_rule_id),
                        "article_id": aid, "outlet_id": article["outlet_id"],
                        "canonical_url": article["canonical_url"],
                        "subject_id": id_for("PERSON", text_key(person)),
                        "subject_name": person, "subject_type": "Person",
                        "relationship_type": "ACTED_IN",
                        "object_id": id_for("WORK", text_key(title)),
                        "object_name": title, "object_type": "Work",
                        "sentence_id": f"{aid}:s{sentence_index}",
                        "evidence_text": sentence[:450],
                        "evidence_start": str(offset),
                        "evidence_end": str(offset + len(sentence)),
                        "trigger_text": cast_rule_id,
                        "extraction_method": "deterministic_explicit_role_rule",
                        "rule_id": cast_rule_id,
                        "auto_status": "candidate_not_verified",
                        "human_review_status": "pending", "reviewer": "", "review_notes": "",
                        "scope_status": "scope_uncertain_pending_review",
                    }
    return list(out.values())


def extract(args) -> dict:
    articles = {r["article_id"]: r for r in csv_read(NEWS_DATA / "articles.csv")}
    documents = csv_read(NEWS_DATA / "article_documents.csv")
    results = {r["assertion_id"]: r for r in csv_read(NEWS_DATA / "relation_assertions.csv")}
    processed = 0
    for doc in documents:
        if doc["fetch_status"] != "fetched" or doc["article_id"] not in articles:
            continue
        if processed >= args.limit:
            break
        path = article_path(doc["article_id"])
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        for row in candidates_for_article(articles[doc["article_id"]], body):
            results[row["assertion_id"]] = row
        processed += 1
    csv_write(NEWS_DATA / "relation_assertions.csv", sorted(results.values(),
              key=lambda x: x["assertion_id"]), REL_FIELDS)
    result = {"stage": "news_relation_extraction_v2", "at": now(),
              "processed_articles_this_run": processed,
              "relation_candidates_total": len(results), "wiki_inputs_used": 0,
              "relationship_types_in_candidates": sorted({r["relationship_type"] for r in results.values()}),
              "notice": "Pattern rules are intentionally narrow. No relation is verified automatically."}
    json_report("extract.json", result)
    return result
