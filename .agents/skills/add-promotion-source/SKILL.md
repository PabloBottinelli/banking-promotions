---
name: add-promotion-source
description: Investigate and integrate a new Argentine bank, wallet, or benefits source into Promociones Bancarias, creating scraper, deterministic normalizer, sync entry point, tests, and source-data validation. Use when asked to add a source, bank, billetera, or promotions website.
---

# Add a promotion source

Turn a public source URL/name into a **verified, reviewable integration**, not merely code that passes unit tests. Follow the root `AGENTS.md`; before finishing, check `references/acceptance-checklist.md` and use `references/validation-report.md` to report findings.

## 0 — Understand the code and define scope

1. Inspect `git status` and preserve user changes. Identify the user's source and starting URL. Use a unique, stable lowercase source slug.
2. Read `ScrapeResult`, `NormalizedPromotion`, `PaymentMethod`, `SyncRunner`, the workflow and representative existing scraper/normalizer/tests.
3. Establish what the source exposes: bank promotion, merchant, campaign, category, catalog card, variant, or redirect to a partner. Do **not** assume a catalog item is itself one benefit.
4. Identify up front if benefits are one-to-one, one-to-many, many-to-one or many-to-many with merchants. Check whether `normalize_many()` is needed.

## 1 — Investigate the live source before coding

1. Inspect the supplied site and its real network responses. Prefer verifiable public JSON APIs, then HTML, then browser interaction/Playwright only if it adds data that cannot be accessed otherwise.
2. Verify endpoint URLs, method/headers/parameters, cursor/page offsets, category filters, per-request caps, identifiers, link resolution and detail endpoints. Explore whether the UI hides variants under tabs/buttons.
3. Prove or bound the discovery coverage. Compare browser listings, API catalog metadata and actual returned unique IDs. **Test whether apparent totals are result-page counts rather than source totals**, and whether ranking/search endpoints silently cap responses.
4. Inspect sample records of different kinds: regular merchants, category benefits, campaigns, multi-benefit merchants, card-specific variants, entries with missing detail and external links. Save small, sanitized *unaltered* real fixtures for tests.
5. Make a field mapping note: where do merchant, title, discount, dates, days, caps, periodicity, methods, channels, minimum purchase, eligibility and legal terms originate? If a field has multiple competing values, preserve the source distinctions.
6. If access/coverage cannot be verified, document the precise blocker; do not fabricate endpoints, examples, or guarantees.

## 2 — Implement robust raw extraction

Files normally needed:

```text
backend/scraping/sources/<source>/__init__.py
backend/scraping/sources/<source>/scraper.py
```

- Implement `<Source>Scraper` with injectable HTTP client when practical and reuse existing retry/timeouts. Do not disable TLS verification by default.
- Implement catalog, pagination, detail retrieval, deduplication and partial failures explicitly. Avoid fetching the same shared detail many times (cache by verified stable ID when appropriate).
- Preserve original catalog/detail payloads and source URLs in raw records plus `source`, stable `source_id`, UTC `scraped_at`. Do not discard non-normalizable catalog entries from the raw data.
- Distinguish: catalog items found; unique entities; unique promotions/benefits; entity-benefit associations; successful details; unavailable details; HTTP/parsing failures; duplicates.
- **Log real progress**, per page or category, detail attempts, outcomes, errors/IDs, completion status and final JSON path. Follow existing scraper CLI entry-point behavior (`python -m scraping.sources.<source>.scraper`). Avoid import-time imports in `__init__.py` that cause `runpy` warnings.
- `scrape(limit=N)` is *always* a partial run unless independent evidence proves otherwise. A `limit` must never accidentally make `ScrapeResult.complete` true.
- If total source coverage is unverified, mark extraction conservatively incomplete under the existing model and explain this; never pretend a subset is complete because all requested items downloaded.
- Guard against empty/partial runs overwriting good raw files as if they were successful; prefer atomic writes where practical.

## 3 — Normalize the **actual** benefit model

Files normally needed:

```text
backend/normalization/sources/<source>.py
backend/synchronization/sync_<source>.py
```

