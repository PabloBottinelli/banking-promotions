import json

import pytest

from processing.preview import preview_snapshot


def test_preview_without_normalizer(tmp_path):
    path = tmp_path / "promotions.json"
    path.write_text(json.dumps([{"source_id": "1"}, {"source_id": "2"}]), encoding="utf-8")

    result = preview_snapshot("test", path)

    assert result["total"] == 2
    assert result["not_attempted"] == 2
    assert result["failed"] == 0
    assert result["variants"] == 0


def test_preview_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "promotions.json"
    path.write_text(json.dumps([{"source_id": "1"}, {"source_id": "1"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicado"):
        preview_snapshot("test", path)