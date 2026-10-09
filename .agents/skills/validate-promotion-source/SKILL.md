---
name: validate-promotion-source
description: Independently audit or QA an existing Argentine bank, wallet, or promotion-source integration for correctness, completeness, safe synchronization and meaningful tests. Use for "auditar scraper", "validar fuente", "revisar integración", "QA de Prex" or after add-promotion-source.
---

# Validate a promotion source — independent QA workflow

You are the **reviewer**, not the implementer. Read repository `AGENTS.md` and use `references/audit-checklist.md` plus `references/audit-report.md`. Prefer a **new, separate agent session** with no implementation conversation history. Do not say the review was independent if you authored or co-designed the implementation in the same session.

**Scope restriction:** No new golden/reference dataset, `backend/tests/validation/` folder, snapshot-based tests or dedicated reference-test framework. Manual source comparisons are essential; ordinary focused tests in the **existing** scraping/normalization test directories are allowed when useful.

## 0. Bound the audit and preserve code

1. Identify the source and official URL (from the request or current scraper); inspect `git status` and relevant contracts (`ScrapeResult`, `NormalizedPromotion`, `SyncRunner`). Do not overwrite existing edits.
2. Treat implementer reports, test assertions, code comments and past normalizer output as **claims to verify**, not truth. Where tools permit, investigate official-source evidence **before reading implementation logic/tests**; write down candidate expected values and source URLs first.
3. Define what catalog is being audited: the public `/promociones` listing, every category, national vs location-specific promotions, external partner pages, etc. Never conflate a scoped listing with all bank promotions.
4. If the official site cannot be reached, clearly state that live behavior could not be independently checked. You may do a static audit, but do not assign an unqualified pass.

## 1. Independently investigate the actual source

- Browse the official catalog without assuming the scraper's endpoint is exhaustive. Check HTML links against what a user sees, categories, filters, pagination, infinite scroll, lazy-loaded content, region constraints and hidden benefit variants.
- Understand source/API totals: is `resultCount` a total or a returned-page count? Test per-request caps and whether filters/ranking hide records. Check IDs and relationships separately for catalog entities and benefits.
- Confirm catalog exhaustion structurally where possible. **No explicit total is required** for a complete finite listing if absence of pagination/lazy load and full card coverage can be demonstrated. State the exact coverage scope and uncertainty.
- For representative benefits, independently capture official expected facts **before consulting implementation assertions**: merchant, title, discounts/installments, days, validity, caps/scope/period, purchase minima, payment networks vs app/QR, physical/online channel, eligibility and legal restrictions.
- Examine different benefit types, multi-benefit items, missing/expired pages, externally linked benefits and ambiguous merchant relationships. Use official terms to resolve conflicts. Do not assume a visible logo/card applies to all variants.

## 2. Inspect and exercise the implementation

- Review the scraper, normalizer, sync entry point, `ScrapeResult` semantics and shared runner. Inspect the developer's tests only **after** forming source-derived expectations where practicable.
- Run the scraper CLI against the public source only if network/rate limits permit. Run the normalizer locally on the resulting raw data; **never** invoke `sync_<source>` or `SyncRunner.run`, including `--from-file`.
- Compare discovered catalog IDs and detail URLs to independent official listing results. Identify absent/excess, missing details, duplicate IDs, unhandled variants and unavailable/errors counted as success.
- Quantify raw entities vs unique benefits vs associations vs normalized rows. Check collision/stability of normalized IDs, one-to-many relations, skipped items by reason, false merchant labels, unparsed dates and misclassified fields.
- Verify category/region scope and correctness of `complete` and `coverage_verified`; distinguish scraper completeness from normalization completeness. Read the actual `SyncRunner` deactivation logic: even a complete catalog can be dangerous if normalization silently skips valid benefits. Treat the safety of production deactivation as a distinct audit gate.
- Inspect mismatches in **all records using programmatic aggregate checks** (not just cherry-picked examples), then manually confirm at least 10 representative real examples where available; if fewer than 10, inspect all.

## 3. Independent testing (within existing suites)

- Run existing targeted tests and `python -m pytest -q` from `backend/` if possible; distinguish actual executed tests, mocked tests and live source checks.
- Challenge developer-supplied expected values against terms: do not accept an assertion such as `online=True` because it already passes. Identify tests that only prove implementation behavior, hardcode counts, alter captured source facts or depend on ignored local files.
- Where helpful, **add a small independent regression/unit test** to `backend/tests/scraping/test_<source>_scraper.py` or `backend/tests/normalization/test_<source>_normalizer.py` (or a conventional companion test in the same directory). Derive assertions from independently checked source behavior or well-defined contracts. Keep HTTP mocked and file paths isolated.
- Do **not** change production scrapers, normalizers, shared models, sync code or workflows. If a production defect is exposed, leave a clear failing reproduction/test and document it; the developer repairs it, then QA re-tests. Avoid modifying existing tests merely to make the suite green.
- **Do not** create a separate reference/golden test layer or permanent live-source expectation catalog at this stage. No new dataset of 10 hand-curated golden records is required; verification can be documented in the QA report.

## 4. Report actionable findings, then stop

Every substantive finding needs:

- **Severity:** Blocker / High / Medium / Low.
- **Evidence:** official page/API/terms URL or source snapshot location and the exact observed fact.
- **Reproduction:** relevant file/function, command or input ID, expected vs actual normalized/scraped value.
- **Impact:** missing promotion, wrong merchant, misleading savings, false complete flag, unsafe deactivation, brittle test, etc.
- **Suggested fix**, without making production modifications yourself.

Use `references/audit-report.md` and checklist. Include all checks performed, source records compared, discrepancies, tests run, blockers and any unverified claims. Separate **confirmed**, **likely**, and **unverified** defects. Recommend one outcome:

- **Pass QA / ready for user's deployment decision** — scoped catalog and data assertions sufficiently verified, no blocking errors, deactivation safety understood; does **not** authorize deploying.
- **Needs fixes / re-audit** — actionable defects remain.
- **Blocked / insufficient evidence** — independent verification was not possible.

Do not push, commit, open PR, schedule workflows or access Supabase without explicit permission. Do not certify a source as ready solely because tests pass.

## Handoff for the next iteration

Tell the developer which **production code** to fix, link each discrepancy to official evidence and existing/missing tests, then request another **separate QA pass** after the fixes. Never silently become the developer for convenience.
