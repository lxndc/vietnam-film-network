# Project Status — Expanded Collector v0.3

Status: v0.3 source package prepared and unit-tested; not yet run against the user's WSL environment.

## Targets
- 4,000 unique Core Nodes (Person + Work + Organization)
- 10,000 valid, evidence-backed, deduplicated Edges
- 20 Relationship Types with real, verified records
- Edge Precision > 90% on an independent labeled sample

## Changes from v0.2
- Wikipedia search is paginated in up to 50-result pages; `--wikipedia-limit` supports 1–500.
- Work QIDs from Wikipedia pages with Work scope are unioned with Wikidata Work seeds for credit retrieval.
- Expansion report distinguishes Wikidata seed count, Wikipedia Work QID count and selected unique QID union.
- List-of-films index pages use `scope: index`, preventing these index pages from being counted as Work entities.
- Five further audiovisual credit properties are supported: make-up artist, scenographer, assistant director, generic film crew member (requires explicit role qualifier P3831), and art director.
- `P2438` narrator and `P11108` recorded participant candidates are limited to human targets to reduce false Person classification.
- Task namespace is upgraded to v3 so v2 checkpoints do not suppress the new collection tasks.

## Not yet completed
- No live v0.3 collection has been run from the user's WSL environment.
- No candidate is considered verified solely because it was collected or passed structural validation.
- Cross-source entity resolution (including Wikipedia/Wikidata identities), manual evidence review and independent precision measurement remain required.
- 25 supported property mappings do not imply 20 populated/verified relationship types.
- No Neo4j import or final acceptance is claimed.

## Data integrity safeguards
- Stable IDs and append-only raw JSONL are retained.
- Existing v2 raw data and checkpoints are not deleted.
- Existing review CSVs should be preserved; new records must be reviewed by candidate ID.
- `P3092` generic crew member requires role qualifier `P3831`.
- Narrator and recorded-participant claims are constrained to human items before they can be typed as Person.
- Every Edge still requires source evidence and validation before import.
