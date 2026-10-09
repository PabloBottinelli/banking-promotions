---
name: add-promotion-source
description: Add a new bank, digital wallet, or benefits/promotions website to the Promociones Bancarias repository. Use when asked to integrate a new source, bank, scraper, normalizer, sync, and tests ("agregar banco", "nueva fuente", "incorporar promociones").
---

# Add a promotion source

## Goal

Given a source name and public URL (or another verifiable starting point), investigate the source and implement a reliable integration that fits the existing pipeline: scrape -> normalize -> synchronize -> test. Produce reviewable code, not a runtime LLM dependency.

Read the root `AGENTS.md` first. Consult `references/acceptance-checklist.md` before declaring the integration finished.

## 1. Inspect the repository

- Check working-tree changes first; preserve unrelated edits.
- Read `ScrapeResult`, `NormalizedPromotion`, `PaymentMethod`, `SyncRunner`, the current workflow, and representative scraper/normalizer/tests.
- Choose a lowercase, stable `<source>` slug that matches existing naming conventions; check for collisions.
- Determine whether the source can yield one promotion per record (`normalize`) or multiple benefit variants (`normalize_many`).

## 2. Investigate and verify the source

- Open the supplied public URL and inspect real responses. Prefer publicly accessible structured JSON APIs when available; otherwise evaluate HTML extraction. Use browser inspection only when necessary and permitted.
- Record **verified** catalog/detail URLs (if any), request parameters, pagination rules, item counts, stable IDs, rate limits, and whether individual detail requests are needed.
- Capture representative, sanitized real samples covering differing promotion formats, including legal conditions when available. Do not commit large raw datasets or sensitive material.
- Establish how full catalog coverage can be detected. If there is no reliable completeness signal, flag it as a blocker before enabling scheduled synchronization.
- If the site is inaccessible or the format cannot be established, stop inventing implementation details. Report what was tried, what was observed, and what remains unknown.

## 3. Implement the scraper

Create or update only the files needed, normally:

```
backend/scraping/sources/<source>/__init__.py
backend/scraping/sources/<source>/scraper.py
```

- Name the implementation `<Source>Scraper`. Follow existing constructor/client injection patterns so HTTP responses can be mocked.
- Reuse `scraping.http_client.get_with_retries` and the current timeout conventions where suitable.
- Implement pagination, detail retrieval, deduplication, and explicit handling of missing IDs and failed requests.
- Expose `scrape()` returning `ScrapeResult(promotions, catalog_count, failed_ids)` and `save_raw_promotions(promotions)` consistent with existing sources.
- Raw records must include `source`, stable `source_id`, UTC `scraped_at`, and all useful original catalog/detail data with a source URL where available.
- Distinguish successful full extractions from limited or partial runs. The existing `ScrapeResult.complete` is derived from counts: never manufacture counts that make incomplete data appear complete. If this contract cannot represent the source safely, raise the design issue and propose a tested change instead of silently bypassing it.
- Fail safely on unexpected source-level schema changes and empty results. Do not swallow errors to produce a misleading success.

## 4. Implement the normalizer

Create:

```
backend/normalization/sources/<source>.py
```

- Name the implementation `<Source>Normalizer`.
- Map all supported source fields to `NormalizedPromotion` using the actual model definitions; inspect existing normalizers for date, day, cap, payment-method, segment, and URL conventions.
- Implement `normalize(raw)` or `normalize_many(raw)` according to the source's benefit structure.
- Use deterministic parsing rules, not an LLM call per promotion. Normalize ambiguous free text conservatively; do not invent facts.
- Preserve terms/eligibility conditions. Ensure every output has stable identity and validated dates. When critical required values cannot be established, surface a clear normalization error.
- If a source record expands to multiple promotions, use stable, non-colliding variant IDs.

## 5. Add the sync entry point and schedule only if verified

Create:

```
backend/synchronization/sync_<source>.py
```

- Reuse `SyncRunner`; do not create a second synchronization implementation.
- Set `normalize_many=True` only if required.
- Update `.github/workflows/sync-promotions.yml` only after the scraper has demonstrated reliable full-source coverage, safe completeness behavior, and passing tests.
- Do not run synchronization scripts against Supabase without explicit authorization, including `--from-file`.

## 6. Test and verify

Create:

```
backend/tests/scraping/test_<source>_scraper.py
backend/tests/normalization/test_<source>_normalizer.py
```

- Base tests on observed source responses. Use `httpx.MockTransport` or fixtures to keep unit tests offline and repeatable.
- Test pagination and completeness, missing IDs, failed details/pages, empty or changed responses, and deduplication where applicable.
- Test representative normalizations: dates, weekdays, discounts, caps, payment methods, channels, missing optional fields, and multiple variants when applicable.
- Run targeted tests, then `python -m pytest -q` from `backend/`. Fix discovered defects and rerun; if failures remain, report them rather than claiming success.
- Optionally run a small, read-only live scraper check if access is available and the site's limits allow it. Do not confuse a sample check with proof of full catalog coverage.
- Never invoke production synchronization as part of testing.

## 7. Deliver the result

- List all changed files, verified source URLs, data coverage/completeness evidence, and any assumptions.
- Report the exact tests executed and their outcomes; separate mocked tests from live validation.
- Mark the integration as **ready for review**, **partial / not scheduled**, or **blocked**, with the reason.
- Explain whether the scheduled workflow was modified and why.
- Commit, push, or create a PR only when requested and authorized.

Prefer completing the achievable stages over stopping for minor ambiguities. Never claim a source is production-ready if coverage, data correctness, or safe synchronization cannot be demonstrated.
