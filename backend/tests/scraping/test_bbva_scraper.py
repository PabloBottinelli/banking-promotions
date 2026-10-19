"""Synthetic API responses exercise capture safety, never real snapshots."""
import json

import httpx
import pytest

from scraping.sources.bbva.scraper import BBVAScraper


def detail(i):
    return {'id': i, 'cabecera': 'Comercio 20%', 'basesCondiciones': '20% de reintegro con BBVA.',
            'beneficios': [{'cuota': 0, 'tope': None, 'requisitos': ['Tarjetas BBVA']}]}


def raw(i):
    return {'source': 'bbva', 'source_id': i, 'scraped_at': '2026-10-19T12:00:00+00:00',
            'catalog': {'id': i}, 'detail': detail(i)}


def scraper(tmp_path, ids=(1, 2), *, broken=None, total=True):
    def handler(request):
        if request.url.path.endswith('/communications'):
            page = int(request.url.params['pager'])
            data = [{'id': i} for i in ids] if page == 0 else []
            envelope = {'code': 0, 'data': data}
            if total:
                envelope['message'] = f'Comunicaciones: {len(ids)}   paginas: {1 if ids else 0}'
            return httpx.Response(200, json=envelope)
        i = int(request.url.path.rsplit('/', 1)[1])
        data = detail(i)
        if broken:
            data = broken(i, data)
        return httpx.Response(200, json={'code': 0, 'data': data})
    return BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)), output_path=tmp_path / 'raw.json')


def baseline(s, ids=(1, 2)):
    s.output_path.write_text(json.dumps([raw(i) for i in ids]), encoding='utf8')
    return s.output_path.read_bytes()


def test_fetch_catalog_paginates_and_repeats(tmp_path):
    s = scraper(tmp_path)
    assert [r['id'] for r in s.fetch_catalog()] == [1, 2]
    assert s.coverage['official_total'] == 2
    assert s.coverage['pagination_verified'] is True


def test_scrape_candidate_does_not_save_and_absent_baseline_blocks(tmp_path):
    s = scraper(tmp_path)
    r = s.scrape()
    assert r.complete
    assert not s.output_path.exists()
    assert s.coverage['catalog_complete'] is True
    assert s.coverage['snapshot_replace_allowed'] is False
    assert s.coverage['requires_review'] is True
    assert s.coverage['safe_to_deactivate'] is False
    with pytest.raises(ValueError, match='not approved'):
        s.save_raw_promotions(r.promotions)


def test_no_total_reports_limit(tmp_path):
    s = scraper(tmp_path, total=False)
    assert s.scrape().complete
    assert s.coverage['official_total'] is None
    assert 'No reliable' in s.coverage['total_verification_limit']


@pytest.mark.parametrize('payload', [None, [], {}, {'code': 1, 'data': []}, {'code': 0},
                                     {'data': []}, {'code': 0, 'data': {}}, {'code': 0, 'data': [None]},
                                     {'code': 0, 'data': [{'id': ' '}]}, {'code': 0, 'data': [{'id': None}]}])
def test_malformed_catalog_is_not_empty_page(tmp_path, payload):
    s = BBVAScraper(httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))), output_path=tmp_path/'raw.json')
    r = s.scrape()
    assert not r.complete and r.failed_ids
    assert s.coverage['catalog_complete'] is False


@pytest.mark.parametrize('ids', [(1, 1), (' ',), (None,)])
def test_duplicate_or_blank_ids_fail(tmp_path, ids):
    assert not scraper(tmp_path, ids).scrape().complete


def test_duplicate_page_fails(tmp_path):
    s = BBVAScraper(httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200,json={'code':0,'data':[{'id':1}]}))), output_path=tmp_path/'raw.json')
    assert not s.scrape().complete
    assert 'duplicate' in s.coverage['errors'][0]


def test_pagination_changes_between_passes(tmp_path):
    calls = 0
    def handler(req):
        nonlocal calls
        calls += 1
        page = int(req.url.params['pager'])
        return httpx.Response(200,json={'code':0,'data':[{'id':1 if calls<=2 else 2}] if page==0 else []})
    s = BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)),output_path=tmp_path/'raw.json')
    assert not s.scrape().complete
    assert 'unstable' in s.coverage['errors'][0]


