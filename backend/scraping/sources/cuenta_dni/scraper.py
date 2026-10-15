"""Cuenta DNI SSR catalog and the same public detail API used by its modals.

Merchant search directories are eligibility lookups, not additional campaigns.
No snapshots are written by scrape(). Missing historical IDs require review.
"""
import base64
import hashlib
import io
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult

SITE = "https://www.bancoprovincia.com.ar"
LIST_URL = SITE + "/cuentadni/contenidos/cdnibeneficios/"
DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def text(html):
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


class CuentaDNIScraper:
    def __init__(self, client=None, output_path=None):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self.output_path = Path(output_path) if output_path else DATA_DIR / "cuenta_dni_promotions.json"
        self.coverage = {}
        self.result = None
        self._candidate_digest = None

    def _get(self, url):
        return get_with_retries(self.client, url)

    @staticmethod
    def _digest(records):
        return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def _validate(records):
        if not isinstance(records, list) or not records:
            raise ValueError("Empty Cuenta DNI snapshot")
        ids = []
        for row in records:
            if not isinstance(row, dict) or row.get("source") != "cuenta_dni":
                raise ValueError("Invalid source")
            identifier = row.get("source_id")
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("Blank source_id")
            ids.append(identifier)
            entity = row["payload"]["Entity"]
            b = entity["Beneficio"]
            if str(b["id"]) != identifier or not text(b.get("titulo")):
                raise ValueError("Blank title or mismatched detail ID")
            if not text(b.get("legal")):
                if not row.get("external_terms", {}).get("text", "").strip():
                    raise ValueError("Blank essential legal detail")
            if b.get("urlPagina") and not row.get("linked_page", {}).get("html", "").strip():
                raise ValueError("Missing linked campaign page")
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate source_id")
        return set(ids)

    def _external_terms(self, entity):
        """Resolve the linked Visa offer and its legally binding PDF, not other offers."""
        buttons = entity.get("Botones", [])
        links = [b.get("link", "") for b in buttons if "rminos" in b.get("texto", "")]
        if len(links) != 1:
            raise ValueError("Blank legal without one official external terms link")
        url = links[0]
        parsed = urlparse(url)
        if parsed.hostname != "www.visa.com.ar" or not re.search(r"/\d+$", parsed.path):
            raise ValueError("Unsupported external legal provider")
        api = "https://www.visa.com.ar/offers/api/offer/" + parsed.path.rsplit("/", 1)[-1] + "?locale=es_ar"
        payload = self._get(api).json()
        soup = BeautifulSoup(payload.get("merchantTerms", {}).get("richText", ""), "html.parser")
        pdfs = [urljoin(url, a["href"]) for a in soup.select('a[href]') if a["href"].lower().endswith(".pdf")]
        if len(pdfs) != 1 or urlparse(pdfs[0]).hostname != "www.visa.com.ar":
            raise ValueError("Missing official Visa terms PDF")
        binary = self._get(pdfs[0]).content
        pages = PdfReader(io.BytesIO(binary)).pages
        legal = "\n".join(page.extract_text() or "" for page in pages)
        if not legal.strip():
            raise ValueError("Blank external legal PDF")
        return {"url": url, "api_url": api, "payload": payload, "pdf_url": pdfs[0],
                "pdf_base64": base64.b64encode(binary).decode(), "text": legal}

    def scrape(self):
        self._candidate_digest = None
        self.coverage = {}
        soup = BeautifulSoup(self._get(LIST_URL).text, "html.parser")
        cards = soup.select(".callModalCDNI.BEN_filterDiv")
        failed, records = [], []
        ids = [card.get("id", "").rsplit("-", 1)[-1] for card in cards]
        structure_ok = bool(cards) and len(ids) == len(set(ids)) and all(i.isdigit() for i in ids)
        # The official page's filters operate on the preloaded elements collection.
        # Detect newly introduced server/browser pagination rather than assuming it absent.
        if soup.select('[rel="next"], .pagination, [data-next-page], .load-more'):
            structure_ok = False
        script = self._get(SITE + "/cuentadni/assets/js/cuentaDNI_v2.js").text
        if "elements[i].style.display" not in script or "getBeneficioData" not in script:
            structure_ok = False
        now = datetime.now(timezone.utc).isoformat()
        for card, identifier in zip(cards, ids):
            try:
                detail_url = SITE + "/cuentadni/Home/GetBeneficioData2?idBeneficio=" + identifier
                payload = self._get(detail_url).json()
                if payload.get("Success") is not True:
                    raise ValueError("Detail API refused campaign")
                entity = payload["Entity"]
                b = entity["Beneficio"]
                row = {"source": "cuenta_dni", "source_id": identifier, "scraped_at": now,
                       "catalog_url": LIST_URL, "detail_url": detail_url,
                       "promotion_url": LIST_URL + "#" + b["url"],
                       "card_html": str(card), "payload": payload}
                if b.get("urlPagina"):
                    url = urljoin(SITE, b["urlPagina"])
                    page = self._get(url).text
                    if "BONIFICACI" not in text(page).upper():
                        raise ValueError("Blank linked campaign terms")
                    row["linked_page"] = {"url": url, "html": page}
                if not text(b.get("legal")):
                    row["external_terms"] = self._external_terms(entity)
                self._validate([row])
                records.append(row)
            except (ValueError, KeyError, TypeError, httpx.HTTPError) as error:
                failed.append(identifier)
                # Keep reproducible errors in compact coverage, never silently skip.
                self.coverage.setdefault("errors", []).append({"source_id": identifier, "error": str(error)})
        if not structure_ok:
            failed.append("catalog-structure")
        self.result = ScrapeResult(records, len(cards), failed)
        reasons = []
        missing = []
        baseline = "unavailable; durable historical baseline unknown"
        if self.output_path.exists():
            previous = json.loads(self.output_path.read_text(encoding="utf8"))
            previous_ids = self._validate(previous)
            missing = sorted(previous_ids - {r["source_id"] for r in records})
            baseline = "local valid snapshot; CI durability not guaranteed"
            if missing:
                reasons.append("Historical campaign IDs disappeared")
        # Source contradictions remain visible and block live replacement/upsert.
        for row in records:
            e = row["payload"]["Entity"]
            legal = text(e["Beneficio"].get("legal")).lower()
            conditions = (" ".join(c.get("texto", "") for c in e.get("Condiciones", [])) + " " + e["Beneficio"].get("bajada", "")).lower()
            if "no acumulable" in legal and "beneficio acumulable" in conditions:
                reasons.append(row["source_id"] + ": conflicting accumulation conditions")
            if "por sábado" in legal and "total de compras realizadas en el mes" in legal:
                reasons.append(row["source_id"] + ": conflicting cap period")
            if "por cuit" in legal and "unificado significa" in legal and "en todos los comercios adheridos" in legal:
                reasons.append(row["source_id"] + ": conflicting merchant-specific versus campaign-wide monetary cap scope")
            if row.get("external_terms"):
                reasons.append(row["source_id"] + ": external PDF contains contradictory NFC exclusion; human review required")
        errors = self.coverage.get("errors", [])
        self.coverage = {"source": "cuenta_dni", "scraped_at": now,
                         "scope": "All campaigns in Cuenta DNI SSR catalog, own linked campaign pages and linked binding terms; merchant directories retained as lookups",
                         "catalog_count": len(cards), "detail_success_count": len(records),
                         "source_ids": ids, "failed_ids": failed, "errors": errors,
                         "pagination_verified": structure_ok,
                         "pagination_evidence": "SSR cards; official JS filters existing elements by display; no next/load-more controls",
                         "catalog_complete": self.result.complete and structure_ok,
                         "normalization_complete": None,
                         "historical_baseline": baseline, "missing_previous_ids": missing,
                         "review_reasons": reasons, "requires_review": bool(reasons) or not self.result.complete,
                         "snapshot_replace_allowed": self.result.complete and not reasons,
                         "safe_to_deactivate": False}
        if self.result.complete:
            self._candidate_digest = self._digest(records)
        return self.result

    def save_raw_promotions(self, records):
        ids = self._validate(records)
        if not self.result or not self.result.complete or self._digest(records) != self._candidate_digest:
            raise ValueError("Not the complete reviewed scrape candidate")
        if self.coverage.get("snapshot_replace_allowed") is not True or self.coverage.get("requires_review") is not False:
            raise ValueError("Snapshot replacement requires source review")
        if self.output_path.exists():
            previous = json.loads(self.output_path.read_text(encoding="utf8"))
            if self._validate(previous) - ids:
                raise ValueError("Historical IDs disappeared; review required")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=self.output_path.parent,
                                             delete=False, suffix=".tmp") as stream:
                temporary = Path(stream.name)
                json.dump(records, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, self.output_path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
