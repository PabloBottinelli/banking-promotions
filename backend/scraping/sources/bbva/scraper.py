from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult
import os
import tempfile
import hashlib

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
        self.result = None
        self.coverage = {}
        self._limited = False
        self._terminal_verified = False
        self._pages_fetched = 0
        self._candidate_hash = None

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None

        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(content)
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary, path)

        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

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
        seen_ids = set()
        first_page_ids = None
        page = 0

        self._terminal_verified = False
        self._pages_fetched = 0

        while page < 500:
            items = self.fetch_catalog_page(page)
            self._pages_fetched += 1

            print(f"Página {page}: {len(items)} promociones")

            if not items:
                if not promotions:
                    raise ValueError("El catálogo BBVA está vacío")

                confirmation = self.fetch_catalog_page(page)
                self._pages_fetched += 1

                if confirmation:
                    raise ValueError("Fin de paginación BBVA inestable")

                current_first_page = self.fetch_catalog_page(0)
                self._pages_fetched += 1

                current_ids = [str(item.get("id")) for item in current_first_page]

                if current_ids != first_page_ids:
                    raise ValueError("La primera página del catálogo cambió durante la captura")

                self._terminal_verified = True
                return promotions

            page_ids = []

            for item in items:
                if not isinstance(item, dict):
                    raise ValueError(f"Registro inválido en página {page}")

                source_id = str(item.get("id") or "").strip()

                if not source_id:
                    raise ValueError(f"Promoción sin ID en página {page}")

                if source_id in seen_ids:
                    raise ValueError(f"ID duplicado en catálogo: {source_id}")

                seen_ids.add(source_id)
                page_ids.append(source_id)

            if page == 0:
                first_page_ids = page_ids

            promotions.extend(items)
            page += 1

        raise ValueError("Se alcanzó el límite de páginas sin verificar el final del catálogo")

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
        self.coverage = {}
        self._candidate_hash = None
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

        self.coverage = {
            "source": "bbva",
            "catalog_complete": self.result.complete and self._terminal_verified and not self._limited,
            "limited": self._limited,
            "failed_ids": errors,
            "catalog_count": len(catalog),
            "detail_success": len(promotions),
            "terminal_verified": self._terminal_verified,
            "pages_fetched": self._pages_fetched,
            "safe_to_deactivate": False,
        }

        canonical = json.dumps(promotions, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self._candidate_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        return self.result

    def save_raw_promotions(self, promotions: list[dict], approved_missing_ids: set[str] | None = None) -> None:
        approved_missing_ids = approved_missing_ids or set()
        if self.result is None or not self.result.complete or self._limited:
            raise ValueError("No se puede guardar una captura incompleta o limitada")

        if self.coverage.get("catalog_complete") is not True:
            raise ValueError("La cobertura BBVA no fue verificada")

        if promotions != self.result.promotions:
            raise ValueError("Las promociones no coinciden con la captura validada")

        canonical = json.dumps(promotions, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        candidate_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        if candidate_hash != self._candidate_hash:
            raise ValueError("El candidato cambió después de la captura")

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

            unapproved_ids = missing_ids - approved_missing_ids
            unexpected_approvals = approved_missing_ids - missing_ids

            if unapproved_ids:
                raise ValueError(f"Desaparecieron promociones sin aprobación: {sorted(unapproved_ids)}")

            if unexpected_approvals:
                raise ValueError(f"IDs aprobados que no desaparecieron: {sorted(unexpected_approvals)}")

            self.coverage["approved_missing_ids"] = sorted(missing_ids)

            if missing_ids:
                previous_bytes = output_path.read_bytes()
                previous_hash = hashlib.sha256(previous_bytes).hexdigest()[:16]
                backup_path = output_path.with_name(f"bbva_promotions_previous_{previous_hash}.json")

                if backup_path.exists():
                    if backup_path.read_bytes() != previous_bytes:
                        raise ValueError("El respaldo existente no coincide con el snapshot anterior")
                else:
                    self._atomic_write(backup_path, previous_bytes)

        snapshot_bytes = json.dumps(promotions, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")

        coverage = {
            **self.coverage,
            "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        }

        coverage_bytes = json.dumps(coverage, ensure_ascii=False, indent=2).encode("utf-8")

        self._atomic_write(output_path, snapshot_bytes)
        self._atomic_write(output_path.with_name("bbva_coverage.json"), coverage_bytes)

        self.coverage = coverage

        print(f"Guardadas {len(promotions)} promociones en {output_path}")


if __name__ == "__main__":
    scraper = BBVAScraper()
    result = scraper.scrape()
    scraper.save_raw_promotions(result.promotions)