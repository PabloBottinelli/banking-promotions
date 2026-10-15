from datetime import date
from decimal import Decimal

import pytest

from normalization.sources.banco_del_sol import BancoDelSolNormalizer


def raw(slug, title, terms, summary=""):
    return {"source_id": slug, "scraped_at": "2026-10-14T12:00:00+00:00",
            "promotion_url": "https://www.bancodelsol.com/beneficios/" + slug,
            "detail": {"title": title, "summary": summary, "terms": terms, "category": "Comercios", "regions": []}}


def test_simultaneous_cashback_and_financing_with_cap():
    legal = ("Promoción válida para clientes registrados que realicen compras en Freekick utilizando la tarjeta de crédito "
             "MASTERCARD emitida por el Banco. Válida todos los días, desde las 00:00 hs del 13/10/2026, "
             "hasta las 23:59 hs del 18/10/2026. Aplicable exclusivamente en la tienda online de Freekick. "
             "El beneficio consiste en abonar las compras en 3 (tres) y hasta 9 (nueve) cuotas sin interés y, "
             "adicionalmente, en un reintegro del 20% sobre el monto abonado, con un tope de reintegro de $25.000 "
             "por cliente por promoción. Promoción válida únicamente sobre productos seleccionados, sujeto a stock.")
    item = BancoDelSolNormalizer().normalize_many(raw("freekick", "Freekick", legal))[0]
    assert [(benefit.type, benefit.percentage) for benefit in item.benefits] == [
        ("cashback", Decimal("20")), ("installments", None)]
    assert item.limits[0].amount == Decimal("25000") and item.limits[0].period == "promotion"
    assert item.payment_methods[0].network == "Mastercard"
    assert item.valid_from == date(2026, 10, 13) and item.valid_to == date(2026, 10, 18)
    assert item.applies_every_day is True and item.days_of_week == []
    assert item.online is True and item.physical is False
    assert "productos seleccionados" in item.specific_conditions


def test_weekday_unknown_cap_and_no_invented_value():
    legal = ("Promoción válida los viernes, desde las 00:00 hs del 01/07/2026 hasta las 23:59 hs del 30/11/2026. "
             "Promoción válida para compras con tarjeta de débito VISA emitida por el Banco. "
             "El beneficio consiste en un reintegro del 30% con un tope de \"\" por cliente por mes calendario. "
             "No aplica para los sábados.")
    item = BancoDelSolNormalizer().normalize_many(raw("local", "Local", legal))[0]
    assert item.days_of_week == ["friday"] and item.applies_every_day is None
    assert item.limits == []
    assert item.payment_methods[0].card_type == "debit"


def test_empty_legal_or_unparsed_benefit_is_error():
    normalizer = BancoDelSolNormalizer()
    with pytest.raises(ValueError):
        normalizer.normalize_many(raw("x", "X", ""))
    with pytest.raises(ValueError):
        normalizer.normalize_many(raw("x", "X", "No hay beneficio estructurable."))


def test_elite_segment_rates_and_shared_rail_cap():
    terms = ("Promoción válida para clientes de los segmentos Elite o Elite Plus que realicen consumos presenciales en Botanicafé "
             "utilizando la tarjeta de débito VISA emitida por el Banco o mediante pago con código QR desde la aplicación de BDS. "
             "Válida todos los días, desde las 00:00 hs del 15/09/2026 hasta las 23:59 hs del 30/11/2026. "
             "Segmento Elite: reintegro del 10% con un tope de $8.000 por cliente por mes calendario. "
             "Segmento Elite Plus: reintegro del 15% con un tope de $10.000 por cliente por mes calendario. "
             "El tope es único y mensual por cliente y se computará conjuntamente para tarjeta de débito VISA y pago con código QR.")
    normalizer = BancoDelSolNormalizer()
    elite = normalizer.normalize_many(raw("botanicafe-elite", "Botanicafé", terms))[0]
    plus = normalizer.normalize_many(raw("botanicafe-eliteplus", "Botanicafé", terms))[0]
    assert elite.benefits[0].percentage == Decimal("10")
    assert plus.benefits[0].percentage == Decimal("15")
    assert elite.limits[0].amount == Decimal("8000")
    assert plus.limits[0].amount == Decimal("10000")
    assert elite.promotion_group_id == plus.promotion_group_id == "botanicafe"
    assert {p.payment_rail for p in elite.payment_methods} == {"card", "qr"}
    assert elite.physical is True and elite.online is False


