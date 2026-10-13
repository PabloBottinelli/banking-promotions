# Independent QA checklist — V2

- [ ] Fresh separate QA context; evidence collected from official pages/API/terms before trusting Dev tests.
- [ ] Official URLs and catalog boundary/pagination/filters documented; temporal availability noted.
- [ ] All entities checked when ≤30; diverse stratified sampling with explicit confidence otherwise.
- [ ] Actual `backend/normalization/models.py` schema and real raw/normalized pipeline examined.
- [ ] Benefits checked across all kinds, including fee waivers, free services, points/crypto; no unexplained loss.
- [ ] Compatible multi-benefits versus mutually exclusive variants, stable IDs and group IDs checked.
- [ ] Percent/amount/currency/reward currency validated; no commercial-value fallback constants.
- [ ] Correct typed monetary caps, usage, stock, minimum and shared cap period/scope verified.
- [ ] Allowed issuer/card/wallet/rail combinations checked; no false cards or channels.
- [ ] Nullable dates, day-of-week parsing, `applies_every_day`, source validity vs legal clauses checked.
- [ ] `Comercios de barrio` or adherents have useful special conditions + official URL + flag.
- [ ] Specific conditions capture plan/region/segment/code/exclusions; original terms preserved.
- [ ] Apparent mojibake checked against real UTF-8 bytes/codepoints, not display alone.
- [ ] Scraping completeness, normalization coverage and deactivation safety assessed separately.
- [ ] Tests examined critically; commands/results accurate; no files changed and no sync attempted.
- [ ] QA-IDs reproducible with official expected vs output actual; no speculative defects as confirmed.
- [ ] Verdict PASS/FAIL/BLOCKED with specific follow-up; no reference-test suite created.
