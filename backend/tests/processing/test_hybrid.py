from processing.hybrid import *

def test_without_normalizer():

    raw = {
        "source": "buepp",
        "source_id": "123",
        "title": "Promoción de prueba"
    }

    result = process_promotion(
        raw,
        source="buepp"
    )

    assert result.source_id == "123"
    assert result.raw_data == raw
    assert result.normalized_data == []
    assert result.normalization_status == "not_attempted"
    
def test_failed_normalization():

    class FailedNormalizer:
        def normalize(self, raw):
            raise ValueError("No se pudo interpretar")

    raw = {
        "source": "buepp",
        "source_id": "123"
    }

    result = process_promotion(
        raw,
        source="buepp",
        normalizer=FailedNormalizer()
    )

    assert result.normalization_status == "failed"
    assert result.raw_data == raw
    assert result.normalized_data == []
    assert result.normalization_error is not None