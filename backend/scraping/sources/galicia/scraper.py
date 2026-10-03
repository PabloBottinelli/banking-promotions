from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BACKEND_DIR / "data"

class GaliciaScraper:
    BASE_URL = "https://loyalty.bff.bancogalicia.com.ar/api/portal"

    CATALOG_URL = f"{BASE_URL}/personalizacion/v1/promociones/catalogo"

    DETAIL_URL = f"{BASE_URL}/catalogo/v1/promociones/idPromocion"

    def __init__(self, page_size: int = 100, client: httpx.Client | None = None,):
        self.page_size = page_size

        self.client = client or httpx.Client(
            timeout=30,
            follow_redirects=True,
        )

    def fetch_catalog_page(self, page: int) -> dict:
        response = self.client.get(
            self.CATALOG_URL,
            params={
                "page": page,
                "pageSize": self.page_size,
            },
            timeout=30,
        )

        response.raise_for_status()

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

            print(f"Página {page}: " f"{len(promotions)}/{total_size}")

            if not items or len(promotions) >= total_size:
                break

            page += 1

        return promotions

    def fetch_promotion_detail(self, promotion_id: int) -> dict:
        response = self.client.get(
            f"{self.DETAIL_URL}/{promotion_id}",
            timeout=30,
        )

        response.raise_for_status()

        return response.json()["data"]

    def scrape(self, limit: int | None = None,) -> list[dict]:
        catalog = self.fetch_catalog()

        if limit is not None:
            catalog = catalog[:limit]

        promotions = []

        for index, item in enumerate(catalog, start=1):
            promotion_id = item["id"]

            print(
                f"[{index}/{len(catalog)}] "
                f"Descargando {promotion_id}"
            )

            try:
                detail = self.fetch_promotion_detail(promotion_id)
            except httpx.HTTPError as error:
                print(f"Error descargando {promotion_id}: {error}")
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

        return promotions

    def save_raw_promotions(self, promotions: list[dict]) -> None:
        output_path = DATA_DIR / "galicia_promotions.json"

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                promotions,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(
            f"Guardadas {len(promotions)} promociones en {output_path}"
        )

    def preview(self):
        response = self.fetch_catalog_page(1)
        catalog = response["data"]["list"]

        for promotion in catalog[:10]:
            detail = self.fetch_promotion_detail(promotion["id"])

            print("-" * 60)
            print(f"ID: {detail['id']}")
            print(f"Marca: {detail['marca']['nombre']}")
            print(f"Categoría: " f"{detail['marca']['categoria']['descripcion']}")
            print(f"Descuento: {detail['porcentajeAhorro']}%")
            print(
                f"Cuotas: "
                f"{detail['cuotaSinInteresDesde']} - "
                f"{detail['cuotaSinInteresHasta']}"
            )
            print(f"Vigencia: " f"{detail['fechaDesde']} → " f"{detail['fechaHasta']}")
            print(f"Días: {detail['diasAplicacion']}")
            print(f"Tope: {detail['topeReintegro']} " f"({detail['tipoTope']})")
            print(f"Online: {detail['tiendaOnline']}")
            print(f"Físico: {detail['tiendaFisica']}")


if __name__ == "__main__":
    scraper = GaliciaScraper()

    promotions = scraper.scrape(limit=10)

    scraper.save_raw_promotions(promotions)