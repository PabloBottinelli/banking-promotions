"""Official detail excerpts captured 2026-10-15; no dependency on data/."""
import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.sources.personal_pay import PersonalPayNormalizer, weekdays

FIXTURE = Path(__file__).parents[1] / "fixtures/personal_pay/official_examples.json"


def raw(identity):
    return next(x for x in json.loads(FIXTURE.read_text(encoding="utf-8")) if x["source_id"] == str(identity))


def rows(identity):
    return PersonalPayNormalizer().normalize_many(raw(identity))


def test_personal_flow_all_four_legal_levels_and_stable_ids():
    actual = rows(9232)
    assert [p.source_id for p in actual] == ["9232:lvl01", "9232:lvl02", "9232:lvl03", "9232:lvl04"]
    assert [p.benefits[0].percentage for p in actual] == list(map(Decimal, [10, 15, 20, 25]))
    assert [next(l.amount for l in p.limits if l.type == "monetary_cap") for p in actual] == list(map(Decimal, [750, 2000, 3500, 7000]))
    original = raw(9232)
    changed = copy.deepcopy(original)
    changed["detail"]["levels"].reverse()
    changed["detail"]["title"] = "Changed marketing title"
    assert {p.source_id for p in PersonalPayNormalizer().normalize_many(changed)} == {p.source_id for p in actual}
    assert all(p.promotion_group_id == "9232" and "Exclusivo Nivel" in p.specific_conditions for p in actual)


def test_first_recharge_separates_balance_and_keeps_components_and_extra_credit():
    weekly, first = rows(9206)
    assert weekly.source_id == "9206:weekly"
    assert first.source_id == "9206:first-balance"
    assert [b.percentage for b in first.benefits if b.type == "cashback"] == [Decimal(20), Decimal(80)]
    assert [b.percentage for b in weekly.benefits if b.type == "cashback"] == [Decimal(20)]
    assert first.benefits[-1].type == "other" and first.benefits[-1].percentage == Decimal(20)
    assert all(m.payment_rail == "account_balance" for m in first.payment_methods)
    assert {l.amount for l in first.limits if l.type == "monetary_cap"} == {Decimal(2000), Decimal(8000), Decimal(10000)}
    assert next(l.amount for l in weekly.limits if l.type == "minimum_purchase") == Decimal(500)


@pytest.mark.parametrize("identity", [9361, 9473])
def test_binding_sin_tope_overrides_display_dummy_cap(identity):
    item = rows(identity)[0]
    assert not any(l.type == "monetary_cap" for l in item.limits)
    assert "SIN TOPE" in item.terms.upper()
    if identity == 9473:
        assert any(l.type == "usage_count" and l.quantity == 1 and l.period == "promotion" for l in item.limits)
    else:
        assert any(l.type == "minimum_purchase" and l.amount == Decimal(20000) for l in item.limits)
        assert any(l.type == "usage_count" and l.quantity == 1 for l in item.limits)


def test_usd_fixed_discount_and_minimum_are_not_ars_or_percentages():
    item = rows(9365)[0]
    assert item.benefits[0].amount == Decimal(10) and item.benefits[0].currency == "USD"
    assert item.benefits[0].percentage is None
    assert any(l.type == "minimum_purchase" and l.amount == Decimal(90) and l.currency == "USD" for l in item.limits)


def test_ypf_payment_is_app_ypf_visa_card_not_online():
    item = rows(9500)[0]
    assert item.days_of_week == ["tuesday"]
    assert item.online is False and item.physical is True
    assert [(m.wallet, m.network, m.payment_rail) for m in item.payment_methods] == [("YPF", "Visa", "card")]
    assert {(l.amount, l.period) for l in item.limits if l.type == "monetary_cap"} == {(Decimal(5000), "transaction"), (Decimal(10000), "monthly")}
    assert any(l.type == "usage_count" and l.quantity == 2 and l.period == "monthly" for l in item.limits)


