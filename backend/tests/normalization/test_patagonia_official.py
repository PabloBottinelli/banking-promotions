"""Official excerpts retrieved with certificate verification on 2026-10-19.

Expected facts come from each linked detail/terms, including contradictions.
"""
import json
import copy
from pathlib import Path
from decimal import Decimal

import pytest

from normalization.sources.patagonia import PatagoniaNormalizer


@pytest.fixture
def official():
    path = Path(__file__).parents[1] / "fixtures/patagonia/official_details_20261019.json"
    return {r["catalog"]["source_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def methods(p):
    return {(m.network, m.card_type, m.wallet, m.payment_rail) for m in p.payment_methods}


def test_carrefour_tiers_caps_and_credit_wallet_exceptions(official):
    rows = PatagoniaNormalizer().normalize_many(official["carrefour3"])
    assert [p.benefits[0].percentage for p in rows] == [Decimal("15"), Decimal("20"), Decimal("30")]
    assert [p.limits[0].amount for p in rows] == [10000, 15000, 20000]
    for p in rows:
        assert p.benefits[0].type == "cashback"
        assert (p.limits[0].period, p.limits[0].scope) == ("monthly", "account")
        assert p.days_of_week == ["wednesday"]
        assert p.online is True and p.physical is True
        assert ("american_express", "credit", None, "card") in methods(p)
        assert ("visa", "credit", None, "card") in methods(p)
        assert ("mastercard", "credit", None, "card") in methods(p)
        assert all(m.card_type for m in p.payment_methods)
        assert "PROGRAMANDO LA ENTREGA" in p.specific_conditions
        assert p.valid_from is None and p.valid_to is None
        assert p.terms == PatagoniaNormalizer()._extract_terms_from_main(official["carrefour3"]["detail"]["main_text"])


def test_temple_wallet_exception_only_applies_to_credit(official):
    rows = PatagoniaNormalizer().normalize_many(official["temple-bar"])
    assert [p.benefits[0].percentage for p in rows] == [20, 30]
    assert [p.limits[0].amount for p in rows] == [15000, 20000]
    for p in rows:
        assert p.applies_every_day is True
        assert p.physical is True and p.online is None
        assert p.requires_merchant_verification
        assert all(m.card_type == "credit" for m in p.payment_methods if m.wallet)
        assert {m.wallet for m in p.payment_methods if m.wallet} == {"MODO", "Apple Pay", "Google Pay"}
        assert "/plus/temple-bar.html" in p.terms
        assert "/singular/temple-bar.html" in p.terms
    assert PatagoniaNormalizer()._storefront_conflicts(official["temple-bar"]) == []


def test_contradictory_storefront_does_not_choose_an_economic_value(official):
    raw = copy.deepcopy(official["temple-bar"])
    extra = raw["storefront_details"][0]["detail"]
    extra["summary_text"] = extra["summary_text"].replace("20\n%", "25\n%")
    n = PatagoniaNormalizer()
    assert n._storefront_conflicts(raw) == ["plus"]
    row = n.normalize_many(raw)[0]
    assert row.benefits[0].percentage is None
    assert row.limits == [] and row.payment_methods == []
    assert "storefronts" in row.specific_conditions


def test_adidas_salary_segments_installments_and_promotion_cap(official):
    rows = PatagoniaNormalizer().normalize_many(official["adidas2"])
    assert [p.benefits[0].percentage for p in rows] == [20, 30]
    assert [p.limits[0].amount for p in rows] == [12500, 20000]
    for p in rows:
        assert "salary" in p.specific_conditions
        assert p.limits[0].period == "promotion"
        b = next(b for b in p.benefits if b.type == "installments")
        assert b.installment_options == [3] and b.interest_free is True
        assert all(m.network != "mastercard" for m in p.payment_methods)
        assert p.requires_merchant_verification is True
        assert "Consultar locales/sucursales adheridos" in p.specific_conditions
        assert p.promotion_url.endswith("/adidas2.html")


def test_on_bares_keeps_official_day_and_validity_contradictions(official):
    n = PatagoniaNormalizer()
    p, = n.normalize_many(official["bares-on"])
    assert p.source_id.endswith(":on")
    assert p.benefits[0].percentage == 30
    assert p.limits[0].amount == 10000
    assert (p.limits[0].period, p.limits[0].scope) == ("monthly", "account")
    assert methods(p) == {("mastercard", "credit", None, "card")}
    assert p.days_of_week == [] and p.applies_every_day is None
    assert p.valid_from is None and p.valid_to is None
    assert "Días contradictorios" in p.specific_conditions
    assert "VIERNES" in p.terms
    assert "Sábados" in official["bares-on"]["detail"]["summary_text"]


@pytest.mark.parametrize("text,online,physical", [
    ("Más información en https://ejemplo.com; comercio adherido", None, None),
    ("No válido para venta online. Válida en locales físicos", False, True),
    ("No válida en locales físicos. Promoción válida en tienda online", True, False),
    ("No aplica en portales de pago online excepto MODO", None, None),
    ("Promoción válida en locales y tienda online", True, True),
    ("Promoción válida en tienda online. No aplica para venta online", None, None),
])
def test_channels_require_eligibility_clauses(text, online, physical):
    n = PatagoniaNormalizer()
    assert n._detect_online(text) is online
    assert n._detect_physical(text) is physical


def test_payment_eligibility_does_not_mix_unrelated_clauses():
    n = PatagoniaNormalizer()
    text = "Válida abonando con tarjetas Visa de crédito Banco Patagonia mediante MODO QR. No aplica para tarjetas Mastercard de débito. Más información Apple Pay."
    rows = n._extract_payment_methods(text, ["Visa", "Mastercard", "Apple Pay"])
    assert {(m.network, m.card_type, m.wallet, m.payment_rail) for m in rows} == {("visa", "credit", "MODO", "qr")}


def test_financial_rates_examples_and_excluded_days_are_not_benefits():
    n = PatagoniaNormalizer()
    assert n._extract_discount("TNA: 99%. Ejemplo: 40% de descuento. Recibirá un 15% de descuento.") == 15
    assert n._extract_discount("CFT 42%. Tasa nominal anual 80%.") is None
    assert n._extract_days("Responsabilidad. No aplica los sábados. Todos los jueves") == ["thursday"]
    assert n._parse_amount("15.000,50") == Decimal("15000.50")


def load_official(slug):
    path = Path(__file__).parents[1] / f"fixtures/patagonia/{slug}_20261019.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_havanna_exclusive_wallets_override_reimbursement_and_generic_exceptions():
    row, = PatagoniaNormalizer().normalize_many(load_official("havanna"))
    assert methods(row) == {("visa", "credit", "Google Pay", "nfc"), ("visa", "credit", "Apple Pay", "nfc")}
    assert row.benefits[0].percentage == 30
    assert row.limits[0].amount == 20000


def test_exclusive_wallets_do_not_expand_to_other_cards_from_legal_boilerplate():
    text = "Abonando exclusivamente con Google Pay con tarjeta Visa de crédito recibirá un 20% de descuento. Los reintegros correspondientes con tarjetas de crédito Mastercard se acreditarán en resumen. No aplica a billeteras virtuales a excepción de MODO y Google Pay. Exclusivo NFC"
    rows = PatagoniaNormalizer()._extract_payment_methods(text, ["Mastercard", "MODO"])
    assert {(m.network, m.card_type, m.wallet, m.payment_rail) for m in rows} == {("visa", "credit", "Google Pay", "nfc")}


def test_almundo_independent_discount_and_financing_scopes():
    raw = load_official("almundo-hoteles")
    rows = PatagoniaNormalizer().normalize_many(raw)
    assert len(rows) == 2
    discount, financing = rows
    assert discount.source_id.endswith(":discount")
    assert financing.source_id.endswith(":installments")
    assert discount.promotion_group_id == financing.promotion_group_id == raw["source_id"]
    assert [(b.type, b.percentage) for b in discount.benefits] == [("discount", Decimal("10"))]
    assert {(l.type, l.amount, l.quantity) for l in discount.limits} == {("monetary_cap", Decimal("200000"), None), ("stock", None, 30)}
    for token in ("HTLPATAGONIABRC", "ACTPATAGONIABRC", "BARILOCHE"):
        assert token in discount.specific_conditions
        assert token in discount.benefits[0].description
        assert token not in financing.specific_conditions
    assert [(b.type, b.installment_options, b.interest_free) for b in financing.benefits] == [("installments", [12], True)]
    assert financing.limits == []
    assert discount.payment_methods == []
    assert {m.network for m in financing.payment_methods} == {"visa", "mastercard", "american_express"}
    assert discount.terms == financing.terms
    assert "STOCK DE 30 UNIDADES" in financing.terms


@pytest.mark.parametrize("store", ["ahorrosybeneficios", "on"])
def test_decathlon_financing_does_not_gain_debit_from_residual_fragment(store):
    raw = load_official(store + "_decathlon-octubre")
    row, = PatagoniaNormalizer().normalize_many(raw)
    assert [(b.type, b.installment_options, b.interest_free) for b in row.benefits] == [("installments", [6], True)]
    assert {m.card_type for m in row.payment_methods} == {"credit"}
    assert {m.network for m in row.payment_methods} == {"visa", "mastercard", "american_express"}
    assert row.days_of_week == ["friday", "saturday"]
    assert "PARA COMPRAS CON TARJETAS DE DÉBITO." in row.terms


def test_settlement_cannot_create_payment_eligibility_without_a_positive_offer():
    n = PatagoniaNormalizer()
    text = "Para compras con tarjetas de débito. Los reintegros correspondientes a compras con tarjetas de crédito Visa se visualizarán en el resumen."
    assert n._extract_payment_methods(text, ["Visa Débito", "Visa"]) == []


@pytest.mark.parametrize("slug,percentage,coupon", [("educacion-it", 50, "BENEFICIO_ON"), ("cui-idiomas", 15, "PATAGONIA")])
def test_education_cart_discount_coupon_account_and_single_use(slug, percentage, coupon):
    row, = PatagoniaNormalizer().normalize_many(load_official("on_" + slug))
    assert [(b.type, b.percentage) for b in row.benefits] == [("discount", Decimal(percentage))]
    assert [(limit.type, limit.quantity, limit.period) for limit in row.limits] == [("usage_count", 1, "promotion")]
    assert coupon in row.specific_conditions
    assert "CUENTA ABIERTA Y ACTIVA" in row.specific_conditions
    assert "PREVIO AL PAGO" in row.specific_conditions
    assert "ÚNICA VEZ" in row.specific_conditions
    assert row.online is True
    assert row.physical is None
    if slug == "cui-idiomas":
        assert "PRECIO CORPORATE" in row.specific_conditions
    assert "SIN TOPE DE REINTEGRO" in row.terms


def test_changomas_presentation_headers_do_not_erase_matching_segment_benefits():
    raw = load_official("ahorrosybeneficios_changomas3")
    extra = load_official("plus_changomas3")
    raw["storefront_details"] = [{k: extra[k] for k in ("catalog", "detail", "scraped_at")}]
    n = PatagoniaNormalizer()
    assert n._storefront_conflicts(raw) == []
    rows = n.normalize_many(raw)
    assert [p.benefits[0].percentage for p in rows] == [15, 30]
    assert [p.limits[0].amount for p in rows] == [10000, 20000]
    for row in rows:
        assert (row.limits[0].period, row.limits[0].scope) == ("monthly", "account")
        assert row.days_of_week == ["saturday"]
        assert row.payment_methods and {m.card_type for m in row.payment_methods} == {"credit"}
        assert row.valid_from is None and row.valid_to is None
        assert "Vigencias contradictorias" in row.specific_conditions
        assert "Patagonia Clásica Y Plus" in row.terms
        assert "Patagonia Plus" in row.terms


def test_commercial_text_is_not_removed_as_a_presentation_header():
    from scraping.sources.patagonia.text import strip_legal_headers
    text = "Patagonia Plus ofrece un 20% de descuento en locales."
    assert strip_legal_headers(text) == text


def test_official_salary_headers_keep_tiers_and_do_not_create_false_conflicts():
    raw = load_official("carrefour-plan-sueldo")
    n = PatagoniaNormalizer()
    assert n._storefront_conflicts(raw) == []
    rows = n.normalize_many(raw)
    assert [p.benefits[0].percentage for p in rows] == [20, 25, 35]
    assert [p.limits[0].amount for p in rows] == [15000, 20000, 25000]
    assert all("salary" in row.specific_conditions for row in rows)
    assert "(Exclusivo Plan Sueldo)" in rows[0].terms


def test_header_salary_restriction_is_not_erased_as_presentation():
    raw = load_official("carrefour-plan-sueldo")
    extra = raw["storefront_details"][0]["detail"]
    extra["main_text"] = extra["main_text"].replace("(Exclusivo Plan Sueldo)", "")
    if extra.get("description_text"):
        extra["description_text"] = extra["description_text"].replace("(Exclusivo Plan Sueldo)", "")
    assert PatagoniaNormalizer()._storefront_conflicts(raw)


def test_agricola_master_alias_preserves_complete_credit_alternatives():
    raw = load_official("la-agricola-regional-supermercados-regionales")
    rows = PatagoniaNormalizer().normalize_many(raw)
    assert [row.benefits[0].percentage for row in rows] == [15, 20, 30]
    assert [row.limits[0].amount for row in rows] == [10000, 10000, 15000]
    for row in rows:
        assert {m.network for m in row.payment_methods} == {"visa", "mastercard", "american_express"}
        assert {m.card_type for m in row.payment_methods} == {"credit"}
        assert ("mastercard", "credit", None, "card") in methods(row)
        assert {m.wallet for m in row.payment_methods if m.network == "mastercard"} == {None, "MODO", "Google Pay", "Apple Pay"}
        assert (row.limits[0].period, row.limits[0].scope) == ("monthly", "account")
        assert row.valid_from is None and row.valid_to is None
        assert "MÁSTER" in row.terms
        assert "Vigencias contradictorias" in row.specific_conditions


def test_master_alias_is_not_inferred_from_marketing_or_images():
    assert PatagoniaNormalizer()._extract_payment_methods("Master en programación. Más información y tarjetas disponibles.", ["Máster", "Mastercard"]) == []


@pytest.mark.parametrize("slug", ["filarmonica-de-berlin-teatro-colon", "ciclo-grandes-interpretes-teatro-colon-grigorian"])
def test_colon_network_membership_conditions_without_invented_card_type_or_stock(slug):
    raw = load_official(slug)
    row, = PatagoniaNormalizer().normalize_many(raw)
    assert len(row.benefits) == 1 and row.benefits[0].type == "other"
    assert "2x1" in row.benefits[0].description
    assert methods(row) == {("mastercard", None, None, None)}
    assert row.payment_methods[0].issuer is None
    for token in ("Black", "World Legend", "Priceless.com", "Argentina"):
        assert token in row.specific_conditions
    assert not any(limit.type == "stock" for limit in row.limits)
    original_legal = raw["detail"].get("description_text") or raw["detail"]["main_text"].split("Términos y Condiciones", 1)[1].split("Available stores are loading", 1)[0].strip()
    assert original_legal in row.terms
    if slug.startswith("filarmonica"):
        assert "al menos 2 semanas" in row.specific_conditions
        assert "34 personas" in row.specific_conditions
        assert "40 asientos premium" in row.specific_conditions
        assert "World Legend a nivel global" in row.specific_conditions
    else:
        assert "2 semanas" not in row.specific_conditions
        for token in ("Uruguay", "14 butacas", "6 personas", "no está incluido", "formato digital", "Juan Diego Flórez", "Matthias Goerne", "20 lugares por fecha"):
            assert token in row.specific_conditions


def test_grigorian_same_day_spellings_do_not_hide_metadata_date_conflict():
    raw = load_official("ciclo-grandes-interpretes-teatro-colon-grigorian")
    n = PatagoniaNormalizer()
    row, = n.normalize_many(raw)
    assert "08/12/2026" in raw["detail"]["summary_text"]
    assert "8/12/2026" in raw["detail"]["summary_text"]
    assert row.valid_from is None and row.valid_to is None
    assert "Vigencias contradictorias" in row.specific_conditions
    assert any("Vigencias contradictorias" in reason for reason in n.review_issues(raw))


@pytest.mark.parametrize("text,expected_parts", [("MARTES\n08/12/2026\nEl martes 8/12/2026", (2026, 12, 8)), ("VIERNES\n09-01-2026\nEl viernes 9.1.2026", (2026, 1, 9))])
def test_single_day_is_deduplicated_by_date_instead_of_spelling(text, expected_parts):
    from datetime import date
    n = PatagoniaNormalizer()
    expected = date(*expected_parts)
    assert n._extract_validity(text, "2026-10-19T18:00:00+00:00") == (expected, expected)


def test_canonical_single_day_matches_same_metadata_date():
    from datetime import date
    n = PatagoniaNormalizer()
    assert n._extract_validity("08/12/2026\n8/12/2026", "2026-10-19T18:00:00+00:00", main_text="VIGENCIA DESDE\n8 dic. 2026\nVIGENCIA HASTA\n08 dic. 2026") == (date(2026, 12, 8), date(2026, 12, 8))


def test_wine_fest_ticket_maximum_family_and_verified_online_channel():
    raw = load_official("patagonia-wine-fest")
    row, = PatagoniaNormalizer().normalize_many(raw)
    assert [(b.type, b.installment_options, b.interest_free) for b in row.benefits] == [("installments", [3], True)]
    assert row.online is True
    assert row.physical is None
    assert "WWW.TUENTRADA.COM" in row.specific_conditions
    assert "CONSUMOS DE TIPO FAMILIAR" in row.specific_conditions
    assert "4 (CUATRO) TICKETS POR PERSONA" in row.specific_conditions
    limit, = row.limits
    assert (limit.type, limit.quantity, limit.scope) == ("other", 4, "person")
    assert limit.amount is None and limit.currency is None and limit.period is None
    assert "TICKETS POR PERSONA" in limit.description
    assert {m.network for m in row.payment_methods} == {"visa", "mastercard"}
    assert {m.card_type for m in row.payment_methods} == {"credit"}


def test_ticket_limit_does_not_conflate_stock_uses_or_monetary_caps():
    n = PatagoniaNormalizer()
    assert n._extract_ticket_limits("Stock de 20 tickets. Una sola vez por persona. Tope de reintegro $5000 por persona.") == []
    limit, = n._extract_ticket_limits("Máximo de 7 entradas por cuenta.")
    assert (limit.type, limit.quantity, limit.scope) == ("other", 7, "account")
    assert limit.amount is None and limit.currency is None and limit.period is None
    assert n._detect_online("Más información de entradas en www.tuentrada.com") is None
    assert n._detect_online("Las entradas no son válidas para venta online.") is False
