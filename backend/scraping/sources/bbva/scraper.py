from datetime import datetime, timezone
import json
from pathlib import Path

import httpx


BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BACKEND_DIR / "data"


class BBVAScraper:
    BASE_URL = "https://go.bbva.com.ar/willgo/fgo/API/v3"
    CATALOG_URL = f"{BASE_URL}/communications"
    DETAIL_URL = f"{BASE_URL}/communication"

    HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://www.bbva.com.ar",
        "Referer": "https://www.bbva.com.ar/beneficios/",
    }

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=30, follow_redirects=True, headers=self.HEADERS)

    def fetch_catalog_page(self, page: int) -> list[dict]:
        response = self.client.get(self.CATALOG_URL, params={"pager": page}, timeout=30)
        response.raise_for_status()

        data = response.json().get("data", [])

        if not isinstance(data, list):
            return []

        return data

    def fetch_catalog(self) -> list[dict]:
        promotions = []
        page = 0

        while True:
            items = self.fetch_catalog_page(page)

            print(f"Página {page}: {len(items)} promociones")

            if not items:
                break

            promotions.extend(items)
            page += 1

        return promotions

    def fetch_promotion_detail(self, promotion_id: str | int) -> dict:
        response = self.client.get(f"{self.DETAIL_URL}/{promotion_id}", timeout=30)
        response.raise_for_status()

        detail = response.json().get("data", {})

        if not isinstance(detail, dict):
            return {}

        return detail

    def scrape(self, limit: int | None = None) -> list[dict]:
        catalog = self.fetch_catalog()

        if limit is not None:
            catalog = catalog[:limit]

        promotions = []
        errors = []

        for index, item in enumerate(catalog, start=1):
            promotion_id = item.get("id")

            if not promotion_id:
                print(f"[{index}/{len(catalog)}] Promoción sin ID")
                continue

            print(f"[{index}/{len(catalog)}] Descargando {promotion_id}")

            try:
                detail = self.fetch_promotion_detail(promotion_id)
            except httpx.HTTPError as error:
                print(f"Error descargando {promotion_id}: {error}")
                errors.append(promotion_id)
                continue

            promotions.append(
                {
                    "source": "bbva",
                    "source_id": promotion_id,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "catalog": item,
                    "detail": detail,
                }
            )

        print()
        print(f"Catálogo: {len(catalog)}")
        print(f"Descargadas: {len(promotions)}")
        print(f"Errores: {len(errors)}")

        if errors:
            print(f"IDs con error: {errors}")

        return promotions

    def save_raw_promotions(self, promotions: list[dict]) -> None:
        output_path = DATA_DIR / "bbva_promotions.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(promotions, file, ensure_ascii=False, indent=2)

        print(f"Guardadas {len(promotions)} promociones en {output_path}")


if __name__ == "__main__":
    scraper = BBVAScraper()
    promotions = scraper.scrape()
    scraper.save_raw_promotions(promotions)