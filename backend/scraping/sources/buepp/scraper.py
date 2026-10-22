"""Public Buepp catalog API used by the official Angular application."""
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from scraping.http_client import DEFAULT_TIMEOUT, RETRYABLE_STATUS_CODES
from scraping.models import ScrapeResult

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class BueppScraper:
    SITE_URL = "https://www.buepp.com.ar"
    API_URL = SITE_URL + "/buepp_api/"

    def __init__(self, client=None, output_path=None):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self.output_path = Path(output_path) if output_path else DATA_DIR / "buepp_promotions.json"
        self.result = None
        self.coverage = {}

    def _post(self, path, payload):
        for attempt in range(3):
            try:
                response = self.client.post(self.API_URL + path, json=payload, timeout=DEFAULT_TIMEOUT)
                response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in RETRYABLE_STATUS_CODES
                if not retryable or attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid API object")
        return data

    def scrape(self):
        payload = dict(palabra_clave="", rubros=[0], dias="", medios_de_pago=[0],
                       limite_descuento=0, latitud=None, longitud=None, zona=None,
                       aplica_tienda=False, ordenamiento="POPULARIDAD", numero_pagina=1,
                       tamano_pagina=12)
        catalog, errors = {}, []

        page_count = 0
        terminal_page_empty = False

        total = None
        try:
            while True:
                data = self._post("beneficios/filter", payload)
                page_count += 1
                declared = data.get("cantidadTotalBeneficios")
                items = data.get("beneficios")
                if not isinstance(declared, int) or declared <= 0 or not isinstance(items, list):
                    raise ValueError("Missing/nonpositive catalog total or benefit list")
                if total is not None and total != declared:
                    raise ValueError("Catalog total changed during retrieval")
                total = declared
                for item in items:
                    identifier = str(item["idBeneficio"])
                    if identifier in catalog:
                        raise ValueError("Duplicate catalog ID: " + identifier)
                    catalog[identifier] = item
                if len(catalog) > total:
                    raise ValueError("Catalog exceeds published total")
                if len(catalog) == total:
                    payload["numero_pagina"] += 1

                    terminal = self._post("beneficios/filter", payload)
                    page_count += 1

                    if (terminal.get("cantidadTotalBeneficios") != total or terminal.get("beneficios") != []):
                        raise ValueError(
                            "Pagination boundary is not empty/stable"
                        )

                    terminal_page_empty = True
                    break
                if not items:
                    raise ValueError("Premature empty page")
                payload["numero_pagina"] += 1
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            errors.append("catalog: " + str(exc))
        records = []
        timestamp = datetime.now(timezone.utc).isoformat()
        for identifier, item in catalog.items():
            try:
                detail = self._post("beneficios/" + identifier, dict(latitud=None, longitud=None))
                detail.pop("googleMapsKey", None)
                benefit = detail.get("beneficio")
                if not isinstance(benefit, dict) or str(benefit.get("id")) != identifier or not benefit.get("legales"):
                    raise ValueError("Missing/mismatched detail or legal terms")
                records.append(dict(source="buepp", source_id=identifier, scraped_at=timestamp,
                                    promotion_url=self.SITE_URL + "/beneficios/" + identifier,
                                    detail_url=self.API_URL + "beneficios/" + identifier,
                                    catalog=item, detail=detail))
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(identifier + ": " + str(exc))
        self.result = ScrapeResult(records, total or len(catalog), errors)
        self.coverage = dict(
            scope=self.SITE_URL + "/beneficios (unfiltered, no geolocation)",
            catalog_url=self.API_URL + "beneficios/filter",
            request_template={**payload, "numero_pagina": 1},
            scraped_at=timestamp,
            catalog_count=total,
            unique_discovered=len(catalog),
            detail_success=len(records),
            failed_ids=errors,
            catalog_complete=self.result.complete,
            pagination={
                "pages_fetched": page_count,
                "terminal_page_empty": terminal_page_empty,
            },
            safe_to_deactivate=False,
        )
        return self.result

    def save_raw_promotions(self, promotions):
        if self.result is None or not self.result.complete or promotions != self.result.promotions:
            raise ValueError("Only a verified complete scrape may replace the raw snapshot")
        if self.output_path.exists():
            old = json.loads(self.output_path.read_text(encoding="utf-8"))
            if len(promotions) < len(old) * 0.7:
                raise ValueError("Severe catalog decline: preserve snapshot for human review")
        self._atomic(self.output_path, promotions)
        self._atomic(self.output_path.with_name("buepp_coverage.json"), self.coverage)

    @staticmethod
    def _atomic(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    scraper = BueppScraper()
    result = scraper.scrape()
    print(f"Catalog: {result.catalog_count}; details: {len(result.promotions)}; complete: {result.complete}; errors: {result.failed_ids}")
    scraper.save_raw_promotions(result.promotions)