def test_total_mismatch_fails(tmp_path):
    def handler(req):
        return httpx.Response(200,json={'code':0,'message':'Comunicaciones: 3 paginas: 1',
            'data':[{'id':1}] if req.url.params['pager']=='0' else []})
    s=BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)),output_path=tmp_path/'raw.json')
    assert not s.scrape().complete
    assert 'mismatch' in s.coverage['errors'][0]


@pytest.mark.parametrize('field,value', [('cabecera',' '), ('basesCondiciones','\n'),
    ('basesCondiciones','<p>&nbsp;</p>'), ('beneficios',[]), ('beneficios',[{}]), ('beneficios',[None]), ('id',999)])
def test_blank_http_200_detail_is_failure(tmp_path, field, value):
    def broken(i,d):
        if i==1: d[field]=value
        return d
    s=scraper(tmp_path,broken=broken)
    old=baseline(s)
    r=s.scrape()
    assert r.failed_ids==['1'] and not r.complete
    assert len(r.promotions)==1 and r.promotions[0]['source_id']==2
    with pytest.raises(ValueError): s.save_raw_promotions(r.promotions)
    assert s.output_path.read_bytes()==old


def test_limit_is_incomplete_even_without_detail_errors(tmp_path):
    s=scraper(tmp_path)
    r=s.scrape(limit=1)
    assert r.catalog_count==2 and not r.complete
    assert s.coverage['snapshot_replace_allowed'] is False


@pytest.mark.parametrize('old_ids,new_ids', [((1,2,3),(1,2)), ((1,2),(1,3))])
def test_missing_previous_ids_block_even_with_same_count(tmp_path,old_ids,new_ids):
    s=scraper(tmp_path,new_ids)
    old=baseline(s,old_ids)
    r=s.scrape()
    assert r.complete
    assert s.coverage['catalog_complete'] is True
    assert s.coverage['missing_previous_ids']==[str(i) for i in set(old_ids)-set(new_ids)]
    assert s.coverage['requires_review'] is True
    with pytest.raises(ValueError): s.save_raw_promotions(r.promotions)
    assert s.output_path.read_bytes()==old


def test_addition_and_same_id_update_can_be_saved(tmp_path):
    s=scraper(tmp_path,(1,2,3))
    baseline(s)
    r=s.scrape()
    assert s.coverage['snapshot_replace_allowed'] is True
    s.save_raw_promotions(r.promotions)
    assert len(json.loads(s.output_path.read_text()))==3
    assert s.coverage['safe_to_deactivate'] is False


def test_candidate_mutation_rejected(tmp_path):
    s=scraper(tmp_path)
    old=baseline(s)
    r=s.scrape()
    r.promotions[0]['detail']['cabecera']='tampered'
    with pytest.raises(ValueError): s.save_raw_promotions(r.promotions)
    assert s.output_path.read_bytes()==old


def test_baseline_changed_after_scrape_rechecked(tmp_path):
    s=scraper(tmp_path)
    baseline(s)
    r=s.scrape()
    old=baseline(s,(1,2,3))
    with pytest.raises(ValueError,match='baseline'): s.save_raw_promotions(r.promotions)
    assert s.output_path.read_bytes()==old


def test_atomic_replace_failure_preserves_bytes(tmp_path,monkeypatch):
    s=scraper(tmp_path)
    old=baseline(s)
    r=s.scrape()
    def fail(*args): raise OSError('interrupted')
    monkeypatch.setattr('scraping.sources.bbva.scraper.os.replace',fail)
    with pytest.raises(OSError): s.save_raw_promotions(r.promotions)
    assert s.output_path.read_bytes()==old
    assert list(tmp_path.glob('.bbva_*.tmp'))==[]


def test_malformed_previous_snapshot_fails_closed(tmp_path):
    s=scraper(tmp_path)
    s.output_path.write_text('[{}]')
    r=s.scrape()
    assert r.complete
    assert s.coverage['snapshot_replace_allowed'] is False
    assert 'Invalid baseline' in s.coverage['baseline_review_reason']


def test_commercial_conflict_blocks_even_with_baseline(tmp_path):
    def broken(i,d):
        d['basesCondiciones']='20% DE REINTEGRO CON TOPE DE $30.000 POR USUARIO POR VIGENCIA.'
        d['beneficios'][0]['frecuenciaTope']='Por Mes'
        return d
    s=scraper(tmp_path,broken=broken)
    baseline(s)
    assert s.scrape().complete
    assert s.coverage['requires_review'] is True
    assert s.coverage['snapshot_replace_allowed'] is False
    assert len(s.coverage['commercial_review_reasons'])==2


