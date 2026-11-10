#!/usr/bin/env bash
# Vietnam Film Network News V4: bounded growth run, without fabricating edges.
set -Eeuo pipefail

PROJECT="${VFN_PROJECT:-$HOME/projects/vietnam-film-network/vietnam-film-network}"
MAX_ROUNDS="${1:-3}"
if ! [[ "$MAX_ROUNDS" =~ ^[1-9][0-9]*$ ]] || (( MAX_ROUNDS > 10 )); then
  echo "Usage: bash vfn_run_to_counts_v4.sh [rounds: 1..10]" >&2
  exit 64
fi
cd "$PROJECT"
if [[ ! -f news_pipeline/rss_expand.py || ! -f news_pipeline/unified.py ]]; then
  echo "News V4 / V3 modules are missing in: $PWD" >&2
  exit 65
fi
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
mkdir -p reports/news_v2

# Prevent two crawlers/importers from overwriting the same checkpoint files.
if ps -eo args= | grep -E 'python(3(\.[0-9]+)?)? .*\-m news_pipeline\.(rss_expand|unified) run' | grep -v -F 'grep -E' >/dev/null; then
  echo "Another RSS V4/unified pipeline appears to be active. Stop or finish it before starting this one." >&2
  exit 66
fi

count_csv() {
  python - "$1" <<'PY'
import csv, pathlib, sys
p = pathlib.Path(sys.argv[1]); print(sum(1 for _ in csv.DictReader(p.open(encoding='utf-8-sig', newline=''))) if p.exists() else 0)
PY
}

printf 'Registering RSS V4 feeds (safe to repeat).\n'
python -m news_pipeline.rss_expand register

for (( round=1; round<=MAX_ROUNDS; round++ )); do
  before_urls=$(count_csv data/news_v2/articles.csv)
  before_edges=$(count_csv data/news_v2/export/graph/edges.csv)
  echo "========== ROUND $round/$MAX_ROUNDS: $before_urls URLs / $before_edges edges before =========="

  # V4 RSS: checkpoint after every publisher feed.
  python -u -m news_pipeline.rss_expand collect \
    --limit 1000 --delay 2 \
    2>&1 | tee "reports/news_v2/v4_rss_round_${round}.log"

  # RSS + historical publisher sitemap/archive, fetch, explicit evidence, audit, dedup, Neo4j.
  # Bounded per-publisher index work; all original robots and URL policy checks remain enforced.
  python -u -m news_pipeline.unified run \
    --discover both \
    --discover-limit 12000 \
    --max-sitemaps 12 \
    --max-pages 15 \
    --max-attempts 20 \
    --fetch-limit 250 \
    --fetch-batches 60 \
    --delay 2 \
    --batch-size 200 \
    2>&1 | tee "reports/news_v2/v4_unified_round_${round}.log"

  python -m news_pipeline.rss_expand report > "reports/news_v2/v4_progress_round_${round}.json"
  after_urls=$(count_csv data/news_v2/articles.csv)
  after_edges=$(count_csv data/news_v2/export/graph/edges.csv)

  if python - <<'PY'
import csv
from pathlib import Path
base = Path('data/news_v2/export/graph')
def read(name):
    path = base / name
    if not path.is_file(): return []
    with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
nodes, edges = read('nodes.csv'), read('edges.csv')
types = {e.get('relationship_type') for e in edges if e.get('relationship_type')}
print(f'GROWTH CHECK: nodes={len(nodes)}/2200 edges={len(edges)}/5500 types={len(types)}/11')
print('PRECISION: not independently measured; automatic screening is not a Gold Standard score')
raise SystemExit(0 if len(nodes) >= 2200 and len(edges) >= 5500 and len(types) >= 11 else 1)
PY
  then
    echo "All THREE machine-screened graph COUNT targets have been reached. Independent precision is unmeasured."
    exit 0
  fi

  if (( after_urls == before_urls && after_edges == before_edges )); then
    echo "No new URLs or graph edges in this round; stopping to avoid repeated crawling with no progress." >&2
    exit 2
  fi
  echo "Round $round added $((after_urls-before_urls)) URLs and $((after_edges-before_edges)) unique edges."
done

echo "Stopped after $MAX_ROUNDS bounded rounds. Graph count targets not all reached; see reports/news_v2/v4_progress_round_*.json." >&2
exit 2
