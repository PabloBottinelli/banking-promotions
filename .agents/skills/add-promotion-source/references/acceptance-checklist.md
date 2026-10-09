# Acceptance checklist — new promotion source

Use this checklist as the definition of done. Report failures explicitly instead of checking them off without evidence.

## Discovery

- [ ] The supplied source and its public entry URL were verified.
- [ ] Real sample responses were inspected; the catalog and detail structures are understood.
- [ ] Pagination/coverage and stable source IDs are understood, or the limitation is documented.
- [ ] Request throttling and public access constraints were considered.

## Scraping

- [ ] `<Source>Scraper` follows repository patterns and supports mocked HTTP requests.
- [ ] `scrape()` returns `ScrapeResult` and retains available raw source information.
- [ ] `source`, `source_id`, `scraped_at`, and source provenance are present where available.
- [ ] Missing IDs, failed pages/details, duplicates, and empty responses are handled safely.
- [ ] Incomplete extraction cannot be mistaken for a complete scrape in the synchronization pipeline.

## Normalization

- [ ] `<Source>Normalizer` returns valid `NormalizedPromotion` records.
- [ ] Discount, installments, validity, weekdays, caps, payment methods, channels, segments, eligibility, and terms are mapped where supported.
- [ ] Unknown data is not guessed; invalid required data fails visibly.
- [ ] One-to-many benefits, if present, produce stable, collision-free variant IDs.

## Integration and tests

- [ ] `sync_<source>.py` reuses `SyncRunner` correctly.
- [ ] Targeted scraper/normalizer tests pass using mocked real-source fixtures.
- [ ] The full repository test suite has been run and its result reported.
- [ ] Live read-only checks, if performed, are reported separately from unit tests.
- [ ] Workflow scheduling is enabled **only** when full extraction and safe completeness handling have been verified.
- [ ] No writes to production Supabase were made without explicit approval.

## Handoff

- [ ] All changed files, verified endpoints, test results, and outstanding risks are summarized.
- [ ] The result is labeled ready for review, partial/not scheduled, or blocked.
