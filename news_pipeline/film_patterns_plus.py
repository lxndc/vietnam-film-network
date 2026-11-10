"""Additional high-recall but explicitly evidenced Vietnamese film-credit rules.

No ungrounded pairwise co-occurrence links. Assertions are machine-screened, not
independently validated. This is intentionally a small conservative upgrade.
"""
from __future__ import annotations

import re

from . import extract as original
from .common import id_for, text_key

P = original.PERSON
Q = r'["“‘«](?P<work>[^"”’»\n]{2,80})["”’»]'
FLAGS = re.I | re.UNICODE

# Both endpoints and the precise role appear in the same source sentence.
ROLE_RULES = [
    ("v4dir01", "DIRECTED", rf'(?:bộ\s+)?phim\s+{Q}\s+do\s+(?:đạo\s+diễn\s+)?(?P<person>{P})\s+(?:đạo\s+diễn|thực\s+hiện|cầm\s+trịch|chỉ\s+đạo)(?=$|[.,;:!?\s])'),
    ("v4dir02", "DIRECTED", rf'(?:bộ\s+)?phim\s+{Q}\s+(?:là\s+)?(?:bộ\s+phim\s+)?của\s+đạo\s+diễn\s+(?P<person>{P})(?=$|[.,;:!?\s])'),
    ("v4dir03", "DIRECTED", rf'đạo\s+diễn\s+(?P<person>{P})\s+(?:đứng\s+sau|thực\s+hiện|cầm\s+trịch|chỉ\s+đạo)\s+(?:bộ\s+)?phim\s+{Q}'),
    ("v4dir04", "DIRECTED", rf'(?P<person>{P})\s+(?:là\s+đạo\s+diễn|đảm\s+nhận\s+vai\s+trò\s+đạo\s+diễn)\s+(?:của|cho)\s+(?:bộ\s+)?phim\s+{Q}'),
    ("v4cast01", "ACTED_IN", rf'(?:diễn\s+viên\s+)?(?P<person>{P})\s+(?:tham\s+gia|góp\s+mặt|đóng\s+chính|đóng\s+vai|thủ\s+vai)\s+(?:trong\s+)?(?:bộ\s+)?phim\s+{Q}'),
    ("v4cast02", "ACTED_IN", rf'(?:bộ\s+)?phim\s+{Q}\s+(?:quy\s+tụ|có\s+sự\s+tham\s+gia\s+của|có\s+sự\s+góp\s+mặt\s+của)\s+(?:diễn\s+viên\s+)?(?P<person>{P})(?=$|[.,;:!?\s])'),
    ("v4write01", "WROTE", rf'(?:bộ\s+)?phim\s+{Q}\s+(?:có\s+)?kịch\s+bản\s+(?:do|của)\s+(?:biên\s+kịch\s+)?(?P<person>{P})\s+(?:viết|chấp\s+bút)'),
    ("v4write02", "WROTE", rf'biên\s+kịch\s+(?P<person>{P})\s+(?:viết\s+kịch\s+bản|chấp\s+bút)\s+(?:cho\s+)?(?:bộ\s+)?phim\s+{Q}'),
    ("v4produce01", "PRODUCED", rf'nhà\s+sản\s+xuất\s+(?P<person>{P})\s+(?:sản\s+xuất|đứng\s+sau)\s+(?:bộ\s+)?phim\s+{Q}'),
    ("v4voice01", "VOICE_ACTED_IN", rf'(?:diễn\s+viên|nghệ\s+sĩ)\s+(?P<person>{P})\s+lồng\s+tiếng\s+(?:cho|trong)\s+(?:bộ\s+)?phim\s+{Q}'),
    ("v4music01", "COMPOSED_MUSIC_FOR", rf'nhạc\s+sĩ\s+(?P<person>{P})\s+(?:sáng\s+tác|viết|soạn)\s+nhạc\s+(?:cho\s+)?(?:bộ\s+)?phim\s+{Q}'),
]
COMPILED = [(rule, relation, re.compile(expr, FLAGS)) for rule, relation, expr in ROLE_RULES]

