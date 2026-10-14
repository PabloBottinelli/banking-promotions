"""Test deactivation policy without running Supabase or a live scraper."""

import pytest

from scraping.models import ScrapeResult
from synchronization import runner as runner_module


@pytest.mark.parametrize(
    ("from_file", "allow_deactivation", "expected_deactivations"),
    [(False, False, 0), (False, True, 1), (True, True, 0)],
)
def test_runner_deactivation_gate(monkeypatch, from_file, allow_deactivation, expected_deactivations):
    class Repository:
        def __init__(self):
            self.deactivation_calls = 0
            self.upsert_calls = 0

        def upsert_many(self, promotions, batch_size, seen_at):
            self.upsert_calls += 1
            assert len(promotions) == 1
            return 1

        def deactivate_not_seen(self, source, seen_at):
            self.deactivation_calls += 1
            assert source == "buepp"
            return 1

    repository = Repository()
    monkeypatch.setattr(runner_module, "SupabasePromotionRepository", lambda: repository)
    runner = runner_module.SyncRunner("buepp", object, object, allow_deactivation=allow_deactivation)
    result = ScrapeResult([{"source_id": "1"}], 1, [])
    monkeypatch.setattr(runner, "scrape_promotions", lambda: result)
    monkeypatch.setattr(runner, "load_raw_promotions", lambda: result.promotions)
    monkeypatch.setattr(runner, "normalize_promotions", lambda raw: [object()])

    runner.run(from_file=from_file)

    assert repository.upsert_calls == 1
    assert repository.deactivation_calls == expected_deactivations
