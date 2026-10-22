
from datetime import datetime, timezone

import pytest

from normalization.models import Benefit, NormalizedPromotion
from scraping.models import ScrapeResult
from synchronization import runner as runner_module


def make_promotion(source_id="x", source="buepp"):
    return NormalizedPromotion(
        source=source, source_id=source_id, title="Test", scope="merchant",
        valid_from=None, valid_to=None, scraped_at=datetime.now(timezone.utc),
        benefits=[Benefit(type="other", description="test")],
    )


class Repository:
    def __init__(self, fail_count=False):
        self.called = 0
        self.deactivated = 0
        self.fail_count = fail_count

    def upsert_many(self, promotions, batch_size, seen_at):
        self.called += 1
        return len(promotions) - (1 if self.fail_count else 0)

    def deactivate_not_seen(self, source, seen_at):
        self.deactivated += 1
        return 1


class Scraper:
    def __init__(self, data, *, complete=True, coverage=None):
        self.data = data
        self.saved = False
        self.complete = complete
        self.coverage = coverage or {}

    def scrape(self):
        return ScrapeResult(self.data, len(self.data) + int(not self.complete), [])

    def save_raw_promotions(self, promotions):
        self.saved = True


class Normalizer:
    def normalize_many(self, raw):
        kind = raw.get("kind")
        if kind == "empty":
            return []
        if kind == "duplicate":
            return [make_promotion("dup"), make_promotion("dup")]
        if kind == "wrong_source":
            return [make_promotion(raw["source_id"], source="otra_fuente")]
        if kind == "bad_type":
            return [object()]
        if kind == "fail":
            raise ValueError("fallo del normalizador")
        return [make_promotion(raw["source_id"])]


def setup(monkeypatch, records, *, complete=True, coverage=None, fail_count=False, allow_deactivation=False):
    repo = Repository(fail_count=fail_count)
    scraper = Scraper(records, complete=complete, coverage=coverage)
    runner = runner_module.SyncRunner("buepp", lambda: scraper, Normalizer, normalize_many=True,
                                       allow_deactivation=allow_deactivation)
    monkeypatch.setattr(runner_module, "SupabasePromotionRepository", lambda: repo)
    return runner, scraper, repo


@pytest.mark.parametrize("records", [
    [],
    [{"source_id": "x"}, {"source_id": "x"}],
    [{"title": "sin ID"}],
    ["no es dict"],
    [{"source_id": "x", "source": "otra_fuente"}],
    [{"source_id": "x", "kind": "empty"}],
    [{"source_id": "x", "kind": "duplicate"}],
    [{"source_id": "x", "kind": "wrong_source"}],
    [{"source_id": "x", "kind": "bad_type"}],
    [{"source_id": "x", "kind": "fail"}],
])
def test_invalid_candidates_never_write(monkeypatch, records):
    runner, scraper, repo = setup(monkeypatch, records)
    with pytest.raises(RuntimeError):
        runner.run()
    assert scraper.saved is False
    assert repo.called == 0
    assert repo.deactivated == 0


def test_incomplete_scrape_never_writes(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}], complete=False)
    with pytest.raises(RuntimeError, match="incompleto"):
        runner.run()
    assert not scraper.saved
    assert repo.called == 0


def test_requires_review_never_writes(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}], coverage={"requires_review": True})
    with pytest.raises(RuntimeError, match="no autoriza"):
        runner.run()
    assert not scraper.saved
    assert repo.called == 0


def test_snapshot_rejection_never_writes_supabase(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}])
    def reject(_):
        raise ValueError("IDs desaparecidos")
    scraper.save_raw_promotions = reject
    with pytest.raises(ValueError, match="desaparecidos"):
        runner.run()
    assert repo.called == 0


def test_full_validation_then_save_then_upsert(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}])
    runner.run()
    assert scraper.saved
    assert repo.called == 1
    assert repo.deactivated == 0


def test_upsert_partial_count_does_not_deactivate(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}], fail_count=True,
                                  coverage={"safe_to_deactivate": True}, allow_deactivation=True)
    with pytest.raises(RuntimeError, match="Upsert incompleto"):
        runner.run()
    assert scraper.saved
    assert repo.called == 1
    assert repo.deactivated == 0


def test_from_file_does_not_resave_and_does_not_deactivate(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}],
                                  coverage={"safe_to_deactivate": True}, allow_deactivation=True)
    monkeypatch.setattr(runner, "load_raw_promotions", lambda: scraper.data)
    runner.run(from_file=True)
    assert not scraper.saved
    assert repo.called == 1
    assert repo.deactivated == 0


def test_validate_only_does_not_write_raw_or_supabase(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}])
    runner.run(validate_only=True)
    assert not scraper.saved
    assert repo.called == 0
    assert repo.deactivated == 0


def test_validate_from_file_does_not_write_raw_or_supabase(monkeypatch):
    runner, scraper, repo = setup(monkeypatch, [{"source_id": "x"}])
    monkeypatch.setattr(runner, "load_raw_promotions", lambda: scraper.data)
    runner.run(from_file=True, validate_only=True)
    assert not scraper.saved
    assert repo.called == 0
    assert repo.deactivated == 0
