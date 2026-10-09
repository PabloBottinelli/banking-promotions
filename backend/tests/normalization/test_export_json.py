"""Smoke tests for the read-only V2 JSON export command."""
import json
from datetime import datetime, timezone

import pytest

from normalization import export_json
from normalization.models import Benefit, NormalizedPromotion


def promotion(source_id="id-1"):
    return NormalizedPromotion(
        source="fake", source_id=source_id,
        scraped_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        title="Beneficio", scope="other", valid_from=None, valid_to=None,
        benefits=[Benefit(type="cashback", percentage="12.5")],
    )


def test_exports_json_without_db(tmp_path, monkeypatch):
    (tmp_path / "fake_promotions.json").write_text(
        json.dumps([{"source_id": "raw-1"}]), encoding="utf-8"
    )

    class FakeNormalizer:
        def normalize(self, raw):
            return promotion()

    monkeypatch.setitem(export_json.SOURCES, "fake", (FakeNormalizer, False))
    result = export_json.export_source("fake", input_dir=tmp_path)
    output = tmp_path / "normalized" / "fake_promotions.json"
    data = json.loads(output.read_text(encoding="utf-8"))
    assert result["normalized_count"] == 1
    assert data[0]["valid_to"] is None
    assert data[0]["benefits"][0]["percentage"] == "12.5"
    assert data[0]["source_id"] == "id-1"
    assert json.loads((tmp_path / "fake_promotions.json").read_text()) == [{"source_id": "raw-1"}]


def test_bad_record_does_not_overwrite_previous_export(tmp_path, monkeypatch):
    (tmp_path / "fake_promotions.json").write_text(
        json.dumps([{"source_id": "good"}, {"source_id": "bad"}]), encoding="utf-8"
    )
    output_dir = tmp_path / "normalized"
    output_dir.mkdir()
    old = output_dir / "fake_promotions.json"
    old.write_text("previous valid snapshot", encoding="utf-8")

    class FakeNormalizer:
        def normalize(self, raw):
            if raw["source_id"] == "bad":
                raise ValueError("could not parse")
            return promotion()

    monkeypatch.setitem(export_json.SOURCES, "fake", (FakeNormalizer, False))
    with pytest.raises(RuntimeError, match="source_id='bad'"):
        export_json.export_source("fake", input_dir=tmp_path)
    assert old.read_text(encoding="utf-8") == "previous valid snapshot"


def test_duplicate_ids_fail_and_do_not_write_file(tmp_path, monkeypatch):
    (tmp_path / "fake_promotions.json").write_text(
        json.dumps([{"source_id": "raw-1"}, {"source_id": "raw-2"}]), encoding="utf-8"
    )

    class FakeNormalizer:
        def normalize(self, raw):
            return promotion("same-id")

    monkeypatch.setitem(export_json.SOURCES, "fake", (FakeNormalizer, False))
    with pytest.raises(RuntimeError, match="source_id duplicado"):
        export_json.export_source("fake", input_dir=tmp_path)
    assert not (tmp_path / "normalized" / "fake_promotions.json").exists()
