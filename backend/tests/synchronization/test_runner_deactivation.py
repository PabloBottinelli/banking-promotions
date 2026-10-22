
import pytest
from scraping.models import ScrapeResult
from synchronization import runner as runner_module


class FakeRepository:
    def __init__(self):
        self.received = []
        self.deactivation_calls = 0

    def upsert_many(self, promotions, batch_size, seen_at):
        self.received.extend(promotions)
        return len(promotions)

    def deactivate_not_seen(self, source, seen_at):
        self.deactivation_calls += 1
        return 1


class FakeScraper:
    def __init__(self, raw, *, complete=True, safe=False):
        self.raw = raw
        self.complete = complete
        self.saved = False
        self.coverage = {"safe_to_deactivate": safe, "snapshot_replace_allowed": True}

    def scrape(self):
        return ScrapeResult(self.raw, len(self.raw) if self.complete else len(self.raw) + 1, [])

    def save_raw_promotions(self, promotions):
        self.saved = True


class ValidNormalizer:
    def normalize(self, raw):
        from normalization.models import Benefit, NormalizedPromotion
        from datetime import datetime, timezone
        return NormalizedPromotion(
            source="buepp", source_id=raw["source_id"],
            scraped_at=datetime.now(timezone.utc),
            title="Beneficio", scope="merchant", valid_from=None,
            valid_to=None, benefits=[Benefit(type="discount", percentage=10)],
        )


@pytest.mark.parametrize(
    ("from_file", "allow_deactivation", "safe", "expected"),
    [(False, False, True, 0), (False, True, False, 0),
     (False, True, True, 1), (True, True, True, 0)],
)
def test_deactivation_requires_all_gates(monkeypatch, from_file, allow_deactivation, safe, expected):
    repo = FakeRepository()
    scraper = FakeScraper([{"source_id": "promo-1", "source": "buepp"}], safe=safe)
    monkeypatch.setattr(runner_module, "SupabasePromotionRepository", lambda: repo)
    runner = runner_module.SyncRunner("buepp", lambda: scraper, ValidNormalizer, allow_deactivation=allow_deactivation)
    monkeypatch.setattr(runner, "load_raw_promotions", lambda: scraper.raw)
    runner.run(from_file=from_file)

    assert repo.deactivation_calls == expected
    assert len(repo.received) == 1
    assert scraper.saved is (not from_file)
