from datetime import datetime, timezone

import httpx

from persistence.hybrid_serializer import serialize_hybrid_promotion
from processing.hybrid import HybridPromotion


class HybridPromotionRepository:
    def __init__(self, base_url: str, headers: dict[str, str], client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.client = client

    def upsert_many(self, promotions: list[HybridPromotion], batch_size: int = 50, seen_at: datetime | None = None) -> int:
        if batch_size < 1:
            raise ValueError("batch_size debe ser positivo")

        keys = [(p.source, p.source_id) for p in promotions]

        if len(keys) != len(set(keys)):
            raise ValueError("Hay promociones con identificadores duplicados")

        if not promotions:
            return 0

        seen_at = seen_at or datetime.now(timezone.utc)

        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
        post = self.client.post if self.client else httpx.post

        total = 0

        for start in range(0, len(promotions), batch_size):
            batch = promotions[start:start + batch_size]
            data = [serialize_hybrid_promotion(p, seen_at) for p in batch]

            response = post(f"{self.base_url}/rest/v1/promotions_hybrid", headers=headers, params={"on_conflict": "source,source_id"}, json=data, timeout=60.0)
            response.raise_for_status()

            total += len(batch)

        return total