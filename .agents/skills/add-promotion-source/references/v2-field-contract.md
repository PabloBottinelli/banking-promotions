# V2 field contract and examples — read `backend/normalization/models.py` first

This reference matches the agreed **V2 proposal**. If actual code differs, rely on current code and report the drift rather than inventing fields.

| Concept | V2 representation | Common mistake to reject |
|---|---|---|
| Identity | `source`, per-variant `source_id`, `promotion_group_id` | Index-based variant IDs, changing with title/order |
| Any kind of benefit | `benefits: list[Benefit]` with supported `type` and source-based description | Omitting financial services; fake default 10%/20% |
| Refund vs direct discount | `cashback` vs `discount`, `%` vs monetary `amount` | Mixing reimbursement with instant discount |
| Financing | `Benefit(type="installments", installment_options=[...], interest_free=True/None)` | Claiming interest-free without proof |
| Fixed amounts | `Decimal` amount + explicit `currency` | Treating USD or BTC as pesos |
| Crypto reward | `reward_currency` separate from purchase currency | Modeling crypto payout as ARS money |
| Topes/minimums/stock | `limits: list[PromotionLimit]` typed + amount/quantity/period/scope | Mapping 5 uses into $5 cap; treating transfer operating ceiling as cashback cap |
| Shared cap | `PromotionLimit.shared_group_id` | Presenting a shared cap as a separate cap per store |
| Payment | `payment_methods: list[PaymentMethod]` complete combinations | Joining unrelated issuer/card/rail choices into false options |
| Dates | `valid_from`, `valid_to` accept `None` | Invented last-day-of-year expiry or dropping offer |
| Days | `applies_every_day=True` explicit; otherwise precise `days_of_week` or unknown | `[]` interpreted every day; `sab` in `responsabilidad` |
| Channel | nullable `online`, `physical` | App payment equals e-commerce |
| Attached merchants | descriptive `merchant`, `requires_merchant_verification`, `promotion_url` | Requiring per-store records for Cuenta DNI/Buepp |
| Special restrictions | `specific_conditions` plus full original `terms` | Adding dozens of bank-specific schema columns |

## V2 partial examples — illustrative, not current promotions

**Comercios de barrio:** `merchant="Comercios de barrio"`, `scope="category"`, `requires_merchant_verification=True`, `promotion_url=<official campaign page>`, `specific_conditions="Solo comercios adheridos: consultar listado oficial."`. **No need** to model individual shops.

**Personal Pay by level:** distinct normalized rows `offer:level-1`, `offer:level-2` with shared `promotion_group_id="offer"`, each with its own `cashback` percentage, cap and `specific_conditions="Exclusivo Nivel N"`. Never fabricate percentages if absent.

**Credicoop discount plus financing:** compatible unconditional discount + financing can coexist in `benefits`. An additional discount requiring MODO and a particular card requires a separate payment-specific variant, not an unconditional summed percentage.

**Cabify-like offer:** `Benefit(type="cashback", percentage=Decimal("50"))`, `PromotionLimit(type="monetary_cap", amount=Decimal("4000"), currency="ARS", period="transaction")`, `PromotionLimit(type="usage_count", quantity=5, period="promotion", scope="person")`; actual facts must come from the live source, not this example.

**Fee-free transfer:** `Benefit(type="fee_waiver", description="Transferencia sin comisión")`, include USD transfer operation limits in `specific_conditions`/`terms`; do not create a fictional refund cap.

**Unpublished expiry:** `valid_to=None`. Keep the source URL and date-related uncertainty explicit; `None` does not mean evergreen.

## Source versus database

- Keep legacy flat fields **out of V2 objects** (`discount_percentage`, `installments`, `cap_amount`, `minimum_purchase`, `qr`, `nfc`, `contactless`, `customer_segments`, `eligibility_requirements`).
- Serialize with `model_dump(mode="json")`; `Decimal` generally becomes a JSON string, suitable for preserving precision in `jsonb` if the schema supports it.
- `ScrapeResult.complete=True` is a catalog-level claim, not a blanket permit for `deactivate_not_seen` after partial normalization.
