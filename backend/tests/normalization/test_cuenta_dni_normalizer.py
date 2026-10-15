import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.sources.cuenta_dni import CuentaDNINormalizer, validity, weekdays


@pytest.fixture
def examples():
    path = Path(__file__).parents[1] / "fixtures/cuenta_dni/official_examples.json"
    return {x["source_id"]: x for x in json.loads(path.read_text(encoding="utf8"))}


def test_dia_distinct_payment_rates(examples):
    rows = CuentaDNINormalizer().normalize_many(examples["1076"])
    assert [r.source_id for r in rows] == ["1076:nfc", "1076:saldo"]
    assert [r.benefits[0].percentage for r in rows] == [Decimal(20), Decimal(10)]
    assert rows[0].payment_methods[0].network == "Visa"
    assert rows[0].payment_methods[0].card_type == "credit"
    assert rows[1].payment_methods[0].payment_rail == "other"
    assert rows[1].payment_methods[0].card_type is None
    assert all(r.valid_from == date(2026, 10, 1) and r.valid_to == date(2026, 12, 31) for r in rows)
    assert rows[0].days_of_week == ["monday"]
    assert all(r.online is None and r.physical is True for r in rows)


def test_mostaza_rates_caps_not_stacked(examples):
    a, b = CuentaDNINormalizer().normalize_many(examples["1030"])
    assert a.benefits[0].percentage == 25 and b.benefits[0].percentage == 30
    assert a.limits[0].amount == 8000 and b.limits[0].amount == 15000
    assert b.limits[0].period == "weekly"
    assert {m.card_type for m in b.payment_methods} == {"debit", "credit"}
    assert all(m.payment_rail == "nfc" for m in b.payment_methods)
    assert all(m.card_type is None for m in a.payment_methods)
    assert a.physical is True and b.physical is True
    assert b.online is None
    assert a.valid_from == date(2026, 8, 13)  # legal, not API display start Aug 1


def test_nfc_does_not_imply_physical_without_positive_channel(examples):
    raw = copy.deepcopy(examples["1030"])
    b = raw["payload"]["Entity"]["Beneficio"]
    b["legal"] = b["legal"].replace("DE MANERA PRSENCIAL ", "")
    rows = CuentaDNINormalizer().normalize_many(raw)
    nfc = next(row for row in rows if row.source_id.endswith(":nfc"))
    assert nfc.physical is None and nfc.online is None


def test_localidades_own_two_offers_not_referenced_third(examples):
    rows = CuentaDNINormalizer().normalize_many(examples["1069"])
    assert len(rows) == 2
    assert [r.benefits[0].percentage for r in rows] == [15, 10]
    assert rows[0].limits[0].amount == 7000
    assert rows[0].limits[0].scope == "person_merchant_tax_id"
    assert rows[1].limits == []
    assert rows[0].days_of_week == ["monday", "tuesday"]
    assert rows[1].days_of_week == ["wednesday", "thursday"]
    assert all(r.requires_merchant_verification and "localidad" in r.promotion_url.lower() for r in rows)
    for row in rows:
        assert "Hasta abril" not in row.specific_conditions
        assert "por vigencia" not in row.specific_conditions
        assert "Promociones no acumulables" not in row.specific_conditions
        assert "SE EXCLUYE PET SHOP" not in row.specific_conditions
        assert "GASTRONOMÍA" not in row.specific_conditions
        assert "Acumulable con Comercios de Cercanía" in row.specific_conditions
        assert "desactualizada" in row.specific_conditions
    assert "$7000" in rows[0].specific_conditions and "semanal" in rows[0].specific_conditions
    assert "Sin tope de reintegro" in rows[1].specific_conditions
    assert "7000" not in rows[1].specific_conditions and "7.000" not in rows[1].specific_conditions
    # The other campaign's section and the obsolete API are still traceable.
    assert "SE EXCLUYE PET SHOP" in rows[0].terms
    assert examples["1069"]["payload"]["Entity"]["Beneficio"]["subtitulo"] == "Hasta abril"


def test_marcas_cap_scope_is_unresolved_not_per_merchant(examples):
    row = CuentaDNINormalizer().normalize_many(examples["1063"])[0]
    assert row.limits[0].amount == 15000 and row.limits[0].period == "monthly"
    assert row.limits[0].scope is None
    assert "sin resolver" in row.limits[0].description
    assert "Alcance del tope contradictorio" in row.specific_conditions
    assert "por comercio" in row.specific_conditions
    assert "todos los comercios adheridos" in row.specific_conditions


