# Developer handoff — V2

**Status:** READY_FOR_INDEPENDENT_QA | PARTIAL | BLOCKED

- Source, official URL and exact catalog scope:
- Source mechanism (API/SSR/HTML), categories, pagination and completeness evidence:
- Files changed (scraper, normalizer, sync, tests):
- Commands run and **actual** outcomes (network errors and missing checks included):
- Raw records / unique source IDs / fetched details / unavailable / parser errors:
- Normalized V2 rows / unique per-variant IDs / groups / multiple benefits:
- Each excluded record and reason (if any):
- Evidence for benefit types, typed caps/minimums/stock, payment alternatives, weekdays, nullable dates, merchant checks:
- User-facing `specific_conditions` and preserved original `terms`:
- Unknowns and explicit source evidence limitations:
- Can `ScrapeResult.complete` be justified for the exact scope? Why?
- Does `scrape()` avoid saving raw and return a candidate only? Evidence/tests:
- Whole-candidate runner validation (raw IDs, zero variants, normalized IDs/source), expected rejection behavior:
- Does source `save_raw_promotions()` safely reject blanks, lost IDs and atomic failures? Historical baseline availability:
- `catalog_complete` (source evidence): YES / NO / UNKNOWN; why:
- `normalization_complete` (every raw entry/variant): YES / NO / UNKNOWN; why:
- `snapshot_replace_allowed` (source coverage flag, if exposed): TRUE / FALSE / UNKNOWN / NOT EXPOSED; why:
- `requires_review` (source coverage flag, if exposed): TRUE / FALSE / UNKNOWN / NOT EXPOSED; why:
- `safe_to_deactivate` (source coverage flag + independent rationale): TRUE / FALSE / UNKNOWN / NOT EXPOSED; why:
- Mock tests for `--validate-only`, blocked writes, partial upsert and deactivation gates; command/results:
- Runner `--validate-only` import/credential limitation and any scraper side effects:
- Raw/Supabase non-transactional failure/retry risks:
- Can deactivation safely occur after this normalization? If unknown, **block** and explain.
- No Supabase writes / no scheduling changes confirmation:
- Independent QA questions / suggested cases:
