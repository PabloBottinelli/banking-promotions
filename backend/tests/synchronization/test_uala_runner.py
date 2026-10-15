"""Runner boundaries exercised only against fixtures, tmp_path and fake persistence."""
import copy
import json
from pathlib import Path

import pytest

from normalization.sources.uala import UalaNormalizer
from scraping.models import ScrapeResult
from scraping.sources.uala.scraper import UalaScraper, fingerprint
from synchronization import runner as runner_module


def setup(tmp_path, monkeypatch, *, mode="valid", short=False, failed=False, allow=False, safe=False):
    records = json.loads((Path(__file__).parents[1] / "fixtures/uala/official_promotions.json").read_text(encoding="utf-8"))
    s = UalaScraper(output_path=tmp_path / "raw.json")
    if mode in {"variant_removed", "variant_replaced"}:
        s.output_path.write_text(json.dumps(records), encoding="utf-8")
        sport = next(r for r in records if r["source_id"] == "6CReo7313gFFfYZ1SzdZ2j")
        if mode == "variant_removed":
            sport["detail"]["specs"].pop()
            sport["catalog"]["fields"]["PromotionSpecs"].pop()
        else:
            sport["detail"]["specs"][1]["id"] = "replacement-plus-spec"
            sport["catalog"]["fields"]["PromotionSpecs"][1]["sys"]["id"] = "replacement-plus-spec"
    s.coverage = dict(catalog_complete=True, snapshot_replace_allowed=True, requires_review=False, safe_to_deactivate=safe)
    if mode == "review": s.coverage["requires_review"] = True
    if mode == "refused": s.coverage["snapshot_replace_allowed"] = False
    if mode == "blank": records[0]["detail"]["specs"][0]["legalDisclaimer"] = " "
    if mode == "duplicate_raw": records.append(copy.deepcopy(records[0]))
    if mode == "missing_raw": records[0]["source_id"] = " "
    result = ScrapeResult(records, len(records) + int(mode == "partial"), [])
    s.result = result
    s._candidate_hash = fingerprint(records)
    monkeypatch.setattr(s, "scrape", lambda: result)
    if mode == "save_refused":
        def reject(_): raise ValueError("Rejected snapshot")
        monkeypatch.setattr(s, "save_raw_promotions", reject)

    class Normalizer(UalaNormalizer):
        def normalize_many(self, raw):
            if mode == "zero": return []
            variants = super().normalize_many(raw)
            if mode == "duplicate_normalized": return [variants[0], variants[0]]
            if mode == "wrong_source": variants[0].source = "other"
            return variants

    class Repository:
        calls = 0
        deactivations = 0
        def upsert_many(self, promotions, **kwargs):
            self.calls += 1
            assert s.output_path.exists() or from_file_state[0]
            if failed: raise OSError("mock network interrupted")
            return len(promotions) - int(short)
        def deactivate_not_seen(self, *args):
            self.deactivations += 1
            return 1
    repo = Repository()
    from_file_state = [False]
    monkeypatch.setattr(runner_module, "SupabasePromotionRepository", lambda: repo)
    runner = runner_module.SyncRunner("uala", lambda: s, Normalizer, normalize_many=True, allow_deactivation=allow)
    monkeypatch.setattr(runner, "load_raw_promotions", lambda: records)
    return runner, s, repo, from_file_state


@pytest.mark.parametrize("mode", ["review", "refused", "blank", "duplicate_raw", "missing_raw", "partial", "zero", "duplicate_normalized", "wrong_source", "save_refused"])
def test_uala_candidate_rejections_never_write(tmp_path, monkeypatch, mode):
    runner, s, repo, _ = setup(tmp_path, monkeypatch, mode=mode)
    with pytest.raises((ValueError, RuntimeError)): runner.run()
    assert not s.output_path.exists() and repo.calls == 0 and repo.deactivations == 0


@pytest.mark.parametrize("mode", ["variant_removed", "variant_replaced"])
def test_qa001_existing_campaign_variant_loss_never_upserts(tmp_path, monkeypatch, mode):
    runner, s, repo, _ = setup(tmp_path, monkeypatch, mode=mode)
    baseline = s.output_path.read_bytes()
    with pytest.raises(ValueError, match="historical variant IDs"): runner.run()
    assert s.output_path.read_bytes() == baseline
    assert repo.calls == 0 and repo.deactivations == 0


@pytest.mark.parametrize("from_file", [False, True])
def test_uala_validate_only_no_writes(tmp_path, monkeypatch, from_file):
    runner, s, repo, _ = setup(tmp_path, monkeypatch)
    runner.run(from_file=from_file, validate_only=True)
    assert not s.output_path.exists() and repo.calls == 0 and repo.deactivations == 0


@pytest.mark.parametrize("short,failed", [(True, False), (False, True)])
def test_upsert_failure_leaves_new_raw_but_never_deactivates(tmp_path, monkeypatch, short, failed):
    runner, s, repo, _ = setup(tmp_path, monkeypatch, short=short, failed=failed, allow=True, safe=True)
    with pytest.raises((OSError, RuntimeError)): runner.run()
    assert s.output_path.exists() and repo.calls == 1 and repo.deactivations == 0
    # Retry is explicit and idempotent at the source snapshot boundary.
    s.save_raw_promotions(s.result.promotions)


@pytest.mark.parametrize("from_file,allow,safe,expected", [(False, False, True, 0), (False, True, False, 0), (True, True, True, 0), (False, True, True, 1)])
def test_every_deactivation_gate(tmp_path, monkeypatch, from_file, allow, safe, expected):
    runner, s, repo, state = setup(tmp_path, monkeypatch, allow=allow, safe=safe)
    state[0] = from_file
    runner.run(from_file=from_file)
    assert repo.deactivations == expected
    assert s.output_path.exists() is (not from_file)
