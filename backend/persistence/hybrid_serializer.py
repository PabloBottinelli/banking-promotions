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

    data["raw_hash"] = hash_raw_data(data["raw_data"])
    data["last_seen_at"] = (seen_at or datetime.now(timezone.utc)).isoformat()
    data["active"] = True

    return data

def hash_raw_data(raw_data: dict) -> str:
    content = remove_capture_metadata(raw_data)
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()