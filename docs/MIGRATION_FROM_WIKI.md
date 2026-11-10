# Migration from Wiki-based sources to newspaper-first

## Required changes

1. Disable Wikidata and Wikipedia as candidate node/edge generators.
2. Stop using Wikidata work seeds, Wikipedia pagination and Wikidata credits.
3. Discover articles from RSS feeds and publisher archives.
4. Create article metadata and entity mention datasets.
5. Resolve Person/Work/Organization with context and project-owned IDs; QIDs are not required.
6. Extract relations only from explicit sentence-level evidence.
7. Keep old Wiki-derived datasets in a `legacy` archive; do not merge them into production.
8. Create a fresh Gold Standard from news-derived edges.
9. Reuse Neo4j only after verifying new export and evidence schemas.

## Revised targets

- 2,200 verified core nodes
- 5,500 verified edges
- at least 11 populated relationship types
- Edge Precision >90%

The first three targets are 10% above inferred baselines 2,000 / 5,000 / 10. Precision remains unchanged.

## Implementation checklist

- [ ] Validate `config/news_sources.csv`.
- [ ] Implement RSS discovery and article metadata collector.
- [ ] Implement article body extraction with publisher-specific fallbacks.
- [ ] Add robots/terms review, throttling, caching and backoff.
- [ ] Implement article deduplication and syndication grouping.
- [ ] Implement Vietnamese entity extraction.
- [ ] Implement project-owned entity IDs and alias resolution.
- [ ] Implement relation extraction with sentence-level evidence spans.
- [ ] Create human evidence review queue.
- [ ] Generate stratified independently adjudicated Gold Standard.
- [ ] Calculate overall and per-relation precision.
- [ ] Update acceptance config to 2,200 / 5,500 / 11 / >90%.
- [ ] Export verified nodes, edges and evidence.
- [ ] Test Neo4j staging import.
- [ ] Run production import only after all acceptance checks pass.

Never bypass the import precision guard or relabel pending assertions as correct.
