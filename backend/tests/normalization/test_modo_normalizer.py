import copy
import json
from pathlib import Path

import pytest

from normalization.sources.modo import ModoNormalizer


def raw():
    d = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "modo" / "cardon.json").read_text(encoding="utf-8"))
    return {"source": "modo", "source_id": d["id"], "scraped_at": "2026-10-15T03:00:00+00:00",
            "promotion_url": "https://www.modo.com.ar/promos/" + d["slug"], "detail": d,
            "banks": [{"id": "6a089c91-a7d3-4199-a578-2132a3733f69", "name": "Macro"}], "categories": []}


def fixture_raw(name):
    r = raw()
    r["detail"] = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "modo" / (name + ".json")).read_text(encoding="utf-8"))
    r["source_id"] = r["detail"]["id"]
    r["promotion_url"] = "https://www.modo.com.ar/promos/" + r["detail"]["slug"]
    return r


def test_get_the_look_conflicts_are_explicit_not_fabricated_benefits():
    r = fixture_raw("get_the_look")
    messages = ModoNormalizer.evidence_conflicts(r["detail"])
    assert len(messages) == 3  # benefit, weekdays, brand cap
    assert any("25%" in x for x in messages)
    assert any("50.000" in x for x in messages)
    p = ModoNormalizer().normalize_many(r)[0]
    assert p.applies_every_day is None and p.days_of_week == []
    assert [b.type for b in p.benefits] == ["installments"]
    assert "25%" in p.specific_conditions and "50.000" in p.specific_conditions
    assert "Éminent" in p.specific_conditions
    d = copy.deepcopy(r["detail"])
    d["terms_and_conditions"] = "No válida para Sábado y Domingo comprendidos en la promoción. TNA 25%."
    assert ModoNormalizer.evidence_conflicts(d) == []


def test_santa_fe_preserves_eligibility_daily_participation_and_prize_stock():
    p = ModoNormalizer().normalize_many(fixture_raw("santa_fe_scratch"))[0]
    assert "últimos 60 días" in p.specific_conditions
    assert "no registren deuda en mora" in p.specific_conditions
    assert any(l.type == "usage_count" and l.quantity == 1 and l.period == "daily" for l in p.limits)
    assert any(l.type == "stock" and l.quantity == 7396 and l.scope == "campaign" for l in p.limits)
    assert any(l.type == "usage_count" and l.quantity == 1 and l.period == "promotion" and "ganadores" in l.description for l in p.limits)
    assert p.benefits[0].type == "other" and p.benefits[0].amount is None


def test_tiendabna_motos_flags_official_validity_and_tna_conflicts():
    r = fixture_raw("tiendabna_motos")
    p = ModoNormalizer().normalize_many(r)[0]
    assert p.valid_from.isoformat() == "2026-04-01"
    assert p.valid_to is None  # do not choose between legal Sep 30 and schedule Dec 31
    assert "2026-09-30" in p.specific_conditions and "2026-12-31" in p.specific_conditions
    assert "41,20%" in p.specific_conditions and "35.00%" in p.specific_conditions
    assert p.benefits[0].installment_options == [24]
    assert p.benefits[0].interest_free is False
    assert len(ModoNormalizer.evidence_conflicts(r["detail"])) == 2
    changed = copy.deepcopy(r["detail"])
    changed["conditions"]["schedule"]["stop_date"] = "2026-09-30"
    changed["offers"][0]["outcomes"]["financing"]["installments"][0]["annual_nominal_rate"] = "41.20"
    assert ModoNormalizer.evidence_conflicts(changed) == []


def test_macro_account_month_conflict_preserves_fixed_reward_native_caps_and_legal():
    r = fixture_raw("macro_todos_pagos")
    p = ModoNormalizer().normalize_many(r)[0]
    assert [(b.type, str(b.amount), b.currency) for b in p.benefits] == [("cashback", "2000", "ARS")]
    assert any(l.type == "minimum_purchase" and str(l.amount) == "8000" for l in p.limits)
    assert any(l.type == "monetary_cap" and str(l.amount) == "2000" and l.period == "transaction" for l in p.limits)
    assert any(l.type == "usage_count" and l.quantity == 5 for l in p.limits)
    assert any(l.type == "monetary_cap" and str(l.amount) == "10000" and l.scope == "person" and l.period == "promotion" for l in p.limits)
    assert "El reintegro es por cuenta por mes" in p.specific_conditions
    assert "ámbito/período del tope técnico difiere" in p.specific_conditions
    assert len(ModoNormalizer.evidence_conflicts(r["detail"])) == 1
    changed = copy.deepcopy(r["detail"])
    changed["offers"][0]["limits"]["period_cap"].update(aggregate_by="account", reset_by="month")
    assert ModoNormalizer.evidence_conflicts(changed) == []


