from copy import deepcopy
import json

import httpx
import pytest

from normalization.sources.bbva import BBVANormalizer
from scraping.sources.bbva.scraper import BBVAScraper


LAYOUTS = [
    'Ejemplo: compra con tope de $12.000<hr>{contract}',
    '<div><div>Ejemplo: compra con tope de $12.000</div><hr><section>{contract}</section></div>',
    '<table><tr><td>Ejemplo: compra con tope de $12.000</td></tr><tr><td>{contract}</td></tr></table>',
    '<table><tr><td>Ejemplo: compra con tope de $12.000</td><td>{contract}</td></tr></table>',
    '<table><tbody><tr><td>Ejemplo: compra con tope de $12.000</td></tr><tr><td>Tope de</td><td>${amount}</td><td>por cliente por mes.</td></tr></tbody></table>',
    '<blockquote>Ejemplo: compra con tope de $12.000</blockquote>{contract}',
    '<dl><dt>Ejemplo: compra con tope de $12.000</dt><dd>{contract}</dd></dl>',
]

INLINE_SCOPELESS_LAYOUTS = [
    '<span>Ejemplo: compra con tope de $12.000</span> {contract}',
    '<div><span>Ejemplo: <strong>compra con tope de $12.000</strong></span> {contract}</div>',
]

AMBIGUOUS_TERMS = [
    '<p>20% de reintegro.</p><table><tr><th>Producto</th><th>Tope mensual</th></tr>'
    '<tr><td>Producto A</td><td>$20.000</td></tr><tr><td>Producto B</td><td>$16.000</td></tr></table>',
    '20% de reintegro. Ejemplo: compra con tope de $12.000 y tope de $16.000 por mes.',
    '20% de reintegro. <span>Ejemplo:</span><div>Compra con tope de $20.000 por mes.</div>',
    '20% de reintegro. Clientes Black: tope de $20.000 por mes.',
] + [layout.format(contract=f'Tope de ${amount} por cliente por mes.')
     for layout in INLINE_SCOPELESS_LAYOUTS for amount in ['16.000', '20.000']]


def raw_promotion(terms):
    return {'source': 'bbva', 'source_id': 'html-clause', 'scraped_at': '2026-10-22T12:00:00+00:00',
            'catalog': {'id': 'html-clause', 'cabecera': 'Comercio', 'montoTope': '20000'},
            'detail': {'id': 'html-clause', 'cabecera': 'Comercio', 'basesCondiciones': terms,
                       'beneficios': [{'tope': '20000', 'frecuenciaTope': 'Por Mes',
                                       'requisitos': ['20% de reintegro']}]}}


def legal_text(layout, amount):
    return '20% de reintegro. ' + layout.format(
        contract=f'Tope de ${amount} por cliente por mes.', amount=amount)


@pytest.mark.parametrize('layout', LAYOUTS)
def test_html_contract_after_example_is_an_explicit_conflict(layout):
    raw = raw_promotion(legal_text(layout, '16.000'))
    before = deepcopy(raw)
    with pytest.raises(ValueError, match='conflicting monetary cap') as error:
        BBVANormalizer().normalize_many(raw)
    assert '20000' in str(error.value) and '16000' in str(error.value)
    assert 'conflicting monetary cap' in '; '.join(BBVAScraper._commercial_review([raw]))
    assert raw == before


@pytest.mark.parametrize('layout', LAYOUTS)
def test_html_example_with_different_amount_does_not_change_contract(layout):
    raw = raw_promotion(legal_text(layout, '20.000'))
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 20000
    assert promotion.limits[0].period == 'monthly'
    assert '12.000' in promotion.terms and '20.000' in promotion.terms
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('layout', LAYOUTS + AMBIGUOUS_TERMS)
@pytest.mark.parametrize('defer_review', [False, True])
def test_html_conflict_cannot_replace_valid_snapshot(tmp_path, monkeypatch, layout, defer_review):
    previous = raw_promotion('20% de reintegro. Tope de $20.000 por cliente por mes.')
    assert BBVANormalizer().normalize_many(previous)
    assert not BBVAScraper._commercial_review([previous])
    candidate = raw_promotion(legal_text(layout, '16.000'))

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
    assert result.complete and scraper.coverage['catalog_complete'] is True
    if not defer_review:
        assert scraper.coverage['snapshot_replace_allowed'] is False
        assert scraper.coverage['requires_review'] is True
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.coverage['snapshot_replace_allowed'] is False
    assert scraper.coverage['requires_review'] is True
    assert scraper.coverage['safe_to_deactivate'] is False
    assert scraper.output_path.read_bytes() == before
    assert list(tmp_path.glob('.bbva_*.tmp')) == []