def test_indefinite_usd_interest_is_not_a_cashback_cap():
    terms = ("El presente beneficio está vigente en Argentina a partir del 01/04/2026 y hasta tanto sea modificado. "
             "El saldo de la Caja de Ahorros podrá devengar intereses si la TNA supera 0%. "
             "El tope máximo para el cálculo de intereses es de USD 30.000.")
    item_raw = raw("caja-de-ahorro-en-usd-remunerada", "Caja de Ahorro en USD Remunerada", terms)
    item_raw["detail"].update(valid_from_label="01/04/2026", valid_to_label="31/12/2026")
    item = BancoDelSolNormalizer().normalize_many(item_raw)[0]
    assert item.valid_from == date(2026, 4, 1) and item.valid_to is None
    assert item.benefits[0].type == "other" and item.benefits[0].reward_currency == "USD"
    assert item.limits == []
    assert "USD 30.000" in item.specific_conditions


def test_debit_cashback_and_credit_financing_do_not_stack():
    terms = ("Promoción válida para compras en El Pulqui y La Tostadense. Válida todos los días, desde las 00:00 hs del "
             "15/05/2026 hasta las 23:59 hs del 31/12/2026. Quienes abonen con tarjeta de débito VISA emitida por el Banco "
             "accederán a un reintegro del 20% con un tope de $20.000 por cliente por mes calendario. "
             "Ejemplo: compra de $100.000. Quienes abonen con tarjeta de crédito Mastercard emitida por el Banco "
             "accederán a la posibilidad de financiar sus compras en 6 (seis) y hasta 12 (doce) cuotas sin interés. "
             "Los beneficios de reintegro y financiación no se aplican en una misma transacción.")
    variants = BancoDelSolNormalizer().normalize_many(raw("el-pulqui-la-tostadense", "El Pulqui - La Tostadense", terms))
    assert len(variants) == 2
    assert {v.source_id for v in variants} == {"el-pulqui-la-tostadense:debit-cashback", "el-pulqui-la-tostadense:credit-installments"}
    assert variants[0].benefits[0].type == "cashback" and variants[0].payment_methods[0].card_type == "debit"
    assert variants[1].benefits[0].type == "installments" and variants[1].payment_methods[0].card_type == "credit"
    assert variants[1].limits == []


def test_legal_date_precedes_conflicting_marketing_label():
    terms = ("Promoción válida para compras con tarjeta de débito VISA emitida por el Banco. "
             "Válida los jueves, desde las 00:00 hs del 01/10/2026 hasta las 23:59 hs del 30/11/2026. "
             "El beneficio consiste en un reintegro del 20% con un tope de $15.000 por cliente por mes calendario.")
    item_raw = raw("local", "Local", terms)
    item_raw["detail"]["valid_from_label"] = "10/1/2026"
    item = BancoDelSolNormalizer().normalize_many(item_raw)[0]
    assert item.valid_from == date(2026, 10, 1)
    assert "fecha de inicio de la ficha difiere" in item.specific_conditions


def test_elite_plus_requirement_comes_from_legal_when_slug_has_no_segment():
    terms = ("Promoción válida para clientes de BDS registrados en la aplicación del Banco, pertenecientes al segmento Elite Plus, "
             "que realicen consumos presenciales en Bar and Co utilizando la tarjeta de débito VISA emitida por el Banco "
             "o mediante pago con código QR desde la aplicación de BDS. Válida todos los días, desde las 00:00 hs del "
             "15/09/2026 hasta las 23:59 hs del 30/11/2026. Segmento Elite Plus: reintegro del 20% con un tope de "
             "$15.000 por cliente por mes calendario.")
    item = BancoDelSolNormalizer().normalize_many(raw("bar-and-co", "Bar & Co", terms))[0]
    assert "Exclusivo para clientes del segmento Elite Plus" in item.specific_conditions
    assert item.benefits[0].percentage == Decimal("20")


