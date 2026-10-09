# Independent QA checklist — validate-promotion-source

This is an **audit checklist**, not self-certification by the development agent. Mark **Pass / Fail / Unverified / Not applicable** with evidence.

## Independence

- [ ] Fresh review session/role declared; if not independent, disclosed.
- [ ] Official catalog/terms expectations gathered before relying on the developer's assertions where feasible.
- [ ] Implementation report and tests treated as hypotheses, not the answer key.

## Catalog and extraction

- [ ] In-scope catalog boundary clearly defined; independent official-site inventory attempted.
- [ ] Pagination, dynamic loading, categories, geographic filters and hidden variants checked.
- [ ] Source counts/limits verified for semantics; no assumption that returned-page count equals global total.
- [ ] Catalog IDs and detail retrieval compared against independently observed listing.
- [ ] Complete vs partial evidence appropriate for *that catalog scope*; no mandatory explicit total if structural exhaustiveness demonstrated.
- [ ] API/detail unavailability, HTTP failures and filtered/expired entries not silently reported as successful details.

## Normalization and integrity

- [ ] Entire local raw dataset checked for duplicates, missing benefits, variants, ID instability and silent exclusions.
- [ ] Merchant vs promotion title verified and 1:N / N:M associations handled correctly.
- [ ] At least 10 real cases (or all if fewer) manually checked against official terms/website.
- [ ] Explicit validity, weekdays, discounts, installments, caps and concurrent caps, minima, currency, payment methods, QR vs channel, eligibility and terms checked.
- [ ] No invented dates or confused benefit semantics; unsupported schema cases disclosed.
- [ ] Skip reasons differentiated from errors; raw data preserved.
- [ ] SyncRunner deactivation risks assessed **without running sync**; full scrape cannot conceal incomplete normalization.

## Independent tests

- [ ] Existing tests run and their expected values challenged.
- [ ] Clean-checkout safety: no ignored `backend/data/`, `.env` or machine-specific paths.
- [ ] Reproducible regression test suggestions and expected assertions reported for Dev when justified; QA changed no repository files.
- [ ] No `backend/tests/validation/`, golden/reference datasets or snapshot-test system introduced.

## Result

- [ ] All findings include severity, source evidence, expected/observed, reproduction, impact, proposed fix.
- [ ] Confirmed vs suspected vs unverified issues separated.
- [ ] QA did not modify production code, run Supabase writes or enable workflow.
- [ ] Outcome: **Pass QA / Needs fixes / Blocked**, without claiming deployment authority.