@pytest.mark.parametrize('terms', [
    '<p>2<strong>0</strong><span>%</span> de reintegro. Tope de $<b>20</b>.000 por cliente por <i>mes</i>.</p>',
    '<p>20% de reintegro.</p><table><tr><td>Tope de</td><td>$<b>20.000</b></td><td>por cliente por mes.</td></tr></table>',
    '<p>20% de reintegro.</p><p>Tope de <span>$20.000</span> por cliente por <em>mes</em>.</p>',
])
def test_inline_formatting_keeps_amount_percentage_and_period_contiguous(terms):
    raw = raw_promotion(terms)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.benefits[0].percentage == 20
    assert promotion.limits[0].amount == 20000 and promotion.limits[0].period == 'monthly'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('terms', AMBIGUOUS_TERMS)
def test_uncertain_example_boundary_or_cap_assignment_requires_review(terms):
    raw = raw_promotion(terms)
    with pytest.raises(ValueError, match='unresolved'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('tag', ['p', 'section', 'article', 'li', 'blockquote', 'div'])
@pytest.mark.parametrize('example_first', [False, True])
def test_nested_formatting_in_separate_blocks_preserves_example_scope(tag, example_first):
    example = f'<{tag}><b>Ejemplo:</b> compra con tope de $<i>12.000</i></{tag}>'
    contract = f'<{tag}>Tope de <span>$20.000</span> por cliente por <b>mes</b>.</{tag}>'
    fragments = [example, contract] if example_first else [contract, example]
    raw = raw_promotion('<main><p>20% de reintegro.</p>' + ''.join(fragments) + '</main>')
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 20000 and promotion.limits[0].period == 'monthly'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('layout', LAYOUTS)
def test_missing_api_cap_comes_from_contract_after_html_example(layout):
    raw = raw_promotion(legal_text(layout, '16.000'))
    raw['catalog']['montoTope'] = None
    raw['detail']['beneficios'][0]['tope'] = None
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.limits[0].amount == 16000 and promotion.limits[0].period == 'monthly'
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('layout', LAYOUTS[:4] + LAYOUTS[5:] + [
    'Ejemplo: compra con tope de $12.000; {contract}',
    'Ejemplo: compra con tope de $12.000. {contract}',
    'Ejemplo: compra con tope de $12.000\n{contract}',
])
def test_illustrative_percentage_does_not_override_contract_or_remove_legal_text(layout):
    terms = layout.replace('compra con tope', '80% de reintegro con tope').format(
        contract='20% de reintegro. Tope de $20.000 por cliente por mes.')
    raw = raw_promotion(terms)
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.benefits[0].percentage == 20 and promotion.limits[0].amount == 20000
    assert promotion.terms == BBVANormalizer()._clean_text(terms)
    assert '80%' in promotion.terms and '12.000' in promotion.terms and '20.000' in promotion.terms
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('example', [
    '<b>Ejemplo: compra</b> con tope de $12.000.',
    '<span>Ejemplo: compra con tope de $12.</span>000.',
    '<span>Ejemplo: compra con tope de $</span>12.000.',
    '<b>Ejemplo: 8</b>0% de reintegro con tope de $12.000.',
])
def test_partial_inline_formatting_does_not_end_the_illustration(example):
    raw = raw_promotion(example + ' 20% de reintegro. Tope de $20.000 por cliente por mes.')
    promotion = BBVANormalizer().normalize(raw)
    assert promotion.benefits[0].percentage == 20 and promotion.limits[0].amount == 20000
    assert not BBVAScraper._commercial_review([raw])


@pytest.mark.parametrize('layout', INLINE_SCOPELESS_LAYOUTS)
@pytest.mark.parametrize('amount', ['16.000', '20.000'])
def test_inline_elements_alone_cannot_authorize_ambiguous_cap_assignment(layout, amount):
    raw = raw_promotion(legal_text(layout, amount))
    raw['catalog']['montoTope'] = None
    raw['detail']['beneficios'][0]['tope'] = None
    with pytest.raises(ValueError, match='unresolved example boundary'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])
