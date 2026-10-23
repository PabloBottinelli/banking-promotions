from copy import deepcopy
import json
from pathlib import Path
from itertools import product

import httpx
import pytest

from normalization.sources.bbva import BBVANormalizer
from normalization.sources.bbva_evidence import parse_legal_evidence
from scraping.sources.bbva.scraper import BBVAScraper


MATRIX = json.loads((Path(__file__).parents[1] / 'fixtures/bbva/qa011_qa012_matrix.json').read_text(encoding='utf8'))['cases']
UNACCOUNTED = [
    ('Tope de "$16.000" por mes.', '20000'),
    ('Tope de\n"$16.000" por mes.', '20000'),
    ('Tope máximo aplicable: $16.000 por mes.', '20000'),
    ('Tope de $16 000 por mes.', '16'),
    ('Tope de $20.000 o $16.000 por mes según la compra.', '20000'),
    ('Tope de $20.000 por mes y $80.000 por vigencia.', '20000'),
]
NEGATIVE_CASES = [case for case in MATRIX if case['expected_block']] + [
    {'id': f'unaccounted-{index}', 'terms': '20% de reintegro. ' + terms, 'api_amount': amount}
    for index, (terms, amount) in enumerate(UNACCOUNTED)
]


def evidence_raw(terms):
    return {'source': 'bbva', 'source_id': 'qa-independent', 'scraped_at': '2026-10-22T12:00:00+00:00',
            'catalog': {'id': 'qa-independent', 'cabecera': 'Comercio', 'montoTope': '20000'},
            'detail': {'id': 'qa-independent', 'cabecera': 'Comercio', 'basesCondiciones': terms,
                       'beneficios': [{'tope': '20000', 'frecuenciaTope': 'Por Mes',
                                       'requisitos': ['20% de reintegro']}]}}


@pytest.mark.parametrize('case', MATRIX, ids=lambda case: case['id'])
def test_original_38_independent_expectations(case):
    raw = evidence_raw(case['terms'])
    before = deepcopy(raw)
    if case['expected_block']:
        with pytest.raises(ValueError, match='conflicting monetary cap'):
            BBVANormalizer().normalize_many(raw)
    else:
        promotions = BBVANormalizer().normalize_many(raw)
        assert len(promotions) == 1
        assert promotions[0].benefits[0].percentage == 20
        assert promotions[0].limits[0].amount == 20000
        assert promotions[0].limits[0].period == 'monthly'
        assert 'Ejemplo' in promotions[0].terms and 'Tope de $20.000' in promotions[0].terms
    review = BBVAScraper._commercial_review([raw])
    assert bool(review) is case['expected_block']
    if case['expected_block']:
        assert 'conflicting monetary cap' in '; '.join(review)
    assert raw == before


@pytest.mark.parametrize('case', NEGATIVE_CASES, ids=lambda case: case['id'])
@pytest.mark.parametrize('defer_review', [False, True])
def test_known_negative_cases_preserve_valid_snapshot_bytes(tmp_path, monkeypatch, case, defer_review):
    previous = evidence_raw('20% de reintegro. Tope de $20.000 por cliente por mes.')
    assert BBVANormalizer().normalize_many(previous)
    assert not BBVAScraper._commercial_review([previous])
    candidate = evidence_raw(case['terms'])
    candidate['catalog']['montoTope'] = case.get('api_amount', '20000')
    candidate['detail']['beneficios'][0]['tope'] = case.get('api_amount', '20000')

    def handler(request):
        if request.url.path.endswith('/communications'):
            data = [candidate['catalog']] if request.url.params['pager'] == '0' else []
            return httpx.Response(200, json={'code': 0, 'message': 'Comunicaciones: 1 paginas: 1', 'data': data})
        return httpx.Response(200, json={'code': 0, 'data': candidate['detail']})

    scraper = BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)), output_path=tmp_path / 'accepted.json')
    scraper.output_path.write_text(json.dumps([previous], ensure_ascii=False, indent=2), encoding='utf8')
    before = scraper.output_path.read_bytes()
    with monkeypatch.context() as temporary:
        if defer_review:
            temporary.setattr(scraper, '_commercial_review', lambda rows: [])
        result = scraper.scrape()
    assert result.complete
    if not defer_review:
        assert scraper.coverage['snapshot_replace_allowed'] is False
        assert scraper.coverage['requires_review'] is True
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.coverage['snapshot_replace_allowed'] is False
    assert scraper.coverage['requires_review'] is True
    assert scraper.coverage['safe_to_deactivate'] is False
    assert scraper.output_path.read_bytes() == before
    assert not list(tmp_path.glob('.bbva_*.tmp'))


