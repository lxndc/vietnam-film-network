# Vietnam Film Network – 100% machine-screened graph and Neo4j staging

## Purpose

This package adds an **automated technical audit**, not an independently validated Gold Standard. It does not populate fake reviewer names, reviewer labels, `adjudicated_label`, or false Precision numbers. It does not bypass the production-import acceptance guard.

The script operates only inside `data/news_v2` and `reports/news_v2` and reads original publisher article bodies in the private local news cache. It neither reads nor imports legacy Wikidata/Wikipedia data.

## Technical checks performed for every assertion

- Existing News V2 full-coverage article/edge audit is regenerated from current input.
- Original source URL is on an allowlisted publisher and is not a Wiki domain.
- Article ID, outlet and canonical URL match the current article and fetch metadata.
- Original cached article body exists, length >=250, and SHA-256 matches the fetch record.
- Exact evidence text matches the article at the recorded character offsets.
- Original extraction rule is replayed and must match the **specific** subject, relation and object.
- Relation ontology, direction, node types, IDs and names conform to the current V2 schema.
- Speculative evidence patterns, duplicate claims within an article, self edges and inconsistent IDs are rejected.
- Assertions are deduplicated by `(subject_id, relationship_type, object_id)` while preserving all evidence rows.

Passing these checks is `machine_screened`, **not** `correct`, `verified`, or a proven factual accuracy rate.

## Install (WSL, project root)

Download `vfn_news_auto_safe_import_patch.zip` to Windows Downloads.

```bash
cd ~/projects/vietnam-film-network/vietnam-film-network
source .venv/bin/activate
WIN_PROFILE="$(cmd.exe /c 'echo %USERPROFILE%' | tr -d '\r')"
ZIP="$(wslpath -u "$WIN_PROFILE")/Downloads/vfn_news_auto_safe_import_patch.zip"
mkdir -p /tmp/vfn-auto-news
unzip -oq "$ZIP" -d /tmp/vfn-auto-news
bash /tmp/vfn-auto-news/vfn_news_auto_safe_import_patch/INSTALL_AUTO_NEWS.sh "$PWD"
```

## Run 100% automated screening

Run as one uninterrupted sequence. Do not run the Wiki import script.

```bash
python -m news_pipeline.cli extract
python scripts/news_auto_finalize.py prepare --sample-size 329
python -m json.tool reports/news_v2/auto_screening.json
```

The script creates the blank-label Gold Standard **only if one does not already exist**. It does not overwrite existing human reviewer files.

Output files:

```text
data/news_v2/auto_screening.csv
data/news_v2/auto_gold_screening.csv
data/news_v2/gold_standard_sample.csv         # ONLY created if missing; reviewer labels stay blank
data/news_v2/export/auto_staging/nodes.csv
data/news_v2/export/auto_staging/edges.csv
data/news_v2/export/auto_staging/edge_evidence.csv
reports/news_v2/audit.json
reports/news_v2/auto_screening.json
reports/news_v2/gold_auto_population_sampling.json   # if new sample created
```

`auto_gold_screening.csv` provides `machine_status` and `gold_standard_label=UNASSESSED`. It is **not** the scientific Gold Standard or a Precision estimate.

## Import machine-screened graph into Neo4j staging

```bash
pip install neo4j python-dotenv
```

Put connection settings in the project's **local** `.env` (never commit `.env`):

```ini
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<local password>
NEO4J_DATABASE=neo4j
```

Run:

```bash
python scripts/news_auto_finalize.py import
python -m json.tool reports/news_v2/neo4j_auto_staging.json
```

Imported nodes are labeled `:NewsV2Auto` plus `:Person`, `:Work`, or `:Organization`. Edges have `dataset='news_v2_auto'`, `verification_status='machine_screened'`, and `precision_status='not_independently_measured'`. Old Wiki nodes and human-verified NewsV2 nodes are not modified.

Inspect with Neo4j Browser:

```cypher
MATCH (n:NewsV2Auto) RETURN count(n) AS machine_nodes;
```

```cypher
MATCH (:NewsV2Auto)-[r]->(:NewsV2Auto)
WHERE r.dataset = 'news_v2_auto'
RETURN type(r) AS relationship_type, count(r) AS machine_edges
ORDER BY machine_edges DESC;
```

## Difference from production/Gold Standard

100% machine screening covers every assertion. It does **not** demonstrate Edge Precision >90% or imply that any claimed academic acceptance threshold has been met. To obtain that measurement, sampled edges must have an independent reference judgement. This package does not manufacture or assume that judgement.

The original production importer remains unchanged and will continue to reject imports whose independent evidence requirements are not satisfied. The separate staging import is usable entirely without manual annotation.

## Push the implementation to GitHub

After the Neo4j staging import **succeeds**:

```bash
cd ~/projects/vietnam-film-network/vietnam-film-network
cat >> .gitignore <<'EOF'

# Private source text and local environments
data/news_v2/private/
.env
.venv/
.backup/
# Local copies of copyrighted article text
EOF

git rm -r --cached --ignore-unmatch data/news_v2/private/ .env .venv/ .backup/
git add scripts/news_auto_finalize.py docs/AUTO_SCREENING_AND_NEO4J.md .gitignore
# Optional: only non-sensitive generated summary reports
git add reports/news_v2/auto_screening.json reports/news_v2/neo4j_auto_staging.json

git diff --cached --name-only
git diff --cached --check
git commit -m "feat: add automated newspaper screening and isolated Neo4j staging import"
git push -u origin main
```

If `git add reports/...` shows the files are ignored, only add the script/docs/.gitignore. Never use `git add -f` for private caches or secrets. Gitignore does not erase a secret from earlier commit history. Review the staged list before committing.