def test_http_detail_failure_keeps_other_details_and_blocks(tmp_path):
    def handler(req):
        if req.url.path.endswith('/communications'):
            return httpx.Response(200,json={'code':0,'data':[{'id':1},{'id':2}] if req.url.params['pager']=='0' else []})
        if req.url.path.endswith('/1'): return httpx.Response(404)
        return httpx.Response(200,json={'code':0,'data':detail(2)})
    s=BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)),output_path=tmp_path/'raw.json')
    old=baseline(s)
    r=s.scrape()
    assert not r.complete and r.failed_ids==['1'] and len(r.promotions)==1
    with pytest.raises(ValueError): s.save_raw_promotions(r.promotions)
    assert s.output_path.read_bytes()==old


def test_official_conflicting_rate_alone_blocks_a_valid_baseline(tmp_path):
    from pathlib import Path
    rows=json.loads((Path(__file__).parents[1]/'fixtures/bbva/official_sample.json').read_text(encoding='utf8'))
    r=next(r for r in rows if r['source_id']=='88215')
    def handler(req):
        return httpx.Response(200,json={'code':0,'data':([r['catalog']] if req.url.params['pager']=='0' else [])}) if req.url.path.endswith('/communications') else httpx.Response(200,json={'code':0,'data':r['detail']})
    s=BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)),output_path=tmp_path/'raw.json')
    s.output_path.write_text(json.dumps([r]),encoding='utf8');old=s.output_path.read_bytes()
    result=s.scrape()
    assert result.complete and s.coverage['catalog_complete'] is True
    assert s.coverage['snapshot_replace_allowed'] is False and s.coverage['requires_review'] is True
    assert '40% conflicts with legal 30%' in s.coverage['commercial_review_reasons'][0]
    with pytest.raises(ValueError):s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes()==old


def test_synthetic_conflict_detector_uses_source_rates_not_an_id():
    r=raw(123);r['detail']['cabecera']='Comercio 45%'
    r['detail']['basesCondiciones']='LA PROMOCIÓN CONSTA DE 35% DE REINTEGRO.'
    assert '45% conflicts with legal 35%' in BBVAScraper._commercial_review([r])[0]


def post_qa3_official(source_id):
    from pathlib import Path
    rows = json.loads((Path(__file__).parents[1] / 'fixtures/bbva/official_post_qa3.json').read_text(encoding='utf8'))
    return next(r for r in rows if str(r['source_id']) == source_id)


@pytest.mark.parametrize('api,legal', [('Por Mes', 'vigencia'), ('Por Vigencia de la Promocion', 'mes')])
def test_same_cap_period_conflict_is_detected_both_directions(api, legal):
    r = raw(123)
    r['detail']['beneficios'][0].update(tope='25.000', frecuenciaTope=api)
    r['detail']['basesCondiciones'] = f'20% de reintegro con tope de $25.000 por cliente por {legal}.'
    assert BBVAScraper._commercial_review([r])


def test_different_legitimate_caps_are_not_a_period_conflict():
    r = raw(123)
    r['detail']['beneficios'][0].update(tope='25.000', frecuenciaTope='Por Mes')
    r['detail']['basesCondiciones'] = '20% de reintegro. Tope de $25.000 por cliente por mes y tope de $100.000 por cliente por vigencia.'
    assert BBVAScraper._commercial_review([r]) == []


def test_official_bus_period_conflict_is_not_structurally_silent():
    r = post_qa3_official('88081')
    assert any(reason.startswith('88081:') for reason in BBVAScraper._commercial_review([r]))


def test_dropped_official_gift_and_stock_are_detected_in_actual_output(monkeypatch):
    from normalization.sources.bbva import BBVANormalizer
    r = post_qa3_official('84091')
    variants = BBVANormalizer().normalize_many(r)
    for p in variants:
        p.benefits = [b for b in p.benefits if b.type != 'gift']
        p.limits = [limit for limit in p.limits if limit.type != 'stock']
    monkeypatch.setattr(BBVANormalizer, 'normalize_many', lambda self, raw: variants)
    reasons = BBVAScraper._commercial_review([r])
    assert reasons  # Valid Pydantic variants still lost an official entitlement.


def test_fully_mapped_official_assist_card_is_not_a_multiple_rate_false_positive():
    assert BBVAScraper._commercial_review([post_qa3_official('88051')]) == []