@pytest.mark.parametrize("slug,title", [
    ("le-pain-quotidien", "Le Pain Quotidien"),
    ("cervelar-ep", "Cervelar"),
    ("soy-tu-farmacia", "Soy Tu Farmacia"),
])
def test_official_adherent_local_notice_and_url(slug, title):
    terms = ("Promoción válida para clientes pertenecientes al segmento Elite Plus que realicen consumos presenciales "
             f"en locales de {title} adheridos. La nómina de locales adheridos podrá consultarse en "
             f"www.bancodelsol.com/beneficios/{slug}. Válida todos los días, desde las 00:00 hs del 15/09/2026 "
             "hasta las 23:59 hs del 30/11/2026. Segmento Elite Plus: reintegro del 20% con un tope de $15.000 "
             "por cliente por mes calendario.")
    item = BancoDelSolNormalizer().normalize_many(raw(slug, title, terms))[0]
    assert item.requires_merchant_verification is True
    assert item.promotion_url == f"https://www.bancodelsol.com/beneficios/{slug}"
    assert "Solo locales adheridos" in item.specific_conditions


def test_jbl_keeps_legal_merchant_and_payment_conflict_visible():
    terms = ("Promoción válida para clientes que realicen compras en Samsung, Samshop, Quint y 9z en Argentina, "
             "en 2 (dos) y hasta 24 (veinticuatro) cuotas sin interés utilizando la tarjeta de crédito MASTERCARD "
             "emitida por BDS. Válida todos los días, desde las 00:00 hs del 03/06/2026 hasta las 23:59 hs del "
             "31/12/2026. Aplicable exclusivamente en sucursales y tiendas online de Samsung, Samshop, Quint y 9z.")
    item = BancoDelSolNormalizer().normalize_many(raw("jbl", "JBL", terms, "Hasta 24 cuotas sin interés"))[0]
    assert item.merchant == "Samsung, Samshop, Quint y 9z (según términos legales)"
    assert item.payment_methods[0].issuer == "Banco del Sol"
    assert item.payment_methods[0].network == "Mastercard"
    assert item.payment_methods[0].card_type == "credit"
    assert "ficha anuncia JBL" in item.specific_conditions


def test_sancor_insurance_exclusions_are_user_facing_and_every_day_label_counts():
    terms = ("Promoción válida para clientes registrados de BDS. El beneficio será del 25% de reintegro "
             "en el pago de las primeras 4 (cuatro) cuotas mensuales consecutivas, con un tope de reintegro "
             "de $20.000 por mes. Quedan excluidos aquellos clientes que se hayan favorecido, con anterioridad, "
             "de esta promoción, independientemente del medio de pago utilizado. La presente Promoción no "
             "incluye: Prevención Salud, Prevención ART ni Prevención Retiro.")
    item_raw = raw("sancor-seguros", "Sancor Seguros", terms)
    item_raw["detail"]["days"] = ["Todos los días"]
    item = BancoDelSolNormalizer().normalize_many(item_raw)[0]
    assert item.applies_every_day is True and item.days_of_week == []
    assert "ya recibieron esta promoción" in item.specific_conditions
    for product in ("Prevención Salud", "Prevención ART", "Prevención Retiro"):
        assert product in item.specific_conditions
    assert item.terms == terms


