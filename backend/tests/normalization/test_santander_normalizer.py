"""Official BFF excerpts; expected values read from source, not generated output."""
import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest
from normalization.sources.santander import SantanderNormalizer

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/santander'


def raw(identifier):
    return json.loads((FIXTURES/(identifier+'.json')).read_text(encoding='utf8'))


def test_cafe_qr_cashback_sorpresa_and_legal_dates():
    row = raw('60_7558')
    p, = SantanderNormalizer().normalize_many(row)
    assert p.benefits[0].type == 'cashback'
    assert p.benefits[0].percentage == Decimal('20')
    assert p.valid_to == date(2026,10,31)  # legal, versus Oct 28 presentation window
    assert p.valid_from == date(2026,8,4)
    assert p.days_of_week == ['tuesday','wednesday']
    assert p.applies_every_day is None  # contradictory trailing "todos los días" cannot override flags
    assert {(m.network,m.card_type,m.wallet,m.payment_rail) for m in p.payment_methods} == {
        ('VISA','debit','App Santander','qr'),('VISA','credit','App Santander','qr'),
        ('VISA','debit','MODO','qr'),('VISA','credit','MODO','qr')}
    assert p.online is None
    assert p.limits[0].amount == Decimal('20000')
    assert p.limits[0].currency == 'ARS'
    assert p.limits[0].period == 'monthly'
    assert p.requires_merchant_verification
    assert 'adheridos' in p.specific_conditions
    assert 'Sorpresa' in p.specific_conditions
    assert 'difiere' in p.specific_conditions
    assert p.terms == row['detail']['legal']
    assert p.model_dump(mode='json')['benefits'][0]['percentage'] == '20'


def test_cinepolis_genuine_two_for_one_not_invented_percentage():
    p, = SantanderNormalizer().normalize_many(raw('107_7150'))
    assert p.benefits[0].type == 'other'
    assert p.benefits[0].description == '2x1 en entradas'
    assert p.benefits[0].percentage is None
    assert 'NO APLICA SOBRE TARIFA DE MENORES' in p.specific_conditions


def test_event_financing_and_presale_are_separate_compatible_benefits():
    variants = SantanderNormalizer().normalize_many(raw('1127_7560'))
    assert any(b.type=='installments' and b.installment_options==[6] and b.interest_free is True for p in variants for b in p.benefits)
    assert any(b.type=='other' and 'Preventa' in b.description for p in variants for b in p.benefits)
    for p in variants:
        if any(b.type=='installments' for b in p.benefits):
            assert all(m.card_type=='credit' for m in p.payment_methods)
    assert any(l.type=='stock' and l.quantity==5000 for p in variants for l in p.limits)
    assert any(l.type=='usage_count' and l.quantity==4 for p in variants for l in p.limits)


def test_transport_is_qr_transfer_not_card_or_online():
    p, = SantanderNormalizer().normalize_many(raw('2960_7899'))
    assert p.benefits[0].percentage==Decimal('100')
    assert p.applies_every_day is True
    assert all(m.card_type is None and m.payment_rail=='qr' for m in p.payment_methods)
    assert {m.wallet for m in p.payment_methods}=={'App Santander','MODO'}
    assert p.online is None
    assert 'saldo mínimo de $1200' in p.specific_conditions
    assert 'dos reintegros' in p.specific_conditions
    assert not any(l.type=='minimum_purchase' for l in p.limits)


def test_nfc_complete_wallet_options_and_external_app_rail():
    p,=SantanderNormalizer().normalize_many(raw('131_8075'))
    assert p.benefits[0].type=='discount'
    assert {(m.wallet,m.network,m.card_type,m.payment_rail) for m in p.payment_methods}=={
        ('Apple Pay','VISA','debit','nfc'),('Google Pay','VISA','debit','nfc'),('MODO Contactless','VISA','debit','nfc')}
    assert p.physical is True
    ypf,=SantanderNormalizer().normalize_many(raw('546_7909'))
    assert all(m.wallet=='App YPF' and m.payment_rail=='card' for m in ypf.payment_methods)
    assert ypf.online is None


def test_presale_stage_does_not_broaden_financing_or_debit_eligibility():
    rows=SantanderNormalizer().normalize_many(raw('1127_7560'))
    presale=next(p for p in rows if p.source_id.endswith(':presale'))
    finance=next(p for p in rows if any(b.type=='installments' for b in p.benefits))
    assert presale.valid_from==date(2026,8,3)
    assert presale.valid_to==date(2026,8,4)
    assert presale.benefits[0].type=='other'
    assert not any(b.type=='installments' for b in presale.benefits)
    assert all(m.card_type=='credit' for m in finance.payment_methods)
    assert any(l.type=='stock' and l.period=='presale' for l in presale.limits)
    assert not any(l.type=='stock' and l.period=='presale' for l in finance.limits)


def test_arteba_legal_cap_currency_and_usage():
    p,=SantanderNormalizer().normalize_many(raw('39_7934'))
    assert p.valid_from==date(2025,10,3)
    assert p.limits[0].amount==Decimal('8400')
    assert p.limits[0].currency=='ARS'
    assert any(l.type=='usage_count' and l.quantity==4 for l in p.limits)


def test_shopping_and_credit_noncredit_variants_do_not_stack():
    rows=SantanderNormalizer().normalize_many(raw('387_7757'))
    assert len(rows)==2
    assert all(p.scope=='shopping' for p in rows)
    assert len({p.promotion_group_id for p in rows})==1
    assert any(b.type=='installments' for b in rows[0].benefits)
    assert not any(b.type=='installments' for b in rows[1].benefits)
    changed=raw('387_7757');changed['catalog']['name']='Changed marketing';changed['detail']['order']=999
    assert [p.source_id for p in SantanderNormalizer().normalize_many(changed)]==[p.source_id for p in rows]


def test_unknown_dates_weekdays_channels_are_nullable_and_no_rate_fallback():
    r=raw('60_7557');r['detail'].update(initialDate=None,endDate=None,legal='<p>Beneficio disponible. Responsabilidad del banco. No aplica los sábados online.</p>')
    for day in ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']: r['detail'][day]=False
    p,=SantanderNormalizer().normalize_many(r)
    assert p.valid_from is p.valid_to is None
    assert p.days_of_week==[] and p.applies_every_day is None
    assert p.online is None and p.physical is None
    r['detail']['customerDiscount']=None
    with pytest.raises(ValueError,match='No evidenced benefit'): SantanderNormalizer().normalize_many(r)


@pytest.mark.parametrize('field',['legal','texts'])
def test_blank_evidence_fails(field):
    r=raw('60_7557');r['detail'][field]='   ' if field=='legal' else {'title':'   '}
    with pytest.raises(ValueError):SantanderNormalizer().normalize_many(r)


def test_all_fixture_variants_have_unique_ids_and_no_legacy_fields():
    ids=set()
    for f in FIXTURES.glob('*.json'):
        for p in SantanderNormalizer().normalize_many(json.loads(f.read_text(encoding='utf8'))):
            assert p.source_id not in ids;ids.add(p.source_id)
            assert not {'discount_percentage','installments','cap_amount','qr','nfc'} & set(p.model_dump())
