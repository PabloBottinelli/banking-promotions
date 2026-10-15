# QA V2 — independent read-only report

**VERDICT: PASS | FAIL | BLOCKED**

## Independence and scope
- Fresh QA context and technical read-only isolation (or instruction-only restriction):
- Official catalog URLs, legally binding details, observation timestamp and in-scope boundary:
- Direct official evidence available? If not, what specifically was blocked?
- Raw/normalized snapshot timestamp; risk of stale comparison:

## Catalog and semantic coverage
| Metric | Official observation | Raw | V2 normalization | Notes |
|---|---|---|---|---|
| In-scope entities / unique links | | | | |
| Detail fetches / missing | | | | |
| Independently checked promotions | | | | |
| Output variant IDs / groups | | | | |
| Multiple compatible benefits | | | | |
| Exclusions and classifications | | | | |
| All benefit kinds represented | | | | |

## Per-record review
- For ≤30 entries: one per-ID summary for **all**, including expected and output benefit, dates/day, payment, currency/limits, conditions and any mismatch.
- For >30: explain sample plan and exact inspected IDs; list edge cases and unreviewed areas.

## Findings
For each `QA-###`:
- Severity / confirmed, probable or unverified:
- Official URL and exact fact supporting expectation:
- Input raw evidence and normalized actual (field + ID):
- Reproduction command or function/path:
- User/data integrity or deactivation impact:
- Developer change and ordinary regression assertion requested:

## Five distinct gates (not all are model fields)
- `catalog_complete`: YES / NO / UNKNOWN; official scope, pager/detail evidence and relationship to `ScrapeResult.complete`:
- `normalization_complete`: YES / NO / UNKNOWN; every raw record and variant, exclusions:
- `snapshot_replace_allowed`: YES / NO / UNKNOWN / NOT EXPOSED; source flag (if any), actual save guard, prior accepted baseline:
- `requires_review`: YES / NO / UNKNOWN / NOT EXPOSED; source flag (if any), missing IDs or unresolved anomalies:
- `safe_to_deactivate`: YES / NO / UNKNOWN / NOT EXPOSED; source flag, runner opt-in and evidence (not production permission):
- `ready_for_human_review`: YES / NO:

## Shared runner and snapshot integrity
- Evidence `scrape()` is candidate-only; runner validates raw then all V2 variants before source save/upsert:
- Adversarial tests: incomplete/empty/duplicate/wrong-source raw, zero/duplicate variants, required detail blanks under HTTP 200:
- Valid historical-baseline checks: missing/substituted IDs, legitimate additions/updates, atomic save failure, prior snapshot byte preservation:
- Explicit source review/refusal flags; coverage absent/unknown behavior; CI historical baseline availability:
- `--validate-only` mock no-write result, current eager Supabase-import limitation, no real sync executed:
- Partial upsert and default/explicit deactivation gates; raw + coverage + Supabase are not one transaction:

## Execution and boundaries
- Targeted tests (command/output), full tests (command/output), live comparison available:
- What could not be checked; network/runtime errors versus code errors:
- Confident/false-positive encoding findings confirmed with bytes? If relevant:
- Any repository modification, Supabase writes or workflow change by QA? **Expected: no.**
- Existing finding IDs confirmed resolved / outstanding / unverified:
