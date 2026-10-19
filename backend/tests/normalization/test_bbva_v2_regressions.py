"""Official examples have unmodified API provenance; synthetic cases are named."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from normalization.sources.bbva import BBVANormalizer

FIXTURES = Path(__file__).parents[1] / 'fixtures' / 'bbva'


@pytest.fixture
def official():
    return {r['source_id']: r for r in json.loads((FIXTURES/'official_sample.json').read_text(encoding='utf8'))}


@pytest.mark.parametrize('value,expected', [
    ('15.000','15000'), ('15000','15000'), (15000,'15000'), (15000.25,'15000.25'),
    ('$15.000,50','15000.50'), ('15.000.000,50','15000000.50'), ('15.000.000','15000000'),
    ('15000,50','15000.50'), ('15000.50','15000.50'), ('$15,000.50','15000.50'),
    ('ARS 15.000,50','15000.50'), ('15\u00a0000,50','15000.50'),
    ('15,000',None), ('1.23.456',None), ('12,345,678',None), ('15000.123',None),
    (True,None), ('NaN',None), (float('inf'),None), ('-15',None), ('',None), (None,None),
])
def test_amount_formats_are_decimal_and_ambiguous_values_unknown(value,expected):
    assert BBVANormalizer()._normalize_amount(value) == (Decimal(expected) if expected is not None else None)


def test_official_cashback_and_financing_are_compatible(official):
    p=BBVANormalizer().normalize(official['88114'])
    assert [(b.type,b.percentage,b.installment_options) for b in p.benefits] == [('cashback',Decimal(20),[]),('installments',None,[6])]
    assert p.benefits[1].interest_free is None  # Neither the API nor legal terms promises this here.
    assert p.days_of_week==['tuesday']
    assert p.limits[0].amount==50000 and p.limits[0].period=='monthly'
    assert [(m.issuer,m.card_type,m.wallet,m.payment_rail) for m in p.payment_methods]==[('BBVA','credit','BBVA','qr')]
    assert p.valid_from.isoformat()=='2026-10-06'
    assert p.model_dump(mode='json')['limits'][0]['amount']=='50000'


def test_official_vea_minimum_is_strict_and_friday_not_unknown(official):
    p=BBVANormalizer().normalize(official['86278'])
    assert p.days_of_week==['friday'] and p.applies_every_day is None
    cap,minimum=p.limits
    assert cap.amount==25000 and cap.period=='monthly'
    assert minimum.type=='minimum_purchase' and minimum.amount==100000
    assert 'estrictamente superior' in minimum.description
    assert p.online is None  # MODO promo link is not a purchase channel.
    assert p.payment_methods[0].card_type is None  # Both types named; no artificial type/network product.


def test_official_nfc_requires_specific_card_and_wallets(official):
    p=BBVANormalizer().normalize(official['88410'])
    assert p.scope=='category' and p.category=='Gastronomía'
    assert {(m.network,m.card_type,m.wallet,m.payment_rail) for m in p.payment_methods} == {
        ('visa','credit','Apple Pay','nfc'),('visa','credit','Google Pay','nfc'),('visa','credit','MODO','nfc')}
    assert p.online is None  # BBVA package information under canalesVenta.web.
    assert p.applies_every_day is True
    assert p.limits[0].amount==100000 and p.limits[0].scope=='account'
    assert p.limits[0].shared_group_id
    assert 'Black+ Travel / Black+ All' in p.specific_conditions
    assert 'ADICIONALES' in p.specific_conditions
    assert p.requires_merchant_verification and p.promotion_url


def test_official_legal_qr_does_not_create_nfc_product(official):
    p=BBVANormalizer().normalize(official['88098'])
    assert {m.payment_rail for m in p.payment_methods}=={'qr'}
    assert p.limits[0].type=='minimum_purchase' and p.limits[0].amount==250000
    assert p.benefits[0].installment_options==[9]


def test_official_grimoldi_conditional_financing_is_separate(official):
    p,alt=BBVANormalizer().normalize_many(official['87593'])
    assert p.source_id=='87593' and alt.source_id=='87593:financing-minimum'
    assert p.promotion_group_id==alt.promotion_group_id=='87593'
    assert [(b.type,b.percentage,b.installment_options) for b in p.benefits]==[('cashback',Decimal(20),[]),('installments',None,[6])]
    assert not any(l.type=='minimum_purchase' for l in p.limits)
    assert len(alt.benefits)==1 and alt.benefits[0].installment_options==[9]
    assert alt.benefits[0].interest_free is True
    assert alt.limits[0].amount==250000 and alt.limits[0].type=='minimum_purchase'
    assert not any(l.type=='monetary_cap' for l in alt.limits)
    assert all(m.network=='visa' for m in p.payment_methods)
    with pytest.raises(ValueError,match='normalize_many'): BBVANormalizer().normalize(official['87593'])


def test_official_cabify_text_only_cap_usage_and_black(official):
    p=BBVANormalizer().normalize(official['87336'])
    assert p.benefits[0].type=='discount' and p.benefits[0].percentage==100
    assert [(l.type,l.amount,l.quantity) for l in p.limits]==[('monetary_cap',Decimal(50000),None),('usage_count',None,1)]
    assert p.limits[1].period=='promotion'
    assert p.payment_methods[0].network=='mastercard'
    assert 'MCBBVA2026' in p.specific_conditions and 'Black' in p.specific_conditions
    assert p.online is None


def test_official_fixed_coupon_minimum_stock_and_codes(official):
    p=BBVANormalizer().normalize(official['88152'])
    assert p.benefits[0].amount==7500 and p.benefits[0].currency=='ARS'
    assert [(l.type,l.amount,l.quantity) for l in p.limits]==[('minimum_purchase',Decimal(15000),None),('stock',None,15000)]
    assert p.payment_methods[0].network=='mastercard'
    assert 'BOCAMASTERF14' in p.specific_conditions and '48 horas' in p.specific_conditions
    assert '01/20/2026' in p.terms  # Invalid source typo preserved, never invented/repaired.


def test_official_cinemark_keeps_two_product_benefits_separate(official):
    tickets,combos=BBVANormalizer().normalize_many(official['76010'])
    assert len(tickets.benefits)==1 and tickets.benefits[0].type=='other'
    assert '2x1' in tickets.benefits[0].description
    assert tickets.online is True and tickets.applies_every_day is True
    assert tickets.limits[0].type=='usage_count' and tickets.limits[0].quantity==2
    assert combos.source_id=='76010:combos'
    assert combos.benefits[0].type=='discount' and combos.benefits[0].percentage==20
    assert 'Combos seleccionados' in combos.benefits[0].description
    assert all(b.percentage is None for b in tickets.benefits)


def test_official_lottery_is_not_lost(official):
    p,extra=BBVANormalizer().normalize_many(official['88407'])
    assert p.benefits[0].type=='other'
    assert 'Australian Open 2027' in p.benefits[0].description
    assert p.payment_methods==[] and p.scope=='other'
    assert 'Mastercard' not in p.benefits[0].description
    assert '400 millas por chance' in p.specific_conditions
    assert 'Salta, Neuquén, Río Negro, Tierra del Fuego, Jujuy, Formosa y Mendoza' in p.specific_conditions
    assert extra.source_id=='88407:mastercard-extra-chances'
    assert extra.benefits[0].description.startswith('5 chances extra')
    assert extra.payment_methods[0].network=='mastercard'
    assert extra.limits[0].quantity==1 and extra.limits[0].scope=='person'


def test_official_unidentifiable_benefit_blocks_instead_of_misusing_cap(official):
    with pytest.raises(ValueError,match='benefit not identifiable'):
        BBVANormalizer().normalize_many(official['87567'])


def test_official_cap_period_conflict_is_visible(official):
    p=BBVANormalizer().normalize(official['88050'])
    assert p.limits[0].period=='promotion'
    assert 'Fuente inconsistente' in p.specific_conditions


def synthetic(official):
    r=deepcopy(official['88114'])
    r['detail']['basesCondiciones']='Promoción válida con las tarjetas indicadas en requisitos. Los beneficios son acumulables entre sí.'
    r['detail']['beneficios']=[{'descripcion':'20% de reintegro','requisitos':['Con tarjetas de crédito BBVA'],'cuota':0},
                             {'descripcion':'6 cuotas sin interés','requisitos':['Con tarjetas de crédito BBVA'],'cuota':6}]
    r['catalog']['montoTope']=None
    return r


def test_synthetic_multiple_compatible_nodes_preserve_all_benefits(official):
    r=synthetic(official)
    p=BBVANormalizer().normalize_many(r)
    assert len(p)==1 and [b.type for b in p[0].benefits]==['cashback','installments']
    assert p[0].benefits[1].interest_free is True


def test_synthetic_payment_variants_have_stable_ids_across_rates_and_order(official):
    r=synthetic(official)
    r['detail']['beneficios'][0]['requisitos']=['Exclusivo tarjetas de crédito Visa BBVA']
    r['detail']['beneficios'][1].update(descripcion='30% de descuento',cuota=0,requisitos=['Exclusivo tarjetas de crédito Mastercard BBVA'])
    n=BBVANormalizer()
    before={p.payment_methods[0].network:p.source_id for p in n.normalize_many(r)}
    r['detail']['beneficios'].reverse()
    r['detail']['beneficios'][0]['descripcion']='40% de descuento'
    r['detail']['cabecera']='Marketing actualizado'
    after={p.payment_methods[0].network:p.source_id for p in n.normalize_many(r)}
    assert before==after and len(set(after.values()))==2


def test_synthetic_ambiguous_compatibility_blocks(official):
    r=synthetic(official)
    r['detail']['beneficios'][1].update(descripcion='30% de reintegro',cuota=0)
    with pytest.raises(ValueError,match='ambiguous benefit'): BBVANormalizer().normalize_many(r)


def test_synthetic_nfc_mention_alone_does_not_create_wallets(official):
    r=synthetic(official)
    r['detail']['beneficios']=r['detail']['beneficios'][:1]
    r['detail']['beneficios'][0]['requisitos']=['Pagá mediante NFC o con tus tarjetas físicas BBVA']
    p=BBVANormalizer().normalize(r)
    assert all(m.wallet is None and m.payment_rail is None for m in p.payment_methods)


def test_synthetic_ambiguous_cap_blocks_without_numeric_fallback(official):
    r=deepcopy(official['88114']);r['detail']['beneficios'][0]['tope']='15,000'
    with pytest.raises(ValueError,match='ambiguous or invalid cap'): BBVANormalizer().normalize_many(r)


def test_synthetic_unknown_dates_and_exclusion_weekdays(official):
    r=deepcopy(official['88114'])
    r['catalog']['fechaDesde']=r['catalog']['fechaHasta']=None
    r['catalog']['diasPromo']=r['detail']['diasPromo']=None
    r['detail']['beneficios'][0]['requisitos']=['Responsabilidad de BBVA. No aplica viernes.']
    r['detail']['basesCondiciones']='Promoción BBVA. No aplica sábados.'
    p=BBVANormalizer().normalize(r)
    assert p.valid_from is None and p.valid_to is None
    assert p.days_of_week==[] and p.applies_every_day is None


def test_synthetic_vehicle_name_not_a_multibuy_benefit(official):
    r=deepcopy(official['88114']);r['detail']['cabecera']='Comercio 4x4 20%'
    assert all(b.type!='other' for b in BBVANormalizer().normalize(r).benefits)


def test_official_export_uses_variants_and_blocks_partial_overwrite(official,tmp_path):
    from normalization.export_json import export_source
    path=tmp_path/'bbva_promotions.json'
    path.write_text(json.dumps([official['87593']]),encoding='utf8')
    result=export_source('bbva',input_dir=tmp_path)
    assert result['raw_count']==1 and result['normalized_count']==2
    output=Path(result['output']);old=output.read_bytes()
    path.write_text(json.dumps([official['87593'],official['87567']]),encoding='utf8')
    with pytest.raises(RuntimeError,match='87567'): export_source('bbva',input_dir=tmp_path)
    assert output.read_bytes()==old


@pytest.mark.parametrize('source_id', ['87862','87734'])
def test_official_puppis_gift_does_not_restrict_general_financing(official,source_id):
    financing,gift=BBVANormalizer().normalize_many(official[source_id])
    assert financing.limits==[]
    # 87734 publishes Friday/Saturday in its API bitmask; 87862 leaves it null.
    assert financing.days_of_week==(['friday','saturday'] if source_id=='87734' else [])
    assert financing.payment_methods[0].network is None
    assert [b.type for b in gift.benefits]==['installments','gift']
    assert gift.benefits[0].installment_options==[3]
    assert 'COMEDERO' in gift.benefits[1].description
    assert gift.limits[0].amount==70000 and 'igual o superior' in gift.limits[0].description
    assert gift.limits[1].quantity==1 and gift.limits[1].scope=='person'
    assert gift.payment_methods[0].network=='mastercard'
    assert gift.physical is True and gift.online is False
    assert gift.days_of_week==['friday','saturday']
    assert gift.source_id==source_id+':gift'
    assert financing.requires_merchant_verification and gift.requires_merchant_verification


def test_official_oncity_gift_has_its_own_minimum_weekdays_and_products(official):
    financing,gift=BBVANormalizer().normalize_many(official['88015'])
    assert financing.benefits[0].installment_options==[12] and financing.benefits[0].interest_free is True
    assert financing.limits==[] and financing.days_of_week==[]
    assert 'productos seleccionados' in financing.specific_conditions
    assert gift.benefits[0].type=='gift' and 'JBL' in gift.benefits[0].description
    assert gift.limits[0].amount==350000 and 'estrictamente superior' in gift.limits[0].description
    assert gift.limits[1].quantity==1
    assert gift.days_of_week==['monday','tuesday','wednesday','thursday','friday']
    assert gift.online is True and gift.physical is False
    assert gift.payment_methods[0].network=='mastercard'


@pytest.mark.parametrize('source_id',['86498','87700'])
def test_official_additive_qr_preserves_direct_card_and_account_cap(official,source_id):
    p=BBVANormalizer().normalize(official[source_id])
    assert {(m.wallet,m.payment_rail) for m in p.payment_methods}=={(None,'card'),('BBVA','qr')}
    cap=p.limits[0]
    assert cap.amount==18000 and cap.scope=='account' and cap.period=='monthly'
    assert cap.shared_group_id is None


def test_official_explicit_network_alternatives_are_not_unknown(official):
    p=BBVANormalizer().normalize(official['87255'])
    assert {(m.network,m.card_type,m.issuer) for m in p.payment_methods}=={('visa','credit','BBVA'),('mastercard','credit','BBVA')}


@pytest.mark.parametrize('source_id,amount,campaign',[('87865',15000,'2502'),('86320',10000,None)])
def test_official_shared_caps_are_not_per_merchant(official,source_id,amount,campaign):
    p=BBVANormalizer().normalize(official[source_id]);cap=p.limits[0]
    assert cap.amount==amount and cap.scope=='person'
    assert 'compartido entre los comercios adheridos' in cap.description
    assert ('COMPARTIDO ENTRE' in p.specific_conditions)
    assert cap.shared_group_id==(f'bbva:campaign:{campaign}:cap' if campaign else None)


@pytest.mark.parametrize('source_id',['88215','87797'])
def test_official_contradictory_rates_block_instead_of_silent_precedence(official,source_id):
    with pytest.raises(ValueError,match='conflicting benefit percentage'):
        BBVANormalizer().normalize_many(official[source_id])


@pytest.mark.parametrize('source_id',['87657','84603'])
def test_official_ticket_quantities_have_transaction_scope(official,source_id):
    p=BBVANormalizer().normalize(official[source_id])
    usage=next(l for l in p.limits if l.type=='usage_count')
    assert usage.quantity==6 and usage.period=='transaction' and usage.scope=='transaction'
    assert usage.description=='Entradas por transacción'
    if source_id=='87657':
        stock=next(l for l in p.limits if l.type=='stock')
        assert stock.quantity==300 and stock.period=='presale'
        assert 'no limita la venta general' in stock.description
        assert 'Venta general:' in p.specific_conditions


def test_official_cabify_trip_count_and_discount_semantics(official):
    p=BBVANormalizer().normalize(official['87856'])
    assert p.benefits[0].type=='discount' and p.benefits[0].percentage==50
    usage=next(l for l in p.limits if l.type=='usage_count')
    assert usage.quantity==5 and usage.scope=='person' and usage.period=='promotion'
    assert usage.description=='Viajes elegibles por usuario'


def test_synthetic_changed_gift_amount_keeps_identity_and_general_financing(official):
    r=deepcopy(official['87862']);n=BBVANormalizer();before=n.normalize_many(r)
    r['detail']['basesCondiciones']=r['detail']['basesCondiciones'].replace('$70.000','$80.000')
    r['detail']['beneficios'][0]['requisitos']=[s.replace('$70.000','$80.000') for s in r['detail']['beneficios'][0]['requisitos']]
    after=n.normalize_many(r)
    assert [p.source_id for p in before]==[p.source_id for p in after]
    assert after[0].limits==[] and after[1].limits[0].amount==80000


def test_synthetic_lottery_quantities_and_card_are_not_defaults(official):
    r=deepcopy(official['88407'])
    r['detail']['basesCondiciones']=r['detail']['basesCondiciones'].replace('400 (cuatrocientas)','500 (quinientas)').replace('5 chances extra','7 chances extra').replace('1 canje por cliente','2 canjes por cliente').replace('Mastercard','Visa').replace('18 años','21 años')
    r['detail']['beneficios'][0]['requisitos']=[s.replace('Mastercard','Visa').replace('5 chances extra','7 chances extra') for s in r['detail']['beneficios'][0]['requisitos']]
    general,extra=BBVANormalizer().normalize_many(r)
    assert general.payment_methods==[] and '500 millas por chance' in general.specific_conditions
    assert 'mayores de 21 años' in general.specific_conditions
    assert extra.payment_methods[0].network=='visa'
    assert extra.benefits[0].description.startswith('7 chances extra') and extra.limits[0].quantity==2


def test_official_mileage_redemption_is_not_credit_and_caps_are_not_money(official):
    variants=BBVANormalizer().normalize_many(official['88097'])
    assert len(variants)==2
    caps={p.limits[0].quantity for p in variants}
    assert caps=={3100,16000}
    for p in variants:
        assert p.valid_to.isoformat()=='2026-10-30'
        assert '2026-10-31' in p.specific_conditions and 'requiere revisión' in p.specific_conditions
        assert 'no aplica a compras con tarjeta de crédito' in p.specific_conditions
        assert p.benefits[0].type=='discount' and p.benefits[0].percentage==20
        assert p.benefits[0].description.startswith('hasta un 20%')
        assert p.limits[0].type=='other' and 'Millas BBVA' in p.limits[0].description
        assert all(l.amount is None and l.currency is None for l in p.limits)
        assert p.limits[1].type=='stock' and p.limits[1].quantity==1500 and p.limits[1].shared_group_id
        assert p.limits[2].type=='usage_count' and p.limits[2].quantity==1 and p.limits[2].scope=='person'
        assert p.payment_methods[0].payment_rail=='other'
        assert p.payment_methods[0].card_type is None
        assert 'Portal' in p.payment_methods[0].raw_name and p.online is True
    assert variants[0].limits[1].shared_group_id==variants[1].limits[1].shared_group_id
    assert variants[0].limits[2].shared_group_id==variants[1].limits[2].shared_group_id
    assert variants[0].promotion_group_id==variants[1].promotion_group_id=='88097'


def test_synthetic_mileage_limits_stock_and_date_are_parsed_not_defaults(official):
    r=deepcopy(official['88097']);n=BBVANormalizer();before=n.normalize_many(r)
    r['detail']['basesCondiciones']=r['detail']['basesCondiciones'].replace('3.100','4.200').replace('16.000','17.000').replace('1500 cupos','1800 cupos').replace('30/10/2026','29/10/2026')
    after=n.normalize_many(r)
    assert [p.source_id for p in before]==[p.source_id for p in after]
    assert {p.limits[0].quantity for p in after}=={4200,17000}
    assert all(p.limits[1].quantity==1800 and p.valid_to.isoformat()=='2026-10-29' for p in after)


def test_official_travel_financing_has_two_product_specific_options(official):
    packages,flights=BBVANormalizer().normalize_many(official['87863'])
    assert packages.source_id=='87863:packages-accommodation' and flights.source_id=='87863:domestic-flights'
    assert packages.benefits[0].installment_options==[9]
    assert flights.benefits[0].installment_options==[3]
    assert packages.benefits[0].interest_free is flights.benefits[0].interest_free is True
    assert 'PAQUETES Y ALOJAMIENTOS EN ARGENTINA' in packages.specific_conditions
    assert 'VUELOS CON DESTINO Y ORIGEN EN ARGENTINA' in flights.specific_conditions
    assert 'HASTA 9 CUOTAS' not in flights.specific_conditions
    for p in (packages,flights):
        assert p.online is True and 'Portal de Millas' in p.specific_conditions
        assert p.payment_methods[0].card_type=='credit' and p.payment_methods[0].issuer=='BBVA'
        assert p.applies_every_day is True


def test_official_assistcard_is_blocked_until_all_dimensions_are_represented(official):
    r=official['88051']
    for text in ['40%', '45%', '55%', '50%', '20%', 'GRATIS HASTA 4 PRODUCTOS', 'NO APLICABLE A CUOTAS']:
        assert text in r['detail']['basesCondiciones']
    with pytest.raises(ValueError,match='unresolved product/payment-dependent benefit rates'):
        BBVANormalizer().normalize_many(r)


@pytest.mark.parametrize('terms,reason', [
    ('Producto A: 15% de descuento. Producto B: 25% de descuento.', 'benefit rates'),
    ('Hasta 3 cuotas para alimentos. Hasta 6 cuotas para electrodomésticos.', 'installment options'),
])
def test_synthetic_unrepresented_multi_product_dimensions_never_emit_first_only(official,terms,reason):
    r=deepcopy(official['88114']);r['detail']['basesCondiciones']=terms
    with pytest.raises(ValueError,match=reason): BBVANormalizer().normalize_many(r)
