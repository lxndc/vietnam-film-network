# Vietnam Film Network – News V2.2

## Purpose

V2.2 builds on installed V2.1. It targets the two main bottlenecks: RSS only exposing recent stories and narrow single-person extraction patterns.

This package adds bounded publisher archive/sitemap backfill, expansion of verified RSS categories, explicit multi-actor cast extraction, evidence offset checking, fetch retry controls, and a read-only progress dashboard. **It does not create fictitious edges, run human reviews, or promise 90% measured Precision.**

## Acceptance targets

| Requirement | Target |
|---|---:|
| Independently verified core nodes | 2,200 |
| Independently verified edges | 5,500 |
| Populated relation types | 11 |
| Independently adjudicated Gold Standard Precision | >90% |

## Install in an existing V2/V2.1 project

```bash
bash INSTALL_V2_2.sh /path/to/vietnam-film-network
```

A timestamped backup is created in `.backup/`. Existing source rows are retained, and new RSS feed rows are appended only when absent. The installer does not change cached article texts, CSVs, Gold Standard, Wiki archives or Neo4j data.

## Run current articles first

```bash
python -m news_pipeline.cli diagnose --examples 10
python -m news_pipeline.cli extract
python -m news_pipeline.cli audit
python -m news_pipeline.cli prepare-reviews
python -m news_pipeline.cli progress
```

## Discover additional recent articles

```bash
python -m news_pipeline.cli collect --limit 300 --delay 3
```

RSS only exposes a recent slice; repeated requests to an unchanged feed do not create historical coverage.

## Backfill from publication archives

```bash
python -m news_pipeline.cli backfill --mode archive --source BVH --source BCP --limit 1500 --max-pages 20 --delay 3
```

Only explicitly registered publisher archive pages are used. If the outlet blocks a request, the program records a warning and skips it. No login, CAPTCHA bypass, search-engine scraping, or bulk redistribution of article text is attempted.

## Backfill from publisher-declared sitemaps

```bash
python -m news_pipeline.cli backfill --mode sitemap --source VNE --source TN --source VTV --source TT --limit 2500 --max-sitemaps 30 --delay 3
```

Uses sitemap locations declared by each publisher's `robots.txt`; optional `--sitemap URL` is accepted only for the selected publisher. A sitemap might not publish historical archives or sufficient titles; a zero result is not a guarantee the site has no old articles.

This is bounded to at most 4MB compressed/network response and 8MB uncompressed sitemap data, and site-owned URLs. Article candidates must have article-shaped URLs and film-related title/slug/path evidence. An article candidate is not an evidence-verified edge.

## Fetch, extract and audit

```bash
python -m news_pipeline.cli fetch --limit 1000 --delay 3
python -m news_pipeline.cli extract
python -m news_pipeline.cli audit
python -m news_pipeline.cli prepare-reviews
python -m news_pipeline.cli progress
```

`fetch` now skips previously failed URLs by default so they do not repeatedly fill the request budget. To deliberately retry them:

```bash
python -m news_pipeline.cli fetch --limit 200 --delay 3 --retry-failed
```

A newly fetched article preserves paragraph boundaries. Existing cached texts remain unchanged. The audit verifies a candidate evidence span's exact offsets against the local source text; machine pass still means **needs independent review**, not verified true.

## Outputs

```text
data/news_v2/articles.csv
  article_documents.csv
  relation_assertions.csv
  article_audit.csv
  edge_audit.csv
  edge_review.csv
  gold_standard_sample.csv
  private/article_text/                   # Gitignored
  export/verified/
reports/news_v2/collect.json
  backfill.json
  fetch.json
  diagnose.json
  extract.json
  audit.json
  reviews.json
  progress.json
  evaluation.json
```

The `progress` command reports counts and deficits. Its optional estimate is the number of additional fetched articles needed to obtain 5,500 **audit-pass candidates** at observed yield, not a prediction of 5,500 verified edges or 90% Precision.

## Gold Standard

After enough audited candidate edges exist:

```bash
python -m news_pipeline.cli sample --size 329
```

Do not create the official sample too early; if there are fewer eligible assertions, the sample will be smaller. Existing Gold Standard files are protected from overwrite unless explicitly forced; forcing can destroy reviewer work.

Reviewer A and Reviewer B must independently inspect original articles. The project must retain distinct reviewer names, adjudicated labels, checked URL and notes. Only then:

```bash
python -m news_pipeline.cli evaluate
python -m news_pipeline.cli export
python -m news_pipeline.cli status
```

The `status` gate requires 2,200 verified nodes, 5,500 verified edges, 11 populated relation types and measured Precision >90%. The pipeline does not label its own Gold Standard or count unreviewed candidates as verified.

## Limitations

1. Site archive markup and sitemap formats change. Diagnostics expose fetch errors; adapt publisher-specific selectors when needed, never fabricate article titles or edges.
2. Named-entity resolution is currently name-based and vulnerable to homonyms. Human identity confirmation remains mandatory for production edges.
3. The extractor focuses on explicit phrase patterns, including named cast lists. It is not a general Vietnamese NER/RE model; more sources and specialized extraction models may be required to reach all numeric targets.
4. Full-page copyrighted article bodies must remain private, subject to publisher terms. Respect robots policy and any additional site restrictions.
5. The WSL dataset is not accessible to this ZIP authoring environment; no claim is made that targets have been achieved on the user's actual data.
