import hashlib
import json
from datetime import datetime, timezone

from processing.hybrid import HybridPromotion


def serialize_hybrid_promotion(promotion: HybridPromotion, seen_at: datetime | None = None) -> dict:
    data = promotion.model_dump(mode="json")

    canonical_raw = json.dumps(data["raw_data"], sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    data["raw_hash"] = hashlib.sha256(canonical_raw.encode("utf-8")).hexdigest()
    data["last_seen_at"] = (seen_at or datetime.now(timezone.utc)).isoformat()
    data["active"] = True

    return data