def test_gifts_multi_buy_and_free_shipping_all_preserved():
    assert rows(3113)[0].benefits[0].type == "gift"
    assert rows(352)[0].benefits[0].type == "other" and "2x1" in rows(352)[0].benefits[0].description
    assert [b.type for b in rows(8942)[0].benefits] == ["discount", "free_service"]
    # Sony explicitly allows other currently-active commercial terms, without
    # promising their availability, a number of installments, or free shipping.
    sony = rows(9426)[0]
    assert [b.type for b in sony.benefits] == ["discount"]
    assert "cuotas sin interés" in sony.specific_conditions
    assert not any(m.payment_rail == "qr" for m in sony.payment_methods)


def test_stock_is_quantity_and_cap_is_explicit_source_field_when_legal_silent():
    item = rows(9396)[0]
    assert any(l.type == "stock" and l.quantity == 800 and l.amount is None for l in item.limits)
    assert any(l.type == "monetary_cap" and l.amount == Decimal(20000) and l.period is None for l in item.limits)


def test_legal_dates_override_inconsistent_api_start_and_two_digit_dates():
    assert rows(9132)[0].valid_from == date(2024, 12, 4)
    assert rows(9403)[0].valid_from == date(2026, 2, 26)
    assert rows(9415)[0].valid_from == date(2026, 5, 1)
    assert rows(9415)[0].valid_to == date(2026, 10, 31)


def test_terms_original_and_merchant_lookup_and_json_decimals():
    original = raw(9132)
    item = rows(9132)[0]
    assert item.terms == original["detail"]["legal"]
    assert item.requires_merchant_verification and item.promotion_url.startswith("https://www.personal.com.ar/pay/beneficios")
    assert "Consultá" in item.specific_conditions
    assert item.model_dump(mode="json")["benefits"][0]["percentage"] == "10"
    assert "discount_percentage" not in item.model_dump(mode="json")
    assert any(l.type == "usage_count" and l.quantity == 1 and l.period == "weekly" for l in item.limits)


@pytest.mark.parametrize("values,expected,every", [
    ([], [], None), (["Todos los días"], [], True), (["Lu", "Ma", "Ju"], ["monday", "tuesday", "thursday"], None),
    (["Domingo a Jueves"], ["monday", "tuesday", "wednesday", "thursday", "sunday"], None),
])
def test_positive_weekday_tokens(values, expected, every):
    assert weekdays(values) == (expected, every)


def test_unknown_dates_and_channels_and_fail_closed_unknown_benefit():
    item = raw(9132)
    item["detail"].update(legal="Beneficio sujeto a responsabilidad del comercio.", startDate=None, dueDate=None, days=[])
    row = PersonalPayNormalizer().normalize_many(item)[0]
    assert row.valid_from is None and row.valid_to is None
    assert row.online is None and row.physical is None and row.applies_every_day is None
    assert row.days_of_week == []
    item["detail"]["discounts"] = "unparseable"
    with pytest.raises(ValueError, match="Unparsed"):
        PersonalPayNormalizer().normalize_many(item)


def test_changed_source_economics_are_parsed_without_fallback():
    item = raw(9132)
    item["detail"]["discounts"] = "17% reintegro"
    item["detail"]["legal"] = "Reintegro 17% con tope de $4.567 por transacción."
    row = PersonalPayNormalizer().normalize_many(item)[0]
    assert row.benefits[0].percentage == Decimal(17)
    assert row.limits[0].amount == Decimal(4567)


