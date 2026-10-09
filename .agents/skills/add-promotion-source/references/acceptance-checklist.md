# Add-promotion-source acceptance checklist

Use this as a **gate**, not a rubber stamp. Record evidence for each applicable item. If evidence is missing, mark it unverified rather than passed.

## 1. Source investigation

- [ ] Real public source URL(s) and data retrieval method documented.
- [ ] Catalog, detail and optional alternate endpoints verified from live responses.
- [ ] Pagination/cursors/search ranking/per-request caps tested; category filtering verified.
- [ ] Source-total/completeness signal established **or explicitly declared unverified**.
- [ ] Distinction between merchant/entity, campaign/category and benefit examined.
- [ ] At least one real case with multiple benefits and one ambiguous/missing case examined where available.

## 2. Raw scraping

- [ ] `scrape()` produces correct `ScrapeResult` and raw records (`source`, stable `source_id`, UTC `scraped_at`, original fields, provenance).
- [ ] Detail failures and unavailable details differentiated; no fabricated success.
- [ ] Deduplication does not drop category associations or other useful evidence.
- [ ] `limit` and uncertain coverage never yield `complete=True`.
- [ ] Empty/partial runs do not silently overwrite good raw data.
- [ ] CLI entry point runs; logs catalog/unique/duplicates/details/errors/completeness/output path; no `runpy` warning.

## 3. Normalization

- [ ] All independently applicable benefits represented, including one-to-many variants.
- [ ] Merchant names come from merchant evidence, not benefit titles or vague heuristics.
- [ ] Explicit entity↔benefit relations verified; no arbitrary first promotion.
- [ ] Stable, unique `source_id` values, including variants/shared benefits.
- [ ] Correct dates, weekdays, discounts, installments, caps/scope/periods, payment methods, channels, eligibility, terms and minima where supported.
- [ ] Concurrent caps and source schema mismatches documented (not silently discarded).
- [ ] Skipped/non-normalizable records classified by precise reasons, not made to vanish.
- [ ] No invented values or modified shared schema to hide missing fields.

## 4. Testing

- [ ] Mock HTTP tests cover pagination/caps, errors, empty data, duplicates, completeness, raw saving and logging.
- [ ] Normalizer tests cover multiple/shared benefits, relationships and stable IDs.
- [ ] Real fixtures remain unmodified in tests; synthetic tests clearly separated.
- [ ] Clean-checkout tests do not depend on `backend/data/`, `.env` or previous runs.
- [ ] Targeted tests and full pytest suite executed; exact outcomes reported.

## 5. Real validation

- [ ] Read-only live scraper run performed, or why unavailable explained.
- [ ] Full raw dataset audited: entities, unique promotions, associations, normalized records, field coverage, errors, exclusions.
- [ ] At least 10 representative real cases checked against the source when available; list cases and results.
- [ ] Significant missing fields, relationships, filters and source-only limitations disclosed.
- [ ] Completeness and `ScrapeResult.complete` assessment backed by evidence.

## 6. Operations

- [ ] `sync_<source>.py` delegates to existing `SyncRunner`; no production sync executed.
- [ ] No Supabase writes, deployment, secrets access, workflow scheduling or PR actions without authorization.
- [ ] Files changed and remaining risks summarized.
- [ ] Integration explicitly labeled **Ready for review**, **Partial / not scheduled**, or **Blocked**.
