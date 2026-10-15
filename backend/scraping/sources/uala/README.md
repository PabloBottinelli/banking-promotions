# Ualá — developer handoff

Status: **READY_FOR_INDEPENDENT_QA**. This is developer evidence, not independent acceptance.

## Official scope and capture

Catalog: https://www.uala.com.ar/promociones . Capture: **2026-10-15 20:53:28 UTC** (17:53:28 Argentina).
The scope is every campaign supplied to this public promotions page, including every nested
PromotionSpec. Product navigation and the separate Ualá Bis merchant site are outside this catalog.
There is no arbitrary purchase-only or active-date filter.

The Next.js `__NEXT_DATA__` payload contains `page.components[*].promociones`, a finite array
of 11 Contentful campaigns. The initial rendered UI displays only 9. The live official bundle
`https://www.uala.com.ar/_next/static/chunks/48072-2651de87ab87a34e.js`
(SHA256 `526af0a6bd9e0673d9d668a2279d8a1e1506558ad862021c7f9338e5418fe180`)
shows `promotions` supplied from that array, client-side filters, `slice(0, quantity)`, state
initialized at 9, and load-more incrementing state by 9. There is no separate catalog request
for the next batch. Scraping verifies these live local-pagination markers and rereads the
complete catalog after detail retrieval; an unrecognized UI redesign or changed catalog blocks
acceptance. This verification is deliberately conservative and may need maintenance after a build change.

Each official `/promociones/<slug>` was fetched separately. Campaign IDs, complete spec-ID sets,
nonblank titles/legal text, and exact equality between catalog and detail legal text were checked.
11 campaigns / 11 unique IDs / 11 successful details / 12 specs / 0 errors / 0 exclusions.
SportClub contributes Total and Plus variants. Every raw record yields at least one V2 object;
12 unique stable `campaign-CMS-ID:spec-CMS-ID` identities share their campaign group ID.
IDs do not derive from display order, marketing copy or dates. The original promotional CMS
payload and transformed detail payload are retained; unrelated shared `promotionweb` navigation
is omitted to avoid repeated navigation data. `scraped_at` is timezone aware.

## Developer field comparison (all campaigns)

All commercial values below were read from published terms, not supplied as parser fallbacks.
Dates are retained even if subsequently expired; absent source dates remain nullable.

| Detail URL suffix | Normalized benefit and limits | Eligibility / special conditions |
|---|---|---|
| ypf | 10% cashback; ARS 6,000 weekly/card; ARS 35,000 minimum | 28 Sep–31 Oct 2026; Mondays; credit/prepaid Mastercard via App YPF; physical |
| colectivos | 100% cashback; ARS 25,000 monthly/card | 1–31 Oct 2026; every day; credit/prepaid Mastercard via mobile NFC wallet; enabled bus lines; physical |
| pedidosya | 25% **direct discount**; ARS 15,000 monthly/credit card | 19 Sep–31 Oct 2026; **Saturdays, credit Mastercard only**; active PedidosYa Plus; Mascotas; adherent merchants accepting online payment |
| rappi | 25% cashback; ARS 3,500 Tuesday/user; campaign stock 1,100 each Tuesday | 3 Aug–31 Oct 2026; Tuesday; prepaid; online |
| rappipro | 90% discount on 3-month subscription; one use/person | 3 Aug–31 Dec 2026; new subscribers or no Pro in prior 3 months; RappiProUala; credit/prepaid Mastercard |
| cabify100 | 100% discount voucher; ARS 25,000/next ride; max 2 vouchers/person/promotion | 19 Aug–31 Oct 2026; Mon–Fri; qualifying completed ride 07:00–08:59; manual voucher entry, same account and same-day expiry; specified ride categories; credit/prepaid Mastercard |
| seekerparking | 10% cashback; ARS 2,000 monthly/person; campaign stock 2,200 monthly | 20 Aug–20 Nov 2026; every day; credit/prepaid; website |
| cabify | 50% discount; ARS 4,000/ride; max 5 rides/person | 24 Jun–31 Oct 2026; new users or inactive 90 days; 5MASTER; code usable 30 days or campaign end; credit/prepaid Mastercard |
| gravl | 20% discount on annual plan; one use/person | 24 Jul 2026–30 Jul 2027; new users; UALA; credit/prepaid; website |
| sportclub (Total) | 20% discount; campaign stock 150 subscriptions | 1 Apr 2026–31 Jul 2027; monthly Total plan; Sport-Uala1; Ualá peso account; excludes Mujer Pilar, Ushuaia, Elite; adherent branches; credit/prepaid Mastercard |
| sportclub (Plus) | 20% discount; campaign stock 150 subscriptions | Same dates; monthly Plus plan; SportUala1; Ualá peso account; excludes Mujer Pilar, Ushuaia, Total and Elite; adherent branches; credit/prepaid Mastercard |
| coderhouse | 20% discount; one use per course/career/diploma, unlimited globally | 1 Jul 2026–30 Jun 2027; GRACIASUALA; Ualá peso account; excludes professional development and membership; online and physical; prepaid Mastercard / credit with network unspecified |

