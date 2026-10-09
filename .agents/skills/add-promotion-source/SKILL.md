---
name: add-promotion-source
description: Implement a new bank, wallet, or promotions site in Promociones Bancarias (scraper, normalizer, sync entry point, initial unit tests and initial source validation). Use for "agregar banco", "nueva billetera", "integrar fuente", or similar development requests.
---

# Add a promotion source — developer workflow

You are the **implementer**, not the independent QA reviewer. Apply repository `AGENTS.md`. Follow `references/acceptance-checklist.md` and the report layout in `references/validation-report.md`. After delivery, explicitly recommend a separate fresh session using `$validate-promotion-source`; do not mark the integration independently approved.

## 0. Read the project and set a boundary

1. Inspect `git status`, scope and the user's source URL/name. Preserve unrelated changes.
2. Inspect `ScrapeResult` (including coverage fields), `NormalizedPromotion`, `PaymentMethod`, `SyncRunner`, repository persistence, existing tests and at least two existing sources; confirm their current behavior rather than assuming it.
3. Choose a stable source slug. Define exactly what website/catalog is in scope. Never assume a listing card equals one promotion.
4. Identify whether entities, benefits and variants have 1:1, 1:N or N:M relationships. Decide whether `normalize_many()` will be required.

## 1. Investigate the live source first

1. Inspect the official page and network requests. Prefer public structured API when genuinely complete; otherwise use HTML/SSR, then browser interaction only when essential.
2. Verify method/headers/query, pagination/cursors, categories, geography, ranking, page caps, total semantics, detail endpoints, IDs and URL behavior. Inspect whether visible tabs/buttons change benefit variants.
3. **Establish a defensible discovery boundary.** For a finite HTML catalog, investigate pagination, "load more", infinite scroll, client-rendered cards, hidden categories and other catalog paths. A numeric total is helpful but not mandatory if structural exhaustiveness can be demonstrated. Never confuse returned results with source total.
4. Sample several types of record, including ambiguous/empty data, unusual benefit formats, shared promotions and more than one benefit per merchant. Record where every normalized field actually comes from.
5. If access is blocked, say so; never manufacture evidence. Do not use old exploratory repository code as proof an endpoint still works.

## 2. Extract faithful raw data

Typical files:

```text
backend/scraping/sources/<source>/__init__.py
backend/scraping/sources/<source>/scraper.py
```

- Use injected HTTP clients and existing retry/timeouts where feasible; don't disable TLS verification.
- Crawl the entire in-scope catalog, actual pagination and accessible details; deduplicate without losing entity-benefit relationships. Cache shared details when applicable.
- Preserve source payloads, legal terms, source URLs and `source`, stable `source_id`, UTC `scraped_at`. Keep informational or non-normalizable raw records for audit.
- Maintain useful CLI logs: catalog/items per page, unique/duplicates, details obtained/unavailable/failed, missing IDs, completion assessment, saved file path. No import-time side effects/runpy warning.
- Reject or visibly mark empty, truncated, partially parsed and silently capped results. Never let `scrape(limit=N)` accidentally claim full coverage. Use safe raw saving, preferably atomic, and prevent an empty run from overwriting valid data silently.
- Consider `ScrapeResult.complete` a deactivation-risk indicator, not a vanity status. A source with a verified complete HTML listing may be eligible for coverage verification *without an explicit total*, but only within the defined listing scope. Check the effect of incomplete normalization on `SyncRunner` separately before proposing production use.

## 3. Normalize benefit semantics

Typical files:

```text
backend/normalization/sources/<source>.py
backend/synchronization/sync_<source>.py
```

- Use verified source fields and source-local deterministic rules. Never infer a merchant from a day/title, an online purchase from an app mention, or a cashback cap from an unrelated USD transfer limit.
- When multiple independent benefits or variants exist use `normalize_many()` and configure `SyncRunner(normalize_many=True)`; derive IDs from real stable identifiers, not positions.
- Distinguish card network/type from payment app/rail and from benefits unrelated to a payment card. Normalize only what is evidenced.
- Handle promotions without a traditional percentage: installments, waived fees, services and other perks may require source-specific exclusions or documenting current schema limitations. No invented dates/amounts to force Pydantic success.
- Parse validity from an explicit promotion validity clause; distinguish weekdays from validity; support unambiguous textual formats such as "del 1° al 31 de octubre de 2026" and "viernes, sábados y domingos de octubre de 2026" where justified. Do not globally choose min/max dates from unrelated legal paragraphs.
- Preserve concurrent caps, minima, restrictions, legal text; do not silently map incompatible currencies or concepts into current fields.
- Return no benefit only for a clearly justified, explicitly categorized exclusion. Do not hide a parser failure or ambiguous relation with a silent `[]`.

## 4. Write implementation-level tests, not a self-approval

Typical files:

```text
backend/tests/scraping/test_<source>_scraper.py
backend/tests/normalization/test_<source>_normalizer.py
```

- Add focused unit/mock tests with `httpx.MockTransport`, isolated `tmp_path`, and small, sanitized source examples when useful. No dependence on `backend/data/`, `.env` or a previous local run.
- Cover pagination/caps, empty data, HTTP/parse failures, detail availability, completeness, IDs, raw preservation, multiple benefit variants, skip/error reasons and critical field mappings.
- If adding captured source fixtures, do not mutate their original payload to manufacture missing relations/dates. Keep synthetic examples clearly labeled.
- Ground expected assertions in source evidence; don't just assert existing implementation output. **Your tests are implementation tests, not independent QA acceptance.** No separate golden/reference tests or `backend/tests/validation/` directory.
- Run targeted tests and full `python -m pytest -q` from `backend/`. Report actual pass/fail and any blocked checks.

## 5. Perform an initial live read-only check

- Run the scraper CLI directly when network permits, never `sync_<source>` or `SyncRunner.run` (including `--from-file`). Run local normalization over the raw JSON without Supabase.
- Collect: catalog entities, benefit IDs, entity-benefit associations, raw-to-normalized counts, variants, unique normalized IDs, skipped/error reasons and key-field coverage.
- Manually compare at least 10 representative live examples against official source/terms if available (otherwise all); record known mismatches rather than adjusting assumptions until they pass.
- Check whether a *complete scrape* paired with exclusions/incomplete normalization could cause `SyncRunner` to deactivate valid promotions. If yes, block scheduling/production until fixed or gated.
- Do not claim source-wide completeness from a complete subpage or any unverified category/region.

## 6. Hand off for independent QA

- Create only a thin `sync_<source>.py` and do not execute it against Supabase.
- Do not add the source to scheduled GitHub Actions or deploy. Do not push/commit/PR unless requested.
- Provide a handoff: source name/URL, scope, code files, commands, raw output path (if created), counts, assumptions, known exclusions, `complete` rationale and open questions. **Do not supply self-written tests as the source of truth.**
- Explicitly ask for a separate agent/session with `$validate-promotion-source`, and leave final quality acceptance to that review and the user.

## Result status

Use the report and checklist. Label the implementation **Ready for independent QA**, **Partial / needs investigation**, or **Blocked**. These are development statuses, not production approval.
