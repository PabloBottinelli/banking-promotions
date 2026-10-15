# Personal Pay - final handoff after QA4

Status: **NEEDS_HUMAN_REVIEW**. **QA4 final verdict: FAIL**. Three original
independent audits plus the one additional Dev + fresh QA round explicitly
authorized by the user have been completed. That additional round is exhausted;
no further fixes, captures or audits were performed after QA4. Developer tests
are not independent acceptance. Live snapshot replacement, synchronization and
deactivation remain blocked.

QA4 closed QA-010 and QA-011, but identified two new findings that remain open:

* **QA-012 - incomplete legal payment combinations.** Starbucks 9210 explicitly
  requires Visa for NFC, but normalized network is null. Tostado 9464 states
  prepaid Visa Personal Pay card/QR/NFC, but the NFC method still lacks issuer
  Personal Pay, network Visa and card_type prepaid. Taxi Premium 9429 requires
  its own app exclusively, but normalized wallet is null instead of Taxi Premium.
  The app requirement is not evidence of an online purchase channel.
* **QA-013 - omitted monthly usage restriction.** Avon 9373 states one use per
  final customer per month, but normalization currently contains only the ARS
  8,000 monetary cap. Expected additional typed limit: usage_count, quantity 1,
  monthly, scope person. That does not establish a monthly period for the
  monetary cap, which must not be changed without evidence.

The conflicting Tienda Personal start dates also remain unresolved as a source
issue. Final five judgments: **catalog complete YES; structural normalization
YES but semantic fidelity NO; snapshot replacement NO; review required YES;
safe deactivation NO**. The candidate remains 201 raw records / 207 variants.
QA4 inspected 67 live details, including the 21 stock and 19 NFC cases, and
confirmed all 18 categories and the 200-offer API. Its 112 checks passed, but do
not resolve the evidenced semantic defects. The full developer suite had 319
passing tests without exclusions; that likewise is not acceptance.

Only this final documentation was changed after QA4. Logic, tests, captures,
candidate artifacts and the accepted snapshot remain unchanged. The sections
below describe the implementation and validation handed to QA4, not approval
for production.

## Current capture and review artifacts

Official capture: **2026-10-15T14:41:18.555003Z**.

* Catalog: https://www.personal.com.ar/pay/beneficios
* API: https://www.personal.com.ar/pay/api/benefits?sourceSection=web
* Details: https://www.personal.com.ar/pay/api/benefits/{id}
* Global terms: https://www.personal.com.ar/pay/terminos-y-condiciones/promociones
* Extra mobile credit: https://www.personal.com.ar/pay/promocion-recarga-personal

The complete public API has 200 offers. SSR includes 99; cursor responses are
99 (0->100), 100 (100->200), 1 (200->201), then empty at 201. The second complete
traversal matched the first payload. All 18 category-name filters were exhausted
without extra IDs. IDs are not valid category filter values. All 200 essential
detail payloads were nonblank. The global menu contributes Reintegro Plus:
**201 raw records -> 207 unique V2 variants**, with no raw normalization errors.
App-only personalized offers and unrelated product navigation are outside this
public promotional catalog.

Current QA4 artifacts, deliberately separate from the accepted snapshot:

* `backend/data/personal_pay_candidate_promotions.json`
* `backend/data/normalized/personal_pay_candidate_promotions.json`
* `backend/data/personal_pay_candidate_coverage.json`

The accepted API-only `backend/data/personal_pay_promotions.json` still has
200 records and was not replaced. Its SHA-256 was identical before and after
this round. The registered `normalization.export_json --source personal_pay`
continues to read the accepted file by default; its historical 204-row export
is not the current 207-row review dataset. Current candidates above were locally
exported after validating every raw record, every V2 row and all variant IDs,
using `model_dump(mode="json")` with Decimal strings. No SyncRunner/CLI or
accepted-snapshot gate was bypassed. Generated pipeline JSON is ignored by Git
under the existing repository policy.

Every global menu entry is captured, including the hidden PIX service contract
and the separately linked Pelotas contest document. PIX permits charges and
provides no verified promotional benefit. The Visa contest expired 2026-05-10;
Pelotas expired 2026-06-03. Their complete texts remain in raw context, with
explicit exclusion reasons in compact coverage. Niveles and duplicate campaign
legals are retained as context, not silently discarded.

## QA-010 and QA-011 corrections in this additional round

Fresh official GET evidence was collected for all 19 distinct affected IDs.

QA-010 (closed by QA4): the stock parser consumes the complete numeric token and validates
integer thousands grouping, instead of truncating at the first dot. It parses
10.000 as 10000, 1.000 as 1000, 15.000 as 15000 and plain 800 as 800. Malformed
grouping such as 10.00 raises an error instead of substituting a fallback.
Stock remains `quantity`, never a monetary amount; promotion/daily periods
continue to follow the actual source clause.

The 15 official stock cases have individual regressions: 9386, 9324, 9325, 9326,
9327, 9328, 9385, 9374, 9375, 9376, 9377, 9378, 9379, 9381, 9460.

QA-011 (closed by QA4): positive legal clauses naming Visa Personal Pay and NFC complement
incomplete API helper lists. The six reported offers (5080, 8908, 8909, 8970,
9386, 9385) retain QR/card and gain their evidenced NFC option. A generic legal
NFC option has issuer Personal Pay and network Visa; wallet and card_type remain
null unless separately evidenced. Existing helper app/wallet evidence is kept
without duplicate NFC rows. A prepaid type is set only when the positive clause
explicitly says so. Negative NFC clauses do not create a method. Bukito's
exclusive-card rejection of generic QR and COTO's legal wallet/issuer matrix
remain protected by ordinary tests.

