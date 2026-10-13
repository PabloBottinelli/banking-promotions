# Coordinator checklist — V2 Dev → QA

- [ ] Current working tree, V2 models/runner inspected, unrelated changes preserved.
- [ ] Official in-scope source/catalog link independently verified.
- [ ] **Real** Dev delegation started with agent role (not model=promotion_dev); completion and handoff received.
- [ ] Dev included raw/normalized counts, variant IDs, field semantics, all benefit types and tests.
- [ ] **Fresh independent** QA delegation completed; official source inspected before Dev assertions.
- [ ] Small catalogs (≤30): full per-entry QA coverage; large: representative documented sample.
- [ ] QA checks V2 semantics and full `specific_conditions`/merchant links, including nullable validity.
- [ ] Each QA FAIL is delivered to Dev with precise numbered findings and expected source evidence.
- [ ] Dev fixes ordinary tests; fresh QA verifies previous issues and regressions.
- [ ] ≤3 actual QA audits, stop on PASS, BLOCKED or third FAIL. No automatic “fix” of a networking block.
- [ ] QA performed no edits; technical isolation or instruction-only restriction disclosed.
- [ ] `catalog_complete`, `normalization_complete`, `safe_to_deactivate` evaluated separately.
- [ ] No Supabase writes, CLI sync (including `--from-file`), workflow changes, secret reads, unauthorized pushes or merges.
- [ ] Final outcome + evidence, tests, files, limitations and human review requirement reported.
