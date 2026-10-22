from datetime import datetime, timezone
import hashlib
import html
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import tempfile

import httpx

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult

BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BACKEND_DIR / "data"


class BBVAScraper:
    BASE_URL = "https://go.bbva.com.ar/willgo/fgo/API/v3"
    CATALOG_URL = f"{BASE_URL}/communications"
    DETAIL_URL = f"{BASE_URL}/communication"
    HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
               "Origin": "https://www.bbva.com.ar", "Referer": "https://www.bbva.com.ar/beneficios/"}
    MAX_PAGES = 1000

    def __init__(self, client: httpx.Client | None = None, *, output_path: Path | None = None):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True, headers=self.HEADERS)
        self.output_path = Path(output_path) if output_path is not None else DATA_DIR / "bbva_promotions.json"
        self.coverage = {"scope": "BBVA unfiltered public communications API and linked details",
                         "catalog_complete": False, "snapshot_replace_allowed": False,
                         "requires_review": True, "safe_to_deactivate": False}
        self._candidate_digest = None
        self._page_metadata = None

    def _response_data(self, response, expected_type):
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != 0 or "data" not in payload:
            raise ValueError("Invalid BBVA response envelope")
        if not isinstance(payload["data"], expected_type):
            raise ValueError("Invalid BBVA data structure")
        return payload

    def fetch_catalog_page(self, page: int) -> list[dict]:
        payload = self._response_data(get_with_retries(self.client, self.CATALOG_URL, params={"pager": page}), list)
        match = re.fullmatch(r"\s*Comunicaciones:\s*(\d+)\s+paginas:\s*(\d+)\s*", str(payload.get("message", "")), re.I)
        self._page_metadata = tuple(map(int, match.groups())) if match else None
        for item in payload["data"]:
            if not isinstance(item, dict) or item.get("id") is None or not str(item.get("id", "")).strip():
                raise ValueError("BBVA catalog item without a valid id")
        return payload["data"]

    def _enumerate(self):
        records, seen, pages = [], set(), []
        metadata = None
        for page in range(self.MAX_PAGES):
            items = self.fetch_catalog_page(page)
            if page == 0:
                metadata = self._page_metadata
            elif metadata != self._page_metadata:
                raise ValueError("BBVA official pagination metadata changed")
            ids = [str(item["id"]) for item in items]
            if len(set(ids)) != len(ids) or seen.intersection(ids):
                raise ValueError("BBVA duplicate page or overlapping IDs")
            pages.append(ids)
            if not items:
                if metadata and (len(records) != metadata[0] or page != metadata[1]):
                    raise ValueError("BBVA official total/pages mismatch")
                return records, pages, metadata
            if metadata and page >= metadata[1]:
                raise ValueError("BBVA nonempty page beyond official page count")
            seen.update(ids)
            records.extend(items)
        raise ValueError("BBVA pagination safety bound reached")

    def fetch_catalog(self) -> list[dict]:
        first, pages, total = self._enumerate()
        second, repeat_pages, repeat_total = self._enumerate()
        if first != second or pages != repeat_pages or total != repeat_total:
            raise ValueError("BBVA pagination unstable between complete enumerations")
        self.coverage.update(official_total=total[0] if total else None,
                             official_pages=total[1] if total else None,
                             pagination_verified=True, page_ids=pages,
                             total_verification_limit=None if total else "No reliable published total; repeated enumeration to explicit empty page only")
        return first

    @staticmethod
    def _validate_detail(detail, source_id):
        if not isinstance(detail, dict) or str(detail.get("id")) != str(source_id):
            raise ValueError("BBVA detail identity mismatch")
        for field in ("cabecera", "basesCondiciones"):
            if not isinstance(detail.get(field), str) or not re.sub(r'<[^>]+>', '', html.unescape(detail[field])).strip():
                raise ValueError(f"BBVA blank essential detail: {field}")
        benefits = detail.get("beneficios")
        if not isinstance(benefits, list) or not benefits or any(not isinstance(b, dict) or not b for b in benefits):
            raise ValueError("BBVA missing or malformed benefits")

    def fetch_promotion_detail(self, promotion_id: str | int) -> dict:
        payload = self._response_data(get_with_retries(self.client, f"{self.DETAIL_URL}/{promotion_id}"), dict)
        self._validate_detail(payload["data"], promotion_id)
        return payload["data"]

    @classmethod
    def _validate_records(cls, records):
        if not isinstance(records, list) or not records:
            raise ValueError("BBVA snapshot must be a nonempty list")
        ids = set()
        for raw in records:
            if not isinstance(raw, dict) or raw.get("source") != "bbva":
                raise ValueError("Invalid BBVA raw record")
            source_id = raw.get("source_id")
            if source_id is None or not str(source_id).strip() or str(source_id) in ids:
                raise ValueError("BBVA blank or duplicate raw ID")
            ids.add(str(source_id))
            if not isinstance(raw.get("catalog"), dict) or str(raw["catalog"].get("id")) != str(source_id):
                raise ValueError("BBVA catalog identity mismatch")
            cls._validate_detail(raw.get("detail"), source_id)
        return ids

    def _baseline_check(self, records):
        ids = self._validate_records(records)
        if not self.output_path.is_file():
            return False, [], "No accepted local baseline; historical state unknown (including ephemeral CI)"
        previous = json.loads(self.output_path.read_text(encoding="utf-8"))
        old_ids = self._validate_records(previous)
        missing = sorted(old_ids - ids)
        return not missing, missing, None

    @staticmethod
    def _digest(records):
        return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def _commercial_review(records):
        from normalization.sources.bbva import BBVANormalizer

        normalizer = BBVANormalizer()
        reasons = []
        for raw in records:
            detail = raw['detail']
            terms = html.unescape(detail['basesCondiciones'])
            headline = re.search(r'(\d{1,3}(?:[.,]\d+)?)\s*%', str(detail.get('cabecera', '')))
            legal = re.search(r'(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:\([^)]*\)\s*)?de\s+(?:reintegro|descuento)', terms, re.I)
            if headline and legal and Decimal(headline.group(1).replace(',', '.')) != Decimal(legal.group(1).replace(',', '.')):
                reasons.append(f"{raw['source_id']}: headline benefit percentage {headline.group(1)}% conflicts with legal {legal.group(1)}%")
            try:
                variants = normalizer.normalize_many(raw)
                semantic = normalizer.review_normalized(raw, variants)
            except (ValueError, TypeError, KeyError) as exc:
                semantic = [f"normalization/commercial review blocked: {exc}"]
            reasons.extend(f"{raw['source_id']}: {reason}" for reason in semantic)
            legal_start = re.search(r'\b(?:del|desde)\s+(\d{1,2}/\d{1,2}/\d{4})\b', terms, re.I)
            if legal_start:
                try:
                    start = datetime.strptime(legal_start.group(1), '%d/%m/%Y').date().isoformat()
                except ValueError:
                    reasons.append(f"{raw['source_id']}: invalid legal start date {legal_start.group(1)}")
                else:
                    if raw.get('catalog', {}).get('fechaDesde') and raw['catalog']['fechaDesde'] != start:
                        reasons.append(f"{raw['source_id']}: catalog start {raw['catalog']['fechaDesde']} conflicts with legal {start}")
            legal_range = re.match(r'\s*(?:del|desde)\s+\d{1,2}/\d{1,2}/\d{4}\s+(?:al|hasta)\s+(\d{1,2}/\d{1,2}/\d{4})\b', terms, re.I)
            if legal_range:
                try:
                    end = datetime.strptime(legal_range.group(1), '%d/%m/%Y').date().isoformat()
                except ValueError:
                    reasons.append(f"{raw['source_id']}: invalid legal end date {legal_range.group(1)}")
                else:
                    if raw.get('catalog', {}).get('fechaHasta') and raw['catalog']['fechaHasta'] != end:
                        reasons.append(f"{raw['source_id']}: catalog end {raw['catalog']['fechaHasta']} conflicts with legal {end}")
            for benefit in detail['beneficios']:
                cap_value = benefit.get('tope')
                if cap_value in (None, ''):
                    cap_value = raw.get('catalog', {}).get('montoTope')
                cap = normalizer._normalize_amount(cap_value)
                if cap is None:
                    match = re.search(r'\btope(?:\s+de\s+reintegro)?\s*:?\s*(?:de\s*)?(?:ARS\s*|\$\s*)' + normalizer.MONEY, normalizer._clean_text(terms), re.I)
                    cap = normalizer._normalize_amount(match.group(1)) if match else None
                _, warning = normalizer._cap_period_evidence(
                    normalizer._normalize_cap_period(benefit.get('frecuenciaTope')), cap,
                    normalizer._clean_text(terms))
                if warning:
                    reasons.append(f"{raw['source_id']}: {warning}")
            if re.search(r'compartido.{0,90}adicional', terms, re.I) and re.search(r'no aplica para compras realizadas con tarjetas de cr[eé]dito adicionales', terms, re.I):
                reasons.append(f"{raw['source_id']}: contradictory additional-card eligibility")
        return reasons

    def scrape(self, limit: int | None = None) -> ScrapeResult:
        self._candidate_digest = None
        self.coverage.update(catalog_complete=False, snapshot_replace_allowed=False, requires_review=True, safe_to_deactivate=False)
        try:
            catalog = self.fetch_catalog()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self.coverage["errors"] = [str(exc)]
            return ScrapeResult([], 0, [f"catalog:{exc}"])
        promotions, errors = [], []
        selected = catalog if limit is None else catalog[:limit]
        for item in selected:
            source_id = item["id"]
            try:
                detail = self.fetch_promotion_detail(source_id)
                promotions.append({"source": "bbva", "source_id": source_id,
                                   "scraped_at": datetime.now(timezone.utc).isoformat(),
                                   "source_url": f"{self.DETAIL_URL}/{source_id}", "catalog": item, "detail": detail})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                errors.append(str(source_id))
                self.coverage.setdefault("errors", []).append(f"{source_id}: {exc}")
        result = ScrapeResult(promotions, len(catalog), errors)
        self.coverage.update(catalog_complete=result.complete, discovered_count=len(catalog), detail_count=len(promotions))
        if result.complete:
            try:
                allowed, missing, reason = self._baseline_check(promotions)
            except (OSError, ValueError, TypeError) as exc:
                allowed, missing, reason = False, [], f"Invalid baseline: {exc}"
            self.coverage.update(snapshot_replace_allowed=allowed, requires_review=not allowed,
                                 missing_previous_ids=missing, baseline_review_reason=reason)
            review = self._commercial_review(promotions)
            if review:
                self.coverage.update(snapshot_replace_allowed=False, requires_review=True, commercial_review_reasons=review)
            self._candidate_digest = self._digest(promotions)
        return result

    def save_raw_promotions(self, promotions: list[dict]) -> None:
        if (self.coverage.get("catalog_complete") is not True or
                self.coverage.get("snapshot_replace_allowed") is not True or
                self.coverage.get("requires_review") is not False or
                self._candidate_digest != self._digest(promotions)):
            raise ValueError("BBVA candidate is not approved for snapshot replacement")
        allowed, missing, reason = self._baseline_check(promotions)
        if not allowed:
            raise ValueError(f"BBVA baseline review required: {missing or reason}")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.output_path.parent,
                                             prefix=".bbva_", suffix=".tmp", delete=False) as f:
                temp_path = Path(f.name)
                json.dump(promotions, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.output_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
