from datetime import datetime, timezone
import pytest
from normalization.models import Benefit, NormalizedPromotion
from synchronization.runner import SyncRunner

class TestNormalizer:
    def normalize(self, raw):
        if raw["source_id"] == "fallida":
            raise ValueError("No se pudo interpretar")

        return NormalizedPromotion(source="buepp", source_id=raw["source_id"], scraped_at=datetime.now(timezone.utc), title="Promoción de prueba", scope="merchant", valid_from=None, valid_to=None, benefits=[Benefit(type="discount", percentage=20)])

def test_process_promotions():
    runner = SyncRunner("buepp", object, TestNormalizer)

    raw = [
        {"source_id": "correcta"},
        {"source_id": "fallida"}
    ]

    results = runner.process_promotions(raw)

    assert len(results) == 2

    assert results[0].normalization_status == "normalized"
    assert len(results[0].normalized_data) == 1

    assert results[1].normalization_status == "failed"
    assert results[1].raw_data == raw[1]
    assert results[1].normalized_data == []


def test_duplicate_raw_ids():
    runner = SyncRunner("buepp", object, TestNormalizer)

    raw = [
        {"source_id": "123"},
        {"source_id": "123"}
    ]

    with pytest.raises(RuntimeError):
        runner.process_promotions(raw)