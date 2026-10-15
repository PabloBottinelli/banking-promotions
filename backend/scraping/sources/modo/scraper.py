"""Public MODO web catalog, using the same unauthenticated V2 API as /promos.

Only RUNNING campaigns are in scope, as explicitly requested by the user.
Neither publication display dates nor the home-page slots define eligibility.
"""
import hashlib
import json
import math
import re
import os
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def text(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


class ModoScraper:
    SITE = "https://www.modo.com.ar"
    LIST_URL = SITE + "/promos"
    API = LIST_URL + "/api/rewards"
    STATES = "RUNNING"
    PAGE_SIZE = 100

    def __init__(self, client=None, output_path=None, request_delay=0.15):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self.output_path = Path(output_path) if output_path else DATA_DIR / "modo_promotions.json"
        self.request_delay = request_delay
        self.coverage = {}
        self.result = None
        self._candidate_digest = None

    def _get(self, path, **params):
        response = get_with_retries(self.client, self.API + path, params=params)
        if self.request_delay:
            time.sleep(self.request_delay)
        return response.json()

    @staticmethod
    def digest(records):
        return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def validate_records(records):
        if not isinstance(records, list) or not records:
            raise ValueError("MODO: catálogo vacío o malformado")
        ids = set()
        for raw in records:
            if not isinstance(raw, dict) or raw.get("source") != "modo":
                raise ValueError("MODO: registro/fuente inválida")
            identifier = raw.get("source_id")
            if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
                raise ValueError("MODO: ID vacío o duplicado")
            ids.add(identifier)
            d = raw.get("detail")
            if not isinstance(d, dict) or d.get("id") != identifier or not text(d.get("name")):
                raise ValueError("MODO: detalle vacío o identidad incorrecta")
            offers = d.get("offers")
            if not isinstance(offers, list) or not offers:
                raise ValueError("MODO: detalle sin ofertas")
            offer_ids = [o.get("id") for o in offers if isinstance(o, dict)]
            if len(offer_ids) != len(offers) or any(not x or not str(x).strip() for x in offer_ids) or len(set(offer_ids)) != len(offer_ids):
                raise ValueError("MODO: IDs de ofertas vacíos o duplicados")
            # Null is an actual optional source field (common in financing).
            # A present but blank HTML legal node is a malformed response.
            if d.get("terms_and_conditions") not in (None, "") and not text(d["terms_and_conditions"]):
                raise ValueError("MODO: nodo legal vacío")
            stamp = datetime.fromisoformat(raw["scraped_at"])
            if stamp.tzinfo is None:
                raise ValueError("MODO: timestamp sin zona horaria")
        return ids

    def _check_baseline(self, records):
        ids = self.validate_records(records)
        if not self.output_path.exists():
            return {"baseline_available": False, "missing_previous_ids": [], "lost_detail_ids": []}
        old = json.loads(self.output_path.read_text(encoding="utf-8"))
        old_ids = self.validate_records(old)
        current = {r["source_id"]: r for r in records}
        lost = []
        for r in old:
            if r["source_id"] in current:
                a, b = r["detail"], current[r["source_id"]]["detail"]
                if text(a.get("terms_and_conditions")) and not text(b.get("terms_and_conditions")):
                    lost.append(r["source_id"])
                for key in ("faq", "applicability_description"):
                    if text((a.get("details") or {}).get(key)) and not text((b.get("details") or {}).get(key)):
                        lost.append(r["source_id"])
                old_offers = {o["id"] for o in a["offers"]}
                if old_offers - {o["id"] for o in b["offers"]}:
                    lost.append(r["source_id"])
        return {"baseline_available": True, "missing_previous_ids": sorted(old_ids - ids),
                "lost_detail_ids": sorted(set(lost))}

    def scrape(self):
        """Return a candidate only. No snapshot or coverage file writes."""
        self._candidate_digest = None
        records, cards, errors, page_evidence = [], [], [], []
        timestamp = datetime.now(timezone.utc).isoformat()
        total = 0
        try:
            banks_payload = self._get("/v2/banks")
            categories = self._get("/categories", subcategories="true")
            if not isinstance(banks_payload.get("banks"), list) or not banks_payload["banks"] or not isinstance(categories, list) or not categories:
                raise ValueError("Catálogos auxiliares vacíos")
            banks = {x["id"]: x for x in banks_payload["banks"]}
            cats = {str(x["id"]): x for x in categories}
            def page(n):
                return self._get("/v2/filter", limit=self.PAGE_SIZE, page=n, origin="WEB_MODO", fcalcstatus=self.STATES)
            first = page(1)
            pagination = first["pagination"]
            total = pagination["total_results"]
            pages = pagination["total_pages"]
            if total <= 0 or pages != math.ceil(total / self.PAGE_SIZE):
                raise ValueError("Paginación inconsistente o catálogo vacío")
            for number in range(1, pages + 1):
                payload = first if number == 1 else page(number)
                pg, items = payload["pagination"], payload["cards"]
                expected = min(self.PAGE_SIZE, total - (number - 1) * self.PAGE_SIZE)
                if (pg.get("page") != number or pg.get("limit") != self.PAGE_SIZE or pg.get("total_results") != total
                        or pg.get("total_pages") != pages or not isinstance(items, list) or len(items) != expected):
                    raise ValueError(f"Página {number} inconsistente")
                if any(item.get("calculated_status") != self.STATES for item in items):
                    raise ValueError("El endpoint filtrado devolvió una campaña fuera de RUNNING")
                cards.extend(items)
                page_evidence.append({"page": number, "count": len(items), "card_ids": [x["card_id"] for x in items]})
            card_ids = [x["card_id"] for x in cards]
            if len(set(card_ids)) != len(card_ids):
                raise ValueError("Cards duplicadas entre páginas")
            # Check explicit end AND repeat first page to detect unstable pagination.
            terminal = page(pages + 1)
            repeated = page(1)
            terminal_pg = terminal.get("pagination", {})
            # This API resets total_results/total_pages to zero beyond the end.
            if (terminal.get("cards") != [] or terminal_pg.get("page") != pages + 1
                    or terminal_pg.get("total_results") not in {0, total}
                    or terminal_pg.get("total_pages") not in {0, pages}):
                raise ValueError("Página terminal no vacía o total cambiante")
            if repeated != first:
                raise ValueError("Primera página cambió durante la captura")
            by_benefit = {}
            for card in cards:
                identifier = card["benefit"]["id"]
                by_benefit.setdefault(identifier, []).append(card)
            for identifier, listings in by_benefit.items():
                try:
                    detail = self._get("/v2/benefit/" + identifier)
                    offer_banks = {bank_id for o in detail.get("offers", []) for bank_id in (o.get("requirements") or {}).get("banks", {}).get("list", [])}
                    offer_cats = {str(cat) for o in detail.get("offers", []) for cat in o.get("categories", [])}
                    raw = {"source": "modo", "source_id": identifier, "scraped_at": timestamp,
                           "source_url": self.LIST_URL, "detail_url": self.API + "/v2/benefit/" + identifier,
                           "promotion_url": self.LIST_URL + "/" + (detail.get("slug") or identifier),
                           "listings": listings, "detail": detail,
                           "banks": [banks[k] for k in sorted(offer_banks) if k in banks],
                           "categories": [cats[k] for k in sorted(offer_cats) if k in cats]}
                    self.validate_records([raw])
                    if any(x["offer"]["id"] not in {o["id"] for o in detail["offers"]} for x in listings):
                        raise ValueError("Oferta publicada ausente del detalle")
                    records.append(raw)
                except Exception as exc:
                    errors.append(f"{identifier}: {exc}")
            # Final count/first-page check after potentially long detail collection.
            if page(1) != first:
                raise ValueError("Catálogo cambió durante descarga de detalles")
        except Exception as exc:
            errors.append(f"catalog: {exc}")
        expected_count = len({x["benefit"]["id"] for x in cards}) if cards else total
        self.result = ScrapeResult(records, expected_count, errors)
        self.coverage = {"scope": "Public web MODO: RUNNING only; all banks/categories/channels",
                         "catalog_complete": self.result.complete, "catalog_cards": total,
                         "unique_benefits": expected_count, "detail_success": len(records), "errors": errors,
                         "pages": page_evidence, "pagination_verified": not errors,
                         "safe_to_deactivate": False, "normalization_complete": None,
                         "snapshot_replace_allowed": False, "requires_review": bool(errors),
                         "scraped_at": timestamp}
        self.coverage["counts_by_state"] = dict(Counter(x.get("calculated_status", "UNKNOWN") for x in cards))
        self.coverage["counts_by_native_type"] = dict(Counter(x["benefit"].get("type", "UNKNOWN") for x in cards))
        self.coverage["missing_legal_text_ids"] = [r["source_id"] for r in records if not text(r["detail"].get("terms_and_conditions"))]
        conflicts, unresolved = [], []
        from normalization.sources.modo import ModoNormalizer
        for raw in records:
            detail = raw["detail"]
            advertised = re.findall(r"(\d+(?:[.,]\d+)?)\s*%", text((detail.get("card") or {}).get("benefit")))
            rates = [o.get("outcomes", {}).get("cashback", {}).get("amount") for o in detail["offers"]
                     if o.get("outcomes", {}).get("cashback", {}).get("amount_type") == "percent"]
            if advertised and rates and Decimal(advertised[0].replace(",", ".")) not in [Decimal(str(x)) for x in rates]:
                conflicts.append(raw["source_id"])
                legal = text(detail.get("terms_and_conditions"))
                legal_support = any(re.search(r"(?<!\d)" + re.escape(str(rate)) + r"\s*%", legal) for rate in rates)
                faq_segments = len(ModoNormalizer._offers(detail)) > len(detail["offers"])
                if not legal_support and not faq_segments:
                    unresolved.append(raw["source_id"])
        self.coverage["publication_rate_conflict_ids"] = conflicts
        self.coverage["unresolved_publication_rate_conflict_ids"] = unresolved
        legal_conflicts = {r["source_id"]: ModoNormalizer.evidence_conflicts(r["detail"]) for r in records}
        legal_conflicts = {key: value for key, value in legal_conflicts.items() if value}
        self.coverage["legal_engine_conflicts"] = legal_conflicts
        try:
            baseline = self._check_baseline(records)
            self.coverage.update(baseline)
            review = bool(errors or unresolved or legal_conflicts or baseline["missing_previous_ids"] or baseline["lost_detail_ids"])
            self.coverage.update(requires_review=review, snapshot_replace_allowed=self.result.complete and not review)
        except Exception as exc:
            self.coverage.update(requires_review=True, snapshot_replace_allowed=False, baseline_error=str(exc))
        if self.result.complete:
            self._candidate_digest = self.digest(records)
        return self.result

    def save_raw_promotions(self, records):
        """Recheck candidate, legal/detail loss and baseline immediately before replace."""
        if (self.result is None or not self.result.complete or self.coverage.get("catalog_complete") is not True
                or self.coverage.get("snapshot_replace_allowed") is not True or self.coverage.get("requires_review") is not False
                or self.digest(records) != self._candidate_digest):
            raise ValueError("MODO: candidato no aprobado o modificado")
        baseline = self._check_baseline(records)
        if baseline["missing_previous_ids"] or baseline["lost_detail_ids"]:
            raise ValueError("MODO: desaparecieron IDs o detalles; requiere revisión")
        # Validate the whole candidate even when called outside SyncRunner.
        from normalization.sources.modo import ModoNormalizer
        ids = []
        for raw in records:
            if ModoNormalizer.evidence_conflicts(raw["detail"]):
                raise ValueError("MODO: contradicciones legales/técnicas pendientes de revisión")
            variants = ModoNormalizer().normalize_many(raw)
            if not variants:
                raise ValueError("MODO: oferta sin variantes")
            ids.extend(v.source_id for v in variants)
        if len(ids) != len(set(ids)):
            raise ValueError("MODO: variantes duplicadas")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.output_path.parent, suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                json.dump(records, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.output_path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
