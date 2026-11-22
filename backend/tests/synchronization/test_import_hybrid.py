import hashlib
import json

import pytest

from synchronization.import_hybrid import prepare_import
import sys

from processing.hybrid import HybridPromotion
from synchronization import import_hybrid
from persistence import hybrid_repository
from persistence.hybrid_serializer import hash_raw_data
from processing.hybrid import HybridPromotion
from synchronization.import_hybrid import build_incremental_plan

def make_bbva_snapshot(tmp_path):
    snapshot = tmp_path / "bbva_promotions.json"
    coverage = tmp_path / "bbva_coverage.json"

    records = [
        {
            "source": "bbva",
            "source_id": 123,
            "scraped_at": "2026-11-21T10:00:00",
            "catalog": {"id": 123},
            "detail": {"id": 123}
        }
    ]

    snapshot.write_text(json.dumps(records), encoding="utf-8")

    return snapshot, coverage


def test_bbva_without_coverage_allows_preview(tmp_path):
    snapshot, coverage = make_bbva_snapshot(tmp_path)

    promotions, digest, verified = prepare_import("bbva", snapshot, coverage)

    assert len(promotions) == 1
    assert promotions[0].source_id == "123"
    assert len(digest) == 64
    assert verified is False


def test_bbva_rejects_inconsistent_ids(tmp_path):
    snapshot, coverage = make_bbva_snapshot(tmp_path)

    records = json.loads(snapshot.read_text(encoding="utf-8"))
    records[0]["detail"]["id"] = 999
    snapshot.write_text(json.dumps(records), encoding="utf-8")

    with pytest.raises(ValueError, match="IDs inconsistentes"):
        prepare_import("bbva", snapshot, coverage)


