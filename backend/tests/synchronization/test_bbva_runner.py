"""Real BBVA normalization/snapshot guards, fake HTTP and persistence only."""
import importlib
import json
from pathlib import Path

import httpx
import pytest

from normalization.sources.bbva import BBVANormalizer
from scraping.sources.bbva.scraper import BBVAScraper


@pytest.fixture
def module(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **k: False)
    monkeypatch.setenv('SUPABASE_URL', 'https://tests.invalid')
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'test-placeholder')
    return importlib.import_module('synchronization.runner')


def setup(tmp_path, monkeypatch, module, *, source_id='87593', baseline=True, short=False, fail=False):
    rows=json.loads((Path(__file__).parents[1]/'fixtures/bbva/official_sample.json').read_text(encoding='utf8'))
    raw=next(r for r in rows if r['source_id']==source_id)
    def handler(req):
        if req.url.path.endswith('/communications'):
            return httpx.Response(200,json={'code':0,'message':'Comunicaciones: 1 paginas: 1',
                'data':[raw['catalog']] if req.url.params['pager']=='0' else []})
        return httpx.Response(200,json={'code':0,'data':raw['detail']})
    s=BBVAScraper(httpx.Client(transport=httpx.MockTransport(handler)),output_path=tmp_path/'raw.json')
    if baseline: s.output_path.write_text(json.dumps([raw]),encoding='utf8')
    class Repo:
        calls=0
        deactivations=0
        received=[]
        def upsert_many(self,rows,**kw):
            self.calls+=1;self.received=rows
            if fail: raise OSError('mock network failure')
            return len(rows)-int(short)
        def deactivate_not_seen(self,*args): self.deactivations+=1;return 1
    repo=Repo()
    monkeypatch.setattr(module,'SupabasePromotionRepository',lambda:repo)
    runner=module.SyncRunner('bbva',lambda:s,BBVANormalizer,normalize_many=True)
    return runner,s,repo


def test_bbva_one_raw_emits_two_variants_and_never_deactivates(tmp_path,monkeypatch,module):
    runner,s,repo=setup(tmp_path,monkeypatch,module)
    runner.allow_deactivation=True
    runner.run()
    assert repo.calls==1 and len(repo.received)==2 and repo.deactivations==0
    assert {p.source_id for p in repo.received}=={'87593','87593:financing-minimum'}
    assert s.coverage['safe_to_deactivate'] is False


def test_bbva_validate_only_preserves_baseline_bytes(tmp_path,monkeypatch,module):
    runner,s,repo=setup(tmp_path,monkeypatch,module)
    old=s.output_path.read_bytes()
    runner.run(validate_only=True)
    assert s.output_path.read_bytes()==old and repo.calls==repo.deactivations==0


def test_bbva_absent_baseline_blocks_repository(tmp_path,monkeypatch,module):
    runner,s,repo=setup(tmp_path,monkeypatch,module,baseline=False)
    with pytest.raises(RuntimeError,match='no autoriza'): runner.run()
    assert not s.output_path.exists() and repo.calls==repo.deactivations==0


def test_bbva_unidentified_official_benefit_blocks_whole_candidate(tmp_path,monkeypatch,module):
    runner,s,repo=setup(tmp_path,monkeypatch,module,source_id='87567')
    old=s.output_path.read_bytes()
    with pytest.raises(RuntimeError,match='benefit not identifiable'): runner.run()
    assert s.output_path.read_bytes()==old and repo.calls==repo.deactivations==0


@pytest.mark.parametrize('short,fail',[(True,False),(False,True)])
def test_bbva_failed_or_partial_upsert_never_deactivates(tmp_path,monkeypatch,module,short,fail):
    runner,s,repo=setup(tmp_path,monkeypatch,module,short=short,fail=fail)
    with pytest.raises((OSError,RuntimeError)): runner.run()
    assert s.output_path.exists() and repo.calls==1 and repo.deactivations==0


@pytest.mark.parametrize('source_id,reason',[('88215','conflicting benefit percentage'),('88097','no autoriza')])
def test_bbva_complex_unrepresented_offer_or_conflicting_redemption_blocks_writes(tmp_path,monkeypatch,module,source_id,reason):
    runner,s,repo=setup(tmp_path,monkeypatch,module,source_id=source_id)
    old=s.output_path.read_bytes()
    with pytest.raises(RuntimeError,match=reason): runner.run()
    assert s.output_path.read_bytes()==old and repo.calls==repo.deactivations==0
    assert s.coverage['requires_review'] is True and s.coverage['snapshot_replace_allowed'] is False


def test_bbva_assist_card_mapped_variants_reach_only_mock_repository(tmp_path,monkeypatch,module):
    runner,s,repo=setup(tmp_path,monkeypatch,module,source_id='88051')
    runner.run()
    assert repo.calls == 1 and repo.deactivations == 0
    assert len(repo.received) > 1
    assert len({p.source_id for p in repo.received}) == len(repo.received)
    for p in repo.received:
        has_additional = any(b.type == 'discount' and 'adicional' in (b.description or '').lower() for b in p.benefits)
        if has_additional:
            assert not any(b.type == 'installments' for b in p.benefits)
    assert s.coverage['safe_to_deactivate'] is False