def test_santa_fe_actionable_summary_keeps_full_terms_without_boilerplate_or_questions():
    p = ModoNormalizer().normalize_many(fixture_raw("santa_fe_scratch"))[0]
    for text in ["mayores de 18 años", "Provincia de Santa Fe", "últimos 60 días", "no registren deuda en mora",
                 "App del Banco", "QR", "$25.000", "única participación por día", "probabilidades",
                 "sin obligación de compra", "raspaygana@bancosantafe.com.ar", "Consultar comercios"]:
        assert text in p.specific_conditions
    for text in ["CUIT", "Tucumán", "Responsabilidad:", "Seguridad:", "Impuestos y gastos:", "Imágenes y difusión:", "¿"]:
        assert text not in p.specific_conditions
    assert "Responsabilidad:" in p.terms and "Imágenes y difusión:" in p.terms
    assert len(p.specific_conditions) < 3000  # all selected sections, no arbitrary slice


@pytest.mark.parametrize("field", ["start_date", "stop_date"])
def test_conflicting_validity_unsets_only_affected_boundary(field):
    r = fixture_raw("tiendabna_motos")
    r["detail"]["conditions"]["schedule"].update(start_date="2026-04-01", stop_date="2026-09-30")
    r["detail"]["conditions"]["schedule"][field] = "2026-05-01"
    p = ModoNormalizer().normalize_many(r)[0]
    assert getattr(p, "valid_from" if field == "start_date" else "valid_to") is None
    assert getattr(p, "valid_to" if field == "start_date" else "valid_from") is not None


@pytest.mark.parametrize("legal", [
    "No promoción válida desde el 01/04/2026 al 30/09/2026.",
    "Crédito con TNA 25%. Solicitudes desde el 01/04/2026 al 30/09/2026.",
])
def test_unrelated_or_negative_date_clause_does_not_override_campaign(legal):
    d = fixture_raw("tiendabna_motos")["detail"]
    d["terms_and_conditions"] = legal
    assert ModoNormalizer.validity_conflicts(d) == {}


def test_paruolo_single_issuer_uses_only_its_native_card_options():
    r = fixture_raw("paruolo")
    r["banks"] = [{"id": "ce8aabb1-f663-4832-82ec-de9b5b572aa1", "name": "Comafi"}]
    p = ModoNormalizer().normalize_many(r)[0]
    assert {(m.issuer, m.network, m.card_type, m.payment_rail) for m in p.payment_methods} == {
        ("Comafi", "Visa", "credit", "qr"), ("Comafi", "Mastercard", "credit", "qr")}


def test_payment_issuer_is_resolved_per_offer_never_global_product():
    r = raw()
    second = copy.deepcopy(r["detail"]["offers"][0])
    second.update(id="second-bank")
    second["requirements"]["banks"]["list"] = ["bank-b"]
    r["detail"]["offers"].append(second)
    r["banks"].append({"id": "bank-b", "name": "Bank B"})
    rows = ModoNormalizer().normalize_many(r)
    assert {m.issuer for m in rows[0].payment_methods} == {"Macro"}
    assert {m.issuer for m in rows[1].payment_methods} == {"Bank B"}


def test_official_cardon_compatible_cashback_financing_and_actual_schedule():
    p = ModoNormalizer().normalize_many(raw())[0]
    assert p.valid_from.isoformat() == "2026-10-15"
    assert p.valid_to.isoformat() == "2027-03-31"  # not publication display July 2027
    assert p.benefits[0].type == "cashback"
    assert str(p.benefits[0].percentage) == "30"
    assert p.benefits[1].installment_options == [1, 2, 3, 4, 5, 6, 8, 9, 10, 12]
    assert p.benefits[1].interest_free is True
    assert p.limits == []  # explicitly sin tope, not a zero-peso cap
    assert p.days_of_week == ["monday", "tuesday", "wednesday"]
    assert p.online is None and p.physical is True
    assert p.requires_merchant_verification
    assert "NIVEL 4" in p.specific_conditions
    assert "EMPRESA O AGRO" in p.specific_conditions
    assert "Consultar comercios" in p.specific_conditions
    assert {m.network for m in p.payment_methods} == {"Visa", "Mastercard", "American Express"}
    assert all(m.issuer == "Macro" for m in p.payment_methods)
    assert {m.payment_rail for m in p.payment_methods} == {"qr", "nfc"}
    assert p.model_dump(mode="json")["benefits"][0]["percentage"] == "30"


