from copy import deepcopy
from decimal import Decimal
import json

import httpx
import pytest

from normalization.sources.bbva import BBVANormalizer
from scraping.sources.bbva.scraper import BBVAScraper


QA013 = ['Tope de 16.000 pesos por mes.', 'Tope de reintegro: 16.000 ARS por mes.']
REPRESENTATIONS = ['{amount} pesos', 'ARS {amount}', '{amount} ARS', '$ {amount}', '{amount} $',
                   'Pesos argentinos {amount}', '{amount} PESOS ARGENTINOS', 'AR$ {amount}']


def raw_cap(legal, amount='20000', requirements=None):
    return {'source': 'bbva', 'source_id': 'coverage', 'scraped_at': '2026-10-22T12:00:00+00:00',
            'catalog': {'id': 'coverage', 'cabecera': 'Comercio', 'montoTope': amount},
            'detail': {'id': 'coverage', 'cabecera': 'Comercio', 'basesCondiciones': '20% de reintegro. ' + legal,
                       'beneficios': [{'tope': amount, 'frecuenciaTope': 'Por Mes',
                                       'requisitos': requirements or ['20% de reintegro']}]}}


@pytest.mark.parametrize('legal', QA013)
def test_qa013_is_an_explicit_conflict(legal):
    raw = raw_cap(legal)
    before = deepcopy(raw)
    with pytest.raises(ValueError, match='conflicting monetary cap') as error:
        BBVANormalizer().normalize_many(raw)
    assert '20000' in str(error.value) and '16000' in str(error.value)
    assert 'conflicting monetary cap' in '; '.join(BBVAScraper._commercial_review([raw]))
    assert raw == before


def capture(tmp_path, candidate):
    previous = raw_cap('Tope de $20.000 por mes.')
    assert BBVANormalizer().normalize_many(previous)
    assert not BBVAScraper._commercial_review([previous])

    def handler(request):
        if request.url.path.endswith('/communications'):
            data = [candidate['catalog']] if request.url.params['pager'] == '0' else []
            return httpx.Response(200, json={'code': 0, 'message': 'Comunicaciones: 1 paginas: 1', 'data': data})
        return httpx.Response(200, json={'code': 0, 'data': candidate['detail']})

    scraper = BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)), output_path=tmp_path / 'accepted.json')
    scraper.output_path.write_text(json.dumps([previous], ensure_ascii=False, indent=2), encoding='utf8')
    return scraper


@pytest.mark.parametrize('legal', QA013)
@pytest.mark.parametrize('defer_review', [False, True])
def test_qa013_cannot_replace_valid_snapshot(tmp_path, monkeypatch, legal, defer_review):
    scraper = capture(tmp_path, raw_cap(legal))
    before = scraper.output_path.read_bytes()
    with monkeypatch.context() as temporary:
        if defer_review:
            temporary.setattr(scraper, '_commercial_review', lambda rows: [])
        candidate = scraper.scrape()
    assert candidate.complete
    if not defer_review:
        assert scraper.coverage['snapshot_replace_allowed'] is False
        assert scraper.coverage['requires_review'] is True
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(candidate.promotions)
    assert scraper.output_path.read_bytes() == before
    assert scraper.coverage['snapshot_replace_allowed'] is False
    assert scraper.coverage['requires_review'] is True
    assert scraper.coverage['safe_to_deactivate'] is False
    assert not list(tmp_path.glob('.bbva_*.tmp'))


@pytest.mark.parametrize('representation', REPRESENTATIONS)
@pytest.mark.parametrize('number', ['20.000', '20000', '20.000,00', '20000,00', '20000.00', '20,000.00'])
def test_equivalent_money_representations_have_identical_commercial_result(representation, number):
    legal = 'Tope de reintegro: ' + representation.format(amount=number) + ' por cliente por mes.'
    raw = raw_cap(legal)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == Decimal('20000')
    assert promotion.limits[0].currency == 'ARS' and promotion.limits[0].period == 'monthly'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('representation', REPRESENTATIONS)
