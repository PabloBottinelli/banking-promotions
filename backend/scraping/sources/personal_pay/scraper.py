"""Public Personal Pay catalog. Retrieval never writes the accepted snapshot.

The API cursor counts internal slots, not returned offers. UI pages are merely
client-side slices, and the first SSR response does NOT contain the whole list.
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from scraping.http_client import get_with_retries
from scraping.models import ScrapeResult

PAGE_URL = "https://www.personal.com.ar/pay/beneficios"
API_URL = "https://www.personal.com.ar/pay/api/benefits"
RECHARGE_URL = "https://www.personal.com.ar/pay/promocion-recarga-personal"
TERMS_URL = "https://www.personal.com.ar/pay/terminos-y-condiciones/promociones"
RAW_PATH = Path(__file__).resolve().parents[3] / "data/personal_pay_promotions.json"


def fingerprint(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_records(records):
    if not isinstance(records, list) or not records:
        raise ValueError("Empty or malformed Personal Pay snapshot")
    seen = set()
    for raw in records:
        if not isinstance(raw, dict) or raw.get("source") != "personal_pay":
            raise ValueError("Invalid raw source")
        identity = raw.get("source_id")
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError("Blank or duplicate raw identity")
        seen.add(identity)
        if raw.get("kind") == "legal_campaign":
            entry = raw.get("legal_campaign")
            if not isinstance(entry, dict) or not isinstance(entry.get("tycModel"), dict):
                raise ValueError("Missing legal campaign model")
            for value in [entry.get("title"), entry["tycModel"].get("description")]:
                if not isinstance(value, str) or not BeautifulSoup(value, "html.parser").get_text(strip=True):
                    raise ValueError("Blank essential legal campaign content")
            continue
        detail = raw.get("detail", {})
        if not isinstance(detail, dict):
            raise ValueError("Malformed detail object")
        title = detail.get("title")
        if str(detail.get("id", "")) != identity or not isinstance(title, str) or not title.strip():
            raise ValueError("Missing/mismatched detail identity or title")
        legal = detail.get("legal") or detail.get("documentTyc")
        if not isinstance(legal, str) or not legal.strip():
            raise ValueError("Blank essential legal detail")
        for field in ["description", "discounts"]:
            if not isinstance(detail.get(field), str) or not detail[field].strip():
                raise ValueError("Blank essential benefit detail")
    return seen


class PersonalPayScraper:
    def __init__(self, client=None, raw_path=RAW_PATH, *, allow_initial_snapshot=False):
        self.client = client or httpx.Client(follow_redirects=True)
        self._owns_client = client is None
        self.raw_path = Path(raw_path)
        self.allow_initial_snapshot = allow_initial_snapshot
        self.coverage = {}
        self._candidate_hash = None

    def _get(self, url, **kwargs):
        return get_with_retries(self.client, url, **kwargs)

    def _catalog(self, **filters):
        result, pages, cursor, seen = [], [], 0, set()
        for _ in range(1000):  # bound errors, never a successful truncation
            payload = self._get(API_URL, params={"sourceSection": "web", "offset": cursor, **filters}).json()
            data = payload["data"]
            batch = data["benefits"]
            if not isinstance(batch, list):
                raise ValueError("Malformed catalog batch")
            pages.append({"offset": cursor, "count": len(batch), "next_offset": data["meta"]["offset"]})
            if not batch:
                return result, pages
            for item in batch:
                identity = str(item.get("id", "")).strip()
                if not identity or identity in seen:
                    raise ValueError("Duplicate/blank catalog ID")
                seen.add(identity)
                result.append(item)
            next_cursor = int(data["meta"]["offset"])
            if next_cursor <= cursor:
                raise ValueError("Catalog cursor did not advance")
            cursor = next_cursor
        raise ValueError("Catalog cursor did not terminate")

    def _acceptance(self, promotions):
        try:
            ids = validate_records(promotions)
            if not self.raw_path.exists():
                return self.allow_initial_snapshot, "missing; explicit bootstrap" if self.allow_initial_snapshot else "missing; durable historical baseline unknown", []
            former = validate_records(json.loads(self.raw_path.read_text(encoding="utf-8")))
            missing = sorted(former - ids)
            return not missing, "local valid snapshot", missing
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return False, f"invalid candidate/baseline: {exc}", []

    def _supplemental_legals(self, records, now):
        """Capture every global menu item, including non-drawer linked terms."""
        import re
        from normalization.sources.personal_pay import folded, validity
        response = self._get(TERMS_URL)
        node = BeautifulSoup(response.content, "html.parser").find("script", id="__NEXT_DATA__")
        model = json.loads(node.string)["props"]["pageProps"]["model"]
        entries = model["cqItems"]["tycmenu"]["tycMenu"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("Empty official legal promotions menu")
        followed, classification, unresolved = [], [], []
        for entry in entries:
            slug = entry["url"].rstrip("/").split("/")[-1]
            detail = entry.get("tycModel")
            if detail is None:
                path = entry["url"].replace("/content/cms-personal-pay/ar/es", "/pay")
                url = "https://www.personal.com.ar" + path
                linked = self._get(url)
                linked_node = BeautifulSoup(linked.content, "html.parser").find("script", id="__NEXT_DATA__")
                linked_model = json.loads(linked_node.string)["props"]["pageProps"]["model"]
                detail = linked_model["cqItems"]["tyc"]
                followed.append({"url": url, "model": linked_model})
            if not isinstance(detail.get("description"), str):
                raise ValueError("Blank legal menu detail")
            text = BeautifulSoup(detail["description"], "html.parser").get_text("\n", strip=True)
            if not text:
                raise ValueError("Blank legal menu detail")
            item = {"id": slug, "visible": entry.get("visible", True)}
            if slug == "reintegro-plus":
                raw = {"source": "personal_pay", "source_id": slug, "kind": "legal_campaign", "scraped_at": now,
                       "source_url": TERMS_URL, "legal_campaign": entry}
                validate_records([raw])
                records.append(raw)
                item["classification"] = "standalone benefit; normalized per level"
            elif slug in ["niveles", "pago-de-servicios-personal-flow", "terminales-y-accesorios-en-personal", "recarga-personal"]:
                item["classification"] = "context or duplicated catalog campaign; full model preserved"
            elif slug == "pagos-con-pix-mediante-codigo-qr-brasil":
                item["classification"] = "service contract, no verified promotional benefit; third-party fees may apply"
            elif slug in ["concurso-visa", "concurso-pelotas"]:
                ends = re.search(r"(?:finaliza|hasta).{0,35}?(\d{1,2}) de (\w+) de (\d{4})", folded(text))
                months = dict(zip(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"], range(1, 13)))
                if not ends or ends.group(2) not in months:
                    raise ValueError(f"Unverified contest validity: {slug}")
                end = datetime(int(ends.group(3)), months[ends.group(2)], int(ends.group(1)), tzinfo=timezone.utc).date()
                if end >= datetime.fromisoformat(now).date():
                    raise ValueError(f"New/current contest requires normalization: {slug}")
                item.update(classification="expired contest; retained in raw context", valid_to=end.isoformat())
            else:
                raise ValueError(f"Unclassified official legal campaign: {slug}")
            classification.append(item)
            if slug == "terminales-y-accesorios-en-personal":
                global_dates = validity({}, text)
                for raw in records:
                    offer = raw.get("detail", {})
                    if "terminales y/o accesorios" not in str(offer.get("legal", "")).lower():
                        continue
                    detail_dates = validity(offer, offer["legal"])
                    if global_dates != detail_dates:
                        conflict = {"source_id": raw["source_id"], "field": "validity", "detail_dates": [str(x) for x in detail_dates], "global_dates": [str(x) for x in global_dates],
                            "note": f"Vigencia inicial en conflicto: el legal del detalle indica {detail_dates[0]}, los términos globales indican {global_dates[0]}. Consultar Personal Pay; fecha inicial pendiente de aclaración. Términos globales: {TERMS_URL}."}
                        raw["global_legal_conflict"] = conflict
                        raw["global_legal_campaign"] = entry
                        unresolved.append(conflict)
        return {"global_terms_url": TERMS_URL, "global_terms_model": model, "followed_global_terms": followed}, classification, unresolved

    def scrape(self):
        records, failed, pages = [], [], []
        now = datetime.now(timezone.utc).isoformat()
        try:
            response = self._get(PAGE_URL)
            soup = BeautifulSoup(response.content, "html.parser")
            node = soup.find("script", id="__NEXT_DATA__")
            props = json.loads(node.string)["props"]["pageProps"]
            demand = props["onDemandProps"]
            recharge_response = self._get(RECHARGE_URL)
            recharge_node = BeautifulSoup(recharge_response.content, "html.parser").find("script", id="__NEXT_DATA__")
            recharge_model = json.loads(recharge_node.string)["props"]["pageProps"]["model"]
            seo = recharge_model["cqItems"]["seo"]["metadescription"]
            if not str(seo).strip():
                raise ValueError("Blank supplementary recharge context")
            ssr_ids = {str(x["id"]) for x in demand["initialBenefits"]["data"]["benefits"]}
            catalog, pages = self._catalog()
            if not ssr_ids or not ssr_ids <= {str(x["id"]) for x in catalog}:
                raise ValueError("SSR catalog does not match live API")
            category_checks = []
            catalog_ids = {str(x["id"]) for x in catalog}
            for category in demand["initialCategories"]["data"]:
                filtered, filtered_pages = self._catalog(category=category["name"])
                extra = sorted({str(x["id"]) for x in filtered} - catalog_ids)
                category_checks.append({"name": category["name"], "count": len(filtered),
                                        "extra_ids": extra, "pagination": filtered_pages})
                if extra:
                    raise ValueError(f"Category adds undiscovered offers: {category['name']}: {extra}")
            for listing in catalog:
                identity = str(listing["id"])
                try:
                    url = f"{API_URL}/{identity}"
                    detail = self._get(url).json()["data"]
                    raw = {"source": "personal_pay", "source_id": identity,
                           "scraped_at": now, "source_url": PAGE_URL, "detail_url": url,
                           "listing": listing, "detail": detail}
                    if "primera recarga" in str(detail.get("legal", "")).lower():
                        raw["recharge_context"] = {"url": RECHARGE_URL, "model": recharge_model}
                    validate_records([raw])
                    records.append(raw)
                except (ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
                    failed.append(f"{identity}: {exc}")
            legal_context, legal_classification, unresolved = self._supplemental_legals(records, now)
            # Repeat the entire public sequence to detect moving page boundaries.
            check, check_pages = self._catalog()
            if fingerprint(check) != fingerprint(catalog):
                failed.append("catalog changed during detail retrieval")
            if records:
                records[0]["catalog_context"] = {"page_model": props["model"],
                    "categories": demand["initialCategories"]["data"], **legal_context}
                # The level chart is vector outlines, without machine-readable
                # text. Retain it once for visual review and future comparison.
                grid = props["model"].get("cqItems", {}).get("responsivegrid", {})
                table_path = grid.get(":items", {}).get("logobanner", {}).get("desktopImage", {}).get("path")
                if table_path:
                    table_url = "https://www.personal.com.ar" + table_path
                    table_response = self._get(table_url)
                    if b"<svg" not in table_response.content:
                        raise ValueError("Level chart missing/malformed")
                    records[0]["catalog_context"]["level_chart"] = {"url": table_url, "svg": table_response.content.decode("utf-8")}
            self.coverage = {"scope": "All public /pay/api/benefits sourceSection=web offers beyond SSR, all categories/details/levels/locations; official global promotional terms menu including Reintegro Plus and linked contest documents",
                             "page_url": PAGE_URL, "api_url": API_URL, "scraped_at": now,
                             "categories": [{"id": c["_id"], "name": c["name"]} for c in demand["initialCategories"]["data"]],
                             "pagination": pages, "verification_pagination": check_pages,
                             "category_checks": category_checks,
                             "global_legal_classification": legal_classification,
                             "unresolved_source_discrepancies": unresolved,
                             "ssr_count": len(ssr_ids), "api_catalog_count": len(catalog),
                             "catalog_count": len(catalog) + len([r for r in records if r.get("kind") == "legal_campaign"]),
                             "detail_success_count": len([r for r in records if "detail" in r]),
                             "standalone_legal_count": len([r for r in records if r.get("kind") == "legal_campaign"]), "errors": failed,
                             "catalog_complete": bool(catalog) and not failed,
                             "safe_to_deactivate": False}
            resolved = []
            for raw in records:
                detail = raw.get("detail", {})
                legal = str(detail.get("legal", "") or detail.get("documentTyc", "")).lower()
                if "sin tope" in legal and detail.get("limitAmount") not in (None, "", 0, "0"):
                    resolved.append({"source_id": raw["source_id"], "field": "limitAmount",
                                     "resolution": "Binding legal says sin tope; display cap is not normalized"})
            self.coverage["resolved_source_discrepancies"] = resolved
            count = len(catalog) + len([r for r in records if r.get("kind") == "legal_campaign"])
        except (ValueError, TypeError, KeyError, AttributeError, httpx.HTTPError) as exc:
            failed.append(f"catalog: {exc}")
            count = len(records)
            self.coverage = {"catalog_complete": False, "errors": failed, "pagination": pages,
                             "safe_to_deactivate": False}
        finally:
            if self._owns_client:
                self.client.close()
        allowed, baseline, missing = self._acceptance(records)
        allowed = allowed and self.coverage["catalog_complete"] and not self.coverage.get("unresolved_source_discrepancies")
        self.coverage.update(snapshot_replace_allowed=allowed, requires_review=not allowed,
                             historical_baseline=baseline, missing_prior_ids=missing)
        self._candidate_hash = fingerprint(records)
        return ScrapeResult(records, count, failed)

    def save_raw_promotions(self, promotions):
        """Recheck baseline and candidate immediately before atomic replacement."""
        validate_records(promotions)
        allowed, _, _ = self._acceptance(promotions)
        if (not allowed or self.coverage.get("catalog_complete") is not True
                or self.coverage.get("snapshot_replace_allowed") is not True
                or self.coverage.get("requires_review") is not False
                or fingerprint(promotions) != self._candidate_hash):
            raise ValueError("Personal Pay snapshot replacement refused")
        # This guard also protects direct callers, independently of SyncRunner.
        from normalization.sources.personal_pay import PersonalPayNormalizer
        seen = set()
        for raw in promotions:
            variants = PersonalPayNormalizer().normalize_many(raw)
            if not variants:
                raise ValueError("No normalized variants")
            for row in variants:
                if row.source != "personal_pay" or not row.source_id.strip() or row.source_id in seen:
                    raise ValueError("Invalid normalized identity")
                seen.add(row.source_id)
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.raw_path.parent,
                                             prefix=".personal_pay_", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump(promotions, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.raw_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
