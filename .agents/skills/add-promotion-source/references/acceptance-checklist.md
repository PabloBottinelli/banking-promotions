# Developer checklist — add-promotion-source

Record evidence; label unverifiable steps instead of pretending they passed. This is an **implementation handoff**, not independent sign-off.

## Investigation

- [ ] Current models, runner, other sources and test conventions inspected.
- [ ] Official URL(s), catalog scope and live API/HTML mechanism identified.
- [ ] Actual pagination, geography, categories, result caps and lazy loading investigated.
- [ ] Source completeness argument documented; a site-wide total is **not mandatory** for a structurally exhaustive finite listing.
- [ ] Catalog entities, actual benefits, variants and shared relationships distinguished.
- [ ] Field mapping grounded in original API, visible content or legal terms.

## Extraction

- [ ] Raw fields/provenance preserved; stable entity IDs and UTC timestamp used.
- [ ] Details, HTTP/parse failures, unavailable links and duplicates counted separately.
- [ ] Limit, truncation, unknown coverage, unexpected selector/layout changes never silently count as complete.
- [ ] Safe raw writing and meaningful command-line progress/summary logs.
- [ ] Runnable `python -m scraping.sources.<source>.scraper` without an avoidable `runpy` warning.

## Normalization

- [ ] All independently valid variants represented or exclusions justified.
- [ ] Merchant name ≠ promotion title unless evidenced; N:M relations handled.
- [ ] Unique, stable normalized IDs; no index-based IDs or arbitrary first match.
- [ ] Explicit validity/weekday/payment type/app/channel/amount/currency/caps/terms parsing reviewed.
- [ ] Missing facts not invented; unsupported benefit categories and schema limitations disclosed.
- [ ] Potential loss of valid normalized records and deactivation risk assessed, even if scrape coverage is verified.

## Initial tests and evidence

- [ ] Focused mocked/unit tests for catalog/details/errors/normalization/ID stability/completeness.
- [ ] Tests work without ignored `backend/data/` or production credentials.
- [ ] Captured raw examples unaltered; synthetic cases separated.
- [ ] Targeted tests and full pytest attempted; results truthful.
- [ ] Read-only source and local normalization audit attempted, with counts and edge cases reported.
- [ ] No reference/golden test infrastructure created.

## Handoff

- [ ] No Supabase write, scheduled workflow change, deployment or unauthorized push.
- [ ] Modified files, known limitations and open questions listed.
- [ ] Status **Ready for independent QA**, **Partial** or **Blocked** provided.
- [ ] Separate `$validate-promotion-source` session recommended; no self-claim of QA approval.
