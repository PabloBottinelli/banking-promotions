import copy
import json
from pathlib import Path
import httpx
import pytest
from scraping.sources.santander import scraper as module
from scraping.sources.santander.scraper import SantanderScraper

FIXTURES=Path(__file__).resolve().parents[1]/'fixtures/santander'


def row(name='60_7557'):return json.loads((FIXTURES/(name+'.json')).read_text(encoding='utf8'))


def make_scraper(tmp_path,rows=None,mode=None):
    rows=rows or [row()]
    brands=list({str(r['catalog']['id']):r['catalog'] for r in rows}.values())
    def handler(request):
        path=request.url.path
        if path.endswith('/brands'):
            page=int(request.url.params['page']);limit=int(request.url.params['limit'])
            items=brands[(page-1)*limit:page*limit]
            if mode=='repeat-page':items=brands
            return httpx.Response(200,json={'items':items,'totalItems':len(brands)})
        if '/brands/' in path:
            items=[r['program'] for r in rows if str(r['catalog']['id'])==path.split('/')[-1]]
            if mode=='duplicate-program':items+=copy.deepcopy(items)
            if mode=='conflicting-program':
                duplicate=copy.deepcopy(items[0]);duplicate['customerDiscount']=99;items+=[duplicate]
            return httpx.Response(200,json={'items':items,'totalItems':1})
        if '/publications/' in path:
            r=next(r for r in rows if str(r['detail']['id'])==path.split('/')[-1] and str(r['catalog']['id'])==request.url.params['brandId'])
            d=copy.deepcopy(r['detail'])
            if mode=='blank-legal':d['legal']='<p>   </p>'
            if mode=='blank-title':d['texts']['title']=' '
            if mode=='wrong-id':d['id']=0
            return httpx.Response(200,json=d)
        raise AssertionError(str(request.url))
    return SantanderScraper(httpx.Client(transport=httpx.MockTransport(handler)),tmp_path/'raw.json',workers=1)


def test_two_partition_complete_capture_never_saves_in_scrape(tmp_path):
    s=make_scraper(tmp_path,[row('60_7557'),row('60_7558')]);r=s.scrape()
    assert r.complete and len(r.promotions)==2 and not s.raw_path.exists()
    assert s.coverage['pages']==[{'page':1,'count':1},{'page':2,'count':0}]
    assert s.coverage['verification_pages']==s.coverage['pages']
    assert s.coverage['safe_to_deactivate'] is False and s.coverage['baseline_available'] is False
    assert all(x['scraped_at'].endswith('+00:00') for x in r.promotions)
    s.save_raw_promotions(r.promotions)
    assert len(json.loads(s.raw_path.read_text(encoding='utf8')))==2


@pytest.mark.parametrize('mode',['blank-legal','blank-title','wrong-id','repeat-page','conflicting-program'])
def test_bad_or_incomplete_200_responses_preserve_prior_bytes(tmp_path,mode):
    s=make_scraper(tmp_path,mode=mode);s.raw_path.write_text(json.dumps([row()]),encoding='utf8');before=s.raw_path.read_bytes()
    r=s.scrape()
    assert not r.complete and s.coverage['snapshot_replace_allowed'] is False
    with pytest.raises(ValueError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==before


def test_identical_source_duplicates_preserved_as_occurrence_count(tmp_path):
    s=make_scraper(tmp_path,mode='duplicate-program');r=s.scrape()
    assert r.complete and len(r.promotions)==1 and r.promotions[0]['program_occurrences']==2


def test_same_count_history_swap_requires_review(tmp_path):
    s=make_scraper(tmp_path);s.raw_path.write_text(json.dumps([row('60_7558')]),encoding='utf8');before=s.raw_path.read_bytes();r=s.scrape()
    assert r.complete and s.coverage['missing_previous_ids']==['60:7558'] and s.coverage['requires_review']
    with pytest.raises(ValueError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==before


def test_missing_historical_ids_blocks_even_when_retrieval_complete(tmp_path):
    s=make_scraper(tmp_path);s.raw_path.write_text(json.dumps([row('60_7557'),row('60_7558')]),encoding='utf8');before=s.raw_path.read_bytes();r=s.scrape()
    assert r.complete
    with pytest.raises(ValueError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==before


def test_legitimate_additions_and_same_id_updates_allowed(tmp_path):
    s=make_scraper(tmp_path,[row('60_7557'),row('60_7558')]);s.raw_path.write_text(json.dumps([row()]),encoding='utf8');r=s.scrape();s.save_raw_promotions(r.promotions)
    updated=row();updated['detail']['legal']+='<p>Updated terms</p>'
    s=make_scraper(tmp_path,[updated,row('60_7558')]);r=s.scrape();s.save_raw_promotions(r.promotions)
    assert 'Updated terms' in s.raw_path.read_text(encoding='utf8')


def test_tampering_and_interrupted_atomic_replace_preserve_previous_bytes(tmp_path,monkeypatch):
    s=make_scraper(tmp_path);s.raw_path.write_text(json.dumps([row()]),encoding='utf8');before=s.raw_path.read_bytes();r=s.scrape()
    changed=copy.deepcopy(r.promotions);changed[0]['detail']['customerDiscount']=99
    with pytest.raises(ValueError,match='changed'):s.save_raw_promotions(changed)
    def fail(*args):raise OSError('interrupted replacement')
    monkeypatch.setattr(module.os,'replace',fail)
    with pytest.raises(OSError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==before and not list(tmp_path.glob('.santander-*.tmp'))


@pytest.mark.parametrize('mutation',['duplicate','missing','blank-legal','blank-title','wrong-source','mismatched-brand'])
def test_invalid_raw_details_rejected(mutation):
    rows=[row()]
    if mutation=='duplicate':rows.append(copy.deepcopy(rows[0]))
    if mutation=='missing':rows[0]['source_id']=''
    if mutation=='blank-legal':rows[0]['detail']['legal']=' '
    if mutation=='blank-title':rows[0]['detail']['texts']['title']=' '
    if mutation=='wrong-source':rows[0]['source']='other'
    if mutation=='mismatched-brand':rows[0]['detail']['brands']=[]
    with pytest.raises(ValueError):SantanderScraper.validate_rows(rows)