def test_retiree_extra_has_independent_cap(examples):
    base, retiree = CuentaDNINormalizer().normalize_many(examples["1077"])
    assert len(base.benefits) == 1
    assert [b.percentage for b in retiree.benefits] == [15, 5]
    assert [c.amount for c in retiree.limits] == [20000, 5000]
    assert retiree.limits[1].period is None
    assert "jubilados" in retiree.specific_conditions


def test_pet_conflict_kept_unknown_period(examples):
    row = CuentaDNINormalizer().normalize_many(examples["1071"])[0]
    assert row.days_of_week == ["saturday"]
    assert row.applies_every_day is not True
    assert row.limits[0].amount == 8000 and row.limits[0].period is None
    assert "mensual" in row.specific_conditions


def test_librerias_no_imported_comercios_cap(examples):
    row = CuentaDNINormalizer().normalize_many(examples["561"])[0]
    assert row.benefits[0].percentage == 10
    assert row.limits == []
    assert row.valid_from == date(2026, 9, 1)
    assert row.days_of_week == ["monday", "tuesday"]
    assert {p.payment_rail for p in row.payment_methods} == {"qr", "other"}
    assert "20%" in row.terms


def test_installments_and_decimal_json(examples):
    row = CuentaDNINormalizer().normalize_many(examples["519"])[0]
    assert row.benefits[0].type == "installments"
    assert row.benefits[0].installment_options == [3] and row.benefits[0].interest_free is True
    assert {(p.network, p.card_type, p.issuer, p.payment_rail) for p in row.payment_methods} == {
        ("Visa", "credit", "Banco Provincia", "qr"), ("Mastercard", "credit", "Banco Provincia", "qr")}
    assert row.applies_every_day is True and row.days_of_week == []
    cash = CuentaDNINormalizer().normalize_many(examples["1077"])[0].model_dump(mode="json")
    assert cash["benefits"][0]["percentage"] == "15"
    assert cash["limits"][0]["amount"] == "20000"
    assert "discount_percentage" not in cash


def test_no_fallback_and_stable_ids(examples):
    raw = copy.deepcopy(examples["1077"])
    old = CuentaDNINormalizer().normalize_many(raw)
    raw["payload"]["Entity"]["Beneficio"]["titulo"] = "Marketing edit"
    new = CuentaDNINormalizer().normalize_many(raw)
    assert [r.source_id for r in old] == [r.source_id for r in new]
    raw["payload"]["Entity"]["Beneficio"]["legal"] = "No se informó el beneficio"
    with pytest.raises(ValueError, match="percentage"):
        CuentaDNINormalizer().normalize_many(raw)


def test_unknown_dates_weekday_boundaries():
    assert validity("Vigencia no publicada") == (None, None)
    assert weekdays("", "responsabilidad; no aplica los sábados") == ([], None)
    assert weekdays("PROMOCIÓN VÁLIDA TODOS LOS DIAS SÁBADOS DE OCTUBRE DE 2026 PARA COMPRAS", "") == (["saturday"], None)


def test_external_coto_uses_wallet_specific_card_not_other_visa_options(examples):
    # Synthetic minimal extraction of independently read Visa offer and linked PDF.
    raw = copy.deepcopy(examples["1077"])
    raw["source_id"] = "1034"
    b = raw["payload"]["Entity"]["Beneficio"]
    b.update(id=1034, url="supermercadocoto", legal=" ", titulo="COTO", tipo=1)
    raw["payload"]["Entity"]["Condiciones"] = []
    raw["external_terms"] = {
        "text": "Sucursales físicas en CABA, GBA, Neuquén, Mendoza, Entre Ríos y Santa Fe. No válido para venta online. Exclusiones detalladas en PDF.",
        "pdf_url": "https://www.visa.com.ar/terms.pdf",
        "payload": {"offerShortDescription": {"text": "30% OFF en Coto pagando con Visa Débito NFC todos los jueves. Descuento en caja. Sin tope."},
                    "validityFromDate": "2026-02-26", "validityToDate": "2026-10-15"}}
    row = CuentaDNINormalizer().normalize_many(raw)[0]
    assert row.benefits[0].type == "discount" and row.benefits[0].percentage == 30
    assert len(row.payment_methods) == 1
    assert row.payment_methods[0].card_type == "debit" and row.payment_methods[0].wallet == "Cuenta DNI"
    assert row.days_of_week == ["thursday"] and row.physical is True and row.online is False
    assert row.valid_to == date(2026, 10, 15)
    assert row.limits == []