All 12 current benefits are discount/cashback. No financing, points, crypto, gifts or fee waivers
were found in this exact public catalog; no catalog record was excluded for being a financial service.
New unrecognized benefit structures fail normalization rather than being masked with `other`.
No interest-free, unspecified network or app-implied e-commerce facts are invented.
No shared SportClub stock pool is asserted: the two legal blocks each mention 150 and do not
explicitly state whether the stock is shared. This remains a source ambiguity in full terms.

### Source conflicts preserved for human review

PedidosYa summary says cashback, every day, prepaid and ARS 25,000; its binding legal terms
say direct discount, Saturdays, credit only and ARS 15,000. Normalization prioritizes the legal
terms and corrects the displayed normalized title. Both original payloads remain available.
Cabify100 catalog card says “100% de descuento en dos viajes”, while detail/terms describe
conditional vouchers earned from a morning ride. The variant preserves stages, max vouchers,
same-day use, manual entry, account and category requirements. Its legal text also contains
conflicting accumulation statements (bank promotions allowed versus a later general exclusion);
both are retained in conditions and terms without asserting unconditional accumulation.
SportClub's long `PromotionDescription` mentions a different coupon spelling; detail description
and legal terms agree on Sport-Uala1 / SportUala1, which take precedence.
Coderhouse summary lists Online while legal terms also allow physical branches; both channels
are represented. Legal address/issuer boilerplate remains in `terms`, not as extra source columns.

`specific_conditions` retains plans, codes, account/subscriber restrictions, exclusions, stages,
geographic availability and merchant checks. `terms` is the original unmodified legal text.
PedidosYa, SportClub and Colectivos set merchant verification and a working official detail URL
containing the actionable eligibility information and official merchant links. Local shops are
not invented or individually expanded.

## Five distinct safety judgments

| Judgment | Capture status and evidence |
|---|---|
| catalog_complete | True for the declared public catalog: complete hydrated array, live local-pagination implementation, stable second read, every separate detail validated |
| normalization_complete | True: 11 raw records generate 12 unique V2 variants, no exclusions or parse errors |
| snapshot_replace_allowed | True for this accepted first local capture; subsequent captures and saves compare a valid existing snapshot and reject lost/substituted campaign and `(campaign_id, spec_id)` identities, even at unchanged campaign/variant counts |
| requires_review | False for snapshot acceptance; known marketing/legal inconsistencies are resolved deterministically in favor of legal terms and documented above |
| safe_to_deactivate | **False**, always. No persistent historical/database baseline or independent retirement authorization |

No prior Ualá local snapshot existed. This is explicitly **not evidence of no historical database
rows**. The local comparison does not provide cross-run protection on ephemeral CI. Never enable
deactivation without a separate durable history design and review. Snapshot and Supabase upsert
are separate operations: a later failed/short upsert can leave newer raw data; mocked tests cover
this state, no deactivation, and repeatable snapshot retry. The shared runner eagerly imports
Supabase configuration even for validate-only; the new CLI inherits this caveat and was never run.

## Files and local artifacts

- `scraping/sources/uala/scraper.py`: injected transport, live scope checks, raw validation, historical ID guard, candidate fingerprint, atomic same-directory replacement.
- `normalization/sources/uala.py`: deterministic V2 variants, legal-first rates/caps/payment/days/dates, concise restrictions and full terms.
- `synchronization/sync_uala.py`: thin runner entry point, `normalize_many=True`, default deactivation off. **Not executed**.
- `normalization/export_json.py`: registered Ualá for local export.
- `tests/{scraping,normalization,synchronization}/test_uala_*.py`, `tests/fixtures/uala/official_promotions.json`: ordinary tests and sanitized public excerpts.
- Local ignored artifacts: `data/uala_promotions.json`, `data/normalized/uala_promotions.json`, `data/uala_coverage.json`. Existing repository policy ignores `backend/data/`; this integration does not change it.

## Verification commands and actual outcomes

From `backend/`, using `.venv/Scripts/python.exe`:

