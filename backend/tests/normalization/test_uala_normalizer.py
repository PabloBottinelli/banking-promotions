import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.sources.uala import UalaNormalizer, benefits, validity, weekdays


def catalog():
    data = json.loads((Path(__file__).parents[1] / "fixtures/uala/official_promotions.json").read_text(encoding="utf-8"))
    return {r["catalog"]["fields"]["urlDeLaPromocion"]: r for r in data}


def normalize(slug):
    return UalaNormalizer().normalize_many(catalog()[slug])


def test_all_official_items_and_variants():
    all_promos = [p for r in catalog().values() for p in UalaNormalizer().normalize_many(r)]
    assert len(all_promos) == 12
    assert len({p.source_id for p in all_promos}) == 12
    assert {b.type for p in all_promos for b in p.benefits} == {"discount", "cashback"}
    for p in all_promos:
        assert p.valid_from and p.valid_to and p.terms
        assert p.specific_conditions and len(p.specific_conditions) < len(p.terms)
        assert isinstance(p.model_dump(mode="json")["benefits"][0]["percentage"], str)


def test_ypf_minimum_weekly_cap_and_payment_app():
    p = normalize("ypf")[0]
    assert (p.valid_from, p.valid_to) == (date(2026, 9, 28), date(2026, 10, 31))
    assert p.benefits[0].percentage == Decimal("10")
    assert [(x.type, x.amount) for x in p.limits] == [("monetary_cap", Decimal("6000")), ("minimum_purchase", Decimal("35000"))]
    assert p.limits[0].period == "weekly" and p.limits[0].scope == "card"
    assert {m.wallet for m in p.payment_methods} == {"App YPF"}
    assert p.days_of_week == ["monday"] and p.physical is True and p.online is None


def test_pedidosya_binding_legal_over_conflicting_summary():
    p = normalize("pedidosya")[0]
    assert p.benefits[0].type == "discount" and p.benefits[0].percentage == 25
    assert p.limits[0].amount == 15000 and p.limits[0].period == "monthly"
    assert [m.card_type for m in p.payment_methods] == ["credit"]
    assert p.days_of_week == ["saturday"] and p.applies_every_day is False
    assert p.valid_from == date(2026, 9, 19)
    assert "PedidosYa Plus" in p.specific_conditions
    assert p.requires_merchant_verification and p.promotion_url.endswith("/pedidosya")
    assert "reintegro" not in p.title


def test_colectivos_nfc_is_rail_not_online():
    p = normalize("colectivos")[0]
    assert p.benefits[0].type == "cashback"
    assert p.limits[0].amount == 25000
    assert {m.payment_rail for m in p.payment_methods} == {"nfc"}
    assert p.physical is True and p.online is None and p.applies_every_day is True
    assert p.requires_merchant_verification


@pytest.mark.parametrize("slug,stock,period", [("rappi", 1100, "weekly"), ("seekerparking", 2200, "monthly")])
def test_stock_is_campaign_quantity(slug, stock, period):
    p = normalize(slug)[0]
    limit = next(l for l in p.limits if l.type == "stock")
    assert limit.quantity == stock and limit.amount is None
    assert limit.period == period and limit.scope == "campaign"


def test_cabify_staged_voucher_and_first_five_are_distinct():
    p = normalize("cabify100")[0]
    assert p.days_of_week == ["monday", "tuesday", "wednesday", "thursday", "friday"]
    assert p.limits[0].amount == 25000 and p.limits[0].period == "transaction"
    assert p.limits[1].quantity == 2
    assert "8:59" in p.specific_conditions and "mismo día" in p.specific_conditions
    assert "manualmente" in p.specific_conditions
    q = normalize("cabify")[0]
    assert q.limits[0].amount == 4000 and q.limits[1].quantity == 5
    assert "5MASTER" in q.specific_conditions and "90" in q.specific_conditions


def test_subscription_restrictions_and_merchant_plans():
    p = normalize("rappipro")[0]
    assert p.benefits[0].percentage == 90 and p.limits[0].quantity == 1
    assert "RappiProUala" in p.specific_conditions and "3 meses" in p.specific_conditions
    gravl = normalize("gravl")[0]
    assert "UALA" in gravl.specific_conditions and "usuarios nuevos" in gravl.specific_conditions
    sport = normalize("sportclub")
    assert len(sport) == 2 and sport[0].promotion_group_id == sport[1].promotion_group_id
    assert sport[0].source_id != sport[1].source_id
    for p in sport:
        assert p.requires_merchant_verification and p.limits[0].quantity == 150
        assert "No incluye" in p.specific_conditions and "cuenta" not in p.source_id
    assert "Sport-Uala1" in sport[0].specific_conditions
    assert "SportUala1" in sport[1].specific_conditions


def test_coderhouse_courses_exclusions_and_physical_channel():
    p = normalize("coderhouse")[0]
    assert p.online is True and p.physical is True
    assert p.limits[0].scope == "course" and p.limits[0].quantity == 1
    assert "GRACIASUALA" in p.specific_conditions and "Membresía" in p.specific_conditions
    assert [m.network for m in p.payment_methods] == ["Mastercard", None]


def test_variant_identity_stable_under_order_and_copy_changes():
    raw = catalog()["sportclub"]
    before = {p.source_id for p in UalaNormalizer().normalize_many(raw)}
    raw["detail"]["specs"].reverse()
    raw["detail"]["specs"][0]["title"] = "Nueva presentación"
    raw["detail"]["specs"][0]["description"] = "Texto actualizado"
    assert {p.source_id for p in UalaNormalizer().normalize_many(raw)} == before


def test_unknown_dates_days_and_no_fake_economic_fallback():
    assert validity("Sin fechas publicadas. Plazo de acreditación 30 días.") == (None, None)
    assert weekdays("responsabilidad; no válido los sábados", {}) == ([], None)
    assert weekdays("", {"days": []}) == ([], None)
    with pytest.raises(ValueError): benefits("Falló la captura del descuento", {"title": "Oferta"})
    assert benefits("Transferencia sin comisión", {"title": "Transferencias"})[0].type == "fee_waiver"
