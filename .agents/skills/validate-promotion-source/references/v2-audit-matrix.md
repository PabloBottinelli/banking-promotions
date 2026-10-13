# V2 independent audit matrix

Capture expected official facts *before* reading code, then compare field-by-field. A table row is a review prompt, **not** a golden test fixture.

| Topic | Inspect and distinguish | False positive/negative to avoid |
|---|---|---|
| Source coverage | Official catalog scope, page count, filters, pagination/SSR, detail failure | 15 discovered ≠ all bank benefits unless scoped |
| Record identity | Stable raw ID, per-variant `source_id`, group ID, duplicates | Source's merchant card need not equal one benefit |
| Scope / merchant | Specific merchant vs general category (`Comercios de barrio`), name normalization | Do not invent individual stores |
| Every benefit | Discount, cashback, fixed reward, financing, fee waiver, free service, points, gifts, crypto | Non-shopping benefits must not disappear |
| Compatible benefits | Discount + installments allowed together when simultaneous | Additional segment/card-specific 10% cannot be summed blindly |
| Monetary accuracy | `Decimal`, percentage, `amount`, `currency`, `reward_currency` | Transfer USD 1,000 operational ceiling ≠ ARS reintegro cap |
| Limits | `monetary_cap`, `usage_count`, `minimum_purchase`, `stock`, `shared_group_id`, scope, period | Five uses ≠ $5; campaign shared cap ≠ per merchant |
| Payment combinations | Raw name, issuer, wallet, network, card type, rail | MODO QR does not imply all Visa or online checkout |
| Dates | Nullable `valid_from`/`valid_to`, exact legal period | No invented expiry for source with no date |
| Weekdays | Source positive day clause, `applies_every_day` vs [] | `sab` in responsabilidad; exclusions mentioning days |
| Channels | Actual online/presential versus app, QR, NFC | App YPF ≠ Prex app ≠ e-commerce |
| Merchant verification | Group label, `requires_merchant_verification`, official campaign/list URL | Needn't normalize every Cuenta DNI/Buepp store |
| Special conditions | Segments, plans, region, customer status, code, exclusions, per-stage conditions | `specific_conditions` must be useful, not generic boilerplate |
| Legal fidelity | `terms` original and raw evidence | Header, browser encoding or PowerShell output ≠ raw file corruption |
| Missing information | Unknown, no restriction stated, parser error, justified exclusion | Blank `payment_methods` ≠ all payment methods |
| Sync safety | Catalog completeness + normalization coverage + stable identities + no unseen deactivation | `ScrapeResult.complete` alone insufficient |

## Sampling policy

- **≤30 catalog entities:** review **all** official entries and all normalized variants; show per-ID summary.
- **>30:** stratify by benefit/merchant/region/segment/payment and include rare/outlier records; state exact sample and confidence, never claim every entry verified.
- Compare official terms to a *freshly produced normalized output* when possible; stale snapshots must be labeled with capture date.

## Report checks

1. Official source URL and exact expected statement.
2. Input raw field or excerpt and current normalized field value.
3. Whether failure is from scraper capture, normalizer interpretation, V2 modeling, export, or sync safety.
4. Minimum reproducible command or precise function/record.
5. Severity for real user impact; distinguish **confirmed** from **hypothesis**.
