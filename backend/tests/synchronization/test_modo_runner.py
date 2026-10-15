"""Runner tests load the real runner with a stub persistence MODULE.

No Supabase import, environment file, credentials, network or real snapshots.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from normalization.sources.modo import ModoNormalizer
from scraping.models import ScrapeResult


@pytest.fixture
def setup_runner(tmp_path, monkeypatch):
    backend = Path(__file__).resolve().parents[2]
    stub = types.ModuleType("persistence.supabase_repository")
    stub.SupabasePromotionRepository = object
    monkeypatch.setitem(sys.modules, "persistence.supabase_repository", stub)
    spec = importlib.util.spec_from_file_location("modo_isolated_runner", backend / "synchronization" / "runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    detail = json.loads((backend / "tests" / "fixtures" / "modo" / "cardon.json").read_text(encoding="utf-8"))
    raw = {"source": "modo", "source_id": detail["id"], "scraped_at": "2026-10-15T03:00:00+00:00", "detail": detail,
           "banks": [], "promotion_url": "https://www.modo.com.ar/promos/" + detail["slug"]}
    class Scraper:
        saved = False
        reject_save = False
        coverage = {"snapshot_replace_allowed": True, "requires_review": False, "safe_to_deactivate": False}
        result = ScrapeResult([raw], 1, [])
        def scrape(self):
            return self.result
        def save_raw_promotions(self, records):
            if self.reject_save:
                raise ValueError("source rejected")
            self.saved = True
    class Repo:
        calls = 0
        deactivations = 0
        partial = False
        fail = False
        def upsert_many(self, promotions, **kwargs):
            self.calls += 1
            if self.fail:
                raise OSError("network failed")
            return len(promotions) - int(self.partial)
        def deactivate_not_seen(self, *args):
            self.deactivations += 1
            return 0
    scraper, repository = Scraper(), Repo()
    monkeypatch.setattr(module, "SupabasePromotionRepository", lambda: repository)
    runner = module.SyncRunner("modo", lambda: scraper, ModoNormalizer, normalize_many=True)
    runner.raw_path = tmp_path / "raw.json"
    monkeypatch.setattr(runner, "load_raw_promotions", lambda: scraper.result.promotions)
    return runner, scraper, repository


@pytest.mark.parametrize("issue", ["empty", "duplicate_raw", "blank_id", "wrong_source", "incomplete", "blank_detail", "review", "replace_false", "reject_save", "zero_variants", "duplicate_variants", "wrong_variant_source", "blank_variant_id"])
def test_every_rejection_preserves_both_destinations(setup_runner, monkeypatch, issue):
    runner, scraper, repo = setup_runner
    if issue == "empty":
        scraper.result.promotions = []
    elif issue == "duplicate_raw":
        scraper.result.promotions *= 2
    elif issue == "blank_id":
        scraper.result.promotions[0]["source_id"] = " "
    elif issue == "wrong_source":
        scraper.result.promotions[0]["source"] = "other"
    elif issue == "incomplete":
        scraper.result.failed_ids = ["one"]
    elif issue == "blank_detail":
        scraper.result.promotions[0]["detail"]["terms_and_conditions"] = "<p> </p>"
    elif issue == "review":
        scraper.coverage = {"requires_review": True}
    elif issue == "replace_false":
        scraper.coverage = {"snapshot_replace_allowed": False}
    elif issue == "reject_save":
        scraper.reject_save = True
    else:
        valid = ModoNormalizer().normalize_many(scraper.result.promotions[0])[0]
        if issue == "zero_variants":
            output = []
        elif issue == "duplicate_variants":
            output = [valid, valid]
        elif issue == "wrong_variant_source":
            output = [valid.model_copy(update={"source": "other"})]
        else:
            output = [valid.model_copy(update={"source_id": " "})]
        monkeypatch.setattr(ModoNormalizer, "normalize_many", lambda *_: output)
    with pytest.raises((RuntimeError, ValueError)):
        runner.run()
    assert not scraper.saved and repo.calls == 0 and repo.deactivations == 0


@pytest.mark.parametrize("from_file,validate_only,allow,safe,expected", [
    (False, True, True, True, 0), (True, True, True, True, 0),
    (False, False, False, True, 0), (False, False, True, False, 0),
    (False, False, True, True, 1), (True, False, True, True, 0),
])
def test_validation_and_each_deactivation_gate(setup_runner, from_file, validate_only, allow, safe, expected):
    runner, scraper, repo = setup_runner
    runner.allow_deactivation = allow
    scraper.coverage = {**scraper.coverage, "safe_to_deactivate": safe}
    runner.run(from_file=from_file, validate_only=validate_only)
    assert scraper.saved is (not validate_only and not from_file)
    assert repo.calls == int(not validate_only)
    assert repo.deactivations == expected


@pytest.mark.parametrize("failure", ["partial", "network"])
def test_failed_upsert_retains_new_raw_for_retry_never_deactivates(setup_runner, failure):
    runner, scraper, repo = setup_runner
    runner.allow_deactivation = True
    scraper.coverage = {**scraper.coverage, "safe_to_deactivate": True}
    repo.partial, repo.fail = failure == "partial", failure == "network"
    with pytest.raises((RuntimeError, OSError)):
        runner.run()
    assert scraper.saved and repo.calls == 1 and repo.deactivations == 0