- Map from observed source fields to the current Pydantic model using deterministic rules. Use `normalize` for a genuinely single-benefit record; use `normalize_many` and `SyncRunner(normalize_many=True)` for multiple independent benefits.
- Separate **entity/merchant identity** from **promotion title** and campaign/category classification. Verify relationships through IDs or explicit page associations, not arbitrary first-item fallbacks or merely the fact that a promotion is shared.
- For source item containing several benefits, represent every *verified applicable* benefit; don't drop variants or multiply unrelated benefits. Deduplicate repeated associations and produce stable IDs based on verified identifiers, never positions. Preserve identity across runs.
- Prioritize explicit structured values. Validate against legal terms/UI, not just the API fields. Confirm day encoding, start/end dates, eligibility, payment rails vs card network/type, QR, in-store/online, cap scopes/periods, minimum purchase and installment rules.
- Test multiple concurrent caps; if current `NormalizedPromotion` cannot represent all of them, keep `terms`, document the limitation and seek permission before cross-source schema changes.
- Avoid invented/default values for required fields. Categorize *why* a record is skipped or fails: listing only, truly unavailable/expired, external detail inaccessible, ambiguous relationship, or missing mandatory data.
- Don't hide a real normalization error by returning `[]` or relaxing the shared schema indiscriminately. If non-promotional listings require exclusion, implement explicit, testable source-local policy and report its counts; review compatibility with `SyncRunner`.

## 4 — Test like an independent reviewer

Files normally needed:

```text
backend/tests/scraping/test_<source>_scraper.py
backend/tests/normalization/test_<source>_normalizer.py
backend/tests/fixtures/<source>_*.json     # only small, sanitized fixtures
```

- Use `httpx.MockTransport`, fixtures and `tmp_path`. Tests must run in a clean checkout without ignored `backend/data/` or `.env`.
- Test pagination and silent caps; completeness (including `limit`); missing IDs; empty responses; failed/unavailable details; deduplication; raw preservation; save behavior and operational logs.
- Test single/multiple benefits, shared benefits, stable unique IDs, correct merchant labels, ambiguous relationships, legal conditions, channels, minimum purchases, caps and frequencies, missing mandatory fields.
- **Keep captured real fixtures unchanged**. Never invent missing `associatedBrands`, dates or other relationships inside the "real fixture" test to force a pass. Put artificial conditions in separately labeled synthetic tests.
- Assertions must verify known correct values from raw source evidence (not only `isinstance`, record count or Pydantic success). Include regression tests for any error uncovered while developing.
- Run targeted tests and full `python -m pytest -q` from `backend/`. Re-run after repairs. Clearly identify mock vs real checks.

## 5 — Real read-only end-to-end validation

- Run the scraper directly (not the sync) against the public source when access permits, respecting rate limits. Then run the normalizer *locally on those actual raw records*, with **no Supabase writes**.
- Audit the whole extracted dataset: unique catalog entities, raw unique benefits, raw associations, normalized count, unique normalized IDs, count with multiple benefits, excluded records grouped by reason, extraction errors and field coverage.
- Select **at least 10 representative real cases when available** for verification against the source website/terms; intentionally include multiple benefits for one merchant, shared benefit across merchants, campaigns, edge conditions and missing/invalid cases. If fewer than 10 are available, validate all and explain.
- Check that all variants shown in the UI are either represented or explicitly accounted for; do not assume more normalized rows means higher accuracy.
- Inspect important disagreements manually: missing merchant names despite known merchants, filtered-out API IDs, valid-looking expired promotions, conflicting cap periods, eligibility and legal terms.
- Distinguish a missing API response from an HTTP error, a source listing without a benefit, and an external inaccessible detail. Do not label all of these as "successful extraction".
- If source metadata does not establish true completeness, remain explicit that full coverage is **unverified** even when all discovered records were processed.

## 6 — Sync and deployment boundaries

- Create the thin `sync_<source>.py` using `SyncRunner`. Do **not** execute it or its `--from-file` mode unless the user explicitly authorizes database writes.
- Do not modify `.github/workflows/sync-promotions.yml` or enable scheduled sync without explicit approval after read-only validation and a safe deactivation policy.
- Avoid changes to other sources or shared models unless necessary and justified; request user approval for broad schema/production behavior changes.
- Do not commit, push or open a PR unless requested.

## 7 — Final deliverable

Follow `references/validation-report.md` and `references/acceptance-checklist.md`. Provide exact commands/results, key source evidence, representative verified cases, outstanding gaps, and one status:

- **Ready for review** — code and read-only validation passed; deployment still needs approval.
- **Partial / not scheduled** — useful work exists but coverage, associations, required fields or data correctness remain uncertain.
- **Blocked** — the source could not be investigated or implemented safely.

Do not claim "production-ready" merely because pytest passed or the JSON has many entries.
