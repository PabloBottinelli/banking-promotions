from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult


BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BACKEND_DIR / "data"


class GaliciaScraper:
    BASE_URL = "https://loyalty.bff.bancogalicia.com.ar/api/portal"

    CATALOG_URL = f"{BASE_URL}/personalizacion/v1/promociones/catalogo"
    DETAIL_URL = f"{BASE_URL}/catalogo/v1/promociones/idPromocion"

    def __init__(self, page_size: int = 100, client: httpx.Client | None = None):
        self.page_size = page_size
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)

    def fetch_catalog_page(self, page: int) -> dict:
        response = get_with_retries(
            self.client,
            self.CATALOG_URL,
            params={
                "page": page,
                "pageSize": self.page_size,
            },
        )

        return response.json()

    def fetch_catalog(self) -> list[dict]:
        promotions = []
        page = 1

        while True:
            response = self.fetch_catalog_page(page)

            data = response["data"]
            items = data["list"]
            total_size = data["totalSize"]

            promotions.extend(items)

            print(f"Página {page}: {len(promotions)}/{total_size}")

            if not items or len(promotions) >= total_size:
                break

            page += 1

        return promotions

    def fetch_promotion_detail(self, promotion_id: int) -> dict:
        response = get_with_retries(
            self.client,
            f"{self.DETAIL_URL}/{promotion_id}",
        )

        return response.json()["data"]

    def scrape(self, limit: int | None = None) -> ScrapeResult:
        catalog = self.fetch_catalog()

        if limit is not None:
            catalog = catalog[:limit]

        promotions = []
        errors = []

        for index, item in enumerate(catalog, start=1):
            promotion_id = item.get("id")

            if not promotion_id:
                print(f"[{index}/{len(catalog)}] Promoción sin ID")
                errors.append(f"missing-id:{index}")
                continue

            print(f"[{index}/{len(catalog)}] Descargando {promotion_id}")

            try:
                detail = self.fetch_promotion_detail(promotion_id)
            except httpx.HTTPError as error:
                print(f"Error descargando {promotion_id}: {type(error).__name__}: {error}")
                errors.append(str(promotion_id))
                continue

            promotions.append(
                {
                    "source": "galicia",
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

        return ScrapeResult(
            promotions=promotions,
            catalog_count=len(catalog),
            failed_ids=errors,
        )

    def save_raw_promotions(self, promotions: list[dict]) -> None:
        output_path = DATA_DIR / "galicia_promotions.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(promotions, file, ensure_ascii=False, indent=2)

        print(f"Guardadas {len(promotions)} promociones en {output_path}")

    def preview(self):
        response = self.fetch_catalog_page(1)
        catalog = response["data"]["list"]

        for promotion in catalog[:10]:
            detail = self.fetch_promotion_detail(promotion["id"])

            print("-" * 60)
            print(f"ID: {detail['id']}")
            print(f"Marca: {detail['marca']['nombre']}")
            print(f"Categoría: {detail['marca']['categoria']['descripcion']}")
            print(f"Descuento: {detail['porcentajeAhorro']}%")
            print(f"Cuotas: {detail['cuotaSinInteresDesde']} - {detail['cuotaSinInteresHasta']}")
            print(f"Vigencia: {detail['fechaDesde']} → {detail['fechaHasta']}")
            print(f"Días: {detail['diasAplicacion']}")
            print(f"Tope: {detail['topeReintegro']} ({detail['tipoTope']})")
            print(f"Online: {detail['tiendaOnline']}")
            print(f"Físico: {detail['tiendaFisica']}")


if __name__ == "__main__":
    scraper = GaliciaScraper()
    result = scraper.scrape()
    scraper.save_raw_promotions(result.promotions)