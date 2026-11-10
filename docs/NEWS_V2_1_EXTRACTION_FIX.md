# News V2.1 — Diagnose and fix zero extracted edges

## Failure observed

- 114 RSS articles were audited.
- 113 articles passed the technical article audit.
- `relation_assertions.csv` contained zero candidates.
- Gold Standard sampling failed with `No automatically eligible assertions`.

This is not a Gold Standard bug. A stratified sample cannot be made from an empty eligible assertion pool.

## Changes in this patch

- Added alternative explicit-role templates such as `Phim Mai do Trấn Thành đạo diễn`, `Phim Mai có sự tham gia của diễn viên Hồng Đào`, and explicit `Work -> Organization` production/distribution/broadcast templates.
- Retained old quoted-title templates.
- Added name/title plausibility filters to reduce overmatching and duplicate candidate suppression **within one extraction run**.
- Added a `diagnose` command that reads only the `data/news_v2` namespace and compares the current cached texts against current extraction rules.
- Preserved Gold Standard and manual review gates. A matching regex does not mark an edge correct.

## Steps in WSL

```bash
cd ~/projects/vietnam-film-network/vietnam-film-network
source .venv/bin/activate
python -m news_pipeline.cli diagnose --examples 8
python -m json.tool reports/news_v2/diagnose.json
python -m news_pipeline.cli extract
python -m json.tool reports/news_v2/extract.json
python -m news_pipeline.cli audit
python -m json.tool reports/news_v2/audit.json
python -m news_pipeline.cli prepare-reviews
```

For a quick quantitative check:

```bash
python - <<'PY'
import csv
from collections import Counter
from pathlib import Path
p=Path('data/news_v2/edge_audit.csv')
if p.exists():
    rows=list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
    print('Edge audit rows:', len(rows))
    print('Status counts:', dict(Counter(x['auto_review_status'] for x in rows)))
    print('Types:', dict(Counter(x['relationship_type'] for x in rows)))
else:
    print('edge_audit.csv does not exist')
PY
```

## Create Gold Standard only from a populated pool

After `audit`, if there is a nonzero number of `auto_pass_needs_independent_review` rows:

```bash
python -m news_pipeline.cli sample --size 329
```

The command samples **at most** the number of eligible assertions. If there are 20 eligible assertions, it creates only 20 rows. This does **not** satisfy the default independent-evaluation minimum of 200 and does not prove Precision >90%.

If a Gold Standard CSV already exists, the generator refuses to overwrite it without `--force`. Do not overwrite independently adjudicated labels.

Never fill Gold Standard labels automatically to manipulate measured Precision. For a valid result, human reviewers must examine original articles and independently adjudicate the sample.

## Why RSS alone cannot guarantee the target

RSS usually lists recent content only. Collecting 114 article candidates does not guarantee even one explicit, correctly extractable Person–Work–Organization relation. The 2,200 / 5,500 / 11 targets require substantial permitted historical article discovery and source review. Always keep discovered articles, machine assertions, independently verified edges, and Gold Standard precision separate.

## Safety and data isolation

The patch reads and writes `data/news_v2` only, and retains the earlier publisher URL allowlist. Wiki data is not used to seed entities or relations. The installer backs up the previous extractor/CLI before updating; it does not move or delete local files. No bypass of Neo4j production gates is included.
