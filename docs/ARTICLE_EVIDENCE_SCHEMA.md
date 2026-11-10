# Article and evidence CSV schemas

## `articles.csv`

`article_id,outlet_id,canonical_url,original_url,title,author,published_at,updated_at,section,language,discovered_at,fetched_at,http_status,content_hash,syndication_group,article_status,rights_note`

## `article_entities.csv`

`mention_id,article_id,sentence_id,entity_text,normalized_text,entity_type,char_start,char_end,context_sentence,extraction_method,model_version,confidence,canonical_entity_id,resolution_status,review_decision,reviewer,review_notes`

`entity_type` must be `Person`, `Work`, or `Organization`.

## `relation_assertions.csv`

`assertion_id,article_id,subject_mention_id,subject_entity_id,relationship_type,object_mention_id,object_entity_id,sentence_id,evidence_text,evidence_start,evidence_end,trigger_text,extraction_method,model_version,confidence,scope_status,source_status,review_status,reviewer,review_notes`

`evidence_text` is a short direct span supporting the exact relationship.

## `source_independence.csv`

`article_id,outlet_id,canonical_url,syndication_group,origin_type,independence_status,matched_article_id,matching_reason,reviewer,review_notes`

## `edges.csv` Neo4j export

`edge_id,source_id,target_id,relationship_type,verification_status,scope_status,evidence_count,source_article_ids,source_urls`

Only `verification_status=verified` rows may enter production.
