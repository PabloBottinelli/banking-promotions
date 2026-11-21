from persistence.hybrid_serializer import serialize_hybrid_promotion
from processing.hybrid import HybridPromotion


def test_serialize_normalized_promotion():
    promotion = HybridPromotion(source="buepp", source_id="123", raw_data={"title": "Promoción"}, normalized_data=[{"source_id": "123:credit", "benefits": [{"percentage": 30}]}], normalization_status="normalized")

    result = serialize_hybrid_promotion(promotion)

    assert result["source"] == "buepp"
    assert result["source_id"] == "123"
    assert result["raw_data"] == {"title": "Promoción"}
    assert len(result["normalized_data"]) == 1
    assert result["normalization_status"] == "normalized"
    assert len(result["raw_hash"]) == 64
    assert result["active"] is True
    assert result["last_seen_at"]


def test_serialize_failed_promotion():
    promotion = HybridPromotion(source="bbva", source_id="456", raw_data={"title": "Beneficio desconocido"}, normalization_status="failed", normalization_error="No se pudo interpretar")

    result = serialize_hybrid_promotion(promotion)

    assert result["raw_data"] == {"title": "Beneficio desconocido"}
    assert result["normalized_data"] == []
    assert result["normalization_status"] == "failed"
    assert result["normalization_error"] == "No se pudo interpretar"


def test_raw_hash_changes_with_content():
    first = HybridPromotion(source="bbva", source_id="123", raw_data={"discount": 20}, normalization_status="not_attempted")
    second = HybridPromotion(source="bbva", source_id="123", raw_data={"discount": 30}, normalization_status="not_attempted")

    assert serialize_hybrid_promotion(first)["raw_hash"] != serialize_hybrid_promotion(second)["raw_hash"]