def test_bbva_rejects_incorrect_coverage_hash(tmp_path):
    snapshot, coverage = make_bbva_snapshot(tmp_path)

    coverage.write_text(json.dumps({
        "source": "bbva",
        "snapshot_sha256": "incorrecto",
        "catalog_complete": True,
        "limited": False,
        "failed_ids": [],
        "catalog_count": 1,
        "detail_success": 1
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="no corresponde"):
        prepare_import("bbva", snapshot, coverage)


def test_bbva_accepts_matching_coverage(tmp_path):
    snapshot, coverage = make_bbva_snapshot(tmp_path)

    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    coverage.write_text(json.dumps({
        "source": "bbva",
        "snapshot_sha256": digest,
        "catalog_complete": True,
        "limited": False,
        "failed_ids": [],
        "catalog_count": 1,
        "detail_success": 1,
        "terminal_verified": True,
    }), encoding="utf-8")

    promotions, result_hash, verified = prepare_import("bbva", snapshot, coverage)

    assert verified is True
    assert result_hash == digest
    assert len(promotions) == 1

@pytest.mark.parametrize("force_reprocess", [False, True])
def test_import_uses_cache_only_when_enabled(tmp_path, monkeypatch, force_reprocess):
    snapshot = tmp_path / "promotions.json"
    snapshot.write_text('[{"source":"buepp","source_id":"123"}]', encoding="utf-8")

    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    calls = []
    received_caches = []

    cached = {
        "123": {
            "source_id": "123",
            "raw_hash": "hash",
            "normalization_status": "normalized",
            "normalized_data": [{"source": "buepp", "source_id": "123"}]
        }
    }

    class FakeRepository:
        def __init__(self, base_url, headers):
            calls.append("init")

        def get_existing_promotions(self, source):
            calls.append("read")
            assert source == "buepp"
            return cached

        def upsert_many(self, promotions, batch_size, seen_at=None):
            calls.append("write")
            assert batch_size == 50
            assert seen_at is not None
            assert len(promotions) == 1
            return len(promotions)

        def touch_unchanged(self, source, items, batch_size=200, seen_at=None):
            return len(items)

    def fake_prepare(source, snapshot_path, coverage_path, cache=None):
        received_caches.append(cache)

        promotion = HybridPromotion(
            source="buepp",
            source_id="123",
            raw_data={"source": "buepp", "source_id": "123"},
            normalization_status="not_attempted",
        )

        return [promotion], digest, True

    monkeypatch.setattr(hybrid_repository, "HybridPromotionRepository", FakeRepository)
    monkeypatch.setattr(import_hybrid, "prepare_import", fake_prepare)

    args = [
        "import_hybrid",
        "--source", "buepp",
        "--file", str(snapshot),
        "--write",
        "--expect-count", "1",
        "--expect-sha256", digest,
    ]

    if force_reprocess:
        args.append("--force-reprocess")

    monkeypatch.setattr(sys, "argv", args)

    import_hybrid.main()

    if force_reprocess:
        assert calls == ["init", "write"]
        assert received_caches == [None]
    else:
        assert calls == ["init", "read", "write"]
        assert received_caches == [cached]

def test_incremental_plan_classifies_changes():
    def promotion(source_id, discount):
        return HybridPromotion(source="bbva", source_id=source_id, raw_data={"source_id": source_id, "discount": discount}, normalized_data=[{"source": "bbva", "source_id": source_id}], normalization_status="normalized")

    promotions = [
        promotion("new", 10),
        promotion("same", 20),
        promotion("changed", 40),
        promotion("retry", 30),
    ]

    existing = {
        "same": {
            "raw_hash": hash_raw_data(promotions[1].raw_data),
            "normalization_status": "normalized",
            "normalized_data": [{"source": "bbva", "source_id": "same"}],
            "active": True,
        },
        "changed": {
            "raw_hash": hash_raw_data({"source_id": "changed", "discount": 20}),
            "normalization_status": "normalized",
            "normalized_data": [{"source": "bbva", "source_id": "changed"}],
            "active": True,
        },
        "retry": {
            "raw_hash": hash_raw_data(promotions[3].raw_data),
            "normalization_status": "failed",
            "normalized_data": [],
            "active": True,
        },
        "missing": {
            "raw_hash": "previous",
            "normalization_status": "normalized",
            "normalized_data": [],
            "active": True,
        },
    }

    plan = build_incremental_plan(promotions, existing)

    assert plan["new"] == ["new"]
    assert plan["unchanged"] == ["same"]
    assert plan["modified"] == ["changed"]
    assert plan["retry"] == ["retry"]
    assert plan["missing"] == ["missing"]

def test_incremental_plan_force_reprocess():
    promotion = HybridPromotion(source="bbva", source_id="123", raw_data={"discount": 30}, normalization_status="normalized")

    existing = {
        "123": {
            "raw_hash": hash_raw_data(promotion.raw_data),
            "normalization_status": "normalized",
            "normalized_data": [{"source": "bbva", "source_id": "123"}],
            "active": True,
        }
    }

    plan = build_incremental_plan([promotion], existing, force_reprocess=True)

    assert plan["reprocess"] == ["123"]
    assert plan["unchanged"] == []

def test_incremental_write_only_upserts_changed_promotions(tmp_path, monkeypatch):
    snapshot = tmp_path / "promotions.json"
    snapshot.write_text('[{"source":"bbva","source_id":"same"},{"source":"bbva","source_id":"changed"}]', encoding="utf-8")

    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    raw_same = {"source": "bbva", "source_id": "same", "discount": 20}
    raw_changed = {"source": "bbva", "source_id": "changed", "discount": 40}

    promotions = [
        HybridPromotion(source="bbva", source_id="same", raw_data=raw_same, normalized_data=[{"source": "bbva", "source_id": "same"}], normalization_status="normalized"),
        HybridPromotion(source="bbva", source_id="changed", raw_data=raw_changed, normalized_data=[{"source": "bbva", "source_id": "changed"}], normalization_status="normalized"),
    ]

    existing = {
        "same": {
            "raw_hash": hash_raw_data(raw_same),
            "normalization_status": "normalized",
            "normalized_data": [{"source": "bbva", "source_id": "same"}],
            "active": True,
        },
        "changed": {
            "raw_hash": hash_raw_data({"source": "bbva", "source_id": "changed", "discount": 30}),
            "normalization_status": "normalized",
            "normalized_data": [{"source": "bbva", "source_id": "changed"}],
            "active": True,
        },
    }

    calls = []

    class FakeRepository:
        def __init__(self, base_url, headers):
            pass

        def get_existing_promotions(self, source):
            return existing

        def upsert_many(self, records, batch_size, seen_at=None):
            calls.append(("upsert", [p.source_id for p in records]))
            return len(records)

        def touch_unchanged(self, source, items, batch_size=200, seen_at=None):
            calls.append(("touch", items))
            return len(items)

    def fake_prepare(source, snapshot_path, coverage_path, cache=None):
        return promotions, digest, True

    monkeypatch.setattr(hybrid_repository, "HybridPromotionRepository", FakeRepository)
    monkeypatch.setattr(import_hybrid, "prepare_import", fake_prepare)

    monkeypatch.setattr(sys, "argv", [
        "import_hybrid",
        "--source", "bbva",
        "--file", str(snapshot),
        "--write",
        "--expect-count", "2",
        "--expect-sha256", digest,
    ])

    import_hybrid.main()

    assert calls[0] == ("upsert", ["changed"])
    assert calls[1] == ("touch", [("same", hash_raw_data(raw_same))])