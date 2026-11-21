import hashlib
import json

import pytest

from synchronization.import_hybrid import prepare_import


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
        "detail_success": 1
    }), encoding="utf-8")

    promotions, result_hash, verified = prepare_import("bbva", snapshot, coverage)

    assert verified is True
    assert result_hash == digest
    assert len(promotions) == 1