def test_qa001_reintegro_plus_every_conditional_level_and_no_automatic_stack():
    actual = rows("reintegro-plus")
    assert [r.source_id for r in actual] == ["reintegro-plus:lvl02", "reintegro-plus:lvl03", "reintegro-plus:lvl04"]
    assert [r.benefits[0].percentage for r in actual] == [Decimal(5), Decimal(10), Decimal(15)]
    for row in actual:
        assert row.valid_to == date(2026, 10, 31)
        assert len(row.benefits) == 1
        assert "28/02/2026" in row.specific_conditions
        assert "SERVICIO MOVIL" in row.specific_conditions and "SERVICIO HOGAR" in row.specific_conditions
        assert "$500.000" in row.specific_conditions
        assert "No se presume acumulación" in row.specific_conditions
        assert row.payment_methods == [] and row.applies_every_day is None
        assert not any(l.type == "monetary_cap" for l in row.limits)  # invoice ceiling is not refund cap


def test_qa002_rappi_keeps_secondary_free_service_and_coupon_conditions():
    row = rows(9391)[0]
    assert [b.type for b in row.benefits] == ["discount", "free_service"]
    assert row.benefits[0].percentage == Decimal(90)
    assert "Chat GPT GO" in row.benefits[1].description and "30 días" in row.benefits[1].description
    assert "Cupón" in row.specific_conditions and "60 días" in row.specific_conditions


def test_qa003_exclusive_legal_visa_rejects_generic_qr_option():
    row = rows(9273)[0]
    assert [(m.network, m.payment_rail) for m in row.payment_methods] == [("Visa", "card")]


def test_qa004_coto_legal_matrix_is_not_a_cartesian_product():
    row = rows(9403)[0]
    methods = row.payment_methods
    assert all(m.network == "Visa" and m.payment_rail == "nfc" for m in methods)
    assert {m.wallet for m in methods} == {"Apple Pay", "Google Pay", "MODO Contactless", "Galicia", "Buepp", "Personal Pay"}
    assert any(m.issuer == "BANCO CORRIENTES" and m.wallet == "Google Pay" for m in methods)
    assert not any(m.issuer == "BANCO CORRIENTES" and m.wallet in ["Apple Pay", "MODO Contactless"] for m in methods)
    assert any(m.issuer == "Personal Pay" and m.wallet == "Personal Pay" for m in methods)
    assert all(m.card_type is None and "débito/prepaga" in m.raw_name for m in methods)


def test_qa004_movistar_balance_and_card_routes_are_separate_complete_options():
    row = rows(9351)[0]
    assert {(m.wallet, m.payment_rail) for m in row.payment_methods} == {("Personal Pay", "account_balance"), ("Mi Movistar", "card"), ("Tuenti", "card")}
    assert all(m.network == "Visa" and m.issuer == "Personal Pay" for m in row.payment_methods if m.payment_rail == "card")
    assert "una sola compañía" in row.specific_conditions


@pytest.mark.parametrize("identity", [9496, 8936, 9471])
def test_qa005_both_channels_for_slash_and_y_o_phrases(identity):
    row = rows(identity)[0]
    assert row.online is True and row.physical is True


def test_qa006_arcor_minimum_in_description_and_legal_cap():
    row = rows(8942)[0]
    assert any(l.type == "minimum_purchase" and l.amount == Decimal(60000) and l.currency == "ARS" and l.period == "transaction" for l in row.limits)
    assert any(l.type == "monetary_cap" and l.amount == Decimal(9000) for l in row.limits)


def test_unresolved_binding_dates_are_unknown_and_both_terms_retained():
    item = raw(9473)
    item["global_legal_conflict"] = {"note": "Inicio en conflicto 2026-06-20 frente a 2026-06-22; consultar Personal Pay."}
    row = PersonalPayNormalizer().normalize_many(item)[0]
    assert row.valid_from is None and row.valid_to == date(2026, 10, 31)
    assert "2026-06-20" in row.specific_conditions and "2026-06-22" in row.specific_conditions


@pytest.mark.parametrize("identity,expected", [(9361, (True, True)), (9212, (False, True)), (9403, (False, True)), (9500, (False, True))])
def test_qa007_exclusive_outlets_can_include_both_channels(identity, expected):
    row = rows(identity)[0]
    assert (row.online, row.physical) == expected


