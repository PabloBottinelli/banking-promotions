import json

import pytest

from synchronization.import_buepp_hybrid import prepare_import


def make_files(tmp_path, raw=None):
    raw = raw if raw is not None else [{"source": "buepp", "source_id": "123", "scraped_at": "2026-11-21T10:00:00"}]

    snapshot = tmp_path / "buepp_promotions.json"
    coverage = tmp_path / "buepp_coverage.json"

    snapshot.write_text(json.dumps(raw), encoding="utf-8")
    coverage.write_text(json.dumps({"catalog_complete": True, "catalog_count": len(raw), "detail_success": len(raw), "unique_discovered": len(raw), "scraped_at": "2026-11-21T10:00:00"}), encoding="utf-8")

    return snapshot, coverage


def test_prepare_import(tmp_path):
    snapshot, coverage = make_files(tmp_path)

    promotions, digest = prepare_import(snapshot, coverage)

    assert len(promotions) == 1
    assert promotions[0].source_id == "123"
    assert promotions[0].raw_data["source_id"] == "123"
    assert len(digest) == 64


def test_rejects_incomplete_coverage(tmp_path):
    snapshot, coverage = make_files(tmp_path)

    data = json.loads(coverage.read_text(encoding="utf-8"))
    data["catalog_complete"] = False
    coverage.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="completa"):
        prepare_import(snapshot, coverage)


def test_rejects_duplicate_ids(tmp_path):
    raw = [
        {"source": "buepp", "source_id": "123", "scraped_at": "2026-11-21T10:00:00"},
        {"source": "buepp", "source_id": "123", "scraped_at": "2026-11-21T10:00:00"}
    ]

    snapshot, coverage = make_files(tmp_path, raw)

    with pytest.raises(RuntimeError, match="duplicado"):
        prepare_import(snapshot, coverage)