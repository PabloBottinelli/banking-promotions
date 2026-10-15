import copy
import json
from pathlib import Path
import httpx
import pytest
from scraping.sources.santander import scraper as module
from scraping.sources.santander.scraper import SantanderScraper

FIXTURES=Path(__file__).resolve().parents[1]/'fixtures/santander'


def row(name='60_7557'):
    return json.loads((FIXTURES/(name+'.json')).read_text(encoding='utf8'))


def make_scraper(tmp_path, rows=None, mode=None):
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
            if mode=='duplicate-program':items=items+copy.deepcopy(items)
            if mode=='conflicting-program':
                dup=copy.deepcopy(items[0]);dup['customerDiscount']=99;items=items+[dup]
            return httpx.Response(200,json={'items':items,'totalItems':1})
        if '/publications/' in path:
            r=next(r for r in rows if str(r['detail']['id'])==path.split('/')[-1] and str(r['catalog']['id'])==request.url.params['brandId'])
            d=copy.deepcopy(r['detail'])
            if mode=='blank-legal':d['legal']='<p>   </p>'
            if mode=='blank-title':d['texts']['title']='  '
            if mode=='wrong-id':d['id']=0
            return httpx.Response(200,json=d)
        raise AssertionError(str(request.url))
    return SantanderScraper(httpx.Client(transport=httpx.MockTransport(handler)),tmp_path/'raw.json',workers=1)


def test_full_two_partition_catalog_and_details_without_save(tmp_path):
    s=make_scraper(tmp_path,[row('60_7557'),row('60_7558')]);r=s.scrape()
    assert r.complete and len(r.promotions)==2
    assert not s.raw_path.exists()
    assert s.coverage['pages']==[{'page':1,'count':1},{'page':2,'count':0}]
    assert s.coverage['verification_pages']==s.coverage['pages']
    assert s.coverage['safe_to_deactivate'] is False
    assert s.coverage['baseline_available'] is False
    assert all(x['scraped_at'].endswith('+00:00') for x in r.promotions)
    s.save_raw_promotions(r.promotions)
    assert len(json.loads(s.raw_path.read_text(encoding='utf8')))==2


@pytest.mark.parametrize('mode',['blank-legal','blank-title','wrong-id','repeat-page','conflicting-program'])
def test_partial_blank_200_and_duplicate_catalog_never_replace(tmp_path,mode):
    s=make_scraper(tmp_path,mode=mode);s.raw_path.write_text(json.dumps([row()]),encoding='utf8');old=s.raw_path.read_bytes()
    r=s.scrape()
    assert not r.complete
    assert s.coverage['snapshot_replace_allowed'] is False
    with pytest.raises(ValueError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==old


def test_identical_api_duplicate_is_preserved_as_occurrence_count(tmp_path):
    s=make_scraper(tmp_path,mode='duplicate-program');r=s.scrape()
    assert r.complete and len(r.promotions)==1
    assert r.promotions[0]['program_occurrences']==2


def test_same_total_historical_identity_swap_requires_review(tmp_path):
    old=row('60_7558');s=make_scraper(tmp_path);s.raw_path.write_text(json.dumps([old]),encoding='utf8');before=s.raw_path.read_bytes()
    r=s.scrape()
    assert r.complete
    assert s.coverage['missing_previous_ids']==['60:7558']
    assert s.coverage['requires_review'] is True
    with pytest.raises(ValueError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==before


def test_removal_after_comparable_total_and_additions(tmp_path):
    baseline=[row('60_7557'),row('60_7558')];s=make_scraper(tmp_path)
    s.raw_path.write_text(json.dumps(baseline),encoding='utf8');before=s.raw_path.read_bytes();r=s.scrape()
    with pytest.raises(ValueError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==before
    s=make_scraper(tmp_path,baseline);r=s.scrape();assert r.complete;s.save_raw_promotions(r.promotions)
    assert len(json.loads(s.raw_path.read_text(encoding='utf8')))==2


def test_same_ids_updates_and_legitimate_additions_are_allowed(tmp_path):
    s=make_scraper(tmp_path,[row('60_7557'),row('60_7558')]);s.raw_path.write_text(json.dumps([row()]),encoding='utf8')
    r=s.scrape();assert s.coverage['snapshot_replace_allowed'];s.save_raw_promotions(r.promotions)
    updated=row();updated['detail']['legal']+='<p>Updated terms</p>';s=make_scraper(tmp_path,[updated,row('60_7558')]);r=s.scrape();s.save_raw_promotions(r.promotions)
    assert 'Updated terms' in s.raw_path.read_text(encoding='utf8')


def test_changed_candidate_and_atomic_replace_failure_preserve_bytes(tmp_path,monkeypatch):
    s=make_scraper(tmp_path);s.raw_path.write_text(json.dumps([row()]),encoding='utf8');before=s.raw_path.read_bytes();r=s.scrape()
    changed=copy.deepcopy(r.promotions);changed[0]['detail']['customerDiscount']=99
    with pytest.raises(ValueError,match='changed'):s.save_raw_promotions(changed)
    def fail(*args):raise OSError('interrupted replacement')
    monkeypatch.setattr(module.os,'replace',fail)
    with pytest.raises(OSError):s.save_raw_promotions(r.promotions)
    assert s.raw_path.read_bytes()==before
    assert not list(tmp_path.glob('.santander-*.tmp'))


@pytest.mark.parametrize('mutation',['duplicate','missing','blank-legal','blank-title','wrong-source','mismatched-brand'])
def test_source_validation_rejects_malformed_rows(mutation):
    rows=[row()]
    if mutation=='duplicate':rows.append(copy.deepcopy(rows[0]))
    if mutation=='missing':rows[0]['source_id']=''
    if mutation=='blank-legal':rows[0]['detail']['legal']=' '
    if mutation=='blank-title':rows[0]['detail']['texts']['title']=' '
    if mutation=='wrong-source':rows[0]['source']='other'
    if mutation=='mismatched-brand':rows[0]['detail']['brands']=[]
    with pytest.raises(ValueError):SantanderScraper.validate_rows(rows)