def test_qa008_la_reina_transaction_weekly_caps_and_first_weekly_purchase():
    row = rows(9212)[0]
    assert {(l.amount, l.period) for l in row.limits if l.type == "monetary_cap"} == {(Decimal(7000), "transaction"), (Decimal(7000), "weekly")}
    assert any(l.type == "usage_count" and l.quantity == 1 and l.period == "weekly" for l in row.limits)
    assert any(l.type == "minimum_purchase" and l.amount == Decimal(30000) for l in row.limits)


@pytest.mark.parametrize("identity", [9393, 9394, 9402])
def test_qa008_mas_vision_two_uses_per_month_per_benefit_discount(identity):
    row = rows(identity)[0]
    limits = [l for l in row.limits if l.type == "usage_count"]
    assert len(limits) == 1
    assert (limits[0].quantity, limits[0].period, limits[0].scope) == (2, "monthly", "benefit_discount")
    assert limits[0].shared_group_id is None
    assert "por beneficio y por descuento" in limits[0].description


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_qa009_flow_all_levels_keep_three_payment_routes(index):
    row = rows(9232)[index]
    assert {(m.wallet, m.payment_rail) for m in row.payment_methods} == {("Personal Pay", None), ("Mi Personal", None), ("Personal Pay", "other")}
    assert any("Débito automático" in m.raw_name for m in row.payment_methods)
    assert row.online is None


def test_qa009_recarga_both_apps_with_separate_funding_first_balance_only():
    weekly, first = rows(9206)
    assert {(m.wallet, m.payment_rail) for m in weekly.payment_methods} == {("Personal Pay", "card"), ("Personal Pay", "account_balance"), ("Mi Personal Flow", "card"), ("Mi Personal Flow", "account_balance")}
    assert {(m.wallet, m.payment_rail) for m in first.payment_methods} == {("Personal Pay", "account_balance"), ("Mi Personal Flow", "account_balance")}
    assert all(m.network is None and m.card_type is None for m in first.payment_methods)
    assert all(m.network == "Visa" and m.card_type == "prepaid" for m in weekly.payment_methods if m.payment_rail == "card")


@pytest.mark.parametrize("identity,legal,expected", [
    ("9036", "Válido para todos los días con modalidad presencial / tienda online.", (True, True)),
    ("347", "Válido para compra presencial en línea de cajas únicamente o compra online.", (True, True)),
    ("9416", "COMPRANDO EN TODAS LAS SUCURSALES DE HIPERCHANGOMAS Y CHANGOMAS DE FORMA PRESENCIAL Y A TRAVÉS DE MÁS ONLINE ÚNICAMENTE ELIGIENDO LA OPCIÓN PAGO ONLINE.", (True, True)),
    ("5067", "No válida para tienda online. Válido para todos los días con modalidad presencial o call center.", (False, True)),
    ("9463", "Válido para todos los días con modalidad exclusivamente online.", (True, False)),
    ("9345", "Válido únicamente online: https://movieclub.com.ar/personal-pay.", (True, False)),
    ("8913", "Solo válido para compras online.", (True, False)),
    ("9462", "Beneficio para sucursales adheridas y tienda online.", (True, True)),
    ("9317", "Los clientes que abonen en boletería física o tienda online obtendrán el descuento.", (True, True)),
])
def test_qa007_expanded_official_channel_phrases(identity, legal, expected):
    # Short official legal excerpts from the identified API details, 2026-10-15.
    item = raw(9132)
    item["detail"]["legal"] = legal
    row = PersonalPayNormalizer().normalize_many(item)[0]
    assert (row.online, row.physical) == expected


