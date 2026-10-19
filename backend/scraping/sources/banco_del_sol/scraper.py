"""Browser-rendered catalog of current Banco del Sol benefits.

Install the browser once with ``python -m playwright install chromium``.
"""

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class BancoDelSolScraper:
    SITE = "https://www.bancodelsol.com"
    LIST_URL = SITE + "/beneficios"

    def __init__(self, client: httpx.Client | None = None, output_path: Path | None = None,
                 catalog_states: Callable[[], Iterable[tuple[str, bool]]] | None = None):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self.output_path = Path(output_path) if output_path else DATA_DIR / "banco_del_sol_promotions.json"
        self.catalog_states = catalog_states or self._browser_states
        self.result: ScrapeResult | None = None
        self.coverage: dict = {}
        self._accepted_candidate: str | None = None

    def _get(self, url: str) -> str:
        return get_with_retries(self.client, url).text

    @staticmethod
    def _active_cards(html: str) -> list[dict]:
        section = BeautifulSoup(html, "html.parser").select_one("#id-productos-vigentes")
        if section is None:
            raise ValueError("No existe la colección oficial de beneficios vigentes")
        cards = []
        for anchor in section.select('a.card_link[href^="/beneficios/"]'):
            href = anchor.get("href", "")
            slug = href.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            if slug:
                cards.append({"slug": slug, "href": href, "card_html": str(anchor),
                              "card_text": anchor.get_text(" ", strip=True),
                              "data_inicio": anchor.get("data-inicio")})
        return cards

    def _browser_states(self) -> Iterable[tuple[str, bool]]:
        """Yield cumulative DOM states after clicking the live load-more control."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(self.LIST_URL, wait_until="domcontentloaded", timeout=60000)
                section = page.locator("#id-productos-vigentes")
                section.locator('a.card_link[href^="/beneficios/"]').first.wait_for(timeout=45000)
                page.wait_for_timeout(1000)
                for _ in range(100):
                    cards = section.locator('a.card_link[href^="/beneficios/"]')
                    count = cards.count()
                    pager = section.locator("a.w-pagination-next")
                    if pager.count() != 1:
                        raise ValueError("Control de paginación ausente o ambiguo")
                    visible = pager.is_visible() and pager.get_attribute("aria-hidden") != "true"
                    page.wait_for_timeout(1000)
                    if cards.count() != count:
                        raise ValueError("La colección cambió mientras se verificaba una página")
                    if (pager.count() == 1 and pager.is_visible()
                            and pager.get_attribute("aria-hidden") != "true") != visible:
                        raise ValueError("El estado de paginación no se estabilizó")
                    yield section.evaluate("node => node.outerHTML"), visible
                    if not visible:
                        break
                    pager.click(timeout=15000)
                    page.wait_for_function(
                        "count => document.querySelectorAll('#id-productos-vigentes a.card_link').length > count",
                        arg=count, timeout=30000)
            finally:
                browser.close()

    @staticmethod
    def _detail(html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one("main") or soup
        title = main.select_one("h1")
        terms_node = main.select_one("p.text-size-small.text-align-left")
        if not title or not terms_node:
            raise ValueError("Detalle sin título o términos legales")
        title_text = title.get_text(" ", strip=True)
        terms_text = terms_node.get_text("\n", strip=True).strip(' "').strip()
        if not title_text or not terms_text:
            raise ValueError("Detalle con título o términos legales vacíos")

        def one(selector):
            node = main.select_one(selector)
            return node.get_text(" ", strip=True) if node else None

        def many(selector):
            return list(dict.fromkeys(node.get_text(" ", strip=True) for node in main.select(selector)
                                      if node.get_text(" ", strip=True)))

        return {"title": title_text,
                "summary": one(".text-size-large.text-color-orange-600"),
                "description": one("p.text-size-medium"),
                "valid_from_label": one(".validity-start"),
                "valid_to_label": one(".validity-end"),
                "category": ", ".join(many('a.card_tags.is-rubros')) or None,
                "days": many('a[fs-list-field="dia"]'),
                "regions": many('a[fs-list-field="provincia"]'),
                "payment_labels": many('a[fs-list-field="medio-de-pago"]'),
                "terms": terms_text, "html": html}

    @staticmethod
    def _record_ids(records) -> set[str]:
        if not isinstance(records, list) or not records:
            raise ValueError("El snapshot no contiene una lista no vacía")
        ids = [item.get("source_id") for item in records if isinstance(item, dict)]
        if (len(ids) != len(records) or any(not isinstance(x, str) or not x.strip() for x in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("El snapshot tiene IDs faltantes o repetidos")
        return set(ids)

    def _previous_ids(self) -> set[str] | None:
        """Read the last accepted source IDs; None means no historical baseline.

        Fail closed on corrupt/unusable snapshots rather than silently replacing them.
        """
        if not self.output_path.exists():
            return None
        previous = json.loads(self.output_path.read_text(encoding="utf-8"))
        return self._record_ids(previous)

    def scrape(self) -> ScrapeResult:
        self.result = None
        self.coverage = {}
        self._accepted_candidate = None
        discovered: dict[str, dict] = {}
        errors: list[str] = []
        counts: list[int] = []
        terminal_verified = False
        try:
            for html, has_next in self.catalog_states():
                cards = self._active_cards(html)
                slugs = [card["slug"] for card in cards]
                if not slugs:
                    raise ValueError("Colección vigente vacía o incompleta")
                if len(slugs) != len(set(slugs)):
                    raise ValueError("IDs repetidos en el catálogo renderizado")
                prior = list(discovered)
                if slugs[:len(prior)] != prior or len(slugs) <= len(prior):
                    raise ValueError("La paginación no añadió un lote nuevo y estable")
                discovered = {card["slug"]: card for card in cards}
                counts.append(len(slugs))
                if not has_next:
                    # A hidden control alone does not establish exhaustion.
                    if len(counts) >= 2 and counts[-1] - counts[-2] < counts[0]:
                        terminal_verified = True
                    else:
                        errors.append("catalog: fin de paginación no verificable")
                    break
            else:
                errors.append("catalog: paginación sin límite verificado")
        except Exception as exc:
            errors.append(
                f"catalog: {type(exc).__name__}: {exc}"
            )

        # A browser's hidden load-more control and a short last page cannot
        # prove that older source IDs legitimately disappeared. Compare with
        # the last accepted snapshot and require human review on ANY removal.
        previous_ids: set[str] | None = None
        missing_ids: list[str] = []
        new_ids: list[str] = []
        comparison_errors: list[str] = []
        try:
            previous_ids = self._previous_ids()
            if previous_ids is not None:
                missing_ids = sorted(previous_ids - set(discovered))
                new_ids = sorted(set(discovered) - previous_ids)
        except (OSError, ValueError, TypeError) as exc:
            comparison_errors.append(f"snapshot anterior no verificable: {exc}")

        timestamp = datetime.now(timezone.utc).isoformat()
        records = []
        for slug, card in discovered.items():
            url = urljoin(self.SITE, card["href"])
            try:
                records.append({"source": "banco_del_sol", "source_id": slug,
                                "scraped_at": timestamp, "promotion_url": url,
                                "catalog": card, "detail": self._detail(self._get(url))})
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(slug + ": " + str(exc))
        self.result = ScrapeResult(records, len(discovered), errors)
        self.coverage = {"scope": "Beneficios vigentes publicados en /beneficios; excluye sección no vigentes",
                         "catalog_url": self.LIST_URL, "scraped_at": timestamp,
                         "catalog_count": len(discovered), "unique_discovered": len(discovered),
                         "detail_success": len(records), "discovered_ids": list(discovered),
                         "errors": errors,
                         "pagination": {"states": len(counts), "cumulative_counts": counts,
                                        "terminal_verified": terminal_verified,
                                        "verification": "short final batch and hidden load-more control" if terminal_verified else None},
                         "snapshot_comparison": {
                             "previous_count": len(previous_ids) if previous_ids is not None else None,
                             "missing_ids": missing_ids,
                             "new_ids": new_ids,
                             "requires_review": bool(missing_ids or comparison_errors),
                             "errors": comparison_errors,
                         },
                         "catalog_complete": self.result.complete and terminal_verified,
                         "snapshot_replace_allowed": (self.result.complete and terminal_verified
                                                      and not missing_ids and not comparison_errors),
                         "requires_review": bool(missing_ids or comparison_errors)}
        if self.coverage["snapshot_replace_allowed"]:
            self._accepted_candidate = json.dumps(records, ensure_ascii=False, sort_keys=True)
        return self.result

    def save_raw_promotions(self, promotions: list[dict]) -> None:
        if (self.result is None or not self.result.complete or
                not self.coverage.get("catalog_complete") or
                self.coverage.get("snapshot_replace_allowed") is not True or
                self.coverage.get("requires_review") is not False):
            raise ValueError("El reemplazo del snapshot no está autorizado")

        def validate_before_replace():
            current_ids = self._record_ids(promotions)
            if (self._accepted_candidate is None or
                    json.dumps(promotions, ensure_ascii=False, sort_keys=True) != self._accepted_candidate):
                raise ValueError("El candidato cambió después de verificar la extracción")
            try:
                previous_ids = self._previous_ids()
            except (OSError, ValueError, TypeError) as exc:
                self.coverage["snapshot_replace_allowed"] = False
                self.coverage["requires_review"] = True
                comparison = self.coverage["snapshot_comparison"]
                comparison["requires_review"] = True
                comparison["errors"] = [f"snapshot anterior no verificable: {exc}"]
                raise
            missing = sorted((previous_ids or set()) - current_ids)
            if missing:
                self.coverage["snapshot_replace_allowed"] = False
                self.coverage["requires_review"] = True
                self.coverage["snapshot_comparison"]["missing_ids"] = missing
                self.coverage["snapshot_comparison"]["requires_review"] = True
                raise ValueError(
                    f"No se reemplaza el snapshot: {len(missing)} IDs anteriores "
                    f"desaparecieron sin revisión manual: {missing[:10]}"
                )
        validate_before_replace()
        # Metadata failure must not replace the accepted raw snapshot. Each file
        # is atomic; these two files are not a multi-file transaction.
        self._atomic(self.output_path.with_name("banco_del_sol_coverage.json"), self.coverage)
        self._atomic(self.output_path, promotions, before_replace=validate_before_replace)

    @staticmethod
    def _atomic(path: Path, data, before_replace: Callable[[], None] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
            if before_replace is not None:
                before_replace()
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    scraper = BancoDelSolScraper()
    result = scraper.scrape()
    print(f"Vigentes descubiertos: {result.catalog_count}; detalles: {len(result.promotions)}; "
          f"completo: {scraper.coverage['catalog_complete']}; errores: {result.failed_ids}")
    scraper.save_raw_promotions(result.promotions)