@pytest.mark.parametrize('example', [
    '(Ejemplo: compra mínima: $90.000)',
    '«Ejemplo: compra mínima: $90.000»',
    '<p>Ejemplo: compra mínima: $90.000.</p>',
])
def test_example_minimum_cannot_override_later_contractual_minimum(example):
    terms = '20% de reintegro. Tope de $20.000 por mes. ' + example + ' Compra mínima: $50.000.'
    raw = evidence_raw(terms)
    promotion = BBVANormalizer().normalize(raw)
    assert next(limit for limit in promotion.limits if limit.type == 'minimum_purchase').amount == 50000
    assert '90.000' in promotion.terms and '50.000' in promotion.terms
    assert not BBVAScraper._commercial_review([raw])


def test_illustrative_currency_cannot_change_contractual_cap_currency():
    raw = evidence_raw('(Ejemplo: compra de USD 100.) 20% de reintegro. Tope de ARS 20.000 por mes.')
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 20000 and promotion.limits[0].currency == 'ARS'
    assert 'USD 100' in promotion.terms
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('separator,amount', list(product(['.', '!', '?', ';', '\n', '<br>', '<hr>', '</p><p>', '</td><td>'], ['16.000', '20.000'])))
def test_separators_preserve_contractual_caps_and_later_minimum(separator, amount):
    terms = ('<p><table><tr><td>20% de reintegro. Ejemplo: una compra recibe $12.000'
             + separator + f'Tope de ${amount} por mes. Compra mínima: $50.000.</td></tr></table></p>')
    raw = evidence_raw(terms)
    if amount == '16.000':
        with pytest.raises(ValueError, match='conflicting monetary cap'):
            BBVANormalizer().normalize_many(raw)
        assert BBVAScraper._commercial_review([raw])
    else:
        promotion = BBVANormalizer().normalize(raw)
        assert {(limit.type, limit.amount) for limit in promotion.limits} == {('monetary_cap', 20000), ('minimum_purchase', 50000)}
        assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('tag', ['strong', 'span', 'b', 'em', 'i', 'u'])
@pytest.mark.parametrize('illustration', ['Ejemplo: compra con tope de $12.000.', 'Ejemplo: compra con 80% de reintegro y tope de $12.000.'])
def test_inline_wrapping_at_every_character_preserves_classification(tag, illustration):
    terms = '20% de reintegro. ' + illustration + ' Tope de $20.000 por cliente por mes. Compra mínima: $50.000.'
    for index in range(1, len(terms)):
        formatted = f'<{tag}>' + terms[:index] + f'</{tag}>' + terms[index:]
        promotion = BBVANormalizer().normalize(evidence_raw(formatted))
        assert promotion.benefits[0].percentage == 20
        assert [(limit.type, limit.amount) for limit in promotion.limits] == [('monetary_cap', 20000), ('minimum_purchase', 50000)]
        assert not BBVAScraper._commercial_review([evidence_raw(formatted)])


