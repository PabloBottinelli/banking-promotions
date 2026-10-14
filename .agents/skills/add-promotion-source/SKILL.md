---
name: add-promotion-source
description: Implement or fix a bank, wallet, or financial-platform promotions source in Promociones Bancarias using the V2 Benefit/PromotionLimit/PaymentMethod model; builds a faithful scraper, normalizer, thin sync entry point and developer tests. For automatic independent QA use integrate-promotion-source.
---

# Add promotion source — Dev / V2

You are the **implementation agent**, NOT an independent QA reviewer. Read repository `AGENTS.md`, `references/v2-field-contract.md`, `references/acceptance-checklist.md`. Deliver the handoff format in `references/validation-report.md`.

## 1. Establish contracts and in-scope source

- Inspect `git status` and current `backend/normalization/models.py`, `backend/scraping/models.py`, `backend/synchronization/runner.py`, relevant persistence code, other sources and tests. Detect user changes and model differences; preserve unrelated files.
- Establish public official page/API and exact catalog scope. Check page counts and true pagination, additional categories, lazy-load behavior, regional filters and detail linkage; investigate 1:N campaign → merchant → benefit relationships.
- Verify source format with network/API evidence. A finite HTML listing can be complete without a published count *if* structural checks exclude undiscovered entries, filtering/pagination and hidden sections. Never assume 200 OK or a response length equals coverage.
- Distinguish what's officially stated from assumptions; links to older scraper code are hints, not current evidence.

## 2. Implement raw extraction

- Reuse project client/retries, respect rates, keep TLS certificate validation. Support injected client, deterministic parsing and tests.
- Store complete raw API/HTML/terms data with stable entity IDs, source URL, `scraped_at` in UTC; do not trim fields just because V2 doesn't represent them.
- Count discovered/unique/detail-success/detail-error/unavailable/filtered; never treat pagination limits, missing details, broken selectors, or partial responses as complete.
- Keep raw file saving atomic; an empty or failed extraction must not silently overwrite the previous valid snapshot. Avoid redundant copying of huge catalog HTML into every record when provenance can be preserved once.
- Scraper CLI should log counts, path, coverage scope, completeness and errors; no side effects upon module import.
- Keep generated files organized:
  - `backend/data/`: persistent raw JSON, normalized JSON and
    compact coverage metadata.
  - `backend/.tmp/`: exploratory files, downloaded scripts,
    debugging outputs and temporary test artifacts.
  - `backend/tests/fixtures/`: small, reproducible test data.

- Do not duplicate complete catalog/API responses in coverage
  metadata when they are already preserved in the raw snapshot.

- Remove temporary development artifacts before delivering
  the integration.

## 3. Implement V2 normalization

- `NormalizedPromotion`: `source`, stable per-variant `source_id`, `scraped_at`, `title`, `scope`, nullable `valid_from`/`valid_to`, optional `promotion_group_id`, `merchant`/`category`/`promotion_url`, `requires_merchant_verification`, `benefits`, `limits`, `payment_methods`, `days_of_week`/`applies_every_day`, nullable `online`/`physical`, `specific_conditions`, original `terms`.
- All benefits count, including financial products and services: cashback, discounts, financing, fee waivers, free services, points, gifts and `other` with justified description. No arbitrary exclusion of non-shopping promotions.
- Use `Benefit` for what customer receives, `PromotionLimit` for typed cap/minimum/usage/stock; never place currencies, operating limits or quotas into unrelated money fields. `Decimal` for currency values; distinguish ARS, USD, BTC reward currency, etc.
- **Variants:** a source item with alternate segment/card/category/level/period produces stable separate IDs with a shared group ID via `normalize_many()` and `SyncRunner(normalize_many=True)`. A single variant can have multiple *compatible, simultaneous* Benefit components. Do not flatten four different Personal Pay levels into one percentage or stack conditional Credicoop percentages.
- **Payment options:** each `PaymentMethod` is one complete, supported combination of issuer + card type/network + wallet + payment rail. Keep `raw_name`; don't infer networks from issuer or declare online from app mentions.
- **Merchant eligibility:** `merchant="Comercios de barrio"` or `"Comercios adheridos"` is valid if that is the promoted group. Set `requires_merchant_verification=True`, `promotion_url` to the official campaign/merchant-lookup page and a practical note in `specific_conditions`. No need to individually model merchant lists, branch locations, regions or customer plans. Retain those restrictions in `specific_conditions` and legal detail in `terms`.
- **Validity/days:** dates may be `None` and should not cause forced exclusion. Recognize exact promo validity clauses, not generic legal deadlines. Tokenize weekdays with word boundaries and check positive clauses, not `"sab" in text` or exclusion text. `days_of_week=[]` unknown, `applies_every_day=True` explicit every day; channels nullable.
- **No manufactured output:** don't hardcode changing benefits/caps/dates/stock as a fallback for a broken parser. `other` only when a real documented benefit exists. Preserve raw record plus flagged exclusion if truly impossible to represent.
- Use `backend/normalization/structure.py` helpers if present, but challenge their assumptions against source semantics; never prefer green tests over correctness.
- The user may have migrated Supabase: do not edit schema/migrations without explicit request. Do not emit legacy V1 fields or rely on V1 columns.

## 4. Tests, local JSON and source checks

- Add only ordinary unit/mock tests under `backend/tests/{scraping,normalization}`. Use `httpx.MockTransport`, `tmp_path`, synthetic clearly labeled inputs or small unmodified real excerpts. No golden/reference suite.
- Cover every V2 category relevant to the source: benefits/variants/identity, nullable dates, weekends/unknown every day, amount versus quantity, cap period/scope, payment combinations, source text preservation, attached merchants, empty catalog, partial failures and deactivation safety.
- Test assertions must have independent source-based expected values, not derived by running the current code and copying its output.
- Run a local scraper / JSON normalizer/export in read-only-to-database mode (running scraper may update local raw file; check paths/permissions first). Compare real output **field by field**: *all records for ≤30 entries*, representative plus edge-case sample for larger catalogs. Count raw entities, transformed variants, non-normalizable items and reasons. Mark unknowns rather than make them look valid.
- Run `python -m pytest -q tests` from `backend/`, plus targeted tests. Explicitly report tests that could not run due inaccessible temporary paths or network timeouts; neither means that code is correct.
- Review `ScrapeResult.complete` separate from normalization completeness. `SyncRunner` may deactivate not-seen rows after upsert; an unchecked omission can lose live promotions. Never use `sync_<source>` or even `--from-file` without user approval.
- If pytest requires a custom temporary directory, use
  `--basetemp=.tmp/pytest`. Never place pytest temporary
  directories inside `backend/data/`.

## 5. Handoff

- Add thin `sync_<source>.py`; do **not run** it against Supabase or edit scheduling/workflows.
- Report source scope/evidence, changed files, commands and outcomes, catalog/raw/normalized counts, variant and exclusion details, `complete` reasoning, missing information, validation gaps and risk of destructive deactivation.
- If orchestrated, return this to the coordinator for fresh QA; on `QA-###` findings, fix and add ordinary regression tests, then await new independent QA. If standalone, request `$validate-promotion-source` in a separate fresh context.
- Status is `READY_FOR_INDEPENDENT_QA`, `PARTIAL` or `BLOCKED` — never independent `PASS`.
