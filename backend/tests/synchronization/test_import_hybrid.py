import hashlib
import json

import pytest

from synchronization.import_hybrid import prepare_import
import sys

from processing.hybrid import HybridPromotion
from synchronization import import_hybrid
from persistence import hybrid_repository

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

        def get_cached_normalizations(self, source):
            calls.append("read")
            assert source == "buepp"
            return cached

        def upsert_many(self, promotions, batch_size):
            calls.append("write")
            assert batch_size == 50
            assert len(promotions) == 1
            return len(promotions)

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