@pytest.mark.parametrize('opening,closing', [('(', ')'), ('[', ']'), ('«', '»'), ('“', '”'), ('"', '"'), ("'", "'")])
@pytest.mark.parametrize('contract_first', [False, True])
def test_explicit_example_scope_survives_nested_blocks_and_punctuation(opening, closing, contract_first):
    example = opening + "Ejemplo: <div>compra en McDonald's con tope de $12.000!</div>"
    example += '<table><tr><td>otra compra con tope de $10.000?</td></tr></table>' + closing
    contract = '<p>20% de reintegro: Tope de $20.000 por mes; Compra mínima: $50.000.</p>'
    raw = evidence_raw(contract + example if contract_first else example + contract)
    promotion = BBVANormalizer().normalize(raw)
    assert [limit.amount for limit in promotion.limits] == [20000, 50000]
    assert '12.000' in promotion.terms and '10.000' in promotion.terms
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('example', [
    'Ejemplo: una compra recibe $12.000: Tope de $16.000 por mes.',
    'Ejemplo: una compra cualquiera: Tope de $16.000 por mes.',
    'Ejemplo: compra con tope de $12.000 Tope de $16.000 por mes.',
    '(Ejemplo: compra con tope de $12.000. Tope de $16.000 por mes.',
])
def test_ambiguous_scope_never_silently_accepts_api_amount(example):
    raw = evidence_raw('20% de reintegro. ' + example)
    with pytest.raises(ValueError, match='unresolved'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


def test_clause_roles_retain_complete_source_and_contracts_after_examples():
    text = '20% de reintegro. (Ejemplo: tope de $12.000!) Tope de $20.000 por mes; Compra mínima: $50.000.'
    evidence = parse_legal_evidence(text)
    assert evidence.text == text
    assert any(clause.kind == 'example' and '$12.000' in text[clause.start:clause.end] for clause in evidence.clauses)
    contracts = [text[clause.start:clause.end] for clause in evidence.clauses if clause.kind == 'contractual']
    assert any('$20.000' in clause for clause in contracts)
    assert any('$50.000' in clause for clause in contracts)
    assert '$12.000' not in evidence.contractual_text()


@pytest.mark.parametrize('terms,api_amount', UNACCOUNTED)
def test_unaccounted_contractual_cap_evidence_requires_review(terms, api_amount):
    raw = evidence_raw('20% de reintegro. ' + terms)
    raw['catalog']['montoTope'] = api_amount
    raw['detail']['beneficios'][0]['tope'] = api_amount
    with pytest.raises(ValueError, match='unresolved'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('case', [case for case in MATRIX if not case['expected_block']], ids=lambda case: case['id'])
def test_valid_illustrations_allow_temporary_snapshot_replacement(tmp_path, case):
    previous = evidence_raw('20% de reintegro. Tope de $20.000 por cliente por mes.')
    candidate = evidence_raw(case['terms'])

    def handler(request):
        if request.url.path.endswith('/communications'):
            data = [candidate['catalog']] if request.url.params['pager'] == '0' else []
            return httpx.Response(200, json={'code': 0, 'message': 'Comunicaciones: 1 paginas: 1', 'data': data})
        return httpx.Response(200, json={'code': 0, 'data': candidate['detail']})

    assert BBVANormalizer().normalize_many(previous)
    assert not BBVAScraper._commercial_review([previous])
    scraper = BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)), output_path=tmp_path / 'accepted.json')
    scraper.output_path.write_text(json.dumps([previous], ensure_ascii=False), encoding='utf8')
    result = scraper.scrape()
    assert result.complete
    assert scraper.coverage['snapshot_replace_allowed'] is True
    assert scraper.coverage['requires_review'] is False
    assert scraper.coverage['safe_to_deactivate'] is False
    scraper.save_raw_promotions(result.promotions)
    assert json.loads(scraper.output_path.read_text(encoding='utf8')) == result.promotions
    assert result.promotions[0]['detail']['basesCondiciones'] == case['terms']


@pytest.mark.parametrize('api,legal', [('12345', '12345'), ('12345', '18000'), ('18000', '12345'), ('99999', '99999')])
def test_arbitrary_amounts_use_evidence_instead_of_known_campaign_values(api, legal):
    raw = evidence_raw(f'Ejemplo: compra con tope de $777! 20% de reintegro. Tope de ${legal} por mes.')
    raw['catalog']['montoTope'] = api
    raw['detail']['beneficios'][0]['tope'] = api
    if api == legal:
        promotion = BBVANormalizer().normalize(raw)
        assert str(promotion.limits[0].amount) == api
        assert not BBVAScraper._commercial_review([raw])
    else:
        with pytest.raises(ValueError, match='conflicting monetary cap'):
            BBVANormalizer().normalize_many(raw)
        assert BBVAScraper._commercial_review([raw])