A source-wide developer pattern check examined every API record, all **21 stock
offers** and all **19 offers whose legal mentions NFC**. There were no stock
quantity mismatches or omitted NFC alternatives in those checks. Coverage lists
the checked IDs and explicitly marks this as developer work, not independent QA.
This is not a claim of exhaustive semantic acceptance of every field.

## Prior audit history and preserved V2 behavior

QA1 found QA-001 through QA-006; QA2 closed those and found QA-007 through
QA-009; QA3 closed QA-001 through QA-009 and found QA-010/011. Each original
independent verdict was FAIL. The user then authorized one additional round;
QA4 closed QA-010/011 and returned FAIL with QA-012/013 still open. There were
four completed independent audits in total, with no further automatic cycles.

The integration retains four Personal Flow level variants, separate weekly and
first-balance recharge variants, three Reintegro Plus levels, fixed USD benefits,
gifts, multi-buy offers and free services. Base/additional recharge percentages
are separate compatible components, not summed. Extra mobile credit is distinct
from wallet cashback. Arcor's free shipping and minimum purchase, Rappi's extra
Chat GPT GO service and coupon restrictions, and Sony's conditional commercial
terms remain preserved. Concise source restrictions are in specific_conditions;
full original legal text is retained in terms and raw payloads.

Payment methods preserve complete combinations: COTO issuer/wallet NFC matrix,
Movistar/Tuenti balance versus app/card routes, three Flow payment routes, and
the two named recharge apps with the actual permitted funding alternatives.
Channels follow positive purchase conditions, not app mentions or QR/NFC rails.
La Reina transaction/weekly caps and weekly usage, Mas Vision per-benefit monthly
usage, ticket quantities, stock and currencies remain independently typed.

## Remaining source issue and five gates

Tienda Personal 9473 has incompatible binding start dates: detail legal says
2026-06-20; global legal says 2026-06-22. No explicit source hierarchy resolves
this. Both complete sources/dates are preserved, `valid_from=None`, final date
2026-10-31 and an actionable uncertainty note are emitted. No precedence was
invented to make this candidate eligible for a live write.

* catalog_complete: true for the expanded public scope described above.
* normalization_complete: true structurally, all 201 records yield V2 variants;
  semantic fidelity failed QA4 because QA-012/013 remain open.
* snapshot_replace_allowed: false.
* requires_review: true, due to the unresolved official validity conflict.
* safe_to_deactivate: false, also hard-disabled by the thin sync entry point.

Construction and scrape() never save an accepted snapshot. The source saver
rechecks raw identity/content, candidate hash, historical IDs, coverage flags
and whole-candidate V2 normalization before atomic replacement. A missing or
malformed baseline, disappearing former IDs (including equal-count swaps), blank
HTTP-200 essential fields, altered candidates and failed atomic writes are
covered by tests. The current candidate is rejected by the accepted-snapshot
saver; unknown historical state in ephemeral CI is not treated as safe.
Raw replacement and Supabase writes would not form one database transaction;
a later database/network failure would require an upsert retry.

## Tests and exact execution

**Current full suite: 319 passed in 8.23s. No modules excluded.**
The earlier Banco del Sol / greenlet DLL-control collection error did not recur
on this full rerun; no bypass or unrelated test change was applied.
A preceding limited invocation also passed 276 tests in 7.49s. There are now
113 Personal Pay cases, including 30 new stock/NFC regressions in this round.
All runner tests use in-memory scrapers/repositories and temporary files;
no real SyncRunner or sync CLI was executed.

This Windows Python 3.14 sandbox previously denied pytest mkdir(mode=0700)
temporary paths. The successful full run used the following process-only wrapper
from `backend/`, piped to `.venv/Scripts/python.exe -`:

```python
import pathlib, os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['SUPABASE_URL'] = 'https://unit-test.invalid'
os.environ['SUPABASE_SECRET_KEY'] = 'unit-test-not-a-secret'
import pytest
original = pathlib.Path.mkdir
def compatible_mkdir(self, mode=0o777, parents=False, exist_ok=False):
    if mode == 0o700 and str(self.resolve()).startswith(str(pathlib.Path('.tmp').resolve())):
        mode = 0o777
    return original(self, mode=mode, parents=parents, exist_ok=exist_ok)
pathlib.Path.mkdir = compatible_mkdir
raise SystemExit(pytest.main([
    '-q', 'tests', '--basetemp=.tmp/personal_pay_qa4/tests_unrestricted',
    '-p', 'no:cacheprovider',
]))
```

Use a fresh basetemp path for reproduction. The process disables dotenv loading
and supplies dummy test configuration because the shared runner still eagerly
imports Supabase settings. This is not a claim that production runner commands
are credential-independent.

Files owned by this integration are the Personal Pay scraper/normalizer/thin sync,
ordinary fixtures and three test modules, this report, and the Personal Pay entry
in the local JSON exporter. No shared model/schema changes, Supabase writes,
real synchronization, GitHub Actions edits, migrations, commits, pushes, merges
or deployments occurred. Temporary investigation/test directories stay under
`backend/.tmp/personal_pay*`; recursive cleanup was rejected by automatic approval
review as "blocked by policy" in an earlier round, and that rejection was not
evaded. No investigative files were put in backend/data.
