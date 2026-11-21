import json
from datetime import datetime, timezone

import httpx

from persistence.hybrid_serializer import serialize_hybrid_promotion
from processing.hybrid import HybridPromotion


class HybridPromotionRepository:
    def __init__(self, base_url: str, headers: dict[str, str], client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.client = client

    def upsert_many(self, promotions: list[HybridPromotion], batch_size: int = 50, max_payload_bytes: int = 1_000_000, seen_at: datetime | None = None) -> int:
        if batch_size < 1:
            raise ValueError("batch_size debe ser positivo")

        if max_payload_bytes < 3:
            raise ValueError("max_payload_bytes debe ser mayor o igual a 3")

        keys = [(p.source, p.source_id) for p in promotions]

        if len(keys) != len(set(keys)):
            raise ValueError("Hay promociones con identificadores duplicados")

        if not promotions:
            return 0

        seen_at = seen_at or datetime.now(timezone.utc)

        batches = []
        current_batch = []
        current_size = 2

        for promotion in promotions:
            data = serialize_hybrid_promotion(promotion, seen_at)
            encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            record_size = len(encoded)

            if record_size + 2 > max_payload_bytes:
                raise ValueError(f"Promoción demasiado grande: {promotion.source}:{promotion.source_id} ({record_size} bytes)")

            if current_batch and (len(current_batch) >= batch_size or current_size + record_size + 1 > max_payload_bytes):
                batches.append(b"[" + b",".join(current_batch) + b"]")
                current_batch = []
                current_size = 2

            current_size += record_size + (1 if current_batch else 0)
            current_batch.append(encoded)

        if current_batch:
            batches.append(b"[" + b",".join(current_batch) + b"]")

        headers = {**self.headers, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}
        post = self.client.post if self.client else httpx.post

        total = 0

        for index, payload in enumerate(batches, start=1):
            response = post(f"{self.base_url}/rest/v1/promotions_hybrid", headers=headers, params={"on_conflict": "source,source_id"}, content=payload, timeout=60.0)
            response.raise_for_status()

            count = len(json.loads(payload))
            total += count

            print(f"Lote {index}/{len(batches)}: {count} promociones, {len(payload)} bytes")

        return total