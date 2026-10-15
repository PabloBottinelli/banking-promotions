# Developer checklist — V2 source integration

Mark unchecked work as **not done / blocked**, not passed.

## Source and raw capture
- [ ] `git status` reviewed; current shared models and runner read.
- [ ] Official scope, source links, API/HTML/SSR, pagination, filtering and lazy loading independently investigated.
- [ ] Raw data keeps every relevant record, terms, link, stable ID, timestamp and source payload.
- [ ] Invalid/empty/partial extraction cannot overwrite previous good JSON unnoticed.
- [ ] Explicit catalog completeness evidence; no hardcoded count and no unsupported `complete=True`.
- [ ] `scrape()`/constructor do not save snapshots; `SyncRunner` controls save-after-normalize order.
- [ ] Essential titles/legal text verified non-blank when required, including HTTP 200 with empty nodes.
- [ ] Previous *valid* IDs compared where a durable baseline exists; missing/substituted IDs require review, no false complete/safe inference from a short final page.
- [ ] Source-specific `save_raw_promotions()` guards acceptance, atomic replacement and unchanged prior bytes on rejection.

## V2 semantics
- [ ] All benefit kinds considered, including fee waiver, free service, points and crypto rewards.
- [ ] Multiple simultaneous benefits versus conditional variants distinguished; variant IDs stable and unique.
- [ ] `Benefit` source-grounded, no hardcoded financial fallback; correct discount versus cashback/financing.
- [ ] `PromotionLimit` represents monetary caps, quantities, minimum purchase, stock; correct currency/scope/period.
- [ ] Separate correct payment combinations, issuer/wallet/rail, without invented applicability.
- [ ] Dates nullable without invented defaults; explicit every-day differs from unknown weekdays.
- [ ] `online`, `physical` only where evidenced; no substring weekday parser.
- [ ] Merchant groups and required official adherent list notice (`promotion_url`, flag, `specific_conditions`) preserved.
- [ ] Segments/plans/regions/codes/exclusions in concise `specific_conditions`, full source in `terms`.
- [ ] All real entries audited when ≤30; larger catalog sample spans categories, groups, edge cases.
- [ ] Real UTF-8 file bytes/Unicode inspected before claiming encoding corruption.

## Safety / validation
- [ ] Local normalize/export checked; raw counts, normalized rows, variants and exclusions explicitly reported.
- [ ] Unit and full tests run (`python -m pytest -q tests`), with actual results.
- [ ] `ScrapeResult.complete` and missing normalization / deactivation hazard separately assessed.
- [ ] Raw IDs unique/nonblank; every raw item generates at least one V2 variant; normalized IDs unique across the whole batch.
- [ ] Explicit `snapshot_replace_allowed=False` and `requires_review=True` prevent both raw and Supabase writes; absence of these optional metadata flags is not assumed safe.
- [ ] `--validate-only` verified with mocks: no runner save/upsert; eager Supabase import and scraper side effects noted.
- [ ] Incomplete scrape, blank required detail, disappearing/replaced prior IDs, candidate tampering, failed atomic save and partial upsert tested with **valid** temporary baselines.
- [ ] Deactivation defaults off; only complete live run + `allow_deactivation=True` + `coverage.safe_to_deactivate=True` + complete upsert may deactivate.
- [ ] Ephemeral CI prior-snapshot limitation evaluated; do not claim persistent historical comparison without durable state.
- [ ] No Supabase sync, `--from-file` sync, workflow edits, migrations or secret exposure.
- [ ] No golden/reference test suite added. Developer handoff supplied for independent QA.
