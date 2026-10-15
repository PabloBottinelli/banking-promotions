"""All runner I/O is replaced with in-memory fakes; no real sync execution."""
import copy
import json
from pathlib import Path

import pytest

from normalization.sources.personal_pay import PersonalPayNormalizer
from scraping.models import ScrapeResult
from synchronization import runner as module


@pytest.mark.parametrize("fault", ["none", "partial-upsert", "upsert-error", "save-error", "review", "refusal", "zero", "duplicate", "raw-id", "partial-scrape", "validate-only"])
def test_personal_pay_runner_gates_and_effects(monkeypatch, fault):
    fixture = Path(__file__).parents[1] / "fixtures/personal_pay/official_examples.json"
    raw = copy.deepcopy(json.loads(fixture.read_text(encoding="utf-8"))[:1])
    events = []
    class Scraper:
        coverage = {"snapshot_replace_allowed": fault != "refusal", "requires_review": fault == "review", "safe_to_deactivate": False}
        def scrape(self):
            if fault == "raw-id":
                raw[0]["source_id"] = ""
            return ScrapeResult(raw, 2 if fault == "partial-scrape" else 1, [])
        def save_raw_promotions(self, records):
            if fault == "save-error":
                raise ValueError("rejected source save")
            events.append("save")
    class Repository:
        def upsert_many(self, rows, **kwargs):
            events.append("upsert")
            if fault == "upsert-error":
                raise OSError("network")
            return 0 if fault == "partial-upsert" else len(rows)
        def deactivate_not_seen(self, *args):
            events.append("deactivate")
            raise AssertionError("Source never authorizes deactivation")
    class Normalizer(PersonalPayNormalizer):
        def normalize_many(self, item):
            rows = super().normalize_many(item)
            return [] if fault == "zero" else rows + rows if fault == "duplicate" else rows
    monkeypatch.setattr(module, "SupabasePromotionRepository", Repository)
    runner = module.SyncRunner("personal_pay", Scraper, Normalizer, normalize_many=True, allow_deactivation=True)
    if fault in ["none", "validate-only"]:
        runner.run(validate_only=fault == "validate-only")
    else:
        with pytest.raises((RuntimeError, ValueError, OSError)):
            runner.run()
    assert "deactivate" not in events
    assert events == (["save", "upsert"] if fault in ["none", "partial-upsert", "upsert-error"] else [])
