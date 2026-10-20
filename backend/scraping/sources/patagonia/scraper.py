from datetime import datetime, timezone
import json
import re
import hashlib
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from scraping.http_client import RETRYABLE_STATUS_CODES
from scraping.models import ScrapeResult
from scraping.sources.patagonia.text import strip_legal_headers

import httpx
from bs4 import BeautifulSoup


BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BACKEND_DIR / "data"


class PatagoniaScraper:
    SITE_URL = "https://ahorrosybeneficios.bancopatagonia.com.ar"

    HOME_URL = f"{SITE_URL}/ahorrosybeneficios/"
    ON_URL = f"{SITE_URL}/on/inicio-on"
    PLUS_URL = f"{SITE_URL}/plus/inicio-plus"
    SINGULAR_URL = f"{SITE_URL}/singular/inicio-singular"

    HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer": HOME_URL,
    }

    TIMEOUT = httpx.Timeout(45.0, connect=30.0)

    def __init__(self, client: httpx.Client | None = None, output_path: Path | None = None):
        self.client = client or httpx.Client(timeout=self.TIMEOUT, follow_redirects=True, headers=self.HEADERS, verify=True, trust_env=False)
        self.output_path = output_path or DATA_DIR / "patagonia_promotions.json"
        self.coverage = {}
        self._candidate_digest = None
        self._baseline_digest = None
        self._pages = {}

    def _get(self, url: str) -> httpx.Response:
        """Bounded source-local retries; certificate/security refusals never retried."""
        for attempt in range(3):
            try:
                response = self.client.get(url, timeout=self.TIMEOUT)
                response.raise_for_status()
                if urlparse(str(response.url)).hostname != urlparse(self.SITE_URL).hostname or urlparse(str(response.url)).scheme != "https":
                    raise ValueError("Unexpected redirect outside official Patagonia host")
                return response
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in RETRYABLE_STATUS_CODES or attempt == 2:
                    raise
                retry_after = error.response.headers.get("Retry-After", "")
                delay = min(float(retry_after), 60) if retry_after.isdigit() else 2 ** attempt
            except httpx.TransportError as error:
                certificate_error = any(token in str(error).lower() for token in ("certificate_verify_failed", "certificate verify failed", "hostname mismatch"))
                if certificate_error or not isinstance(error, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)) or attempt == 2:
                    raise
                delay = 2 ** attempt
            time.sleep(delay)
        raise RuntimeError("unreachable")

    def fetch_category_urls(self, root_url: str, path_prefix: str) -> list[tuple[str, str]]:
        response = self._get(root_url)

        soup = BeautifulSoup(response.text, "html.parser")

        links = soup.select("nav.navigation a[href], .navigation a[href], main .owl-carousel a[href]")
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

        self._pages[root_url] = {"categories": [url for _, url in categories]}
        # Featured offers can be absent from a category; retain their discovery too.
        featured, _ = self._parse_category_page(soup, root_url, "Destacados")
        self._pages[root_url]["featured"] = featured
        return categories

    def fetch_category_page(self, url: str, category_name: str) -> tuple[list[dict], str | None]:
        response = self._get(url)

        soup = BeautifulSoup(response.text, "html.parser")

        return self._parse_category_page(soup, url, category_name)

    def _parse_category_page(self, soup, url: str, category_name: str):
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
                self.coverage.setdefault("duplicate_links", []).append(detail_url)
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
                    "html": str(product),
                }
            )

            seen.add(detail_url)

        next_link = soup.select_one("a.action.next[href]")
        next_url = urljoin(url, next_link["href"]) if next_link else None

        if next_url and (not self._is_benefit_page(next_url) or urlparse(next_url).path != urlparse(url).path):
            raise ValueError(f"Invalid pagination target: {next_url}")
        totals = [int(node.get_text(strip=True).replace(",", "")) for node in soup.select(".toolbar-amount .toolbar-number") if node.get_text(strip=True).replace(",", "").isdigit()]
        self._pages[url] = {"count": len(items), "next": next_url, "reported_total": totals[-1] if totals else None}

        return items, next_url

    def fetch_catalog(self, limit: int | None = None) -> list[dict]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        self.coverage = {"catalog_complete": False, "snapshot_replace_allowed": False, "requires_review": True, "safe_to_deactivate": False, "limited": limit is not None, "categories": [], "errors": []}
        self._pages = {}
        sources = [
            {
                "root_url": self.PLUS_URL,
                "path_prefix": "/plus/",
                "segment": "plus",
            },
            {
                "root_url": self.SINGULAR_URL,
                "path_prefix": "/singular/",
                "segment": "singular",
            },
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

        for source in sources:
            try:
                categories = self.fetch_category_urls(source["root_url"], source["path_prefix"])
            except (httpx.HTTPError, ValueError) as error:
                self.coverage["errors"].append({"url": source["root_url"], "error": type(error).__name__, "message": str(error)})
                continue
            if not categories:
                self.coverage["errors"].append({"url": source["root_url"], "error": "empty_category_discovery"})
            for item in self._pages.get(source["root_url"], {}).get("featured", []):
                item["segment"] = source["segment"]
                promotions[item["u"]] = item

            print()
            print(
                f"Categorías encontradas en "
                f"{'Patagonia ON' if source['segment'] == 'on' else 'Patagonia'}: "
                f"{len(categories)}"
            )

            for category_name, category_url in categories:
                page_url = category_url
                page = 1
                visited_pages = set()
                signatures = set()
                category_items = set()
                expected_total = None
                category_meta = {"name": category_name, "url": category_url, "segment": source["segment"], "pages": [], "count": 0}
                self.coverage["categories"].append(category_meta)

                while page_url:
                    if page_url in visited_pages:
                        self.coverage["errors"].append({"url": page_url, "error": "pagination_cycle"})
                        break
                    visited_pages.add(page_url)

                    try:
                        items, next_url = self.fetch_category_page(page_url, category_name)
                    except (httpx.HTTPError, ValueError) as error:
                        self.coverage["errors"].append({"url": page_url, "error": type(error).__name__, "message": str(error)})
                        break
                    category_meta["pages"].append({"url": page_url, **self._pages.get(page_url, {})})
                    reported = self._pages.get(page_url, {}).get("reported_total")
                    if reported is not None:
                        if expected_total is not None and reported != expected_total:
                            self.coverage["errors"].append({"url": page_url, "error": "changing_pagination_total"})
                        expected_total = reported
                    signature = tuple(sorted(item["u"] for item in items))
                    if not items or signature in signatures:
                        self.coverage["errors"].append({"url": page_url, "error": "empty_or_repeated_category_page"})
                        break
                    signatures.add(signature)

                    if items:
                        prefix = "Patagonia ON" if source["segment"] == "on" else "Patagonia"

                        print(
                            f"{prefix} / {category_name} "
                            f"- página {page}: {len(items)} promociones"
                        )

                    for item in items:
                        if item["u"] in category_items:
                            self.coverage["errors"].append({"url": page_url, "error": "pagination_duplicate", "id": item["source_id"]})
                        category_items.add(item["u"])
                        item["segment"] = source["segment"]
                        item["category_urls"] = [category_url]

                        key = item["u"]

                        if key not in promotions:
                            promotions[key] = item
                        else:
                            existing = promotions[key]
                            existing["c"] = list(dict.fromkeys(existing["c"] + item["c"]))
                            existing["category_urls"] = list(dict.fromkeys(existing.get("category_urls", []) + [category_url]))

                        if limit is not None and len(promotions) >= limit:
                            return list(promotions.values())[:limit]

                    page_url = next_url
                    page += 1
                    if page > 1000:
                        self.coverage["errors"].append({"url": page_url, "error": "pagination_safety_limit"})
                        break
                category_meta["count"] = len(category_items)
                if expected_total is not None and expected_total != len(category_items):
                    self.coverage["errors"].append({"url": category_url, "error": "pagination_total_mismatch", "expected": expected_total, "observed": len(category_items)})

        self.coverage["catalog_complete"] = bool(promotions) and not self.coverage["errors"] and limit is None
        return list(promotions.values())

    def fetch_promotion_detail(self, url: str) -> dict:
        response = self._get(url)

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
            "html": str(main or soup),
            "captured_at": datetime.now(timezone.utc).isoformat(),
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

            if not self._valid_detail(detail):
                errors.append(catalog_source_id)
                self.coverage.setdefault("errors", []).append({"url": detail_url, "error": "blank_essential_detail"})
                continue

            source_id = detail.get("sku") or catalog_source_id

            promotions.append(
                {
                    "source": "patagonia",
                    "source_id": source_id,
                    "scraped_at": detail.get("captured_at") or datetime.now(timezone.utc).isoformat(),
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

        # Some official SKUs are reused by different URLs. Keep both records and
        # disambiguate by stable path, never by arrival order.
        self.coverage["discovered_detail_urls"] = len(catalog)
        self.coverage["detail_success"] = len(promotions)
        promotions = self._aggregate_storefronts(promotions)
        sku_counts = {}
        for promotion in promotions:
            sku_counts[promotion["source_id"]] = sku_counts.get(promotion["source_id"], 0) + 1
        reused_skus = self._historically_reused_skus()
        for promotion in promotions:
            if sku_counts[promotion["source_id"]] > 1 or promotion["source_id"] in reused_skus:
                promotion["source_id"] += ":" + urlparse(promotion["detail"]["url"]).path.strip("/").removesuffix(".html").replace("/", ":")
        self.coverage["raw_records"] = len(promotions)
        self.coverage["detail_errors"] = list(errors)
        self.coverage["catalog_complete"] = self.coverage.get("catalog_complete", False) and not errors
        from normalization.sources.patagonia import PatagoniaNormalizer
        normalizer = PatagoniaNormalizer()
        reviews = []
        for promotion in promotions:
            try:
                issues = normalizer.review_issues(promotion)
            except (ValueError, TypeError, KeyError) as error:
                issues = [f"Source normalization review failed: {error}"]
            if issues:
                promotion["review_reasons"] = issues
                reviews.append({"source_id": promotion["source_id"], "reasons": issues})
        self.coverage["promotion_reviews"] = reviews
        self._assess_baseline(promotions)
        self._candidate_digest = self._digest(promotions)
        return ScrapeResult(
            promotions=promotions,
            catalog_count=len(promotions) + len(errors),
            failed_ids=errors,
        )

    def save_raw_promotions(self, promotions: list[dict]) -> None:
        self._validate_records(promotions)
        if not self._candidate_digest or self._digest(promotions) != self._candidate_digest:
            raise ValueError("Candidate is not the validated scrape result")
        if not self.coverage.get("snapshot_replace_allowed") or self.coverage.get("requires_review") or self.coverage.get("limited"):
            raise ValueError("Snapshot replacement requires verified coverage and baseline review")
        if not self.output_path.exists() or hashlib.sha256(self.output_path.read_bytes()).hexdigest() != self._baseline_digest:
            raise ValueError("Accepted baseline changed or is unavailable")
        self._assess_baseline(promotions)
        if not self.coverage["snapshot_replace_allowed"]:
            raise ValueError("Snapshot acceptance changed")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.output_path.parent, prefix=".patagonia-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                json.dump(promotions, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.output_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _aggregate_storefronts(self, promotions):
        """Group the same SKU+slug across general/Plus/Singular, retaining every detail.

        ON is a separate offer family. Reused SKUs on different slugs are not
        merged. Normalization independently compares the segment-specific terms.
        """
        groups = {}
        priority = {None: 0, "plus": 1, "singular": 2, "on": 3}
        for record in sorted(promotions, key=lambda item: priority.get(item["catalog"].get("segment"), 9)):
            slug = Path(urlparse(record["detail"]["url"]).path).stem
            family = "on" if record["catalog"].get("segment") == "on" else "general"
            key = (record["detail"].get("sku") or record["source_id"], slug, family)
            if key not in groups:
                groups[key] = record
            else:
                groups[key].setdefault("storefront_details", []).append({"catalog": record["catalog"], "detail": record["detail"], "scraped_at": record["scraped_at"]})
        return list(groups.values())

    @staticmethod
    def _digest(promotions):
        return hashlib.sha256(json.dumps(promotions, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_detail(detail):
        if not isinstance(detail, dict):
            return False
        legal = str(detail.get("description_text") or "").strip()
        if not legal:
            match = re.search(r"T[eé]rminos\s+y\s+Condiciones\s*(.*)", str(detail.get("main_text") or ""), re.I | re.S)
            if match:
                legal = re.split(r"Available stores are loading|Ver todas las tiendas disponibles", match.group(1), maxsplit=1)[0].strip()
        # A populated heading is not a populated legal body (HTTP 200 can
        # contain only the segment tabs after a CMS failure).
        body = strip_legal_headers(legal)
        substantive = re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{3,}|\d", body)
        return bool(str(detail.get("title") or "").strip() and str(detail.get("summary_text") or "").strip() and substantive)

    def _historically_reused_skus(self):
        """Remember disambiguation even when one formerly colliding URL vanishes."""
        try:
            baseline = json.loads(self.output_path.read_bytes())
            counts = {}
            reused = set()
            for item in baseline:
                sku = item.get("detail", {}).get("sku") or item.get("source_id")
                counts[sku] = counts.get(sku, 0) + 1
                if item.get("source_id") != sku:
                    reused.add(sku)
            return reused | {sku for sku, count in counts.items() if count > 1}
        except (OSError, ValueError, TypeError, AttributeError):
            return set()

    def _validate_records(self, records):
        if not isinstance(records, list) or not records:
            raise ValueError("Empty or malformed raw snapshot")
        seen = set()
        for record in records:
            if not isinstance(record, dict) or record.get("source") != "patagonia":
                raise ValueError("Malformed raw record/source")
            source_id = str(record.get("source_id") or "").strip()
            if not source_id or source_id in seen or not self._valid_detail(record.get("detail")):
                raise ValueError("Blank/duplicate raw ID or essential detail")
            for extra in record.get("storefront_details", []):
                if not isinstance(extra, dict) or not self._valid_detail(extra.get("detail")):
                    raise ValueError("Blank essential storefront detail")
            seen.add(source_id)
        return seen

    def _assess_baseline(self, promotions):
        reasons = []
        try:
            current_ids = self._validate_records(promotions)
        except ValueError as error:
            current_ids = set()
            reasons.append(str(error))
        missing_ids = []
        missing_categories = []
        if not self.output_path.exists():
            reasons.append("No durable accepted baseline available; initial acceptance requires human review")
            self._baseline_digest = None
        else:
            baseline_bytes = self.output_path.read_bytes()
            self._baseline_digest = hashlib.sha256(baseline_bytes).hexdigest()
            try:
                baseline = json.loads(baseline_bytes)
                baseline_ids = self._validate_records(baseline)
                missing_ids = sorted(baseline_ids - current_ids)
                if missing_ids:
                    reasons.append("Previously accepted IDs disappeared")
                previous_categories = {url for item in baseline for url in item.get("catalog", {}).get("category_urls", [])}
                current_categories = {item["url"] for item in self.coverage.get("categories", [])}
                missing_categories = sorted(previous_categories - current_categories)
                if missing_categories:
                    reasons.append("Previously accepted categories disappeared")
            except (ValueError, TypeError, KeyError) as error:
                reasons.append(f"Accepted baseline invalid: {error}")
        if not self.coverage.get("catalog_complete") or self.coverage.get("limited"):
            reasons.append("Catalog coverage incomplete or limited")
        if self.coverage.get("promotion_reviews"):
            reasons.append("Official promotion contradictions require human review")
        self.coverage.update(missing_previous_ids=missing_ids, missing_previous_categories=missing_categories, review_reasons=reasons, requires_review=bool(reasons), snapshot_replace_allowed=not reasons, safe_to_deactivate=False)
    
    def _is_benefit_page(self, url: str) -> bool:
        parsed = urlparse(url)

        if parsed.netloc != urlparse(self.SITE_URL).netloc or parsed.scheme != "https":
            return False

        valid_path = (
            parsed.path.startswith("/ahorrosybeneficios/")
            or parsed.path.startswith("/on/")
            or parsed.path.startswith("/plus/")
            or parsed.path.startswith("/singular/")
        )

        return valid_path and parsed.path.endswith(".html")

    def _clean_text(self, value) -> str:
        if value is None:
            return ""

        return re.sub(r"\s+", " ", str(value)).strip()


if __name__ == "__main__":
    scraper = PatagoniaScraper()
    result = scraper.scrape()
    print(json.dumps(scraper.coverage, ensure_ascii=False, indent=2))
