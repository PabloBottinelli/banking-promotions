from copy import deepcopy
from decimal import Decimal
from itertools import product
import json
from pathlib import Path

import pytest

from normalization.sources.bbva import BBVANormalizer
from scraping.sources.bbva.scraper import BBVAScraper


OFFICIAL_IDS = ['85446', '86124', '86599', '85699', '85698', '85697', '85700',
                '85828', '85830', '85829', '86761', '87809', '87558', '87904']


@pytest.fixture
def official_caps():
    path = Path(__file__).parents[1] / 'fixtures/bbva/official_cap_conflicts.json'
    return {row['source_id']: row for row in json.loads(path.read_text(encoding='utf8'))}


def cap_raw(terms, amount='20000', requirements=None, period='Por Mes'):
    return {'source': 'bbva', 'source_id': 'synthetic', 'scraped_at': '2026-10-22T12:00:00+00:00',
            'catalog': {'id': 'synthetic', 'cabecera': 'Comercio', 'montoTope': amount},
            'detail': {'id': 'synthetic', 'cabecera': 'Comercio', 'basesCondiciones': terms,
                       'beneficios': [{'tope': amount, 'frecuenciaTope': period,
                                       'requisitos': requirements or ['20% de reintegro con tarjetas BBVA']}]}}


@pytest.mark.parametrize('source_id', OFFICIAL_IDS)
def test_official_conflicting_cap_is_blocked_without_altering_raw(official_caps, source_id):
    raw = official_caps[source_id]
    before = deepcopy(raw)
    api_amount, legal_amount = ('25000', '25500') if source_id == '85446' else ('20000', '16000')
    legal_text = '$25.500 POR USUARIO POR MES' if source_id == '85446' else '$16.000 POR USUARIO POR MES'
    assert raw['detail']['beneficios'][0]['tope'] == api_amount
    assert legal_text in raw['detail']['basesCondiciones']
    with pytest.raises(ValueError, match='conflicting monetary cap') as error:
        BBVANormalizer().normalize_many(raw)
    assert api_amount in str(error.value) and legal_amount in str(error.value)
    assert 'conflicting monetary cap' in '; '.join(BBVANormalizer().review_normalized(raw, []))
    assert 'conflicting monetary cap' in '; '.join(BBVAScraper._commercial_review([raw]))
    assert raw == before


@pytest.mark.parametrize('legal', [
    'Tope de $20.000 por usuario por mes.',
    'Tope máximo de reintegro mensual de ARS 20.000.',
    'Tope de reintegro: $20.000,00 por cliente por mes.',
])
def test_matching_cap_accepts_legal_amount_formats(legal):
    raw = cap_raw('20% de reintegro. ' + legal)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == Decimal('20000')
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('api,legal', [('12345', '12000'), ('18000', '22000')])
def test_amount_conflict_is_general_and_does_not_choose_the_smaller_cap(api, legal):
    raw = cap_raw(f'20% de reintegro. Tope de ${legal} por cliente por mes.', api)
    with pytest.raises(ValueError, match='conflicting monetary cap'):
        BBVANormalizer().normalize_many(raw)


def test_minimum_stock_quantities_and_example_caps_are_not_offer_caps():
    raw = cap_raw('20% de reintegro. Tope de $20.000 por mes. Compra mínima: $50.000. '
                  'Stock de 25 cupones por partido. Máximo 2 compras por mes. '
                  'Ejemplo de cálculo de otro producto: compra de $80.000 y tope de $16.000.')
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 20000
    assert any(limit.type == 'minimum_purchase' and limit.amount == 50000 for limit in promotion.limits)
    assert any(limit.type == 'stock' and limit.quantity == 25 for limit in promotion.limits)
    assert not BBVAScraper._commercial_review([raw])


