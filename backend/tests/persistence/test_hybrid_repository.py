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