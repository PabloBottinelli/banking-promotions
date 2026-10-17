"""Only temporary raw files and fake repositories; no Supabase or .env reads."""
import importlib
import json
from pathlib import Path
import pytest
from normalization.sources.santander import SantanderNormalizer
from scraping.models import ScrapeResult
from scraping.sources.santander.scraper import SantanderScraper,digest

FIXTURES=Path(__file__).resolve().parents[1]/'fixtures/santander'


class Repo:
    def __init__(self,short=False,fail=False):self.upserts=0;self.deactivations=0;self.short=short;self.fail=fail
    def upsert_many(self,rows,**kwargs):
        self.upserts+=1
        if self.fail:raise OSError('simulated network failure')
        return len(rows)-int(self.short)
    def deactivate_not_seen(self,*args):self.deactivations+=1;return 0


@pytest.fixture
def module(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv,'load_dotenv',lambda *args,**kwargs:False)
    monkeypatch.setenv('SUPABASE_URL','https://tests.invalid');monkeypatch.setenv('SUPABASE_SECRET_KEY','test-placeholder')
    return importlib.import_module('synchronization.runner')


def setup(tmp_path,monkeypatch,module,short=False,fail=False):
    raw=json.loads((FIXTURES/'60_7557.json').read_text(encoding='utf8'));rows=[raw]
    s=SantanderScraper(raw_path=tmp_path/'raw.json');s._candidate_digest=digest(rows)
    s.coverage=dict(catalog_complete=True,snapshot_replace_allowed=True,requires_review=False,safe_to_deactivate=False)
    monkeypatch.setattr(s,'scrape',lambda:ScrapeResult(rows,1,[]))
    repo=Repo(short,fail);monkeypatch.setattr(module,'SupabasePromotionRepository',lambda:repo)
    runner=module.SyncRunner('santander',lambda:s,SantanderNormalizer,normalize_many=True)
    return runner,s,repo,rows


def test_validate_only_never_saves_or_upserts(tmp_path,monkeypatch,module):
    runner,s,repo,_=setup(tmp_path,monkeypatch,module);runner.run(validate_only=True)
    assert not s.raw_path.exists() and repo.upserts==repo.deactivations==0


@pytest.mark.parametrize('kind',['incomplete','review','replacement-refused','empty-variants','duplicate-variants','wrong-source','duplicate-raw','blank-id','blank-detail','save-refused'])
def test_whole_candidate_rejections_block_snapshot_and_repository(tmp_path,monkeypatch,module,kind):
    runner,s,repo,rows=setup(tmp_path,monkeypatch,module)
    if kind=='incomplete':monkeypatch.setattr(s,'scrape',lambda:ScrapeResult(rows,2,[]))
    elif kind=='review':s.coverage['requires_review']=True
    elif kind=='replacement-refused':s.coverage['snapshot_replace_allowed']=False
    elif kind=='duplicate-raw':rows.append(rows[0])
    elif kind=='blank-id':rows[0]['source_id']=' '
    elif kind=='blank-detail':rows[0]['detail']['legal']=' '
    elif kind=='save-refused':s._candidate_digest='tampered'
    else:
        class Bad:
            def normalize_many(self,raw):
                if kind=='empty-variants':return []
                p=SantanderNormalizer().normalize_many(raw)[0]
                if kind=='duplicate-variants':return [p,p]
                p.source='wrong';return [p]
        runner.normalizer_class=Bad
    with pytest.raises((RuntimeError,ValueError)):runner.run()
    assert not s.raw_path.exists() and repo.upserts==repo.deactivations==0


@pytest.mark.parametrize('short,fail',[(True,False),(False,True)])
def test_failed_or_short_upsert_preserves_saved_raw_and_disables_deactivation(tmp_path,monkeypatch,module,short,fail):
    runner,s,repo,_=setup(tmp_path,monkeypatch,module,short,fail);runner.allow_deactivation=True;s.coverage['safe_to_deactivate']=True
    with pytest.raises((RuntimeError,OSError)):runner.run()
    assert s.raw_path.exists() and repo.upserts==1 and repo.deactivations==0
    repo.short=repo.fail=False;runner.allow_deactivation=False;runner.run()
    assert repo.upserts==2 and repo.deactivations==0


@pytest.mark.parametrize('from_file,allow,safe,expected',[(False,False,True,0),(False,True,False,0),(True,True,True,0),(False,True,True,1)])
def test_deactivation_requires_all_guards(tmp_path,monkeypatch,module,from_file,allow,safe,expected):
    runner,s,repo,rows=setup(tmp_path,monkeypatch,module);runner.allow_deactivation=allow;s.coverage['safe_to_deactivate']=safe
    monkeypatch.setattr(runner,'load_raw_promotions',lambda:rows);runner.run(from_file=from_file)
    assert repo.upserts==1 and repo.deactivations==expected and s.raw_path.exists() is (not from_file)
