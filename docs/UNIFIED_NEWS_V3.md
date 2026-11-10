# News V3: one automatic newspaper graph

Purpose: One execution runs discovery (optional), article fetch, evidence-local relation extraction, full technical audit, deduplication, and direct import into a single Neo4j `:NewsV2` graph. No human review or reviewer-label input is required to execute this pipeline. The report **does not** claim that automated verification is independent Gold Standard evaluation or that precision exceeds 90%.

Prerequisites: existing News V2.2 with sitemap hotfix, configured publishers, `.env` Neo4j credentials, `pip install -r requirements-news-v2.txt`. The installer adds the official Dân trí entertainment RSS channel once (ID `DTR`) without overwriting existing publishers. It also backs up and fixes the sitemap backfill so multiple feeds from the same outlet do not trigger duplicate sitemap walks.

Run against all previously downloaded articles (fastest initial diagnosis):

```bash
python -u -m news_pipeline.unified run --discover none --skip-fetch 2>&1 | tee reports/news_v2/unified.log
```

One command to discover from RSS, publisher archives and permitted sitemaps, fetch in checkpoint batches, extract, audit and import:

```bash
python -u -m news_pipeline.unified run --discover both --discover-limit 1500 --max-sitemaps 10 --max-pages 10 --max-attempts 20 --fetch-limit 200 --fetch-batches 10 --delay 2 2>&1 | tee reports/news_v2/unified.log
```

An additional batch without rediscovery:

```bash
python -u -m news_pipeline.unified run --discover none --fetch-limit 200 --fetch-batches 10 --delay 2
```

Read statuses:

```bash
python -m news_pipeline.unified status
python -m json.tool reports/news_v2/unified_graph.json
python -m json.tool reports/news_v2/unified_neo4j.json
```

The graph uses one label `:NewsV2`, with subtype labels `:Person`, `:Work`, `:Organization` and a `dataset='news_v2'` property. Previously imported `:NewsV2Auto` records are left untouched by default; `--cleanup-legacy` deletes only the old tool-owned `news_v2_auto` nodes after a successful import. **This deletion is irreversible.** The unified importer uses `MERGE` and does not delete other data.

CSV outputs:

- `data/news_v2/relation_assertions.csv` (regenerated from fetched article bodies only)
- `data/news_v2/unified_screening.csv` (one status per candidate)
- `data/news_v2/export/graph/nodes.csv`
- `data/news_v2/export/graph/edges.csv`
- `data/news_v2/export/graph/edge_evidence.csv`
- `reports/news_v2/unified_extraction.json`
- `reports/news_v2/unified_graph.json`
- `reports/news_v2/unified_neo4j.json`

The collector cannot invent sources or relationships. If only 2 nodes remain, `fetched_articles`, `candidate_assertions`, `machine_pass_assertions` and `rejection_reasons` in the report identify the bottleneck. If a stage has fewer records than the thresholds, the reported gap remains positive rather than being altered artificially.

Academic validity: rule replay, exact body hashes, publisher-domain checks, offsets and source links are automated quality gates. Their 100% coverage is **not** 100% factual correctness. Cross-outlet agreement is reported, but is also not an independent precision estimate. No Gold Standard labels are generated.

Neo4j verification:

```cypher
MATCH (n:NewsV2) WHERE n.dataset='news_v2' RETURN count(n) AS nodes;
MATCH (:NewsV2)-[r]->(:NewsV2) WHERE r.dataset='news_v2' RETURN count(r) AS edges, count(DISTINCT type(r)) AS types;
MATCH (:NewsV2)-[r]->(:NewsV2) WHERE r.dataset='news_v2' RETURN type(r) AS relation, count(r) AS total ORDER BY total DESC;
```

Only commit code/documentation and non-sensitive aggregate JSON. Do not commit raw article bodies, private caches, `.env`, or the full evidence CSV by default.
