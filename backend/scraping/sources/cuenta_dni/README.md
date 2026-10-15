# Cuenta DNI

Scope: all campaign cards in the official Cuenta DNI benefit catalog, including
the campaign pages linked by `urlPagina` (localidades and marcas destacadas).
Merchant/branch search directories remain official eligibility lookups. The
link to other Banco Provincia customer promotions is outside this source.

The SSR response contains the entire card collection. The official
`cuentaDNI_v2.js` loads individual modals from `GetBeneficioData2` and its rubro
filters change visibility of existing elements. There is no page or load-more
control. The scraper detects duplicate IDs, detail failures, blank essential
nodes, unexpected pagination and changed filter implementation.

Evidence captured 2026-10-15: 22 raw campaigns, 29 normalized variants, zero
excluded records. Public API response payloads, card markup and linked page
markup are retained. COTO's blank Banco Provincia legal field is backed by the
explicit official Visa terms link, Visa offer API, and linked PDF (full original
bytes in base64 plus extracted text). No other Visa campaigns are in scope.

Main official interfaces:

- https://www.bancoprovincia.com.ar/cuentadni/contenidos/cdnibeneficios/
- https://www.bancoprovincia.com.ar/cuentadni/Home/GetBeneficioData2?idBeneficio=1076
- https://www.bancoprovincia.com.ar/web/CDNI_especial_localidades
- https://www.bancoprovincia.com.ar/web/especialdetemporada
- https://www.visa.com.ar/es_ar/promociones/supermercados-coto/175150
- https://www.visa.com.ar/offers/api/offer/175150?locale=es_ar

The local data/JSON files are **review candidates**, not an approval to write
Supabase. `catalog_complete=true`, `normalization_complete=true`,
`snapshot_replace_allowed=false`, `requires_review=true`,
`safe_to_deactivate=false`. Exact reasons and identifiers are in compact
`data/cuenta_dni_coverage.json`:

- COTO's linked PDF promotes NFC but also includes a contradictory general NFC
  exclusion. The source card restricts Cuenta DNI to Visa debit Android; no
  other wallets/card combinations are invented from the broader Visa offer.
- Pet shops/veterinaries: legal cap says per Saturday but also total purchases
  in the month. Its period is left unknown, with both statements preserved.
- Pet shops/veterinaries and universities: display text says accumulation is
  allowed while the legal terms say non-accumulable. Both remain visible.
- Marcas destacadas: heading and cap clause say per merchant/CUIT, but the
  explanation unifies purchases across all participating merchants. The monthly
  amount is preserved; cap scope is unknown, explicitly explained and flagged
  for review rather than assigned a per-merchant scope.

QA correction: Localidades variant conditions now come exclusively from each
current linked-page legal clause and its accumulation header. Obsolete API
display text (April, per-validity cap and non-accumulation) remains in the raw
payload, with an explanation of the discrepancy. The Wednesday/Thursday variant
explicitly has no cap and does not inherit Monday/Tuesday's amount or the third
legal section's Comercios de Cercanía exclusions.

QA #2 correction: Mostaza's official NFC clause misspells "presencial" as
"prsencial". The normalizer recognizes the contextual phrase "compras realizadas
de manera prsencial ... en locales" as physical eligibility. NFC alone still
leaves channels unknown, with a regression covering that distinction. Both
Mostaza payment variants are physical; online remains unknown.

The legal text takes precedence over API display dates; e.g. DIA begins October
1, Mostaza August 13, librerías September 1. The source's examples and references
to separate compatible campaigns do not become additional percentages/caps.
Localidades retains its two real offers; its third legal section refers to the
existing Comercios de Cercanía campaign and is not duplicated as a third reward.
Retiree supplements are separate segment variants containing the primary and
additional compatible benefit, with an independent cap and unknown cap period.

`scrape()` never saves. Source saving requires the exact complete candidate,
explicit acceptance flags, valid detail fields and no missing previous IDs,
then performs atomic file replacement. A missing local historical baseline is
reported as unknown, and never authorizes deactivation. Ephemeral CI requires a
durable accepted baseline for cross-run disappearance protection. Raw saving
and a future Supabase upsert are separate operations; an upsert failure can leave
the raw snapshot ahead of database state. Shared runner tests cover failed/short
upserts, validation rejection and all deactivation gates. No sync entry point
has been executed.

The runner still eagerly imports its Supabase repository; `--validate-only` is
not credential-independent. Tests were run with dotenv loading disabled and
dummy URL/key values in process, with persistence mocked. Python 3.14 in this
Windows sandbox creates inaccessible mode-0700 temporary directories; the test
process adapts only `os.mkdir(mode=0700)` to 0755. No project or library code is
changed by this test harness. The direct pytest attempt failed on those temp
permissions; after QA #2 corrections the adapted source run passed 26 tests in
1.74 seconds, and the adapted full suite passed 232 tests in 8.40 seconds.
`pypdf` is a new runtime dependency for source-linked PDFs.

Exact full-suite PowerShell command, run from `backend/` (the dummy environment
and disabled dotenv prevent reading real Supabase credentials):

```powershell
$env:PYTHONIOENCODING='utf-8'; @'
import os,pytest,dotenv
original=os.mkdir
def mkdir(path,mode=0o777,*,dir_fd=None):
 return original(path,0o755 if mode==0o700 else mode,dir_fd=dir_fd)
os.mkdir=mkdir
dotenv.load_dotenv=lambda *a,**kw:False
os.environ['SUPABASE_URL']='https://example.invalid'
os.environ['SUPABASE_SECRET_KEY']='unit-test-placeholder'
raise SystemExit(pytest.main(['-q','tests','-p','no:cacheprovider','--basetemp=.tmp/cuenta-dni-qa2-full']))
'@ | .venv/Scripts/python.exe -
```

The targeted command uses the same bootstrap, replacing the `pytest.main` line:

```python
raise SystemExit(pytest.main(['-q','tests/scraping/test_cuenta_dni_scraper.py','tests/normalization/test_cuenta_dni_normalizer.py','-p','no:cacheprovider','--basetemp=.tmp/cuenta-dni-qa2-targeted']))
```