- Source-local candidate scrape → normalization of every record → unique-ID checks → `save_raw_promotions()` (no runner, no Supabase): **11 raw / 12 normalized / 0 excluded**.
- `python -X utf8 -m normalization.export_json --source uala`: **success, 11 → 12**. Initial export without `-X utf8` wrote valid UTF-8 JSON but its console success arrow failed under cp1252; rerun succeeded.
- Source scraper/normalizer/runner tests: **43 passed**. Includes blank HTTP-200 detail nodes, pagination changes, missing/duplicate IDs, empty variants, wrong source, partial scrape, explicit refusal/review, candidate mutation, same-count historical substitutions, valid additions/updates, atomic interruption, no-write validation, rejected snapshot save, failed/short upsert and every deactivation gate.
- Full existing suite plus Ualá: **249 passed in 12.75s**. After the final conditions-only cleanup, focused suite rerun: **43 passed in 4.54s**.

Windows Python 3.14 `mkdir(mode=0700)` creates pytest directories inaccessible to this sandbox.
The initial plain pytest attempts failed on collection (duplicate test basenames, corrected) and
temporary-directory permissions (16 passed, remaining temp-fixture setup errors, corrected in
execution adapter). Tests use an execution-only adapter making `os.mkdir` pass 0777, a unique
`.tmp/uala/pytest-*` base and `-p no:cacheprovider`; product code is unchanged for this issue.
Final focused command uses a `sys.modules['persistence.supabase_repository']` stub **before**
importing runner. Full-suite execution disabled `dotenv.load_dotenv` before import and supplied
only fictitious environment values, so `.env` was not read and every persistence operation was mocked.
Exploratory HTML/scripts/candidates and successful test temporary directories were removed.
The initially created `backend/.tmp/pytest-uala` is inaccessible (WinError 5); an ACL reset
also failed, so this empty/failed pytest directory remains as an environment cleanup limitation.

Reproduce the final targeted run without secrets (Python script, from `backend/`):

```python
import os, sys, types, pytest
stub = types.ModuleType('persistence.supabase_repository')
stub.SupabasePromotionRepository = type('NoDatabase', (), {})
sys.modules[stub.__name__] = stub
mkdir = os.mkdir
os.mkdir = lambda path, mode=0o777, **kw: mkdir(path, 0o777, **kw)
raise SystemExit(pytest.main([
    '-q', 'tests/scraping/test_uala_scraper.py',
    'tests/normalization/test_uala_normalizer.py',
    'tests/synchronization/test_uala_runner.py',
    '--basetemp=.tmp/uala-tests', '-p', 'no:cacheprovider']))
```

No Supabase synchronization, `.env` access, Actions modification, schema changes, push, merge or deployment.
No shared model changes; runtime V2 contract matches the fields used here.

## QA-001 correction after independent audit #1

Independent audit #1 returned FAIL for one medium-severity safety defect: historical comparison
covered campaign IDs but did not cover the nested PromotionSpec identities used by normalized
variants. Consequently, removing SportClub Plus (`7nlFAU5cWk0cMRVO5ecm6U`) or replacing its CMS ID
inside the same SportClub campaign (`6CReo7313gFFfYZ1SzdZ2j`) could pass snapshot acceptance despite
retaining the same eleven campaigns. The independent reviewer confirmed all eleven campaigns /
twelve variants commercially faithful and the exported JSON exact; that does not waive this defect.

The source now compares sets of `(campaign_id, spec_id)` as well as campaign IDs during capture
and again immediately before snapshot replacement. Missing normalized identities are reported in
compact `coverage.missing_previous_variant_ids`. A loss or substitution leaves structural
`ScrapeResult.complete` and `catalog_complete` separate from acceptance, sets
`snapshot_replace_allowed=False` and `requires_review=True`, and blocks saving/upserting.
If a baseline appears or changes between capture and save, the second check also updates these
flags and refuses replacement; the old bytes remain intact. This does not provide a filesystem
lock against concurrent writers after that final check, nor a durable baseline on ephemeral CI.

Seven ordinary regression cases cover removal and replacement with unchanged campaign counts,
the same two changes when history appears only after capture, stable IDs with marketing/date
updates plus a legitimate new spec, and two mocked runner save-boundary refusals with no upsert
or deactivation. No shared runner/model contract was changed. The live raw/export commercial
data remain unchanged (11/12); the compact coverage artifact gains the new empty missing-ID list
for its original first-capture context. Re-audit is required; developer tests are not QA approval.
Final full-suite verification after the correction: **256 passed in 11.94s**, using the documented
Windows mkdir adapter, `-p no:cacheprovider`, `.tmp/uala-qa001-final` and the repository module stub
before runner import. No `.env` or real persistence module was accessed. The seven added tests
increase Ualá's source-specific total from 43 to 50. Test temporary directories were removed.
