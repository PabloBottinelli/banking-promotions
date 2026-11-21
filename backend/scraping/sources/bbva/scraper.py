from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult
import os
import tempfile


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
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True, headers=self.HEADERS)

    def fetch_catalog_page(self, page: int) -> list[dict]:
        response = get_with_retries(
            self.client,
            self.CATALOG_URL,
            params={"pager": page},
        )

        payload = response.json()

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError(f"Respuesta de catálogo inválida en página {page}")

        return payload["data"]

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
        response = get_with_retries(
            self.client,
            f"{self.DETAIL_URL}/{promotion_id}",
        )

        payload = response.json()
        detail = payload.get("data") if isinstance(payload, dict) else None

        if not isinstance(detail, dict) or not detail:
            raise ValueError(f"Detalle inválido para promoción {promotion_id}")

        if str(detail.get("id")) != str(promotion_id):
            raise ValueError(f"ID incorrecto en detalle de promoción {promotion_id}")

        return detail

    def scrape(self, limit: int | None = None) -> ScrapeResult:
        self.result = None
        self._limited = limit is not None
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
            except (httpx.HTTPError, ValueError, TypeError) as error:
                print(f"Error descargando {promotion_id}: {type(error).__name__}: {error}")
                errors.append(str(promotion_id))
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

        self.result = ScrapeResult(
            promotions=promotions,
            catalog_count=len(catalog),
            failed_ids=errors,
        )

        return self.result

    def save_raw_promotions(self, promotions: list[dict]) -> None:
        if self.result is None or not self.result.complete or self._limited:
            raise ValueError("No se puede guardar una captura incompleta o limitada")

        if promotions != self.result.promotions:
            raise ValueError("Las promociones no coinciden con la captura validada")

        new_ids = {str(p["source_id"]) for p in promotions}

        if len(new_ids) != len(promotions):
            raise ValueError("Existen identificadores duplicados")

        output_path = DATA_DIR / "bbva_promotions.json"

        if output_path.exists():
            previous = json.loads(output_path.read_text(encoding="utf-8"))

            if not isinstance(previous, list):
                raise ValueError("El snapshot anterior es inválido")

            previous_ids = {str(p["source_id"]) for p in previous}

            if len(previous_ids) != len(previous):
                raise ValueError("El snapshot anterior contiene IDs duplicados")

            missing_ids = previous_ids - new_ids

            if missing_ids:
                raise ValueError(f"Desaparecieron {len(missing_ids)} promociones anteriores. Requiere revisión.")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        temporary = None

        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump(promotions, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary, output_path)

        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        print(f"Guardadas {len(promotions)} promociones en {output_path}")


if __name__ == "__main__":
    scraper = BBVAScraper()
    result = scraper.scrape()
    scraper.save_raw_promotions(result.promotions)