def test_different_period_caps_are_not_amount_contradictions():
    raw = cap_raw('20% de reintegro. Tope de $20.000 por mes y tope de $80.000 por vigencia.')
    assert not BBVANormalizer().review_normalized(raw, BBVANormalizer().normalize_many(raw))
    raw['detail']['beneficios'][0].update(tope='80000', frecuenciaTope='Por Vigencia de la Promocion')
    raw['catalog']['montoTope'] = '80000'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('requirements,terms,amount', [
    (['20% de reintegro para clientes Black'],
     '20% de reintegro. Clientes Black: tope de $30.000 por mes. Clientes Gold: tope de $10.000 por mes.', '30000'),
    (['20% de reintegro para clientes Gold'],
     '20% de reintegro. Clientes Black: tope de $30.000 por mes. Clientes Gold: tope de $10.000 por mes.', '10000'),
    (['20% de reintegro para clientes Gold'],
     '20% de reintegro. Clientes Black: tope de $30.000 por mes y clientes Gold: tope de $10.000 por mes.', '10000'),
    (['20% de reintegro pagando con QR'],
     '20% de reintegro. Pagos con QR: tope de $20.000 por mes. Pagos con NFC: tope de $10.000 por mes.', '20000'),
    (['20% de reintegro en un pago'],
     '20% de reintegro. En un pago: tope de $20.000 por mes. En 3 cuotas: tope de $10.000 por mes.', '20000'),
    (['20% de reintegro. Compras superiores a $50.000'],
     '20% de reintegro. Compras superiores a $50.000: tope de $20.000 por mes. Compras superiores a $90.000: tope de $30.000 por mes.', '20000'),
])
def test_explicit_segment_or_payment_conditions_disambiguate_caps(requirements, terms, amount):
    raw = cap_raw(terms, amount, requirements)
    assert not BBVAScraper._commercial_review([raw])
    assert BBVANormalizer().normalize(raw).limits[0].amount == Decimal(amount)


def test_unmapped_conditional_caps_require_review_even_if_one_amount_matches():
    raw = cap_raw('20% de reintegro. Clientes Black: tope de $20.000 por mes. '
                  'Clientes Gold: tope de $10.000 por mes.')
    with pytest.raises(ValueError, match='unresolved conditional monetary caps'):
        BBVANormalizer().normalize_many(raw)


def test_inherited_card_group_disambiguates_cap_segment():
    raw = cap_raw('20% de reintegro. Clientes Black: tope de $30.000 por mes. '
                  'Clientes Gold: tope de $10.000 por mes.', '30000')
    raw['detail']['grupoTarjeta'] = 'Tarjetas BBVA Black'
    assert not BBVAScraper._commercial_review([raw])


def test_structured_installments_disambiguate_payment_modality_caps():
    raw = cap_raw('20% de reintegro. En un pago: tope de $30.000 por mes. '
                  'En 3 cuotas: tope de $20.000 por mes.')
    raw['detail']['beneficios'][0]['cuota'] = 3
    assert not BBVAScraper._commercial_review([raw])


def test_caps_for_different_benefits_are_not_compared_as_one():
    raw = cap_raw('Reintegro en alimentos: tope de $20.000 por mes. '
                  'Descuento en entradas: tope de $10.000 por mes.')
    assert BBVANormalizer().normalize(raw).limits[0].amount == 20000
    assert not BBVAScraper._commercial_review([raw])


def test_explicit_scopes_disambiguate_simultaneous_caps():
    raw = cap_raw('20% de reintegro. Tope de $20.000 por tarjeta por mes. '
                  'Tope de $50.000 por cliente por mes.')
    raw['detail']['beneficios'][0]['tipoTope'] = 'Por tarjeta'
    assert not BBVAScraper._commercial_review([raw])
    assert BBVANormalizer().normalize(raw).limits[0].amount == 20000


def test_distinct_products_map_each_api_cap_to_its_legal_clause():
    raw = cap_raw('20% de reintegro. Producto A: tope de $20.000 por mes. '
                  'Producto B: tope de $10.000 por mes.')
    raw['detail']['beneficios'] = [
        {'id': 'a', 'tope': '20000', 'frecuenciaTope': 'Por Mes', 'requisitos': ['20% de reintegro. Producto A']},
        {'id': 'b', 'tope': '10000', 'frecuenciaTope': 'Por Mes', 'requisitos': ['20% de reintegro. Producto B']},
    ]
    variants = BBVANormalizer().normalize_many(raw)
    assert len(variants) == 2
    assert {promotion.limits[0].amount for promotion in variants} == {Decimal('20000'), Decimal('10000')}
    assert not BBVAScraper._commercial_review([raw])
    raw['detail']['beneficios'][1]['tope'] = '20000'
    with pytest.raises(ValueError, match='conflicting monetary cap'):
        BBVANormalizer().normalize_many(raw)


