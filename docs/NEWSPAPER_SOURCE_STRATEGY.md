# Newspaper-First Collection Strategy

## Acceptance targets

| Measure | Inferred baseline | Revised target |
|---|---:|---:|
| Verified core nodes | 2,000 | 2,200 |
| Verified edges | 5,000 | 5,500 |
| Populated relation types | 10 | 11 |
| Edge Precision | >90% | >90% |

The baseline is inferred by halving the previous doubled targets. Precision is not relaxed. Candidate counts never count as acceptance.

## Discovery and collection

1. Read official RSS feeds and source archives from `config/news_sources.csv`.
2. Save feed GUID, canonical URL, title, author, published time, section, outlet, discovered time.
3. Fetch only public article pages; observe publisher terms, robots.txt and rate limits.
4. Use a descriptive User-Agent, cache responses, throttle by domain, and retry with backoff.
5. Deduplicate by canonical URL, normalized title and content hash.
6. Track republication/syndication groups. Republishing one wire story does not create independent corroboration.
7. Store article metadata, URL, content hash and minimal evidence spans. Do not publicly redistribute full copyrighted article text.

## Entity extraction

Entity types: `Person`, `Work`, `Organization`.

Store each mention before merging:
`mention_id,article_id,sentence_id,entity_text,normalized_text,entity_type,char_start,char_end,context_sentence,confidence,canonical_entity_id,resolution_status`.

Use project-owned IDs. Resolve people with the context of their role, work, organization, career details and article context. Names alone are insufficient for merging homonyms. Wikidata QIDs are not required.

## Relation extraction

Allowed initial ontology:
`ACTED_IN`, `VOICE_ACTED_IN`, `DIRECTED`, `PRODUCED`, `EXECUTIVE_PRODUCED`, `WROTE`, `COMPOSED_MUSIC_FOR`, `CINEMATOGRAPHED`, `EDITED`, `DISTRIBUTED_BY`, `BROADCAST_BY`.

Examples of explicit triggers:
- “đảm nhận vai ... trong phim ...” -> `ACTED_IN`
- “do ... đạo diễn” -> `DIRECTED`
- “đơn vị ... sản xuất” -> `PRODUCED`
- “kịch bản do ... chấp bút” -> `WROTE`
- “phát hành bởi ...” -> `DISTRIBUTED_BY`
- “phát sóng trên ...” -> `BROADCAST_BY`

Do not create relation from co-occurrence, tags, captions alone, speculative claims, unresolved pronouns or role ambiguity. An article saying a person is connected with a title without describing their role does not support `ACTED_IN`.

Each assertion needs subject, predicate, object, article URL, sentence ID, short evidence span, trigger phrase, extraction model/method/version and confidence.

## Evidence review states

- `candidate`: machine extracted, not reviewed.
- `source_accessible`: original article fetched.
- `supports_exact_edge`: sentence supports this exact subject-predicate-object.
- `independent`: article has independent origin, not a syndicated duplicate.
- `verified`: scope eligible and human checked.
- `rejected`: contradicted or unsupported.
- `uncertain`: insufficient context/evidence.

Reachable URL != evidence. Reputable outlet != every claim verified. Duplicate syndicated articles != independent sources.

## Gold Standard

Build a new stratified sample from the article-derived edge population after scope filtering and deduplication. Stratify by relationship and outlet. Two independent reviewers label `correct`, `incorrect`, or `uncertain`, then adjudicate disagreements. Report overall and per-type precision, sample size, reviewer agreement and confidence interval. Keep dataset version/hash with evaluation. Do not alter labels to reach target.

## Legacy Wiki data

Archive old Wikidata/Wikipedia candidate data for traceability. Do not merge it into the new candidate or production data, count it toward targets, or use it as evidence for newspaper-derived edges.
