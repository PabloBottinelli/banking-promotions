import json

import httpx
import pytest

from persistence.hybrid_repository import HybridPromotionRepository
from processing.hybrid import HybridPromotion


def test_upsert_many():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)

    promotions = [
        HybridPromotion(source="buepp", source_id="123", raw_data={"title": "Primera"}, normalization_status="not_attempted"),
        HybridPromotion(source="buepp", source_id="456", raw_data={"title": "Segunda"}, normalization_status="failed", normalization_error="Error de normalización")
    ]

    with httpx.Client(transport=transport) as client:
        repository = HybridPromotionRepository("https://supabase.invalid", {"apikey": "test"}, client)
        total = repository.upsert_many(promotions, batch_size=1)

    assert total == 2
    assert len(requests) == 2

    first = json.loads(requests[0].content)[0]
    second = json.loads(requests[1].content)[0]

    assert first["source_id"] == "123"
    assert first["raw_data"] == {"title": "Primera"}
    assert first["normalized_data"] == []
    assert first["normalization_status"] == "not_attempted"
    assert len(first["raw_hash"]) == 64

    assert second["normalization_status"] == "failed"
    assert second["normalization_error"] == "Error de normalización"

    assert all("/rest/v1/promotions_hybrid" in str(request.url) for request in requests)


def test_upsert_rejects_duplicates():
    promotions = [
        HybridPromotion(source="buepp", source_id="123", raw_data={}, normalization_status="not_attempted"),
        HybridPromotion(source="buepp", source_id="123", raw_data={}, normalization_status="not_attempted")
    ]

    repository = HybridPromotionRepository("https://supabase.invalid", {"apikey": "test"})

    with pytest.raises(ValueError, match="duplicados"):
        repository.upsert_many(promotions)


def test_upsert_propagates_http_errors():
    def handler(request):
        return httpx.Response(500, json={"message": "Error de prueba"})

    promotion = HybridPromotion(source="buepp", source_id="123", raw_data={}, normalization_status="not_attempted")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        repository = HybridPromotionRepository("https://supabase.invalid", {"apikey": "test"}, client)

        with pytest.raises(httpx.HTTPStatusError):
            repository.upsert_many([promotion])

def test_upsert_splits_batches_by_size():
    from datetime import datetime, timezone
    from persistence.hybrid_serializer import serialize_hybrid_promotion

    requests = []
    seen_at = datetime(2026, 11, 21, tzinfo=timezone.utc)

    def handler(request):
        requests.append(request)
        return httpx.Response(201)

    promotions = [
        HybridPromotion(source="buepp", source_id=str(i), raw_data={"description": "A" * 200}, normalization_status="not_attempted")
        for i in range(3)
    ]

    single_record = serialize_hybrid_promotion(promotions[0], seen_at)
    limit = len(json.dumps([single_record], ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 10

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        repository = HybridPromotionRepository("https://supabase.invalid", {"apikey": "test"}, client)
        total = repository.upsert_many(promotions, batch_size=50, max_payload_bytes=limit, seen_at=seen_at)

    assert total == 3
    assert len(requests) == 3
    assert all(len(request.content) <= limit for request in requests)
    assert [json.loads(request.content)[0]["source_id"] for request in requests] == ["0", "1", "2"]

def test_upsert_rejects_oversized_record_before_writing():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201)

    promotions = [
        HybridPromotion(source="buepp", source_id="normal", raw_data={"description": "Pequeña"}, normalization_status="not_attempted"),
        HybridPromotion(source="buepp", source_id="grande", raw_data={"description": "A" * 5000}, normalization_status="not_attempted")
    ]

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        repository = HybridPromotionRepository("https://supabase.invalid", {"apikey": "test"}, client)

        with pytest.raises(ValueError, match="demasiado grande"):
            repository.upsert_many(promotions, max_payload_bytes=1000)

    assert len(requests) == 0

def test_upsert_rejects_invalid_payload_limit():
    repository = HybridPromotionRepository("https://supabase.invalid", {"apikey": "test"})

    with pytest.raises(ValueError, match="max_payload_bytes"):
        repository.upsert_many([], max_payload_bytes=0)

def test_get_existing_promotions_paginates():
    rows = [
        {"source_id": str(i), "raw_hash": "hash", "normalization_status": "normalized", "normalized_data": [{"source_id": str(i)}]}
        for i in range(3)
    ]

    requests = []

    def handler(request):
        requests.append(request)

        assert request.method == "GET"
        assert request.url.params["source"] == "eq.bbva"
        assert "normalization_status" not in request.url.params

        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])

        return httpx.Response(200, json=rows[offset:offset + limit])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        repository = HybridPromotionRepository("https://supabase.invalid", {"apikey": "test"}, client)
        cache = repository.get_existing_promotions("bbva", page_size=2)

    assert len(cache) == 3
    assert set(cache) == {"0", "1", "2"}
    assert len(requests) == 2