def test_same_amount_period_contradiction_still_requires_review():
    raw = cap_raw('20% de reintegro. Tope de $20.000 por usuario por vigencia.')
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].period is None
    assert 'Fuente inconsistente' in promotion.specific_conditions
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('terms', [
    '20% de reintegro. Ejemplo: una compra de $100.000 recibe $20.000. '
    'Condiciones generales: tope de $16.000 por cliente por mes.',
    '20% de reintegro. Ejemplo de cálculo: compra de $100.000 con tope de $12.000. '
    'El beneficio tiene un tope de $16.000 por cliente por mes.',
    '20% de reintegro. EJEMPLOS: compra de $100.000 con tope de $12.000; '
    'Condiciones generales: tope de $16.000 por cliente por mes.',
    '20% de reintegro. Ver ejemplos de cálculo en la web. Tope de $16.000 por cliente por mes.',
    '20% de reintegro. Ejemplo: compra de $100.000 con tope de $12.000. '
    'Tope de $16.000 por cliente por mes. Ejemplo: otra compra con tope de $10.000.',
    '20% de reintegro. Ejemplo: una compra recibe $20.000. '
    'Condiciones generales: tope de $16.000 por cliente por mes.',
    '<p>20% de reintegro.</p><p>Ejemplo: compra con tope de $12.000</p>'
    '<p>Tope de $16.000 por cliente por mes.</p>',
    '20% de reintegro. Ejemplo: compra con tope de $12.000 '
    'Condiciones generales: tope de $16.000 por cliente por mes.',
    '20% de reintegro. Ejemplo: una compra recibe $20.000;Tope de $16.000 por cliente por mes.',
    '20% de reintegro. Ejemplo: una compra recibe $20.000.Tope de $16.000 por cliente por mes.',
])
def test_contractual_caps_after_examples_are_not_discarded(terms):
    raw = cap_raw(terms)
    original = deepcopy(raw)
    normalizer = BBVANormalizer()
    with pytest.raises(ValueError, match='conflicting monetary cap') as error:
        normalizer.normalize_many(raw)
    assert '16000' in str(error.value)
    assert normalizer.review_normalized(raw, [])
    assert BBVAScraper._commercial_review([raw])
    assert raw == original


@pytest.mark.parametrize('terms', [
    '20% de reintegro. Tope de $20.000 por mes. '
    'Ejemplo: una compra de $100.000 con tope de $12.000.',
    '20% de reintegro. Ejemplo: compra con tope de $12.000. '
    'Tope de $20.000 por cliente por mes.',
    '<p>20% de reintegro.</p><p>Ejemplo: compra con tope de $12.000</p>'
    '<p>Tope de $20.000 por cliente por mes.</p>',
    '20% de reintegro. Por ejemplo, una compra con tope de $12.000; '
    'Condiciones generales: tope de $20.000 por cliente por mes.',
    '20% de reintegro. Ejemplo: compra con tope de $12.000 '
    'Condiciones generales: tope de $20.000 por cliente por mes.',
])
def test_illustrative_caps_do_not_conflict_with_the_contractual_cap(terms):
    raw = cap_raw(terms)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 20000
    assert not BBVAScraper._commercial_review([raw])
    assert promotion.terms == BBVANormalizer()._clean_text(terms)


@pytest.mark.parametrize('period,requires_review', [('mes', False), ('vigencia', True)])
def test_example_period_cannot_override_contractual_period(period, requires_review):
    raw = cap_raw('20% de reintegro. Ejemplo: tope de $20.000 por cliente por mes. '
                  f'Tope de $20.000 por cliente por {period}.')
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].period == (None if requires_review else 'monthly')
    assert bool(BBVAScraper._commercial_review([raw])) is requires_review


@pytest.mark.parametrize('period,requires_review', [('mes', False), ('vigencia', True)])
def test_missing_structured_cap_is_taken_from_contract_not_example(period, requires_review):
    raw = cap_raw('20% de reintegro. Ejemplo: tope de $12.000 por mes. '
                  f'Tope de $16.000 por cliente por {period}.', amount=None)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 16000
    assert promotion.limits[0].period == (None if requires_review else 'monthly')
    assert bool(BBVAScraper._commercial_review([raw])) is requires_review


