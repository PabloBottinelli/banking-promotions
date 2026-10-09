# Integration validation report — response template

Use this structure in the final reply; do not invent values. Use `unverified` / `not run` where evidence is absent.

## Source and implementation

- Source / website:
- Verified endpoints or HTML pages (and retrieval approach):
- Files created/changed:
- Key design decisions (especially entity↔benefit relationship and IDs):

## Live extraction metrics

| Metric | Value | Evidence / caveat |
|---|---:|---|
| Catalog entities found | | |
| Unique catalog entity IDs | | |
| Unique benefit IDs returned | | |
| Entity-benefit associations | | |
| Detail retrieval success | | |
| Detail unavailable | | |
| Detail HTTP/parsing failures | | |
| Normalized promotion rows | | |
| Unique normalized IDs | | |
| Source entities with multiple benefits | | |
| Skipped non-promotional listings | | |
| Missing required data | | |
| Ambiguous/unverified associations | | |

## Normalized field coverage

Report present/known/missing or not-applicable counts for merchant, category, discount, installments, validity, weekdays, caps, payment methods, minimum purchase, channels, and terms. Null does not automatically imply an error.

## Source cross-check

Give a table of real representative cases (ideally ≥10): source page or ID, what the source says, what normalization produces, pass/mismatch and notes. Include multiple variants and negative cases when available.

## Tests / execution

- Mocked unit tests: commands, pass/fail counts.
- Real scraper command: outcome and path saved.
- Local normalization audit command: outcome.
- Full pytest command: outcome.
- No database sync performed: yes/no.

## Completeness and recommendation

- `ScrapeResult.complete`: true/false with precise reasoning.
- Is full source coverage independently verified? yes/no, evidence.
- Risks and unresolved records grouped by cause.
- State: **Ready for review / Partial – not scheduled / Blocked**.
- Scheduled workflow changed? yes/no and user authorization.