CAST_LIST = re.compile(
    rf'(?:bộ\s+)?phim\s+{Q}\s+(?:quy\s+tụ|với\s+dàn\s+diễn\s+viên\s+gồm|có\s+dàn\s+diễn\s+viên\s+gồm|có\s+sự\s+tham\s+gia\s+của)\s+(?:các\s+diễn\s+viên\s+|diễn\s+viên\s+)?(?P<cast>[^.!?;:\n]{{8,175}})',
    FLAGS,
)
SPECULATIVE = re.compile(r'(?:tin đồn|đồn đoán|nghi vấn|được cho là|có thể sẽ|chưa xác nhận|dự kiến)', FLAGS)


def _assertion(article: dict, sentence: str, start: int, index: int, rule: str,
               relation: str, person: str, work: str) -> dict:
    aid = article['article_id']
    return {
        'assertion_id': id_for('ASSERT', aid, relation, person, work, index, rule),
        'article_id': aid, 'outlet_id': article['outlet_id'], 'canonical_url': article['canonical_url'],
        'subject_id': id_for('PERSON', text_key(person)), 'subject_name': person, 'subject_type': 'Person',
        'relationship_type': relation, 'object_id': id_for('WORK', text_key(work)),
        'object_name': work, 'object_type': 'Work', 'sentence_id': f'{aid}:s{index}',
        'evidence_text': sentence, 'evidence_start': str(start), 'evidence_end': str(start + len(sentence)),
        'trigger_text': rule, 'extraction_method': 'deterministic_explicit_role_rule',
        'rule_id': rule, 'auto_status': 'candidate_not_verified',
        'human_review_status': 'not_required_by_this_workflow', 'reviewer': '', 'review_notes': '',
        'scope_status': 'automated_evidence_screening',
    }


def candidates(article: dict, body: str) -> list[dict]:
    output = {}
    for idx, (start, sentence) in enumerate(original.sentences(body)):
        if len(sentence) > 450 or SPECULATIVE.search(sentence):
            continue
        for rule, relation, pattern in COMPILED:
            for m in pattern.finditer(sentence):
                person = original.clean_entity_name(m.group('person'))
                work = original.clean_entity_name(m.group('work'))
                if not original.is_reasonable_person(person) or not original.is_reasonable_work(work):
                    continue
                if not original.candidate_name(person) or not original.candidate_name(work, 2):
                    continue
                if text_key(person) == text_key(work):
                    continue
                key = (relation, text_key(person), text_key(work))
                output.setdefault(key, _assertion(article, sentence, start, idx, rule, relation, person, work))
        for m in CAST_LIST.finditer(sentence):
            work = original.clean_entity_name(m.group('work'))
            if not original.is_reasonable_work(work) or not original.candidate_name(work, 2):
                continue
            raw_list = m.group('cast')
            # Reject unrelated clauses and cap to initial cast enumeration.
            raw_list = re.split(r'\s+(?:trong\s+khi|còn|đồng\s+thời|để|nhưng|với\s+vai)\b', raw_list, maxsplit=1, flags=FLAGS)[0]
            if len(raw_list) > 170:
                continue
            names = re.split(r'\s*,\s*|\s+và\s+|\s+cùng\s+', raw_list)
            if len(names) < 2 or len(names) > 12:
                continue
            for fragment in names:
                person = original.clean_entity_name(re.sub(r'^(?:NSND|NSƯT|nghệ\s+sĩ|diễn\s+viên)\s+', '', fragment, flags=FLAGS))
                if not original.is_reasonable_person(person) or not re.fullmatch(P, person):
                    continue
                if not original.candidate_name(person) or text_key(person) == text_key(work):
                    continue
                key = ('ACTED_IN', text_key(person), text_key(work))
                output.setdefault(key, _assertion(article, sentence, start, idx, 'v4castlist', 'ACTED_IN', person, work))
    return list(output.values())
