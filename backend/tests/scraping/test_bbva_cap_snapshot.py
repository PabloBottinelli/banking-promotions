from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from normalization.sources.bbva import BBVANormalizer
from scraping.sources.bbva.scraper import BBVAScraper


IDS = ['85446', '86124', '86599', '85699', '85698', '85697', '85700',
       '85828', '85830', '85829', '86761', '87809', '87558', '87904']


def capture(tmp_path, source_id):
    path = Path(__file__).parents[1] / 'fixtures/bbva/official_cap_conflicts.json'
    raw = next(row for row in json.loads(path.read_text(encoding='utf8')) if row['source_id'] == source_id)
    previous = deepcopy(raw)
    legal_amount = '25500' if source_id == '85446' else '16000'
    previous['catalog']['montoTope'] = legal_amount
    previous['detail']['beneficios'][0]['tope'] = legal_amount
    if source_id != '85446':
        previous['detail']['beneficios'][0]['requisitos'] = [text.replace('$20.000', '$16.000') for text in previous['detail']['beneficios'][0]['requisitos']]
    assert BBVANormalizer().normalize_many(previous)
    assert BBVAScraper._commercial_review([previous]) == []

    def handler(request):
        if request.url.path.endswith('/communications'):
            data = [raw['catalog']] if request.url.params['pager'] == '0' else []
            return httpx.Response(200, json={'code': 0, 'message': 'Comunicaciones: 1 paginas: 1', 'data': data})
        return httpx.Response(200, json={'code': 0, 'data': raw['detail']})

    scraper = BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)), output_path=tmp_path / 'accepted.json')
    scraper.output_path.write_text(json.dumps([previous], ensure_ascii=False, indent=2), encoding='utf8')
    return scraper, raw


@pytest.mark.parametrize('source_id', IDS)
def test_official_cap_conflict_blocks_replacement_and_preserves_valid_baseline(tmp_path, source_id):
    scraper, raw = capture(tmp_path, source_id)
    before = scraper.output_path.read_bytes()
    result = scraper.scrape()
    assert result.complete and len(result.promotions) == 1
    assert result.promotions[0]['detail'] == raw['detail']
    assert scraper.coverage['catalog_complete'] is True
    assert scraper.coverage['snapshot_replace_allowed'] is False
    assert scraper.coverage['requires_review'] is True
    assert scraper.coverage['safe_to_deactivate'] is False
    assert 'conflicting monetary cap' in '; '.join(scraper.coverage['commercial_review_reasons'])
    with pytest.raises(ValueError, match='not approved'):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_bytes() == before
    assert list(tmp_path.glob('.bbva_*.tmp')) == []


def test_saving_rechecks_commercial_evidence_before_writing(tmp_path, monkeypatch):
    scraper, _ = capture(tmp_path, '85446')
    before = scraper.output_path.read_bytes()
    with monkeypatch.context() as temporary:
        temporary.setattr(scraper, '_commercial_review', lambda rows: [])
        candidate = scraper.scrape()
    assert scraper.coverage['snapshot_replace_allowed'] is True
    with pytest.raises(ValueError, match='commercial review required'):
        scraper.save_raw_promotions(candidate.promotions)
    assert scraper.output_path.read_bytes() == before
    assert scraper.coverage['snapshot_replace_allowed'] is False
    assert scraper.coverage['requires_review'] is True


@pytest.mark.parametrize('defer_review', [False, True])
@pytest.mark.parametrize('terms', [
    '20% de reintegro. Ejemplo: una compra de $100.000 recibe $20.000. '
    'Condiciones generales: tope de $16.000 por cliente por mes.',
    '<p>20% de reintegro.</p><p>Ejemplo: compra con tope de $12.000</p>'
    '<p>Tope de $16.000 por cliente por mes.</p>',
    '20% de reintegro. Ejemplo: compra de $100.000 recibe $20.000\n'
    'Tope de $16.000 por cliente por mes.',
    '20% de reintegro. (Ejemplo: compra con tope de $12.000) '
    'Tope de $16.000 por cliente por mes.',
])
def test_contractual_cap_after_example_cannot_replace_valid_snapshot(tmp_path, monkeypatch, defer_review, terms):
    previous = {'source': 'bbva', 'source_id': 'example-contract', 'scraped_at': '2026-10-22T12:00:00+00:00',
                'catalog': {'id': 'example-contract', 'cabecera': 'Comercio', 'montoTope': '20000'},
                'detail': {'id': 'example-contract', 'cabecera': 'Comercio',
                           'basesCondiciones': '20% de reintegro. Tope de $20.000 por cliente por mes.',
                           'beneficios': [{'tope': '20000', 'frecuenciaTope': 'Por Mes',
                                           'requisitos': ['20% de reintegro']}]}}
    assert BBVANormalizer().normalize_many(previous)
    assert BBVAScraper._commercial_review([previous]) == []
    candidate = deepcopy(previous)
    candidate['detail']['basesCondiciones'] = terms

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
    assert scraper.output_path.read_bytes() == before
    assert scraper.coverage['snapshot_replace_allowed'] is False
    assert scraper.coverage['requires_review'] is True
    assert list(tmp_path.glob('.bbva_*.tmp')) == []
