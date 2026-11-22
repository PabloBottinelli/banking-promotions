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

from persistence.hybrid_serializer import hash_raw_data


def test_reuses_normalization_when_raw_hash_matches():
    class CountingNormalizer:
        calls = 0

        def normalize(self, raw):
            self.calls += 1
            raise ValueError("Se ejecutó el normalizador")

    normalizer = CountingNormalizer()
    runner = SyncRunner("bbva", object, lambda: normalizer, storage_mode="hybrid")

    previous_raw = {
        "source": "bbva",
        "source_id": "123",
        "scraped_at": "2026-11-20T10:00:00",
        "detail": {"discount": 30}
    }

    current_raw = {
        **previous_raw,
        "scraped_at": "2026-11-22T10:00:00"
    }

    cache = {
        "123": {
            "raw_hash": hash_raw_data(previous_raw),
            "normalization_status": "normalized",
            "normalized_data": [{
                "source": "bbva",
                "source_id": "123",
                "title": "Promoción anterior",
                "scraped_at": previous_raw["scraped_at"]
            }]
        }
    }

    result = runner.process_promotions([current_raw], cache=cache)

    assert normalizer.calls == 0
    assert result[0].normalization_status == "normalized"
    assert result[0].normalized_data[0]["title"] == "Promoción anterior"
    assert result[0].normalized_data[0]["scraped_at"] == current_raw["scraped_at"]
    assert result[0].raw_data == current_raw

def test_reprocesses_when_commercial_content_changes():
    class CountingNormalizer:
        calls = 0

        def normalize(self, raw):
            self.calls += 1
            raise ValueError("Normalización ejecutada")

    normalizer = CountingNormalizer()
    runner = SyncRunner("bbva", object, lambda: normalizer, storage_mode="hybrid")

    previous_raw = {"source": "bbva", "source_id": "123", "detail": {"discount": 30}}
    current_raw = {"source": "bbva", "source_id": "123", "detail": {"discount": 40}}

    cache = {
        "123": {
            "raw_hash": hash_raw_data(previous_raw),
            "normalization_status": "normalized",
            "normalized_data": [{"source": "bbva", "source_id": "123"}]
        }
    }

    result = runner.process_promotions([current_raw], cache=cache)

    assert normalizer.calls == 1
    assert result[0].normalization_status == "failed"