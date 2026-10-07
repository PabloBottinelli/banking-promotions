from datetime import datetime, timezone
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult

import httpx
from bs4 import BeautifulSoup


BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BACKEND_DIR / "data"


class PatagoniaScraper:
    SITE_URL = "https://ahorrosybeneficios.bancopatagonia.com.ar"

    HOME_URL = f"{SITE_URL}/ahorrosybeneficios/"
    ON_URL = f"{SITE_URL}/on/inicio-on"

    HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer": HOME_URL,
    }

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True, headers=self.HEADERS, verify=False)

    def fetch_category_urls(self, root_url: str, path_prefix: str) -> list[tuple[str, str]]:
        response = get_with_retries(self.client, root_url)

        soup = BeautifulSoup(response.text, "html.parser")

        links = soup.select("nav.navigation a[href], .navigation a[href]")
        categories = []
        seen = set()

        for link in links:
            href = link.get("href")

            if not href:
                continue

            url = urljoin(root_url, href)
            parsed = urlparse(url)

            if parsed.netloc != urlparse(self.SITE_URL).netloc:
                continue

            if not parsed.path.startswith(path_prefix):
                continue

            if not parsed.path.endswith(".html"):
                continue

            if url in seen:
                continue

            name = self._clean_text(link.get_text(" ", strip=True))

            if not name:
                continue

            categories.append((name, url))
            seen.add(url)

        return categories

    def fetch_category_page(self, url: str, category_name: str) -> tuple[list[dict], str | None]:
        response = get_with_retries(self.client, url)

        soup = BeautifulSoup(response.text, "html.parser")

        items = []
        seen = set()

        for product in soup.select(".product-item-info"):
            link = product.select_one("a.product-item-link[href]")

            if link is None:
                link = product.select_one("a[href]")

            if link is None:
                continue

            detail_url = urljoin(url, link.get("href", ""))

            if not self._is_benefit_page(detail_url):
                continue

            if detail_url in seen:
                continue

            title = self._clean_text(link.get_text(" ", strip=True))

            if not title:
                title_node = product.select_one(".product-item-name")
                title = self._clean_text(title_node.get_text(" ", strip=True)) if title_node else ""

            items.append(
                {
                    "source_id": Path(urlparse(detail_url).path).stem,
                    "value": title,
                    "u": detail_url,
                    "c": [category_name],
                }
            )

            seen.add(detail_url)

        next_link = soup.select_one("a.action.next[href]")
        next_url = urljoin(url, next_link["href"]) if next_link else None

        return items, next_url

    def fetch_catalog(self, limit: int | None = None) -> list[dict]:
        sources = [
            {
                "root_url": self.HOME_URL,
                "path_prefix": "/ahorrosybeneficios/",
                "segment": None,
            },
            {
                "root_url": self.ON_URL,
                "path_prefix": "/on/",
                "segment": "on",
            },
        ]

        promotions = {}
        visited_pages = set()

        for source in sources:
            categories = self.fetch_category_urls(
                source["root_url"],
                source["path_prefix"],
            )

            print()
            print(
                f"Categorías encontradas en "
                f"{'Patagonia ON' if source['segment'] == 'on' else 'Patagonia'}: "
                f"{len(categories)}"
            )

            for category_name, category_url in categories:
                page_url = category_url
                page = 1

                while page_url and page_url not in visited_pages:
                    visited_pages.add(page_url)

                    items, next_url = self.fetch_category_page(
                        page_url,
                        category_name,
                    )

                    if items:
                        prefix = "Patagonia ON" if source["segment"] == "on" else "Patagonia"

                        print(
                            f"{prefix} / {category_name} "
                            f"- página {page}: {len(items)} promociones"
                        )

                    for item in items:
                        item["segment"] = source["segment"]

                        key = item["u"]

                        if key not in promotions:
                            promotions[key] = item

                        if limit is not None and len(promotions) >= limit:
                            return list(promotions.values())

                    page_url = next_url
                    page += 1

        return list(promotions.values())

    def fetch_promotion_detail(self, url: str) -> dict:
        response = get_with_retries(self.client, url)

        soup = BeautifulSoup(response.text, "html.parser")

        title_node = soup.find("h1")
        summary = soup.select_one(".product-info-main")
        description = soup.select_one(".product.attribute.description")
        main = soup.select_one("main")

        sku_node = soup.select_one(".product.attribute.sku .value")

        if sku_node is None:
            sku_node = soup.select_one("[itemprop='sku']")

        sku = self._clean_text(sku_node.get_text(" ", strip=True)) if sku_node else None

        image_root = summary or main or soup
        image_alts = []

        for image in image_root.find_all("img"):
            alt = self._clean_text(image.get("alt"))

            if alt and alt not in image_alts:
                image_alts.append(alt)

        return {
            "sku": sku,
            "title": self._clean_text(title_node.get_text(" ", strip=True)) if title_node else None,
            "summary_text": summary.get_text("\n", strip=True) if summary else None,
            "description_text": description.get_text("\n", strip=True) if description else None,
            "main_text": main.get_text("\n", strip=True) if main else None,
            "image_alts": image_alts,
            "url": url,
        }

    def scrape(self, limit: int | None = None) -> ScrapeResult:
        catalog = self.fetch_catalog(limit=limit)

        promotions = []
        errors = []

        print()
        print(f"Promociones encontradas: {len(catalog)}")
        print()

        for index, item in enumerate(catalog, start=1):
            catalog_source_id = item["source_id"]
            detail_url = item["u"]

            print(f"[{index}/{len(catalog)}] Descargando {catalog_source_id}")

            try:
                detail = self.fetch_promotion_detail(detail_url)
            except httpx.HTTPError as error:
                print(f"Error descargando {catalog_source_id}: {error}")
                errors.append(catalog_source_id)
                continue

            source_id = detail.get("sku") or catalog_source_id

            promotions.append(
                {
                    "source": "patagonia",
                    "source_id": source_id,
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
        output_path = DATA_DIR / "patagonia_promotions.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(promotions, file, ensure_ascii=False, indent=2)

        print(f"Guardadas {len(promotions)} promociones en {output_path}")
    
    def _is_benefit_page(self, url: str) -> bool:
        parsed = urlparse(url)

        if parsed.netloc != urlparse(self.SITE_URL).netloc:
            return False

        valid_path = (
            parsed.path.startswith("/ahorrosybeneficios/")
            or parsed.path.startswith("/on/")
        )

        return valid_path and parsed.path.endswith(".html")

    def _clean_text(self, value) -> str:
        if value is None:
            return ""

        return re.sub(r"\s+", " ", str(value)).strip()


if __name__ == "__main__":
    scraper = PatagoniaScraper()
    result = scraper.scrape()
    scraper.save_raw_promotions(result.promotions)