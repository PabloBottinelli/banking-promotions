import hashlib
import json
from datetime import datetime, timezone

from processing.hybrid import HybridPromotion

CAPTURE_FIELDS = {"scraped_at", "captured_at"}


def remove_capture_metadata(value):
    if isinstance(value, dict):
        return {key: remove_capture_metadata(item) for key, item in value.items() if key not in CAPTURE_FIELDS}

    if isinstance(value, list):
        return [remove_capture_metadata(item) for item in value]

    return value

def serialize_hybrid_promotion(promotion: HybridPromotion, seen_at: datetime | None = None) -> dict:
    data = promotion.model_dump(mode="json")

    content = remove_capture_metadata(data["raw_data"])
    canonical_raw = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    data["raw_hash"] = hashlib.sha256(canonical_raw.encode("utf-8")).hexdigest()
    data["last_seen_at"] = (seen_at or datetime.now(timezone.utc)).isoformat()
    data["active"] = True

    return data