def test_card_variants_explain_additional_cards_and_existing_card_eligibility():
    terms = ("Promoción válida para tarjetas de crédito Mastercard emitidas por BDS. Quedan excluidas de la "
             "Promoción las tarjetas adicionales, empresariales o cualquier otra tarjeta distinta de las "
             "expresamente indicadas. Las Tarjetas Nuevas accederán a una bonificación del 100% del cargo "
             "de mantenimiento mensual durante los primeros tres (3) meses desde el alta; a partir del cuarto "
             "mes en un 100% si los consumos son superiores a $600.000; en un 50% si los consumos son "
             "superiores a $300.000 e inferiores o iguales a $600.000. Para el caso de Tarjetas Existentes, "
             "el beneficio de bonificación del cargo de mantenimiento será aplicable únicamente si al inicio "
             "del Plazo de Vigencia, el cliente no se encontrara gozando de un beneficio promocional vigente "
             "de igual naturaleza, o si dicho beneficio anterior se encontrare vencido. El plazo de "
             "bonificación se computará a partir del inicio del Plazo de Vigencia y se aplicarán las mismas "
             "condiciones para las Tarjetas Nuevas a partir del cuarto mes. Bonificación del 100 (cien por "
             "ciento) del cargo anual de renovación durante los primeros doce meses con consumos anuales "
             "superiores a $1.800.000.")
    item_raw = raw("tarjeta-de-credito", "Tarjeta de crédito", terms)
    item_raw["detail"]["days"] = ["Todos los días"]
    variants = BancoDelSolNormalizer().normalize_many(item_raw)
    assert len(variants) == 4
    assert len({variant.source_id for variant in variants}) == 4
    for variant in variants:
        conditions = variant.specific_conditions
        assert "tarjetas adicionales, empresariales" in conditions
        assert "bonificación similar vigente" in conditions
        assert "desde el inicio de la promoción" in conditions
        assert variant.applies_every_day is True
    assert "Tarjetas nuevas" in variants[0].specific_conditions


def test_every_day_label_does_not_turn_missing_or_restricted_days_into_every_day():
    terms = "Promoción válida para clientes registrados. El beneficio consiste en un reintegro del 10%."
    labeled = raw("local", "Local", terms)
    labeled["detail"]["days"] = ["Todos los días"]
    assert BancoDelSolNormalizer().normalize_many(labeled)[0].applies_every_day is True
    assert BancoDelSolNormalizer().normalize_many(raw("local", "Local", terms))[0].applies_every_day is None
    restricted = raw("local", "Local", "Promoción válida los viernes. El beneficio consiste en un reintegro del 10%.")
    restricted["detail"]["days"] = ["Todos los días"]
    item = BancoDelSolNormalizer().normalize_many(restricted)[0]
    assert item.days_of_week == ["friday"] and item.applies_every_day is None


@pytest.mark.parametrize("slug,display_days,legal_day,expected_day,display_rate,legal_rate,display_cap,legal_cap", [
    ("zapateria-sergio-68mky", ["Miércoles"], "viernes", "friday", 20, 20, "15.000", "15.000"),
    ("de-punta-libreria", ["Sábado"], "viernes", "friday", 20, 20, "15.000", "15.000"),
    ("los-sunchales-y-sunbar", ["Todos los días"], "sábados", "saturday", 15, 20, "10.000", "15.000"),
])
def test_official_card_and_legal_discrepancies_are_actionable(
    slug, display_days, legal_day, expected_day, display_rate, legal_rate, display_cap, legal_cap,
):
    terms = (f"Promoción válida para clientes Elite Plus que realicen consumos presenciales en el local. "
             f"Válida los {legal_day}, desde las 00:00 hs del 01/10/2026 hasta las 23:59 hs del 30/11/2026. "
             f"Segmento Elite Plus: reintegro del {legal_rate}% con un tope de ${legal_cap} por cliente por mes calendario.")
    item_raw = raw(slug, slug, terms, f"{display_rate}% de reintegro")
    item_raw["detail"]["days"] = display_days
    item_raw["detail"]["description"] = f"Aprovechá {display_rate}% de reintegro con tope ${display_cap} por mes"
    item = BancoDelSolNormalizer().normalize_many(item_raw)[0]
    assert item.days_of_week == [expected_day] and item.applies_every_day is None
    assert item.benefits[0].percentage == Decimal(legal_rate)
    assert item.limits[0].amount == Decimal(legal_cap.replace(".", ""))
    assert display_days[0] in item.specific_conditions
    assert legal_day in item.specific_conditions
    if display_rate != legal_rate:
        assert f"{display_rate}%" in item.specific_conditions
        assert f"{legal_rate}%" in item.specific_conditions
    if display_cap != legal_cap:
        assert f"${display_cap}" in item.specific_conditions
        assert f"${legal_cap}" in item.specific_conditions
    assert item.terms == terms
