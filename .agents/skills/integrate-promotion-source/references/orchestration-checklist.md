# Orchestration checklist — integrate-promotion-source

Use as an in-memory checklist; do not create a persistent log or golden dataset by default.

- [ ] Source name/URL and exact official catalog boundary identified.
- [ ] Existing uncommitted user changes preserved; no out-of-scope edits.
- [ ] Delegation to `promotion_dev` happened; no simulated developer role.
- [ ] Developer completed implementation, initial tests and read-only data check where possible.
- [ ] A **different** `promotion_qa` was spawned after developer completion, with a fresh context and independent official-source-first audit.
- [ ] QA returned `VERDICT: PASS`, `FAIL`, or `BLOCKED`, with evidence and scope.
- [ ] On FAIL, developer addressed issue IDs, then fresh QA reviewed the fixes.
- [ ] Audit count never exceeded **3 total**; stopped on PASS/BLOCKED/third FAIL.
- [ ] QA remained read-only; only developer edited implementation or ordinary tests.
- [ ] No new reference/golden test infrastructure created.
- [ ] No Supabase writes, workflow scheduling, production deployment or unauthorized pushes/merges.
- [ ] Final handoff states files, real data metrics, QA cycle history, unresolved findings and human decision required.