def test_qa008_related_daily_benefit_count_and_ticket_quantity_are_not_money():
    item = raw(9132)
    item["detail"]["legal"] = "Válido hasta 2 (dos) beneficios por usuario por día, total de entradas 4 (cuatro)."
    row = PersonalPayNormalizer().normalize_many(item)[0]
    assert any(l.type == "usage_count" and l.quantity == 2 and l.period == "daily" for l in row.limits)
    item["detail"]["legal"] = "Máximo 2 (dos) entradas por usuario."
    row = PersonalPayNormalizer().normalize_many(item)[0]
    assert any(l.type == "other" and l.quantity == 2 and l.scope == "person" and l.amount is None for l in row.limits)


@pytest.mark.parametrize("token,expected", [("10.000", 10000), ("1.000", 1000), ("15.000", 15000), ("800", 800), ("10000", 10000)])
def test_qa010_complete_stock_quantity_not_monetary_amount(token, expected):
    item = raw(9132)
    item["detail"]["legal"] = f"Promoción válida hasta agotar stock de {token} cupones."
    row = PersonalPayNormalizer().normalize_many(item)[0]
    stock = next(l for l in row.limits if l.type == "stock")
    assert stock.quantity == expected
    assert stock.amount is None and stock.currency is None
    assert stock.period == "promotion" and stock.scope == "campaign"


@pytest.mark.parametrize("identity,expected", [
    (9386, 10000), (9324, 10000), (9325, 10000), (9326, 10000), (9327, 1000),
    (9328, 10000), (9385, 10000), (9374, 10000), (9375, 15000), (9376, 15000),
    (9377, 15000), (9378, 10000), (9379, 15000), (9381, 10000), (9460, 10000),
])
def test_qa010_all_fifteen_affected_official_stock_offers(identity, expected):
    row = rows(identity)[0]
    stock = [l for l in row.limits if l.type == "stock"]
    assert len(stock) == 1 and stock[0].quantity == expected
    assert stock[0].period == "promotion" and stock[0].amount is None


def test_qa010_malformed_count_is_not_silently_truncated_or_defaulted():
    item = raw(9132)
    item["detail"]["legal"] = "Válido hasta agotar stock de 10.00 cupones."
    with pytest.raises(ValueError, match="Malformed integer quantity"):
        PersonalPayNormalizer().normalize_many(item)


@pytest.mark.parametrize("identity", [5080, 8908, 8909, 8970, 9386, 9385])
def test_qa011_legal_nfc_option_complements_incomplete_helper_list(identity):
    row = rows(identity)[0]
    assert {m.payment_rail for m in row.payment_methods} == {"qr", "card", "nfc"}
    nfc = [m for m in row.payment_methods if m.payment_rail == "nfc"]
    assert len(nfc) == 1
    assert nfc[0].issuer == "Personal Pay" and nfc[0].network == "Visa"
    assert nfc[0].wallet is None and nfc[0].card_type is None
    assert "NFC" in nfc[0].raw_name


def test_qa011_existing_helper_nfc_preserves_evidenced_app_without_duplication():
    row = rows(9324)[0]
    nfc = [m for m in row.payment_methods if m.payment_rail == "nfc"]
    assert len(nfc) == 1 and nfc[0].wallet == "Personal Pay"
    assert nfc[0].issuer == "Personal Pay" and nfc[0].network == "Visa"


def test_qa011_negative_nfc_clause_does_not_create_an_option():
    item = raw(9132)
    item["detail"]["legal"] = "Medios de pago exclusivo con tarjeta Visa Personal Pay. No válido para pagos NFC."
    row = PersonalPayNormalizer().normalize_many(item)[0]
    assert [m.payment_rail for m in row.payment_methods] == ["card"]


def test_qa011_card_type_only_when_evidenced_in_positive_nfc_clause():
    item = raw(9132)
    item["detail"]["legal"] = "Pagando con tarjeta prepaga Visa Personal Pay física o NFC."
    row = PersonalPayNormalizer().normalize_many(item)[0]
    nfc = next(m for m in row.payment_methods if m.payment_rail == "nfc")
    assert nfc.card_type == "prepaid" and nfc.wallet is None
