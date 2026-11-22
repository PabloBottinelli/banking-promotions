
from datetime import datetime, timezone

import pytest

from normalization.models import Benefit, NormalizedPromotion
from scraping.models import ScrapeResult
from synchronization import runner as runner_module
from persistence.hybrid_serializer import hash_raw_data

def make_promotion(source_id="x", source="buepp"):
    return NormalizedPromotion(
        source=source, source_id=source_id, title="Test", scope="merchant",
        valid_from=None, valid_to=None, scraped_at=datetime.now(timezone.utc),
        benefits=[Benefit(type="other", description="test")],
    )

def verified_buepp_coverage():
    return {
        "catalog_complete": True,
        "failed_ids": [],
        "pagination": {
            "terminal_page_empty": True,
        },
    }

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
    with pytest.raises(RuntimeError, match="Sincronización incompleta"):
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

def test_hybrid_run_preserves_failed_normalization(monkeypatch):
    raw = [{"source_id": "correcta"}, {"source_id": "fallida", "kind": "fail"}]
    runner, scraper, legacy_repository = setup(monkeypatch, raw, coverage=verified_buepp_coverage())
    runner.storage_mode = "hybrid"

    received = []

    class FakeHybridRepository:
        def __init__(self, base_url, headers):
            pass

        def upsert_many(self, promotions, batch_size, seen_at):
            received.extend(promotions)
            return len(promotions)

        def get_existing_promotions(self, source):
            return {}

        def touch_unchanged(self, source, items, batch_size=200, seen_at=None):
            assert items == []
            return 0

    monkeypatch.setattr(runner_module, "HybridPromotionRepository", FakeHybridRepository)
    monkeypatch.setattr(runner_module, "SUPABASE_URL", "https://supabase.invalid")
    monkeypatch.setattr(runner_module, "get_headers", lambda: {"apikey": "test"})

    runner.run()

    assert scraper.saved
    assert legacy_repository.called == 0
    assert len(received) == 2
    assert received[0].normalization_status == "normalized"
    assert received[1].normalization_status == "failed"
    assert received[1].raw_data == raw[1]


def test_hybrid_incomplete_scrape_never_writes(monkeypatch):
    runner, scraper, legacy_repository = setup(monkeypatch, [{"source_id": "123"}], complete=False)
    runner.storage_mode = "hybrid"

    def forbidden_repository(*args, **kwargs):
        raise AssertionError("No debería acceder a Supabase")

    monkeypatch.setattr(runner_module, "HybridPromotionRepository", forbidden_repository)

    with pytest.raises(RuntimeError, match="incompleto"):
        runner.run()

    assert not scraper.saved
    assert legacy_repository.called == 0

def test_hybrid_validate_only_never_writes(monkeypatch):
    runner, scraper, legacy_repository = setup(monkeypatch, [{"source_id": "123"}], coverage=verified_buepp_coverage())
    runner.storage_mode = "hybrid"

    def forbidden_repository(*args, **kwargs):
        raise AssertionError("No debería acceder a Supabase")

    monkeypatch.setattr(runner_module, "HybridPromotionRepository", forbidden_repository)

    runner.run(validate_only=True)

    assert not scraper.saved
    assert legacy_repository.called == 0