def test_example_alone_does_not_supply_an_unknown_cap():
    raw = cap_raw('20% de reintegro. Ejemplo: compra con tope de $12.000 por mes.', amount=None)
    promotion = BBVANormalizer().normalize(raw)
    assert not any(limit.type == 'monetary_cap' for limit in promotion.limits)


@pytest.mark.parametrize('separator', ['\n', '\r\n', '\r', '\u2028', '\u2029', '<br>', '</p><p>'])
def test_line_or_block_boundary_after_example_keeps_contractual_cap(separator):
    terms = ('20% de reintegro. Ejemplo: compra de $100.000 recibe $20.000'
             + separator + 'Tope de $16.000 por cliente por mes.')
    raw = cap_raw(terms)
    with pytest.raises(ValueError, match='conflicting monetary cap'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('wrapper', [('(', ')'), ('[', ']'), ('«', '»'), ('“', '”'), ('"', '"')])
def test_bounded_inline_examples_do_not_create_contractual_caps(wrapper):
    opening, closing = wrapper
    terms = ('20% de reintegro. Tope de $20.000 por mes. '
             + opening + 'Ejemplo: otra compra con tope de $12.000' + closing + '.')
    raw = cap_raw(terms)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 20000
    assert promotion.terms == BBVANormalizer()._clean_text(terms)
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('example', [
    '(Ejemplo: compra con tope de $12.000 (cálculo ilustrativo))',
    '(Ejemplo: compra con tope de $12.000. Otra compra con tope de $10.000.)',
    '(Ejemplo: compra con tope de $12.000\ny otra compra con tope de $10.000)',
    '(Por ejemplo, una compra con tope de $12.000)',
    '(Ejemplo: compra de $100.000 recibe $20.000)',
])
def test_contractual_cap_after_closing_example_is_preserved(example):
    raw = cap_raw('20% de reintegro. ' + example + ' Tope de $16.000 por cliente por mes.')
    with pytest.raises(ValueError, match='conflicting monetary cap'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('cap', [
    'Tope de\n$20.000 por cliente por vigencia.',
    'Tope de $20.000\npor cliente por vigencia.',
    'Tope de $20.000 por cliente\npor vigencia.',
    'Tope de $20.000 por cliente por\nvigencia.',
])
def test_wrapped_cap_period_remains_contractual(cap):
    raw = cap_raw('20% de reintegro. Ejemplo: compra con tope de $12.000. ' + cap)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].period is None
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('terms', [
    '20% de reintegro. Ejemplo: compra con tope de $12.000\nTope de $16.000 por mes.',
    '20% de reintegro. (Ejemplo: compra con tope de $12.000) Tope de $16.000 por mes.',
])
def test_missing_structured_cap_uses_contract_after_bounded_example(terms):
    raw = cap_raw(terms, amount=None)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 16000
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('opening', ['(', '[', '“', '"'])
def test_unclosed_example_with_cap_requires_explicit_review(opening):
    raw = cap_raw('20% de reintegro. Tope de $20.000 por mes. '
                  + opening + 'Ejemplo: otra compra con tope de $12.000')
    with pytest.raises(ValueError, match='unresolved example boundary'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


def test_bounded_examples_do_not_change_contractual_amount_or_approval():
    examples = ['(Ejemplo: otra compra con tope de $12.000)',
                '[Ejemplo: otra compra con tope de $12.000]',
                '«Ejemplo: otra compra con tope de $12.000»',
                '“Ejemplo: otra compra (hipotética) con tope de $12.000”',
                '"Ejemplo: otra compra con tope de $12.000"',
                '(Ejemplo: otra compra con tope de $12.000\ny otra con tope de $10.000)']
    for example, separator, before, amount in product(examples, [' ', '\n', '; ', '<br>'], [False, True], ['20000', '16000']):
        contract = f'Tope de ${amount} por cliente por mes.'
        fragments = [example, contract] if before else [contract, example]
        raw = cap_raw('20% de reintegro. ' + separator.join(fragments))
        if amount == '16000':
            with pytest.raises(ValueError, match='conflicting monetary cap'):
                BBVANormalizer().normalize_many(raw)
            assert BBVAScraper._commercial_review([raw])
        else:
            promotion = BBVANormalizer().normalize(raw)
            assert promotion.limits[0].amount == 20000 and promotion.limits[0].period == 'monthly'
            assert not BBVAScraper._commercial_review([raw])
