from datetime import datetime, timezone

import httpx

from normalization.models import NormalizedPromotion
from persistence.supabase_client import SUPABASE_URL, get_headers


class SupabasePromotionRepository:
    def _serialize(self, promotion: NormalizedPromotion, seen_at: datetime | None = None) -> dict:
        data = promotion.model_dump(mode="json")
        data["source_id"] = str(data["source_id"])
        data["active"] = True
        data["last_seen_at"] = (seen_at or datetime.now(timezone.utc)).isoformat()

        return data

    def upsert(self, promotion: NormalizedPromotion) -> dict:
        data = self._serialize(promotion)

        headers = get_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"

        response = httpx.post(
            f"{SUPABASE_URL}/rest/v1/promotions",
            headers=headers,
            params={"on_conflict": "source,source_id"},
            json=data,
            timeout=30.0,
        )

        response.raise_for_status()

        return response.json()[0]

    def upsert_many(self, promotions: list[NormalizedPromotion], batch_size: int = 500, seen_at: datetime | None = None) -> int:
        if not promotions:
            return 0

        seen_at = seen_at or datetime.now(timezone.utc)

        headers = get_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"

        total = 0

        for start in range(0, len(promotions), batch_size):
            batch = promotions[start:start + batch_size]
            data = [self._serialize(promotion, seen_at) for promotion in batch]

            response = httpx.post(
                f"{SUPABASE_URL}/rest/v1/promotions",
                headers=headers,
                params={"on_conflict": "source,source_id"},
                json=data,
                timeout=60.0,
            )

            response.raise_for_status()

            total += len(batch)
            print(f"Subidas {total}/{len(promotions)} promociones")

        return total

    def deactivate_not_seen(self, source: str, seen_at: datetime) -> int:
        headers = get_headers()
        headers["Prefer"] = "return=representation"

        response = httpx.patch(
            f"{SUPABASE_URL}/rest/v1/promotions",
            headers=headers,
            params={
                "source": f"eq.{source}",
                "active": "eq.true",
                "last_seen_at": f"lt.{seen_at.isoformat()}",
            },
            json={"active": False},
            timeout=30.0,
        )

        response.raise_for_status()

        return len(response.json())