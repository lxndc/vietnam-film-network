# Changelog

## v0.3.0

- Paginate Wikipedia search with `sroffset`, in chunks of up to 50 results per request.
- Raise `--wikipedia-limit` maximum from 50 to 500; default to 100.
- Include Wikidata QIDs linked from Wikipedia Work-scope pages when retrieving film credits.
- Separate seed-QID, Wikipedia-Work-QID and selected-union counts in `expansion_report.json`.
- Exclude known list/index articles from Work candidates, including historic v2 matches.
- Extend supported credit properties with make-up artist (P4805), scenographer (P4608), assistant director (P5126), generic film crew member (P3092, requires role qualifier P3831), and art director (P3174).
- Restrict newly fetched narrator (P2438), recorded participant (P11108) and generic crew (P3092) candidates to human targets before classifying them as Person; historic v2 raw credit rows are retained for review.
- Include the role qualifier QID in generic crew candidate IDs so multiple distinct crew roles for the same person/work are not collapsed.
- Move checkpoint namespace to `expanded:v3` so previous v2 completion records do not skip the new tasks.
- Preserve existing raw JSONL and review decisions; no verified status is assigned automatically.

## Validation

- `python -m compileall -q collectors scripts tests`
- `python -m pytest -q` — 9 passed
- YAML parsing for both config files — passed
- Relationship mapping count — 25
