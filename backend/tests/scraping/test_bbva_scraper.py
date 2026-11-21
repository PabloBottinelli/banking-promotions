import httpx
import hashlib
import json
from scraping.sources.bbva.scraper import BBVAScraper
from scraping.models import ScrapeResult

def test_fetch_promotion_detail():
    def handler(request: httpx.Request):
        assert request.url.path.endswith("/communication/123")

        return httpx.Response(
            200,
            json={
                "data": {
                    "id": 123,
                    "cabecera": "20% de descuento",
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = BBVAScraper(client=client)

    detail = scraper.fetch_promotion_detail(123)

    assert detail["id"] == 123
    assert detail["cabecera"] == "20% de descuento"


def test_fetch_catalog_paginates():
    def handler(request: httpx.Request):
        page = int(request.url.params["pager"])

        if page == 0:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": 1},
                        {"id": 2},
                    ]
                },
            )

        if page == 1:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": 3},
                    ]
                },
            )

        return httpx.Response(200, json={"data": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = BBVAScraper(client=client)

    catalog = scraper.fetch_catalog()

    assert len(catalog) == 3
    assert [promotion["id"] for promotion in catalog] == [1, 2, 3]


def test_scrape_continues_when_detail_fails():
    def handler(request: httpx.Request):
        path = request.url.path

        if path.endswith("/communications"):
            page = int(request.url.params["pager"])

            if page == 0:
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": 1},
                            {"id": 2},
                        ]
                    },
                )

            return httpx.Response(200, json={"data": []})

        if path.endswith("/communication/1"):
            return httpx.Response(500, json={"error": "Server error"})

        if path.endswith("/communication/2"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": 2,
                    }
                },
            )

        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = BBVAScraper(client=client)

    result = scraper.scrape()
    promotions = result.promotions

    assert len(promotions) == 1
    assert result.catalog_count == 2
    assert result.failed_ids == ["1"]
    assert result.complete is False

    promotion = promotions[0]

    assert promotion["source"] == "bbva"
    assert promotion["source_id"] == 2
    assert promotion["detail"]["id"] == 2
    assert "scraped_at" in promotion

import pytest


def test_rejects_invalid_catalog_response():
    def handler(request):
        return httpx.Response(200, json={"error": "Unexpected response"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        scraper = BBVAScraper(client=client)

        with pytest.raises(ValueError, match="catálogo inválida"):
            scraper.fetch_catalog_page(0)


def test_rejects_mismatched_detail():
    def handler(request):
        return httpx.Response(200, json={"data": {"id": 999}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        scraper = BBVAScraper(client=client)

        with pytest.raises(ValueError, match="ID incorrecto"):
            scraper.fetch_promotion_detail(123)


def test_incomplete_scrape_cannot_replace_snapshot(tmp_path):
    scraper = BBVAScraper()
    scraper.result = ScrapeResult(
        promotions=[{"source": "bbva", "source_id": "123"}],
        catalog_count=2,
        failed_ids=["456"]
    )
    scraper._limited = False

    with pytest.raises(ValueError, match="incompleta"):
        scraper.save_raw_promotions(scraper.result.promotions)

def test_rejects_unstable_terminal_page():
    terminal_calls = 0

    def handler(request):
        nonlocal terminal_calls
        page = int(request.url.params["pager"])

        if page == 0:
            return httpx.Response(200, json={"data": [{"id": 1}]})

        terminal_calls += 1

        if terminal_calls == 1:
            return httpx.Response(200, json={"data": []})

        return httpx.Response(200, json={"data": [{"id": 2}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        scraper = BBVAScraper(client=client)

        with pytest.raises(ValueError, match="inestable"):
            scraper.fetch_catalog()

def test_rejects_duplicate_catalog_ids():
    def handler(request):
        page = int(request.url.params["pager"])

        if page in (0, 1):
            return httpx.Response(200, json={"data": [{"id": 123}]})

        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        scraper = BBVAScraper(client=client)

        with pytest.raises(ValueError, match="duplicado"):
            scraper.fetch_catalog()

def test_complete_scrape_generates_matching_coverage(tmp_path, monkeypatch):
    from scraping.sources.bbva import scraper as scraper_module

    monkeypatch.setattr(scraper_module, "DATA_DIR", tmp_path)

    def handler(request):
        if request.url.path.endswith("/communications"):
            page = int(request.url.params["pager"])
            data = [{"id": 123}] if page == 0 else []
            return httpx.Response(200, json={"data": data})

        if request.url.path.endswith("/communication/123"):
            return httpx.Response(200, json={"data": {"id": 123, "cabecera": "Beneficio"}})

        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        scraper = BBVAScraper(client=client)
        result = scraper.scrape()

        assert result.complete
        scraper.save_raw_promotions(result.promotions)

    snapshot = tmp_path / "bbva_promotions.json"
    coverage_path = tmp_path / "bbva_coverage.json"

    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    assert coverage["snapshot_sha256"] == digest
    assert coverage["catalog_complete"] is True
    assert coverage["terminal_verified"] is True
    assert coverage["catalog_count"] == 1
    assert coverage["detail_success"] == 1

def test_allows_only_approved_missing_ids(tmp_path, monkeypatch):
    from scraping.sources.bbva import scraper as scraper_module

    monkeypatch.setattr(scraper_module, "DATA_DIR", tmp_path)

    old = [
        {"source": "bbva", "source_id": "88970"},
        {"source": "bbva", "source_id": "87657"}
    ]

    new = [
        {"source": "bbva", "source_id": "87657"}
    ]

    snapshot = tmp_path / "bbva_promotions.json"
    snapshot.write_text(json.dumps(old), encoding="utf-8")

    scraper = BBVAScraper()
    scraper.result = ScrapeResult(new, 1, [])
    scraper._limited = False
    scraper.coverage = {"catalog_complete": True}

    canonical = json.dumps(new, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    scraper._candidate_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    scraper.save_raw_promotions(new, approved_missing_ids={"88970"})

    saved = json.loads(snapshot.read_text(encoding="utf-8"))

    assert saved == new
    assert scraper.coverage["approved_missing_ids"] == ["88970"]

    backups = list(tmp_path.glob("bbva_promotions_previous_*.json"))

    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == old