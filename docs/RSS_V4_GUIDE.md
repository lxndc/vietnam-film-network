# Vietnam Film Network — RSS V4 coverage + relation-recall patch

This overlay is designed for the existing News V3 single-graph pipeline. It does not touch `data/news_v2/*.csv` or Neo4j at installation, and does not read Wiki files.

## Install

Run `bash INSTALL.sh "$PWD"` from the extracted package directory, passing your real project root. The installer backs up the existing source registry, keywords, and `high_yield.py` in `.backup/rss-v4-*` before adding feeds and a deterministic role extraction hook. Reinstalling is idempotent for feed URLs and hook.

## Added feeds

The patch registers up to 11 supplementary channels, subject to whether a URL is already present. The source registry is publisher-specific, not an aggregator. Feeds are drawn from official RSS directories of Tiền Phong, VTV, Thanh Niên, and Tuổi Trẻ. **They were listed by their publishers, but their live availability, response type, and article yield have not been tested in this offline package**; the collector records failures and skips redirected/invalid feeds.

## Single automatic pipeline (default)

```bash
python -u -m news_pipeline.rss_expand run \
  --limit 300 --delay 2 --fetch-limit 200 --fetch-batches 30 \
  2>&1 | tee reports/news_v2/rss_v4.log
```

The `run` command performs RSS discovery, article fetching, evidence-only relation extraction, 100% deterministic candidate screening, de-duplication, CSV export, and import into the **same** Neo4j `NewsV2` graph. It does not need manual labels. The existing News V3 Neo4j label constraint fix must have been applied before import. Use `--no-import` to inspect generated CSV without changing Neo4j.

## Incremental RSS-only collection (optional)

```bash
python -u -m news_pipeline.rss_expand collect --limit 300 --delay 2 \
  2>&1 | tee reports/news_v2/rss_v4_only.log
```

The collector examines at most `--limit` entries **per feed**, de-duplicates by original publisher + canonical article URL, writes `data/news_v2/articles.csv` after **every** feed, writes `reports/news_v2/rss_v4_collect.json`, and prints each feed's yield to stderr. The collector skips redirected feeds, articles outside the publisher's hostname, and Wiki domains. Re-running is safe. `--source TP` or another outlet restricts the source.

## Reprocess already downloaded articles (no new RSS)

With V3's Neo4j label conflict fix already applied:

```bash
python -u -m news_pipeline.unified run \
  --discover none --fetch-limit 200 --fetch-batches 30 --delay 2 \
  2>&1 | tee reports/news_v2/unified_v4.log
python -m news_pipeline.rss_expand report
python -m json.tool reports/news_v2/unified_graph.json
```

This fetches newly discovered article URLs, rebuilds assertions from saved article texts (including the new explicit-role templates), screens **every** candidate using original content, and imports to the single `NewsV2` graph. No manual label data is required. This is machine screening; not an independently measured precision result.

**A successful RSS feed is not a guarantee of relevant, unique film-relationship evidence.** The baseline of 451 fetched articles yielded only 7 assertions. Accordingly, the patch will not guarantee 2,200 nodes, 5,500 edges, 11 populated types or >90% independently measured precision. Historical article coverage and better Vietnamese NLP/entity linking may be needed.

## Verify

```bash
python -m json.tool reports/news_v2/rss_v4_collect.json
python -m json.tool reports/news_v2/rss_v4_progress.json
python -m json.tool reports/news_v2/unified_extraction.json
python -m json.tool reports/news_v2/unified_graph.json
```

Note `--discover none` runs no new RSS discovery in `unified`, since `rss_expand collect` already did it.

Do not commit `.env`, local Neo4j credentials, or stored full newspaper article bodies. Attribution and robots/usage terms remain required.