def test_contract_amount_mutation_always_blocks(representation):
    raw = raw_cap('Tope de ' + representation.format(amount='16.000,50') + ' por mes.')
    with pytest.raises(ValueError, match='conflicting monetary cap'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('legal', ['Tope de reintegro pendiente de definición.', 'Tope según condiciones.',
                                  'Tope de veinte mil pesos por mes.', 'Tope de 20.000 por mes.',
                                  'Tope de $20.000 o $16.000 según la compra.', 'Tope de 16 000 pesos por mes.'])
def test_every_unresolved_contractual_mention_requires_review(legal):
    raw = raw_cap(legal)
    with pytest.raises(ValueError, match='unresolved'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


def test_coverage_inventory_keeps_illustrations_incomplete_mentions_and_comparisons():
    raw = raw_cap('(Ejemplo: Tope de 7.000 pesos.) Tope de 20.000 ARS por mes. Tope a definir.')
    coverage = BBVANormalizer().cap_coverage(raw)
    assert coverage['complete'] is False
    assert len(coverage['mentions']) == 3
    assert [mention['classification'] for mention in coverage['mentions']] == ['example', 'contractual', 'contractual']
    assert [mention['status'] for mention in coverage['mentions']] == ['illustrative', 'interpreted', 'incomplete']
    assert coverage['mentions'][1]['amount'] == 20000
    assert coverage['mentions'][1]['currency'] == 'ARS'
    assert coverage['mentions'][1]['period'] == 'monthly'
    assert coverage['mentions'][1]['comparisons'][0]['result'] == 'matched'
    assert all(mention['original_fragment'] for mention in coverage['mentions'])


@pytest.mark.parametrize('representation', REPRESENTATIONS)
def test_requirement_only_cap_is_preserved_without_api_amount(representation):
    raw = raw_cap('', amount=None, requirements=['20% de reintegro',
                  'Tope de ' + representation.format(amount='20.000') + ' por mes.'])
    promotion = BBVANormalizer().normalize(raw)
    assert any(limit.type == 'monetary_cap' and limit.amount == 20000 and limit.currency == 'ARS'
               for limit in promotion.limits)
    coverage = BBVANormalizer().cap_coverage(raw)
    assert coverage['complete']
    assert coverage['mentions'][0]['origin'] == 'requirements'
    assert coverage['mentions'][0]['comparisons'][0]['result'] == 'legal_only'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('legal', ['Tope de 20.000 pesos uruguayos por mes.',
                                  'Tope de $20.000 por.', 'Tope de 20.000 ARS por quincena.'])
def test_unknown_currency_qualifier_or_period_requires_review(legal):
    raw = raw_cap(legal)
    assert not BBVANormalizer().cap_coverage(raw)['complete']
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('legal,quantity,kind,period', [
    ('Tope de 3 usos por mes.', 3, 'usage_count', 'monthly'),
    ('Tope de stock de 25 unidades.', 25, 'stock', None),
    ('Tope de 4.200 millas por mes.', 4200, 'other', 'monthly'),
])
def test_non_monetary_mentions_are_typed_and_preserved(legal, quantity, kind, period):
    raw = raw_cap(legal, amount=None)
    promotion = BBVANormalizer().normalize(raw)
    assert any(limit.type == kind and limit.quantity == quantity and limit.period == period
               and limit.amount is None and limit.currency is None for limit in promotion.limits)
    coverage = BBVANormalizer().cap_coverage(raw)
    assert coverage['complete']
    assert coverage['mentions'][0]['comparisons'][0]['result'] == 'excluded_non_monetary'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('legal', [
    '(Ejemplo: tope de 7.000 pesos.) Tope de <b>20.000</b> ARS por mes.',
    '“Ejemplo: tope de 7.000 pesos!” Tope de 20.000 ARS por mes.',
    '<p>Ejemplo: tope de <i>7.000 pesos</i>!</p><hr><p>Tope de <b>20.000 ARS</b> por mes.</p>',
    '<table><tr><td>Ejemplo: tope de 7.000 pesos?</td></tr>'
    '<tr><td>Tope de reintegro</td><td><strong>20.000</strong> ARS por mes</td></tr></table>',
])
@pytest.mark.parametrize('contract_amount', ['20.000', '16.000'])
def test_new_currency_forms_preserve_contract_after_nested_examples(legal, contract_amount):
    raw = raw_cap(legal.replace('20.000', contract_amount))
    coverage = BBVANormalizer().cap_coverage(raw)
    assert len(coverage['mentions']) == 2
    assert coverage['mentions'][0]['status'] == 'illustrative'
    if contract_amount == '20.000':
        assert coverage['complete']
        assert not BBVAScraper._commercial_review([raw])
        assert BBVANormalizer().normalize(raw).terms == BBVANormalizer()._clean_text(raw['detail']['basesCondiciones'])
    else:
        assert not coverage['complete']
        with pytest.raises(ValueError, match='conflicting monetary cap'):
            BBVANormalizer().normalize_many(raw)


@pytest.mark.parametrize('requirements,legal,expected', [
    (['20% de reintegro para clientes Black'],
     'Clientes Black: tope de 20.000 ARS por mes. Clientes Gold: tope de 10.000 pesos por mes.', 'different_conditions'),
    (['20% de reintegro pagando con QR'],
     'Pagos con QR: tope de 20.000 ARS por mes. Pagos con NFC: tope de 10.000 pesos por mes.', 'different_conditions'),
    (['20% de reintegro'],
     'Tope de 20.000 ARS por mes. Tope de 80.000 pesos por vigencia.', 'different_period'),
    (['20% de reintegro'],
     'Reintegro: tope de 20.000 ARS por mes. Descuento: tope de 10.000 pesos por mes.', 'different_conditions'),
])
def test_distinct_supported_conditions_are_auditable(requirements, legal, expected):
    raw = raw_cap(legal, requirements=requirements)
    coverage = BBVANormalizer().cap_coverage(raw)
    assert coverage['complete']
    assert coverage['mentions'][1]['comparisons'][0]['result'] == expected
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('legal', ['Tope a definir.', 'Tope de 20.000 por mes.',
                                  '<span>Ejemplo: tope de 7.000 pesos</span> Tope de 20.000 ARS por mes.'])
@pytest.mark.parametrize('defer_review', [False, True])
def test_incomplete_and_ambiguous_mentions_preserve_valid_baseline(tmp_path, monkeypatch, legal, defer_review):
    scraper = capture(tmp_path, raw_cap(legal))
    before = scraper.output_path.read_bytes()
    with monkeypatch.context() as temporary:
        if defer_review:
            temporary.setattr(scraper, '_commercial_review', lambda rows: [])
        result = scraper.scrape()
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_bytes() == before
    assert scraper.coverage['snapshot_replace_allowed'] is False
    assert scraper.coverage['requires_review'] is True
    assert scraper.coverage['safe_to_deactivate'] is False


def test_matching_new_currency_form_can_replace_temporary_valid_baseline(tmp_path):
    scraper = capture(tmp_path, raw_cap('Tope de 20.000,00 pesos por mes.'))
    result = scraper.scrape()
    assert scraper.coverage['snapshot_replace_allowed'] is True
    assert scraper.coverage['requires_review'] is False
    scraper.save_raw_promotions(result.promotions)
    assert json.loads(scraper.output_path.read_text(encoding='utf8')) == result.promotions
    assert scraper.coverage['safe_to_deactivate'] is False


def test_explicit_cap_reference_retains_its_antecedent():
    coverage = BBVANormalizer().cap_coverage(raw_cap(
        'Tope de 20.000 ARS por mes. El tope es compartido entre comercios adheridos.'))
    assert coverage['complete']
    assert coverage['mentions'][1]['status'] == 'resolved_reference'
    assert coverage['mentions'][1]['references'] == [0]


@pytest.mark.parametrize('legal', ['El tope es compartido entre comercios adheridos.',
                                  'Tope de veinte mil pesos compartido entre comercios adheridos.'])
def test_reference_without_interpretable_antecedent_is_incomplete(legal):
    raw = raw_cap(legal)
    assert not BBVANormalizer().cap_coverage(raw)['complete']
    assert BBVAScraper._commercial_review([raw])


def test_non_monetary_unlimited_clause_does_not_conflict_with_monetary_cap():
    raw = raw_cap('Tope de 20.000 ARS por mes. Sin tope de usos.')
    assert BBVANormalizer().cap_coverage(raw)['complete']
    assert BBVANormalizer().normalize(raw).limits[0].amount == 20000
    assert not BBVAScraper._commercial_review([raw])


def test_unlimited_clause_for_different_benefit_is_compared_by_eligibility():
    raw = raw_cap('Reintegro: tope de 20.000 ARS por mes. Descuento: sin tope.')
    coverage = BBVANormalizer().cap_coverage(raw)
    assert coverage['complete']
    assert coverage['mentions'][1]['comparisons'][0]['result'] == 'different_conditions'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('amount,blocked', [(None, False), ('20000', True)])
def test_explicit_monetary_unlimited_clause_is_checked(amount, blocked):
    raw = raw_cap('Sin tope de reintegro.', amount=amount)
    assert bool(BBVAScraper._commercial_review([raw])) is blocked
    assert BBVANormalizer().cap_coverage(raw)['complete'] is not blocked


def test_unlimited_clause_with_numeric_amount_is_ambiguous():
    raw = raw_cap('Sin tope de 16.000 pesos.', amount=None)
    assert not BBVANormalizer().cap_coverage(raw)['complete']
    assert BBVAScraper._commercial_review([raw])


def test_coverage_cannot_be_complete_without_a_benefit_to_compare():
    raw = raw_cap('Tope de 20.000 ARS por mes.')
    raw['detail']['beneficios'] = []
    assert not BBVANormalizer().cap_coverage(raw)['complete']
