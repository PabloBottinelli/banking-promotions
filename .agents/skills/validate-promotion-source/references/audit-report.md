# Independent QA report — validate-promotion-source

Only state checks actually performed. Do not fill unknowns with invented counts.

## Scope and independence

- Source name, official catalog URL and catalog boundaries:
- Was review in a fresh, separate session? If not, describe limitation:
- Official webpages/APIs/terms inspected independently:
- Limits on live browser/network access:

## Independent source vs implementation

| Metric | Official-source evidence | Scraper/raw output | Interpretation |
|---|---|---|---|
| Catalog entities/links | | | |
| Unique benefit IDs / variants | | | |
| Details available vs attempted | | | |
| Entity-benefit relationships | | | |
| Normalized rows / unique IDs | | | |
| Exclusions by reason | | | |
| Catalog coverage and deactivation safety | | | |

## Checked real promotions

For at least 10 varied examples when possible (or all if fewer), show official URL/ID, source facts, output facts, matches/mismatches and confidence. This table lives in the **report**, not a new golden/reference test suite.

## Findings

For each issue:

1. **[Severity] Short title — confirmed / likely / unverified**
2. Official-source evidence and exact expected value:
3. Observed implementation output and file/function:
4. Minimal reproduction/test command or affected ID:
5. User/data integrity impact:
6. Suggested developer correction:

## Tests and actions

- Existing targeted tests: command and exact result:
- Full pytest: command and exact result:
- New/edited **ordinary** tests in existing directories, if any:
- Live scraper/read-only normalization: commands and outcomes:
- Production implementation, workflow or database modified? (expected **no**):
- No reference/golden tests added? (expected **yes**):

## QA decision and handoff

- Scraper completeness: evidence, exact scope and uncertainties.
- Normalization completeness/accuracy: evidence and exclusions.
- Deactivation safety: explicit separate decision.
- Outcome: **Pass QA / Needs fixes / Blocked**.
- Developer action list and what QA must re-check next:
