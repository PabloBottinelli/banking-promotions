import json
from pathlib import Path

import pytest

from normalization.sources.buepp import BueppNormalizer

FIXTURE = Path(__file__).parents[1] / "fixtures/buepp/official_examples.json"


def raw(identifier):
    return next(x for x in json.loads(FIXTURE.read_text(encoding="utf-8")) if x["source_id"] == identifier)


def normalize(identifier):
    return BueppNormalizer().normalize_many(raw(identifier))


def test_neighbors_shared_cap_and_three_actual_payment_types():
    p = normalize("13801")[0]
    assert p.benefits[0].type == "cashback"
    assert str(p.benefits[0].percentage) == "30"
    assert p.limits[0].amount == 15000
    assert p.limits[0].period == "monthly"
    assert p.limits[0].scope == "person"
    assert p.limits[0].shared_group_id == "buepp:comercios-vecinos"
    assert {x.card_type for x in p.payment_methods} == {"credit", "debit", None}
    assert all(x.wallet == "Buepp" and x.payment_rail == "qr" for x in p.payment_methods)
    assert p.requires_merchant_verification and p.physical is True and p.online is None


def test_credit_financing_does_not_apply_to_debit():
    credit,debit = normalize("13104")
    assert credit.source_id == "13104:credit"
    assert debit.source_id == "13104:non-credit"
    assert credit.promotion_group_id == debit.promotion_group_id
    assert [x.type for x in credit.benefits] == ["cashback","installments"]
    assert [x.type for x in debit.benefits] == ["cashback"]
    assert {x.network for x in credit.payment_methods} == {"Visa","Mastercard"}
    assert {x.network for x in debit.payment_methods} == {"Visa","Maestro"}
    assert credit.limits[0].shared_group_id == debit.limits[0].shared_group_id
    assert credit.days_of_week == ["friday"]


def test_legal_overrides_false_discount_marketing():
    p = normalize("13982")[0]
    assert [x.type for x in p.benefits] == ["installments"]
    assert p.benefits[0].installment_options == [6]
    assert "20%" not in p.title
    assert {x.payment_rail for x in p.payment_methods} == {"qr","card"}


@pytest.mark.parametrize("identifier,options",[("15971",[15,18]),("15975",[3,6,9,12])])
def test_installment_lists(identifier,options):
    assert normalize(identifier)[0].benefits[0].installment_options == options


def test_salary_segment_explicit_total_not_sum_of_all_percentages():
    p = normalize("15981")[0]
    assert p.benefits[0].percentage == 20 and p.limits[0].amount == 20000
    assert "90" in p.specific_conditions
    assert "10%" in p.specific_conditions


def test_nonshopping_tax_payment_and_shared_cap():
    p = normalize("15984")[0]
    assert p.scope == "other"
    assert p.limits[0].shared_group_id == "buepp:agip"
    assert all(x.card_type is None and x.payment_rail == "qr" for x in p.payment_methods)
    assert "NFC" in p.specific_conditions
    assert "AMBOS IMPUESTOS" in p.specific_conditions


def test_once_only_is_typed_usage_limit():
    p = normalize("15983")[0]
    assert [(x.type,x.quantity) for x in p.limits] == [("monetary_cap",None),("usage_count",1)]
    assert p.limits[0].period == "promotion"


def test_subscription_external_network_not_inferred_issuer_or_wallet():
    p = normalize("15992")[0]
    assert p.benefits[0].type == "discount" and p.benefits[0].percentage == 25
    assert p.limits[0].scope == "card" and p.limits[0].period == "monthly"
    assert p.online is True
    assert p.payment_methods[0].issuer is None and p.payment_methods[0].wallet is None
    assert p.payment_methods[0].network == "Mastercard"
    assert "suscripción" in p.specific_conditions


def test_budget_is_campaign_stock_not_customer_cap():
    p = normalize("15951")[0]
    assert [x.type for x in p.limits] == ["stock"]
    assert p.limits[0].amount == 2998863000 and p.limits[0].scope == "campaign"
    assert p.benefits[0].percentage == 25


def test_unknown_dates_weekdays_channels_and_no_financial_fallback():
    r = raw("13801")
    b = r["detail"]["beneficio"]
    b.update(legales="Se otorgará un 13% de reintegro. Responsabilidad del proveedor.",fechaDesde=None,fechaHasta=None,dias="-------")
    p = BueppNormalizer().normalize_many(r)[0]
    assert p.valid_from is p.valid_to is None
    assert p.days_of_week == [] and p.applies_every_day is None
    assert p.online is p.physical is None
    assert p.limits == []
    assert p.benefits[0].percentage == 13
    b["legales"] = "Se otorgará un porcentaje desconocido de reintegro."
    with pytest.raises(ValueError,match="No verified benefit"):
        BueppNormalizer().normalize_many(r)


def test_stable_ids_and_json_decimal_strings():
    r = raw("13104")
    first = BueppNormalizer().normalize_many(r)
    r["detail"]["beneficio"]["titulo"] = "Nueva campaña"
    second = BueppNormalizer().normalize_many(r)
    assert [x.source_id for x in first] == [x.source_id for x in second]
    d = second[0].model_dump(mode="json")
    assert d["benefits"][0]["percentage"] == "20"
    assert "discount_percentage" not in d


def test_cinema_exclusions_not_positive_balance_payment():
    p = normalize("15223")[0]
    assert p.benefits[0].percentage == 50
    assert {x.card_type for x in p.payment_methods} == {"credit","debit","prepaid"}
    assert all(x.card_type is not None for x in p.payment_methods)


def test_furniture_financing_channel_payment_variants():
    online,physical = normalize("15424")
    assert online.source_id == "15424:online-qr" and online.online is True
    assert physical.source_id == "15424:physical-card" and physical.physical is True
    assert physical.online is False
    assert all(x.payment_rail == "qr" for x in online.payment_methods)
    assert all(x.payment_rail == "card" and x.wallet is None for x in physical.payment_methods)


def test_coto_explicit_cabal_not_dropped_and_channel_conflict_preserved():
    physical,p = normalize("15956")
    assert {x.network for x in p.payment_methods} == {"Visa","Mastercard","Cabal"}
    assert p.online is None and "contradictorias" in p.specific_conditions
    assert physical.physical is True and physical.online is False
    assert all(x.payment_rail == "card" for x in p.payment_methods)


def test_gastronomy_cap_does_not_share_neighbors_cap():
    r = raw("13801")
    r["detail"]["beneficio"]["legales"] = r["detail"]["beneficio"]["legales"].replace("Comercios Vecinos","Comercios Gastronómicos")
    assert BueppNormalizer().normalize_many(r)[0].limits[0].shared_group_id == "buepp:comercios-gastronomicos"


def test_qa001_no_cap_clause_does_not_capture_purchase_minimum():
    p = normalize("15874")[0]
    assert [(x.type,x.amount,x.period) for x in p.limits] == [("minimum_purchase",35000,"transaction")]
    assert p.benefits[0].percentage == 20


@pytest.mark.parametrize("identifier,minimum,cap",[("15942",30000,20000),("15793",100000,25000)])
def test_qa002_plural_purchase_minimum_and_separate_monthly_cap(identifier,minimum,cap):
    for p in normalize(identifier):
        assert [(x.type,x.amount,x.period) for x in p.limits] == [("monetary_cap",cap,"monthly"),("minimum_purchase",minimum,"transaction")]


@pytest.mark.parametrize("identifier,day",[("15021","tuesday"),("15043","tuesday"),("15808","tuesday"),("15815","tuesday"),("15044","tuesday"),("15816","tuesday"),("15811","tuesday"),("15813","tuesday"),("15814","tuesday"),("15812","tuesday"),("15786","monday")])
def test_qa003_every_tuesday_does_not_mean_every_day(identifier,day):
    for p in normalize(identifier):
        assert p.days_of_week == [day]
        assert p.applies_every_day is not True


def test_qa004_location_url_is_not_online_purchase_evidence():
    p = normalize("15982")[0]
    assert p.online is False and p.physical is True
    assert p.days_of_week == ["monday","tuesday","thursday","saturday"]
    assert "ubicaciones-y-horarios" in p.terms


@pytest.mark.parametrize("identifier",["15021","15855","15793","15931"])
def test_qa005_explicit_online_purchase_variations(identifier):
    assert normalize(identifier)[0].online is True


def test_qa005_physical_source_spelling_and_time_window():
    p = normalize("15820")[0]
    assert p.physical is True
    assert "7:00HS" in p.specific_conditions and "12:00HS" in p.specific_conditions


def test_qa007_nutrican_compound_credit_debit_without_network_invention():
    p = normalize("15857")[0]
    assert {(x.card_type,x.wallet,x.issuer,x.network,x.payment_rail) for x in p.payment_methods} == {
        ("credit","Buepp","Banco Ciudad",None,"qr"),
        ("credit","App Ciudad","Banco Ciudad",None,"qr"),
        ("debit","Buepp","Banco Ciudad",None,"qr"),
        ("debit","App Ciudad","Banco Ciudad",None,"qr"),
    }


def test_qa008_nfc_android_and_qr_have_distinct_valid_wallets():
    qr,nfc = normalize("15942")
    assert qr.source_id == "15942:qr" and nfc.source_id == "15942:nfc-android"
    assert qr.promotion_group_id == nfc.promotion_group_id == "15942"
    assert {x.wallet for x in qr.payment_methods} == {"Buepp","App Ciudad"}
    assert {x.wallet for x in nfc.payment_methods} == {"Buepp","MODO"}
    assert {x.payment_rail for x in qr.payment_methods} == {"qr"}
    assert {x.payment_rail for x in nfc.payment_methods} == {"nfc"}
    assert len(qr.payment_methods) == len(nfc.payment_methods) == 8
    assert {(x.card_type,x.network) for x in nfc.payment_methods} == {("credit","Visa"),("credit","Mastercard"),("debit","Visa"),("debit","Maestro")}
    assert "únicamente en dispositivos Android" in nfc.specific_conditions
    assert "restricción Android corresponde únicamente a NFC" in qr.specific_conditions
    assert qr.limits[0].shared_group_id == nfc.limits[0].shared_group_id
