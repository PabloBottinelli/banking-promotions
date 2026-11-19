from typing import Any, Literal
from pydantic import BaseModel, Field
from normalization.models import NormalizedPromotion

class HybridPromotion(BaseModel):
    source: str
    source_id: str

    raw_data: dict[str, Any]
    normalized_data: list[dict[str, Any]] = Field(default_factory=list)

    normalization_status: Literal["normalized", "failed", "not_attempted"]
    normalization_error: str | None = None

def process_promotion(raw: dict, source: str, normalizer=None, normalize_many: bool = False) -> HybridPromotion:

    if not isinstance(raw, dict):
        raise ValueError("La promoción cruda debe ser un objeto")

    raw_id = raw.get("source_id")

    if raw_id is None or not str(raw_id).strip():
        raise ValueError("Promoción sin identificador")

    source_id = str(raw_id)

    if raw.get("source", source) != source:
        raise ValueError("Fuente incorrecta")

    result = HybridPromotion(source=source, source_id=source_id, raw_data=raw, normalization_status="not_attempted")

    if normalizer is None:
        return result

    try:
        if normalize_many:
            variants = normalizer.normalize_many(raw)
        else:
            variants = [normalizer.normalize(raw)]

        if not variants:
            raise ValueError("No se generaron variantes")

        ids = set()

        for variant in variants:
            if not isinstance(variant, NormalizedPromotion):
                raise ValueError("Variante inválida")

            if variant.source != source:
                raise ValueError("Fuente normalizada incorrecta")

            if not variant.source_id or variant.source_id in ids:
                raise ValueError("Identificador normalizado inválido")

            ids.add(variant.source_id)

        result.normalized_data = [variant.model_dump(mode="json") for variant in variants]

        result.normalization_status = "normalized"

    except Exception as exc:
        result.normalization_status = "failed"
        result.normalization_error = str(exc)

    return result