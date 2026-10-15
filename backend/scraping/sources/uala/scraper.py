"""Ualá public Next.js/Contentful catalog; no credentials or browser required."""
import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from scraping.http_client import DEFAULT_TIMEOUT, get_with_retries
from scraping.models import ScrapeResult

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def next_props(html):
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("script#__NEXT_DATA__")
    if node is None or not node.string:
        raise ValueError("Missing Next.js hydration")
    return json.loads(node.string)["props"]["pageProps"]


def validate_records(records):
    if not isinstance(records, list) or not records:
        raise ValueError("Empty/malformed catalog")
    ids = set()
    for raw in records:
        if not isinstance(raw, dict) or raw.get("source") != "uala":
            raise ValueError("Invalid raw/source")
        identifier = raw.get("source_id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
            raise ValueError("Missing/duplicate ID")
        ids.add(identifier)
        item, detail = raw["catalog"], raw["detail"]
        if item["sys"]["id"] != identifier or detail.get("id") != identifier:
            raise ValueError("Mismatched campaign identity")
        if not item["fields"].get("brand", "").strip():
            raise ValueError("Blank brand")
        specs = detail.get("specs")
        expected = item["fields"].get("PromotionSpecs", [])
        if not specs or {s.get("id") for s in specs} != {s["sys"]["id"] for s in expected}:
            raise ValueError("Missing/mismatched spec IDs")
        if len({s.get("id") for s in specs}) != len(specs):
            raise ValueError("Duplicate spec ID")
        for spec in specs:
            if not spec.get("id") or not spec.get("title", "").strip() or not spec.get("legalDisclaimer", "").strip():
                raise ValueError("Blank essential title/legal detail")
            original = next(s["fields"] for s in expected if s["sys"]["id"] == spec["id"])
            if original.get("promotionLegal") != spec["legalDisclaimer"]:
                raise ValueError("Catalog/detail legal conflict")
    return ids


def fingerprint(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def variant_identities(records):
    """Historical identity includes every normalized CMS spec, not only campaigns."""
    return {(raw["source_id"], spec["id"])
            for raw in records for spec in raw["detail"]["specs"]}


class UalaScraper:
    SITE_URL = "https://www.uala.com.ar"
    CATALOG_URL = SITE_URL + "/promociones"

    def __init__(self, client=None, output_path=None):
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self.output_path = Path(output_path) if output_path else DATA_DIR / "uala_promotions.json"
        self.coverage = {}
        self.result = None
        self._candidate_hash = None

    def _get(self, url):
        return get_with_retries(self.client, url).text

    @staticmethod
    def _catalog(html):
        components = next_props(html)["page"]["components"]
        catalogs = [c["promociones"] for c in components if "promociones" in c]
        if len(catalogs) != 1 or not isinstance(catalogs[0], list) or not catalogs[0]:
            raise ValueError("Missing/ambiguous hydration catalog")
        items = catalogs[0]
        ids = [i["sys"]["id"] for i in items]
        if len(set(ids)) != len(ids) or any(not str(i).strip() for i in ids):
            raise ValueError("Duplicate/blank catalog IDs")
        return items

    def scrape(self):
        records, failures, items = [], [], []
        pagination_evidence = None
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            html = self._get(self.CATALOG_URL)
            items = self._catalog(html)
            # Verify the live UI implementation: slicing an already supplied array,
            # with load-more incrementing local state. Fail closed on UI redesign.
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.select("script[src]"):
                src = script["src"]
                if not src.startswith("/_next/static/chunks/"):
                    continue
                code = self._get(self.SITE_URL + src)
                if ("Cargar m\\xe1s promociones" in code and
                        re.search(r"\.slice\(0,\w+\)\.map", code) and
                        re.search(r"onClick:\(\)=>\w+\(\w+=>\w+\+9\)", code)):
                    pagination_evidence = {"bundle_url": self.SITE_URL + src,
                                           "sha256": hashlib.sha256(code.encode()).hexdigest(),
                                           "mechanism": "hydrated array slice; local load-more +9"}
                    break
            if pagination_evidence is None:
                raise ValueError("Unverified pagination implementation")
            for item in items:
                identifier = item["sys"]["id"]
                try:
                    slug = item["fields"]["urlDeLaPromocion"]
                    if not re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
                        raise ValueError("Unexpected external/malformed promotion URL")
                    url = self.CATALOG_URL + "/" + slug
                    detail = next_props(self._get(url))["promotion"]
                    # Shared site navigation is unrelated to promotion facts and
                    # would otherwise be copied eleven times in the snapshot.
                    promotion_payload = copy.deepcopy(item)
                    promotion_payload["fields"].pop("promotionweb", None)
                    raw = dict(source="uala", source_id=identifier, source_url=url,
                               catalog_url=self.CATALOG_URL, scraped_at=timestamp,
                               catalog=promotion_payload, detail=detail)
                    validate_records([raw])
                    records.append(raw)
                except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
                    failures.append(f"{identifier}: {exc}")
            # A second complete hydration read catches mid-capture changes.
            if self._catalog(self._get(self.CATALOG_URL)) != items:
                raise ValueError("Catalog changed during capture")
        except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
            failures.append("catalog: " + str(exc))
        self.result = ScrapeResult(records, len(items), failures)
        complete = self.result.complete and pagination_evidence is not None
        missing, missing_variants = [], []
        baseline = "unavailable; first local capture is not historical evidence"
        try:
            if self.output_path.exists():
                previous = json.loads(self.output_path.read_text(encoding="utf-8"))
                missing = sorted(validate_records(previous) - {r["source_id"] for r in records})
                missing_variants = sorted(variant_identities(previous) - variant_identities(records))
                baseline = "valid local snapshot; not durable across ephemeral CI"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures.append("baseline: " + str(exc))
            complete = False
        review = bool(missing or missing_variants) or not complete
        self.coverage = dict(catalog_complete=complete, catalog_count=len(items),
                             detail_success=len(records), failed_ids=list(failures),
                             source_ids=[r["source_id"] for r in records],
                             captured_at=timestamp, pagination=pagination_evidence,
                             missing_previous_ids=missing, historical_baseline=baseline,
                             missing_previous_variant_ids=[f"{campaign}:{spec}" for campaign, spec in missing_variants],
                             snapshot_replace_allowed=complete and not missing and not missing_variants,
                             requires_review=review, safe_to_deactivate=False)
        self._candidate_hash = fingerprint(records)
        return self.result

    def save_raw_promotions(self, promotions):
        if (self.result is None or not self.result.complete or
                not self.coverage.get("catalog_complete") or
                self.coverage.get("snapshot_replace_allowed") is not True or
                self.coverage.get("requires_review") is not False):
            raise ValueError("Candidate not accepted")
        ids = validate_records(promotions)
        if fingerprint(promotions) != self._candidate_hash:
            raise ValueError("Candidate changed after capture")
        if self.output_path.exists():
            previous = json.loads(self.output_path.read_text(encoding="utf-8"))
            missing = sorted(validate_records(previous) - ids)
            missing_variants = sorted(variant_identities(previous) - variant_identities(promotions))
            if missing or missing_variants:
                self.coverage.update(
                    snapshot_replace_allowed=False, requires_review=True,
                    missing_previous_ids=missing,
                    missing_previous_variant_ids=[f"{campaign}:{spec}" for campaign, spec in missing_variants])
                kind = "IDs" if missing else "variant IDs"
                raise ValueError(f"Missing historical {kind}; review required")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.output_path.parent,
                                             suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(promotions, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.output_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