def test_hybrid_runner_uses_incremental_sync(monkeypatch):
    raw = [
        {"source": "buepp", "source_id": "same", "discount": 20},
        {"source": "buepp", "source_id": "changed", "discount": 40},
    ]

    previous = make_promotion("same").model_dump(mode="json")

    existing = {
        "same": {
            "raw_hash": hash_raw_data(raw[0]),
            "normalization_status": "normalized",
            "normalized_data": [previous],
            "active": True,
        },
        "changed": {
            "raw_hash": hash_raw_data({"source": "buepp", "source_id": "changed", "discount": 30}),
            "normalization_status": "normalized",
            "normalized_data": [make_promotion("changed").model_dump(mode="json")],
            "active": True,
        },
    }

    calls = []

    class FakeHybridRepository:
        def __init__(self, base_url, headers):
            pass

        def get_existing_promotions(self, source):
            calls.append("read")
            return existing

        def upsert_many(self, promotions, batch_size, seen_at):
            calls.append(("upsert", [p.source_id for p in promotions]))
            return len(promotions)

        def touch_unchanged(self, source, items, batch_size, seen_at):
            calls.append(("touch", [source_id for source_id, _ in items]))
            return len(items)

    runner, scraper, legacy_repo = setup(monkeypatch, raw, coverage=verified_buepp_coverage())

    runner.storage_mode = "hybrid"

    monkeypatch.setattr(runner_module, "HybridPromotionRepository", FakeHybridRepository)
    monkeypatch.setattr(runner_module, "SUPABASE_URL", "https://supabase.invalid")
    monkeypatch.setattr(runner_module, "get_headers", lambda: {"apikey": "test"})

    runner.run()

    assert scraper.saved
    assert legacy_repo.called == 0

    assert calls == [
        "read",
        ("upsert", ["changed"]),
        ("touch", ["same"]),
    ]

def test_hybrid_runner_rejects_unverified_file_import(monkeypatch):
    runner, scraper, legacy_repo = setup(monkeypatch, [{"source_id": "123"}])
    runner.storage_mode = "hybrid"

    monkeypatch.setattr(runner, "load_raw_promotions", lambda: scraper.data)

    with pytest.raises(RuntimeError, match="import_hybrid"):
        runner.run(from_file=True)

    assert not scraper.saved
    assert legacy_repo.called == 0

@pytest.mark.parametrize(
    "coverage",
    [
        {},
        {
            "catalog_complete": False,
            "failed_ids": [],
            "pagination": {"terminal_page_empty": True},
        },
        {
            "catalog_complete": True,
            "failed_ids": ["123"],
            "pagination": {"terminal_page_empty": True},
        },
        {
            "catalog_complete": True,
            "failed_ids": [],
            "pagination": {"terminal_page_empty": False},
        },
    ],
)
def test_hybrid_rejects_invalid_coverage_before_supabase(monkeypatch, coverage):
    runner, scraper, legacy_repo = setup(
        monkeypatch,
        [{"source_id": "123"}],
        coverage=coverage,
    )

    runner.storage_mode = "hybrid"

    def forbidden_repository(*args, **kwargs):
        raise AssertionError("No debería acceder a Supabase")

    monkeypatch.setattr(
        runner_module,
        "HybridPromotionRepository",
        forbidden_repository,
    )

    with pytest.raises(RuntimeError, match="Captura"):
        runner.run()

    assert not scraper.saved
    assert legacy_repo.called == 0

def test_hybrid_bbva_requires_verified_pagination(monkeypatch):
    runner, scraper, legacy_repo = setup(
        monkeypatch,
        [{"source_id": "123"}],
        coverage={
            "catalog_complete": True,
            "failed_ids": [],
            "terminal_verified": False,
            "limited": False,
        },
    )

    runner.source = "bbva"
    runner.storage_mode = "hybrid"

    def forbidden_repository(*args, **kwargs):
        raise AssertionError("No debería acceder a Supabase")

    monkeypatch.setattr(
        runner_module,
        "HybridPromotionRepository",
        forbidden_repository,
    )

    with pytest.raises(RuntimeError, match="BBVA"):
        runner.run()

    assert not scraper.saved
    assert legacy_repo.called == 0

def test_hybrid_validation_fails_on_normalization_errors(monkeypatch):
    raw = [
        {
            "source": "buepp",
            "source_id": "fallida",
            "kind": "fail",
        }
    ]

    runner, scraper, legacy_repo = setup(
        monkeypatch,
        raw,
        coverage=verified_buepp_coverage(),
    )

    runner.storage_mode = "hybrid"

    def forbidden_repository(*args, **kwargs):
        raise AssertionError(
            "La validación no debe acceder a Supabase"
        )

    monkeypatch.setattr(
        runner_module,
        "HybridPromotionRepository",
        forbidden_repository,
    )

    with pytest.raises(
        RuntimeError,
        match="Normalizaciones inválidas",
    ):
        runner.run(validate_only=True)

    assert not scraper.saved
    assert legacy_repo.called == 0