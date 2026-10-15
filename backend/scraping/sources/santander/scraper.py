"""Anonymous Santander Benefits BFF. Capture candidates; never persist in scrape()."""
import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from scraping.http_client import get_with_retries
from scraping.models import ScrapeResult

BASE = "https://www.santander.com.ar"
CATALOG = BASE + "/personas/beneficios#/results?category-code=ALL"
API = BASE + "/bff-benefits"


def text(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class SantanderScraper:
    def __init__(self, client=None, raw_path=None, workers=2):
        self.client = client or httpx.Client(follow_redirects=True)
        self.raw_path = Path(raw_path) if raw_path else Path(__file__).resolve().parents[3] / "data/santander_promotions.json"
        self.workers = workers
        self.coverage = {"catalog_complete": False, "snapshot_replace_allowed": False,
                         "requires_review": True, "safe_to_deactivate": False}
        self._candidate_digest = None

    def _get(self, path, **params):
        return get_with_retries(self.client, API + path, params=params).json()

    def _catalog(self, limit):
        rows, pages, total = [], [], None
        for page in range(1, 10001):
            data = self._get("/brands", page=page, limit=limit)
            batch, count = data["items"], data["totalItems"]
            if not isinstance(batch, list) or not isinstance(count, int) or count <= 0:
                raise ValueError("Invalid/empty brand catalog")
            if total is None:
                total = count
            if total != count:
                raise ValueError("Catalog total changed during pagination")
            pages.append({"page": page, "count": len(batch)})
            if not batch:
                if len(rows) != total:
                    raise ValueError("Premature empty page")
                ids = [str(b["id"]) for b in rows]
                if len(set(ids)) != len(ids):
                    raise ValueError("Duplicate catalog brand IDs")
                return rows, pages
            rows.extend(batch)
            if len(rows) > total or len(batch) > limit:
                raise ValueError("Pagination exceeded reported boundary")
        raise ValueError("Pagination safety bound reached")

    @staticmethod
    def validate_rows(rows):
        if not isinstance(rows, list) or not rows:
            raise ValueError("Empty snapshot")
        seen = set()
        for row in rows:
            identifier = row.get("source_id")
            d, b, p = row["detail"], row["catalog"], row["program"]
            expected = f"{b['id']}:{d['id']}"
            if row.get("source") != "santander" or not identifier or identifier != expected or identifier in seen:
                raise ValueError("Invalid/duplicate source identity")
            seen.add(identifier)
            if str(p.get("id")) != str(d.get("id")):
                raise ValueError("Publication identity mismatch")
            if not text(b.get("name")) or not text(d.get("legal")) or not text(d.get("texts", {}).get("title")):
                raise ValueError("Blank essential publication detail")
            if not any(str(x.get("brand", {}).get("id")) == str(b["id"]) for x in d.get("brands", [])):
                raise ValueError("Publication has no matching attached brand")

    def _brand(self, brand, timestamp):
        programs = self._get("/brands/" + str(brand["id"]))
        items = programs["items"]
        if not items:
            raise ValueError("Empty brand publications")
        unique, occurrences = {}, {}
        for p in items:
            key = str(p['id'])
            if key in unique and unique[key] != p:
                raise ValueError("Conflicting duplicate publication payloads")
            unique[key] = p
            occurrences[key] = occurrences.get(key, 0) + 1
        rows = []
        # totalItems is NOT a publication count (e.g. 1 for two programs).
        for program in unique.values():
            detail = self._get("/publications/" + str(program["id"]), brandId=brand["id"])
            row = dict(source="santander", source_id=f"{brand['id']}:{program['id']}",
                       scraped_at=timestamp, promotion_url=BASE + f"/personas/beneficios#/publication?brandId={brand['id']}&programId={program['id']}",
                       catalog_url=CATALOG, catalog=brand, program=program, detail=detail,
                       program_occurrences=occurrences[str(program['id'])],
                       program_catalog_total=programs.get('totalItems'))
            self.validate_rows([row])
            rows.append(row)
        return rows

    def scrape(self):
        self._candidate_digest = None
        stamp = datetime.now(timezone.utc).isoformat()
        rows, failures, pages, verification = [], [], [], []
        brands = []
        try:
            brands, pages = self._catalog(100)
            # Different page partition + explicit empty terminal page catches ignored/unstable pagination.
            checked, verification = self._catalog(73)
            if {str(b['id']) for b in brands} != {str(b['id']) for b in checked}:
                raise ValueError("Catalog changed between independent page partitions")
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = [(b, pool.submit(self._brand, b, stamp)) for b in brands]
                for b, future in futures:
                    try:
                        rows.extend(future.result())
                    except Exception as exc:
                        failures.append(f"brand:{b['id']}: {type(exc).__name__}: {exc}")
            self.validate_rows(rows)
        except Exception as exc:
            failures.append(f"catalog: {type(exc).__name__}: {exc}")
        prior = None
        missing = []
        try:
            if self.raw_path.exists():
                prior = json.loads(self.raw_path.read_text(encoding="utf8"))
                self.validate_rows(prior)
                missing = sorted({r['source_id'] for r in prior} - {r['source_id'] for r in rows})
        except Exception as exc:
            failures.append(f"baseline: {type(exc).__name__}: {exc}")
        complete = bool(brands and rows and not failures)
        self.coverage = dict(catalog_url=CATALOG, scraped_at=stamp, brand_count=len(brands),
            publication_count=len(rows), brand_ids=[str(b['id']) for b in brands],
            source_ids=[r['source_id'] for r in rows], pages=pages, verification_pages=verification,
            errors=failures, missing_previous_ids=missing, baseline_available=prior is not None,
            baseline_limitation="Local baseline only; ephemeral CI does not establish historical continuity.",
            catalog_complete=complete, snapshot_replace_allowed=complete and not missing,
            requires_review=bool(failures or missing), safe_to_deactivate=False)
        if complete:
            self._candidate_digest = digest(rows)
        # catalog_count measures publication records, not brands. Failed brands explicitly block complete.
        return ScrapeResult(rows, len(rows) if complete else len(rows) + len(failures) or len(brands), failures)

    def save_raw_promotions(self, rows):
        self.validate_rows(rows)
        if (self._candidate_digest != digest(rows) or not self.coverage.get("catalog_complete")
                or self.coverage.get("snapshot_replace_allowed") is not True
                or self.coverage.get("requires_review") is not False):
            raise ValueError("Candidate not accepted or changed after scraping")
        if self.raw_path.exists():
            old = json.loads(self.raw_path.read_text(encoding="utf8"))
            self.validate_rows(old)
            if {r['source_id'] for r in old} - {r['source_id'] for r in rows}:
                raise ValueError("Missing historical IDs require review")
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=self.raw_path.parent,
                                             prefix=".santander-", suffix=".tmp", delete=False) as f:
                temp = Path(f.name)
                json.dump(rows, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.raw_path)
        finally:
            if temp:
                temp.unlink(missing_ok=True)
