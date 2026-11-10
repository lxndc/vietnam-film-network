#!/usr/bin/env bash
# Finalize truthful graph metrics, commit safe code/docs; optionally push to origin.
set -Eeuo pipefail
PUSH=0
RUN=0
REQUIRE_COUNTS=0
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=1 ;;
    --run) RUN=1 ;;
    --require-counts) REQUIRE_COUNTS=1 ;;
    *) echo "Usage: bash scripts/finalize_and_commit.sh [--run] [--require-counts] [--push]" >&2; exit 64 ;;
  esac
done
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
if [[ ! -f news_pipeline/unified.py || ! -f news_pipeline/rss_expand.py ]]; then
  echo "ERROR: V3/V4 pipeline modules missing" >&2; exit 65
fi
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
# Never absorb pre-staged unrelated changes.
if ! git diff --cached --quiet; then
  echo "ERROR: Git index already has staged changes. Commit or unstage them first." >&2
  git diff --cached --name-only
  exit 66
fi
python -m py_compile news_pipeline/unified.py news_pipeline/rss_expand.py scripts/finalize_vfn.py
if (( RUN )); then
  if [[ ! -f scripts/run_to_targets.sh ]]; then
    echo "ERROR: scripts/run_to_targets.sh is missing. Copy vfn_run_to_counts_v4.sh first." >&2; exit 67
  fi
  set +e
  bash scripts/run_to_targets.sh 3
  result=$?
  set -e
  if (( result != 0 && result != 2 )); then
    echo "ERROR: Data pipeline failed with exit code $result" >&2; exit "$result"
  fi
fi
python scripts/finalize_vfn.py "$ROOT"
if (( REQUIRE_COUNTS )); then
  python - <<'PY'
import json, sys
from pathlib import Path
r=json.loads(Path('reports/news_v2/final_status.json').read_text(encoding='utf-8'))
if not r['counts_pass_both']:
    print('BLOCKED: CSV and Neo4j do not both meet the 3 count targets.',file=sys.stderr)
    sys.exit(68)
print('All three count targets met in CSV and Neo4j; precision remains unmeasured independently.')
PY
fi
# Only code, configuration, tests, and authored docs; never private article text or .env.
mapfile -d '' paths < <(python - <<'PY'
from pathlib import Path
import sys
root=Path('.')
names=['README.md','.gitignore','requirements-news-v2.txt','docs/RESULTS_LATEST.md']
patterns=['news_pipeline/**/*.py','scripts/**/*.py','scripts/**/*.sh',
          'config/**/*.csv','config/**/*.txt','config/**/*.yaml','config/**/*.yml',
          'docs/**/*.md','tests/**/*.py']
files=set()
for name in names:
    p=Path(name)
    if p.is_file() and not p.is_symlink(): files.add(p)
for pat in patterns:
    for p in root.glob(pat):
        if p.is_file() and not p.is_symlink() and '.venv' not in p.parts and '__pycache__' not in p.parts:
            if p.stat().st_size > 1_000_000:
                print(f'ERROR: unusually large source file {p}', file=sys.stderr)
                sys.exit(69)
            files.add(p)
for p in sorted(files):
    sys.stdout.buffer.write(str(p).encode()+b'\0')
PY
)
if (( ${#paths[@]} == 0 )); then
  echo "ERROR: No safe code/docs files found" >&2; exit 70
fi
# Do not force add ignored paths; fail rather than accidentally publish private data.
git add -- "${paths[@]}"
if git diff --cached --quiet; then
  echo "No new code/docs changes to commit."
else
  echo '=== FILES STAGED ==='
  git diff --cached --name-only
  git diff --cached --check
  # Defensive: forbid accidental private data in staging.
  python - <<'PY'
import subprocess,sys
paths=subprocess.check_output(['git','diff','--cached','--name-only','-z']).decode().split('\0')
for p in filter(None,paths):
    if p.startswith(('data/','reports/','.venv/','.backup/')) or p in ('.env',):
        print(f'ERROR: Refusing to commit private/cache file: {p}',file=sys.stderr)
        sys.exit(71)
PY
  git commit -m "feat: finalize RSS V4 pipeline and publish measured graph status"
fi
if (( PUSH )); then
  branch="$(git branch --show-current)"
  [[ -n "$branch" ]] || { echo 'ERROR: Detached HEAD' >&2; exit 72; }
  git remote get-url origin >/dev/null
  git push -u origin "$branch"
else
  echo 'Commit finished locally. Push with: git push origin "$(git branch --show-current)"'
fi
echo 'Done. Academic acceptance must still be checked independently for precision.'