def test_stable_offer_variants_never_sum_percentages():
    r = raw()
    other = copy.deepcopy(r["detail"]["offers"][0])
    other.update(id="segment-premium", name="Clientes Premium")
    other["outcomes"]["cashback"]["amount"] = 45
    r["detail"]["offers"].append(other)
    before = ModoNormalizer().normalize_many(r)
    r["detail"]["name"] = "New marketing"
    r["detail"]["offers"].reverse()
    after = ModoNormalizer().normalize_many(r)
    assert {x.source_id for x in before} == {x.source_id for x in after}
    assert {str(x.benefits[0].percentage) for x in after} == {"30", "45"}
    assert len({x.promotion_group_id for x in after}) == 1


def test_official_cafe_martinez_faq_has_two_explicit_segments():
    r = raw()
    r["detail"] = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "modo" / "cafe_martinez.json").read_text(encoding="utf-8"))
    r["source_id"] = r["detail"]["id"]
    r["banks"] = [{"id": "167504f6-caaf-4ead-b65b-6e6695ae6209", "name": "Santander"}]
    rows = ModoNormalizer().normalize_many(r)
    assert len(rows) == 2
    assert [(str(p.benefits[0].percentage), str(p.limits[0].amount)) for p in rows] == [("10", "10000"), ("20", "20000")]
    assert "Sorpresa Santander" in rows[1].specific_conditions
    ids = {p.source_id for p in rows}
    r["detail"]["details"]["faq"] = r["detail"]["details"]["faq"].replace("20%", "25%")
    assert {p.source_id for p in ModoNormalizer().normalize_many(r)} == ids


def test_typed_limits_and_null_currency_without_evidence():
    r = raw()
    r["detail"]["terms_and_conditions"] = None
    o = r["detail"]["offers"][0]
    o["limits"] = {"period_cap": {"amount_by_period": 5000, "amount_of_transactions_by_period": 3, "reset_by": "month", "aggregate_by": "user"}, "transaction_cap": {"amount_by_transaction": 2000}}
    o["requirements"]["amount_range"]["min"] = 10000
    p = ModoNormalizer().normalize_many(r)[0]
    assert [(x.type, str(x.amount), x.quantity) for x in p.limits] == [("monetary_cap", "5000", None), ("usage_count", "None", 3), ("monetary_cap", "2000", None), ("minimum_purchase", "10000", None)]
    assert p.limits[0].period == "monthly" and p.limits[0].scope == "person"
    assert p.limits[0].currency is None
    assert p.terms is None and "no publica texto legal" in p.specific_conditions


def test_scratch_retains_chance_without_guaranteed_amount():
    r = raw()
    r["detail"]["card"]["benefit"] = "¡Hasta $20.000!"
    r["detail"]["offers"][0]["outcomes"] = {"payment_scratch": {"prize_distribution": [{"amount": 0, "probability": 1}]}}
    r["detail"]["offers"][0]["limits"] = {"winning_cap": {"max_wins": 1}}
    p = ModoNormalizer().normalize_many(r)[0]
    assert p.benefits[0].type == "other"
    assert p.benefits[0].amount is None
    assert "aleatorios" in p.benefits[0].description
    assert p.limits[0].quantity == 1


def test_day_tokens_unknown_dates_and_channels():
    r = raw()
    r["detail"]["conditions"]["schedule"] = {}
    r["detail"]["conditions"]["payment_flow"]["flows"] = ["all"]
    r["detail"]["terms_and_conditions"] = "Responsabilidad del banco; no válido los sábados."
    p = ModoNormalizer().normalize_many(r)[0]
    assert p.days_of_week == [] and p.applies_every_day is None
    assert p.valid_from is None and p.valid_to is None
    assert p.online is None and p.physical is None


def test_direct_discount_and_interest_conditions():
    r = raw()
    o = r["detail"]["offers"][0]
    o["outcomes"]["cashback"]["cashback_mode"] = "descuento_en_pdv"
    o["outcomes"]["financing"]["installments"] = [{"type": "con_interes_preferencial", "number": 6}]
    p = ModoNormalizer().normalize_many(r)[0]
    assert p.benefits[0].type == "discount"
    assert p.benefits[1].interest_free is False


@pytest.mark.parametrize("change", [
    lambda o: o.update(outcomes={"unrecognized": {"amount": 99}}),
    lambda o: o.update(outcomes={"financing": {"installments": []}}),
    lambda o: o["outcomes"]["cashback"].update(amount=None),
    lambda o: o.update(limits={"unknown_cap": {"amount": 900}}),
])
def test_unknowns_fail_instead_of_financial_fallback(change):
    r = raw()
    change(r["detail"]["offers"][0])
    with pytest.raises(ValueError):
        ModoNormalizer().normalize_many(r)
