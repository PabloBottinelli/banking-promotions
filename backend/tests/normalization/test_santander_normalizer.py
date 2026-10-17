"""Official BFF excerpts, 2026-10-15; no generated/golden expectations."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest
from normalization.sources.santander import SantanderNormalizer, fold, plain, legal_monthly_caps

FIXTURES=Path(__file__).resolve().parents[1]/'fixtures/santander'


def raw(name):return json.loads((FIXTURES/(name+'.json')).read_text(encoding='utf8'))
def normalize(name):return SantanderNormalizer().normalize_many(raw(name))


def test_cafe_legal_dates_qr_and_sorpresa():
    p,=normalize('60_7558')
    assert (p.valid_from,p.valid_to)==(date(2026,8,4),date(2026,10,31))
    assert p.benefits[0].type=='cashback' and p.benefits[0].percentage==Decimal('20')
    assert p.days_of_week==['tuesday','wednesday'] and p.applies_every_day is None
    assert {(m.card_type,m.wallet,m.payment_rail) for m in p.payment_methods}=={('debit','MODO','qr'),('debit','App Santander','qr'),('credit','MODO','qr'),('credit','App Santander','qr')}
    assert p.online is None
    # Published aggregate 20k versus legal base/extra 10k ceilings remains explicit uncertainty.
    assert (p.limits[0].amount,p.limits[0].currency,p.limits[0].period)==(None,'ARS','monthly')
    assert 'Conflicto de tope mensual' in p.specific_conditions
    assert 'Sorpresa' in p.specific_conditions and 'difiere' in p.specific_conditions
    assert p.requires_merchant_verification and p.promotion_url.startswith('https://www.santander.com.ar/')
    assert p.terms==raw('60_7558')['detail']['legal']
    assert p.model_dump(mode='json')['benefits'][0]['percentage']=='20'


def test_cinepolis_two_for_one_and_prepaid_recargable():
    p,=normalize('107_7150')
    assert p.benefits[0].type=='other' and p.benefits[0].description=='2x1 en entradas'
    assert p.benefits[0].percentage is None
    assert any(m.card_type=='prepaid' for m in p.payment_methods)
    assert 'NO APLICA SOBRE TARIFA DE MENORES' in p.specific_conditions


def test_event_financing_and_presale_are_distinct_stages():
    rows=normalize('1127_7560')
    stage=next(p for p in rows if p.source_id.endswith(':presale'))
    finance=next(p for p in rows if any(b.type=='installments' for b in p.benefits))
    assert (stage.valid_from,stage.valid_to)==(date(2026,8,3),date(2026,8,4))
    assert stage.benefits[0].type=='other' and not any(b.type=='installments' for b in stage.benefits)
    assert any(l.type=='stock' and l.quantity==5000 for l in stage.limits)
    assert any(l.type=='usage_count' and l.quantity==4 for l in stage.limits)
    assert any(b.installment_options==[6] and b.interest_free is True for b in finance.benefits)
    assert all(m.card_type=='credit' for m in finance.payment_methods)
    assert not any(l.type=='stock' and l.period=='presale' for l in finance.limits)


def test_transport_transfer_qr_and_balance_requirement():
    p,=normalize('2960_7899')
    assert p.benefits[0].percentage==Decimal('100') and p.applies_every_day is True
    assert all(m.card_type is None and m.payment_rail=='qr' for m in p.payment_methods)
    assert {m.wallet for m in p.payment_methods}=={'App Santander','MODO'}
    assert p.online is None and 'saldo mínimo de $1200' in p.specific_conditions
    assert 'dos reintegros' in p.specific_conditions
    assert not any(l.type=='minimum_purchase' for l in p.limits)


def test_arteba_subtitle_conflict_legal_currency_and_usage():
    p,=normalize('39_7934')
    assert p.valid_from==date(2025,10,3)
    assert (p.limits[0].amount,p.limits[0].currency)==(Decimal('8400'),'ARS')
    assert any(l.type=='usage_count' and l.quantity==4 for l in p.limits)
    assert 'Conflicto de tope' in p.specific_conditions
    assert 'detail.texts.subtitle' in p.specific_conditions


def test_shopping_variants_stable_and_financing_credit_only():
    rows=normalize('387_7757')
    assert len(rows)==2 and all(p.scope=='shopping' for p in rows)
    assert len({p.promotion_group_id for p in rows})==1
    assert any(b.type=='installments' for b in rows[0].benefits)
    assert not any(b.type=='installments' for b in rows[1].benefits)
    r=raw('387_7757');r['catalog']['name']='Marketing changed';r['detail']['order']=999
    assert [p.source_id for p in SantanderNormalizer().normalize_many(r)]==[p.source_id for p in rows]


def test_coto_nfc_has_verified_complete_options():
    p,=normalize('131_8075')
    assert p.benefits[0].type=='discount' and p.physical is True
    assert {(m.wallet,m.network,m.card_type,m.payment_rail) for m in p.payment_methods}=={(w,'VISA','debit','nfc') for w in ['Apple Pay','Google Pay','MODO Contactless']}


def test_qa003_coto_long_month_legal_validity_overrides_catalog_window():
    # Legal: desde el 26 de febrero de 2026 hasta el 15 de octubre de 2026.
    p,=normalize('131_8075')
    assert (p.valid_from,p.valid_to)==(date(2026,2,26),date(2026,10,15))
    assert 'difiere de la ventana del catálogo' in p.specific_conditions


def test_qa001_carrefour_explicit_shared_cap_crosses_campaign_ids():
    rows=[normalize(name)[0] for name in ['86_8006','87_8005','3721_8003']]
    caps=[next(l for l in p.limits if l.type=='monetary_cap') for p in rows]
    assert len({p.promotion_group_id for p in rows})==3
    assert {l.shared_group_id for l in caps}=={'santander:shared-cap:carrefour'}
    assert all(l.amount==Decimal('10000') and l.currency=='ARS' and l.period=='monthly' for l in caps)
    assert all(l.scope=='account' and 'tope compartido' in l.description for l in caps)
    changed=raw('86_8006');changed['program']['idPromotion']=999;changed['catalog']['name']='New marketing label'
    p,=SantanderNormalizer().normalize_many(changed)
    assert next(l for l in p.limits if l.type=='monetary_cap').shared_group_id==caps[0].shared_group_id


@pytest.mark.parametrize('name',['86_8006','87_8005','3721_8003'])
def test_qa002_carrefour_additional_online_exclusion_retained(name):
    p,=normalize(name)
    assert 'No aplica a compras online.' in p.specific_conditions
    assert 'Tope compartido con las demás promociones en Carrefour.' in p.specific_conditions
    assert any(l.type=='minimum_purchase' and l.amount==Decimal('15000') for l in p.limits)
    # The exclusion alone does not establish a positive purchase channel.
    r=raw(name);r['detail']['legal']='<p>Beneficio de reintegro para clientes Santander.</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert p.physical is None and p.online is None
    assert 'No aplica a compras online.' in p.specific_conditions


def test_ypf_external_app_does_not_prove_online():
    p,=normalize('546_7909')
    assert all(m.wallet=='App YPF' and m.payment_rail=='card' for m in p.payment_methods)
    assert p.online is None


@pytest.mark.parametrize('name',['177_3948','607_7364','1919_7147','58_7592'])
def test_explicit_included_wallets_not_lost_when_api_payment_type_is_null_or_other(name):
    rows=normalize(name)
    wallets={m.wallet for p in rows for m in p.payment_methods}
    assert {'MODO','Google Pay','Apple Pay'}<=wallets
    assert all(m.network=='VISA' and m.card_type in {'credit','debit'} and m.payment_rail=='card' for p in rows for m in p.payment_methods)
    if name=='58_7592':
        assert all('App Cabify' in m.raw_name for p in rows for m in p.payment_methods)


def test_shopping_days_explicit_three_and_six_installment_options():
    p,=normalize('1782_8009')
    benefit=next(b for b in p.benefits if b.type=='installments')
    assert benefit.installment_options==[3,6]
    assert benefit.interest_free is True


@pytest.mark.parametrize('name',['3194_7956','2_7955'])
def test_qa004_positive_wallet_clauses_keep_all_four_supported_wallets(name):
    rows=normalize(name)
    assert {m.wallet for p in rows for m in p.payment_methods if m.wallet}=={
        'App Santander','MODO','Google Pay','Apple Pay'}
    for p in rows:
        assert p.online is None
        assert all(m.network=='VISA' and m.payment_rail=='card' for m in p.payment_methods)
        if any(b.type=='installments' for b in p.benefits):
            assert all(m.card_type=='credit' for m in p.payment_methods)
        elif name=='3194_7956':
            assert all(m.card_type=='debit' for m in p.payment_methods)
        else:
            # 47 Street publishes discount without financing for both card types.
            assert {m.card_type for m in p.payment_methods}=={'credit','debit'}
        assert {m.wallet for m in p.payment_methods if m.wallet}=={
            'App Santander','MODO','Google Pay','Apple Pay'}


def test_qa005_legal_visa_clause_reconciles_contradicted_catalog_networks():
    r=raw('3492_7598')
    assert {c['description'] for c in r['detail']['cards']}=={'VISA','MASTER','AMEX'}
    p,=SantanderNormalizer().normalize_many(r)
    assert {m.network for m in p.payment_methods}=={'VISA'}
    assert {m.card_type for m in p.payment_methods}=={'credit','debit'}
    assert all(m.payment_rail=='qr' for m in p.payment_methods)
    assert 'Conflicto de medios de pago' in p.specific_conditions
    assert 'AMEX' in p.specific_conditions and 'MASTER' in p.specific_conditions
    assert 'Verificar las condiciones con Santander' in p.specific_conditions
    assert {c['description'] for c in r['detail']['cards']}=={'VISA','MASTER','AMEX'}


def test_qa006_shopping_days_retains_payment_platform_exclusion():
    p,=normalize('1782_8009')
    assert 'NO VÁLIDO PARA COMPRAS REALIZADAS A TRAVÉS DE PLATAFORMAS DE PAGOS Y/O AGREGADORES' in p.specific_conditions
    assert p.online is None


def test_qa006_coto_keeps_product_restrictions_and_actionable_full_list_notice():
    p,=normalize('131_8075')
    assert 'NO INCLUYE ELECTRODOMÉSTICOS, NEUMÁTICOS NI RODADOS' in p.specific_conditions
    assert 'PATIOS DE COMIDAS' in p.specific_conditions
    assert 'NO INCLUYE CORTES DE CARNES' in p.specific_conditions
    assert 'listado completo en los términos oficiales' in p.specific_conditions
    assert 'BODEGA MONTEVIEJO' in p.terms


@pytest.mark.parametrize('sentence',[
    'No válido para compras online.',
    'No incluye compras en tiendas online.',
    'No válido en locales adheridos.',
])
def test_negative_eligibility_clauses_do_not_create_positive_channels(sentence):
    r=raw('60_7557');r['detail']['legal']='<p>'+sentence+'</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert p.online is p.physical is None
    assert sentence in p.specific_conditions


def test_breakfast_time_usage_and_conflicting_cap_are_visible():
    p,=normalize('740_7707')
    assert '6 h a 11 h' in p.specific_conditions
    assert 'Conflicto de tope' in p.specific_conditions
    assert any(l.type=='usage_count' and l.quantity==10 and l.period=='monthly' for l in p.limits)
    assert any(l.type=='monetary_cap' and l.period=='transaction' and l.amount is None for l in p.limits)
    assert any(l.type=='monetary_cap' and l.period=='monthly' and l.amount==Decimal('15000') for l in p.limits)


def test_qa007_pedidosya_monthly_disagreement_is_explicit_not_an_asserted_cap():
    r=raw('393_7950')
    assert r['detail']['topAmount']==15000
    p,=SantanderNormalizer().normalize_many(r)
    cap=next(l for l in p.limits if l.type=='monetary_cap')
    assert cap.amount is None and cap.currency=='ARS' and cap.period=='monthly'
    assert 'Conflicto de tope mensual' in cap.description
    assert '15000 ARS' in cap.description and '25000 ARS' in cap.description
    assert 'Conflicto de tope mensual' in p.specific_conditions
    assert '$25.000 por mes' in p.terms
    assert r['detail']['topAmount']==15000  # API evidence remains untouched.


def test_qa007_consistent_official_monthly_cap_remains_structured():
    p,=normalize('546_7909')
    assert any(l.type=='monetary_cap' and l.amount==Decimal('20000') and l.period=='monthly' for l in p.limits)
    assert 'Conflicto de tope mensual' not in p.specific_conditions


@pytest.mark.parametrize('clause',[
    'Tope mensual: $7.000.',
    'Tope de reintegro mensual será de $7.000.',
    'Tope: $7.000 por mes.',
])
def test_monthly_cap_conflict_forms_use_source_numbers_without_fallback(clause):
    r=raw('393_7950');r['detail']['legal']='<p>'+clause+' Ejemplo: reintegro de $15.000.</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert next(l for l in p.limits if l.type=='monetary_cap').amount is None
    assert '7000 ARS' in p.specific_conditions and '15000 ARS' in p.specific_conditions


def test_example_monthly_amount_does_not_override_consistent_eligibility_cap():
    r=raw('546_7909');r['detail']['legal']='<p>Tope mensual: $20.000. Ejemplo: tope mensual: $99.000.</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert next(l for l in p.limits if l.type=='monetary_cap').amount==Decimal('20000')
    assert 'Conflicto de tope mensual' not in p.specific_conditions


def test_qa008_presale_credit_debit_clause_does_not_inherit_general_prepaid():
    r=raw('1127_7560')
    assert any(card['codeType']=='R' for card in r['detail']['cards'])
    rows=SantanderNormalizer().normalize_many(r)
    stage=next(p for p in rows if p.source_id.endswith(':presale'))
    assert {m.card_type for m in stage.payment_methods}=={'credit','debit'}
    assert ('VISA','prepaid') not in {(m.network,m.card_type) for m in stage.payment_methods}
    assert {m.network for m in stage.payment_methods if m.card_type=='debit'}=={'VISA'}
    assert {m.network for m in stage.payment_methods if m.card_type=='credit'}=={'VISA','MASTER','AMEX'}
    assert all(m.card_type=='credit' for p in rows if any(b.type=='installments' for b in p.benefits) for m in p.payment_methods)
    cinepolis,=normalize('107_7150')
    assert any(m.card_type=='prepaid' for m in cinepolis.payment_methods)
    assert any(card['codeType']=='R' for card in r['detail']['cards'])


def test_explicit_prepaid_presale_keeps_only_evidenced_network_type_combination():
    r=raw('1127_7560')
    r['detail']['legal']=r['detail']['legal'].replace('Preventa con tarjeta Santander crédito y débito','Preventa con tarjeta Santander recargable')
    rows=SantanderNormalizer().normalize_many(r)
    stage=next(p for p in rows if p.source_id.endswith(':presale'))
    assert {(m.network,m.card_type) for m in stage.payment_methods}=={('VISA','prepaid')}


def test_contradictory_stage_without_supported_payment_combinations_is_not_silently_lost():
    r=raw('1127_7560')
    r['detail']['legal']=r['detail']['legal'].replace('Preventa con tarjeta Santander crédito y débito','Preventa con tarjeta Santander recargable')
    r['detail']['cards']=[card for card in r['detail']['cards'] if card['codeType']!='R']
    with pytest.raises(ValueError,match='Presale eligibility contradicts'):
        SantanderNormalizer().normalize_many(r)


def test_qa009_grido_uses_explicit_sorpresa_ceiling_instead_of_general_base_cap():
    r=raw('3459_7492')
    assert r['detail']['productSegmentation']=='Sorpresa'
    p,=SantanderNormalizer().normalize_many(r)
    cap=next(l for l in p.limits if l.type=='monetary_cap')
    assert cap.amount==Decimal('10000') and cap.period=='monthly' and cap.currency=='ARS'
    assert 'Sorpresa' in p.specific_conditions
    assert 'Conflicto de tope mensual' not in p.specific_conditions


def test_qa009_segment_scope_is_explicit_and_does_not_mask_real_conflict():
    r=raw('3459_7492');legal=fold(plain(r['detail']['legal']))
    assert legal_monthly_caps(legal,'Masiva')=={Decimal('5000')}
    assert legal_monthly_caps(legal,'Sorpresa')=={Decimal('10000')}
    r['detail']['topAmount']=12000  # Explicit synthetic disagreement with qualified legal cap.
    p,=SantanderNormalizer().normalize_many(r)
    assert next(l for l in p.limits if l.type=='monetary_cap').amount is None
    assert '12000 ARS' in p.specific_conditions and '10000 ARS' in p.specific_conditions


@pytest.mark.parametrize('name',['393_7950','3234_7326','429_7960','60_7558'])
def test_qa009_scoped_ceiling_does_not_suppress_real_conflicts_or_add_extra_caps(name):
    p,=normalize(name)
    assert next(l for l in p.limits if l.type=='monetary_cap').amount is None
    assert 'Conflicto de tope mensual' in p.specific_conditions
    if name=='60_7558':
        assert 'extra' in p.specific_conditions


def test_qa010_babymetal_selects_effective_dated_clause_after_standalone_heading():
    rows=normalize('3040_6908')
    stage=next(p for p in rows if p.source_id.endswith(':presale'))
    assert stage.valid_from==date(2026,4,22)
    assert stage.valid_to is None  # No invented calendar end from 48-hour duration.
    assert len(stage.benefits)==1 and stage.benefits[0].type=='other'
    description=stage.benefits[0].description
    assert description.startswith('Preventa del 22/04/26')
    assert '10hs AM' in description and '48 hs' in description
    assert 'agotar stock' in description
    assert 'CONSULTÁ' not in description and 'C.F.T' not in description
    assert any(l.type=='stock' and l.quantity==3500 for l in stage.limits)


def test_presale_unknown_dates_remain_unknown_without_borrowing_general_validity():
    r=raw('3040_6908')
    r['detail']['legal']=r['detail']['legal'].replace(
        'Preventa del 22/04/26 a las 10hs AM por 48 hs o hasta agotar stock, lo que suceda primero',
        'Preventa para clientes Santander con fechas a confirmar')
    stage=next(p for p in SantanderNormalizer().normalize_many(r) if p.source_id.endswith(':presale'))
    assert stage.valid_from is stage.valid_to is None
    assert 'fechas a confirmar' in stage.benefits[0].description


def test_presale_duration_in_following_positive_sentence_is_preserved():
    # Lollapalooza has a source sentence break between start time and 24-hour duration.
    r=raw('1127_7560')
    r['detail']['legal']='<p>Preventa Santander Visa Crédito y Débito 04/06/26 a las 10hs. Por 24hs o hasta agotar stock, lo que suceda primero.</p>'
    stage=next(p for p in SantanderNormalizer().normalize_many(r) if p.source_id.endswith(':presale'))
    assert stage.valid_from==date(2026,6,4) and stage.valid_to is None
    assert 'Por 24hs' in stage.benefits[0].description


def test_qa011_grido_general_eligibility_reconciles_types_with_warning():
    r=raw('3459_7492')
    p,=SantanderNormalizer().normalize_many(r)
    assert {(m.network,m.card_type,m.wallet,m.payment_rail) for m in p.payment_methods}=={
        ('VISA',typ,wallet,'qr') for typ in ['credit','debit'] for wallet in ['App Santander','MODO']}
    assert 'Conflicto de tipos de tarjeta' in p.specific_conditions
    assert 'VISA RECARGABLE' in p.specific_conditions
    assert any(card['codeType']=='R' for card in r['detail']['cards'])
    assert next(l for l in p.limits if l.type=='monetary_cap').amount==Decimal('10000')
    assert 'Conflicto de tope mensual' not in p.specific_conditions


@pytest.mark.parametrize('name',['3459_7493','267_7961','168_6211'])
def test_analogous_positive_type_clauses_exclude_contradicted_prepaid(name):
    rows=normalize(name)
    assert all(m.card_type!='prepaid' for p in rows for m in p.payment_methods)
    assert all('Conflicto de tipos de tarjeta' in p.specific_conditions for p in rows)
    assert any(m.card_type=='credit' for p in rows for m in p.payment_methods)


def test_explicit_prepaid_sources_are_preserved():
    for name in ['107_7150','53_7857']:
        rows=normalize(name)
        assert any(m.card_type=='prepaid' for p in rows for m in p.payment_methods)
        assert all('Conflicto de tipos de tarjeta' not in p.specific_conditions for p in rows)


def test_positive_network_type_scopes_filter_actual_combinations_without_cross_product():
    r=raw('3492_7598')
    r['detail']['legal']='<p>Válida abonando con Tarjetas Santander Visa débito y Mastercard crédito.</p>'
    rows=SantanderNormalizer().normalize_many(r)
    assert {(m.network,m.card_type) for p in rows for m in p.payment_methods}=={('VISA','debit'),('MASTER','credit')}
    assert all(m.network!='AMEX' for p in rows for m in p.payment_methods)


def test_separate_positive_card_clauses_preserve_each_scoped_alternative():
    r=raw('3492_7598')
    r['detail']['legal']='<p>Válida con Tarjeta Santander Visa débito. Válida con Tarjeta Santander Mastercard crédito.</p>'
    rows=SantanderNormalizer().normalize_many(r)
    assert {(m.network,m.card_type) for p in rows for m in p.payment_methods}=={('VISA','debit'),('MASTER','credit')}


@pytest.mark.parametrize('clause',[
    'No aplica para Tarjetas Santander Visa crédito.',
    'Se excluyen compras con Tarjetas Santander Visa crédito.',
    'Ejemplo: una compra con Tarjeta Santander Visa crédito.',
])
def test_negative_or_example_type_mentions_do_not_become_positive_constraints(clause):
    r=raw('3459_7492');r['detail']['legal']='<p>'+clause+'</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert {m.card_type for m in p.payment_methods}=={'credit','debit','prepaid'}
    assert 'Conflicto de tipos de tarjeta' not in p.specific_conditions


def test_ambiguous_network_type_attachment_is_reported_as_unstructured_eligibility():
    r=raw('3492_7598')
    r['detail']['legal']='<p>Válida con Tarjetas Santander Visa y débito Mastercard.</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert p.payment_methods==[]
    assert 'inequívocamente' in p.specific_conditions
    assert p.benefits


@pytest.mark.parametrize('name',['42_7928','545_7928'])
def test_credit_only_reconciliation_keeps_stable_credit_id_and_removes_unsupported_variant(name):
    r=raw(name)
    assert any(card['codeType']=='D' for card in r['detail']['cards'])
    p,=SantanderNormalizer().normalize_many(r)
    assert p.source_id==r['source_id']+':credit'
    assert {(m.network,m.card_type) for m in p.payment_methods}=={('VISA','credit')}
    assert 'installments' in {b.type for b in p.benefits}
    assert any(b.percentage is not None for b in p.benefits)
    assert 'Conflicto de tipos de tarjeta' in p.specific_conditions


def test_qa012_kilbel_keeps_weekly_and_additional_legal_monthly_caps_separate():
    p,=normalize('3472_7933')
    caps=[l for l in p.limits if l.type=='monetary_cap']
    assert {(l.amount,l.currency,l.period) for l in caps}=={
        (Decimal('6000'),'ARS','weekly'),(Decimal('10000'),'ARS','monthly')}
    assert next(l for l in caps if l.period=='monthly').scope=='account'
    assert any(l.type=='minimum_purchase' and l.amount==Decimal('50000') for l in p.limits)
    assert all(m.payment_rail=='qr' for m in p.payment_methods)
    assert 'los importes no se suman' in p.specific_conditions
    assert 'Conflicto de tope mensual' not in p.specific_conditions
    assert '$10.000 por mes' in p.terms


def test_qa012_monthly_cap_uses_changed_source_value_without_fallback():
    r=raw('3472_7933')
    r['detail']['legal']=r['detail']['legal'].replace('Tope de reintegro $10.000 por mes','Tope de reintegro $12.345 por mes')
    p,=SantanderNormalizer().normalize_many(r)
    assert {(l.amount,l.period) for l in p.limits if l.type=='monetary_cap'}=={
        (Decimal('6000'),'weekly'),(Decimal('12345'),'monthly')}


@pytest.mark.parametrize('excluded',[
    'Ejemplo: tope de reintegro $99.000 por mes.',
    'No aplica un tope de reintegro $99.000 por mes.',
    'Se excluyen compras con tope de reintegro $99.000 por mes.',
])
def test_cross_period_cap_is_not_invented_from_examples_or_negative_clauses(excluded):
    r=raw('3472_7933')
    r['detail']['legal']='<p>Beneficio con tarjetas Santander. '+excluded+'</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert {(l.amount,l.period) for l in p.limits if l.type=='monetary_cap'}=={(Decimal('6000'),'weekly')}


def test_same_period_conflict_is_not_misrepresented_as_independent_monthly_caps():
    p,=normalize('393_7950')
    caps=[l for l in p.limits if l.type=='monetary_cap' and l.period=='monthly']
    assert len(caps)==1 and caps[0].amount is None
    assert 'Conflicto de tope mensual' in p.specific_conditions


def test_qa013_diarco_attributes_unlimited_description_despite_null_api_cap():
    r=raw('151_7929');assert r['detail']['topAmount'] is None
    assert r['detail']['texts']['description']=='Sin tope de reintegro'
    p,=SantanderNormalizer().normalize_many(r)
    assert any(l.type=='monetary_cap' and l.amount==Decimal('15000') and l.period=='monthly' and l.scope=='account' for l in p.limits)
    assert any(l.type=='minimum_purchase' and l.amount==Decimal('100000') for l in p.limits)
    assert all(m.payment_rail=='qr' for m in p.payment_methods)
    assert 'Conflicto de tope' in p.specific_conditions
    assert 'detail.texts.description' in p.specific_conditions
    assert 'Afirmación publicada discordante: «Sin tope de reintegro' in p.specific_conditions
    assert 'verificar las condiciones con Santander' in p.specific_conditions
    assert p.terms==r['detail']['legal']
    assert r['detail']['texts']['description']=='Sin tope de reintegro'


@pytest.mark.parametrize('field',['description','subtitle','title','additionalText','specialCondition'])
def test_unlimited_claim_fields_reconcile_against_legal_cap_when_api_cap_is_null(field):
    r=raw('151_7929')
    r['detail']['texts']['description']=''
    r['program']['texts']['description']=''
    if field in {'additionalText','specialCondition'}:
        r['detail'][field]='Sin tope de reintegro'
        path='detail.'+field
    else:
        r['detail']['texts'][field]='Sin tope de reintegro'
        path='detail.texts.'+field
    p,=SantanderNormalizer().normalize_many(r)
    assert 'Conflicto de tope' in p.specific_conditions and path in p.specific_conditions
    assert any(l.type=='monetary_cap' and l.amount==Decimal('15000') for l in p.limits)
    if field=='title':
        assert 'tope sujeto a confirmación' in p.title


def test_genuine_unlimited_offer_without_contradicting_cap_is_preserved():
    p,=normalize('2_7955')
    assert p.limits==[]
    assert 'Sin tope de reintegro' in p.specific_conditions
    assert 'Conflicto de tope' not in p.specific_conditions
    assert 'Afirmación publicada discordante' not in p.specific_conditions


def test_unknown_cap_is_not_converted_into_an_unlimited_claim():
    r=raw('2_7955')
    r['detail']['texts']['description']=''
    r['program']['texts']['description']=''
    r['detail']['legal']='<p>Beneficio disponible para clientes Santander.</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert p.limits==[]
    assert 'sin tope' not in p.specific_conditions.lower()
    assert 'Conflicto de tope' not in p.specific_conditions


@pytest.mark.parametrize('legal',[
    'Beneficio. Ejemplo: tope mensual: $99.000.',
    'No aplica un tope mensual: $99.000.',
    'Tope mensual para clientes Select: $99.000.',
])
def test_unlimited_claim_is_not_contradicted_by_example_negative_or_other_segment_cap(legal):
    r=raw('151_7929');r['detail']['productSegmentation']='Sorpresa'
    r['detail']['legal']='<p>'+legal+'</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert not any(l.type=='monetary_cap' for l in p.limits)
    assert 'Conflicto de tope' not in p.specific_conditions
    assert 'Afirmación publicada discordante' not in p.specific_conditions


@pytest.mark.parametrize('name,cap',[('146_8000','120000'),('146_8001','300000')])
def test_despegar_budget_and_per_device_reservation_usage(name,cap):
    p,=normalize(name)
    assert p.benefits[0].type=='discount'
    assert any(l.type=='monetary_cap' and l.amount==Decimal(cap) for l in p.limits)
    assert any(l.type=='stock' and l.amount==Decimal('15400000') and l.currency=='ARS' and l.scope=='campaign' for l in p.limits)
    assert {l.scope for l in p.limits if l.type=='usage_count' and l.quantity==1}=={'device','reservation'}
    assert 'dispositivo y por reserva' in p.specific_conditions


def test_minimum_purchase_phrase_has_no_economic_fallback():
    r=raw('60_7557');r['detail']['legal']='<p>Compras mayor o iguales a $15.000.</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert any(l.type=='minimum_purchase' and l.amount==Decimal('15000') for l in p.limits)
    r['detail']['legal']='<p>Compras mayor o iguales a importe no informado.</p>'
    p,=SantanderNormalizer().normalize_many(r)
    assert not any(l.type=='minimum_purchase' for l in p.limits)


def test_unknown_dates_weekdays_and_negative_channel_mentions():
    r=raw('60_7557');r['detail'].update(initialDate=None,endDate=None,legal='<p>Responsabilidad del banco. No aplica los sábados online.</p>')
    for day in ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']:r['detail'][day]=False
    p,=SantanderNormalizer().normalize_many(r)
    assert p.valid_from is p.valid_to is None
    assert p.days_of_week==[] and p.applies_every_day is None
    assert p.online is p.physical is None
    r['detail']['customerDiscount']=None
    with pytest.raises(ValueError,match='No evidenced benefit'):SantanderNormalizer().normalize_many(r)


@pytest.mark.parametrize('field',['legal','texts'])
def test_blank_required_evidence_blocks_normalization(field):
    r=raw('60_7557');r['detail'][field]='   ' if field=='legal' else {'title':'   '}
    with pytest.raises(ValueError):SantanderNormalizer().normalize_many(r)


def test_all_fixture_variants_unique_and_no_legacy_output_fields():
    ids=set()
    for f in FIXTURES.glob('*.json'):
        for p in SantanderNormalizer().normalize_many(json.loads(f.read_text(encoding='utf8'))):
            assert p.source_id not in ids;ids.add(p.source_id)
            assert not {'discount_percentage','installments','cap_amount','qr','nfc'}&set(p.model_dump())
