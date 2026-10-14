import json

import httpx
import pytest

from scraping.sources.buepp.scraper import BueppScraper


def scraper(tmp_path, mode="complete"):
    def handler(request):
        if request.url.path.endswith("/filter"):
            payload = json.loads(request.content)
            assert payload["rubros"] == [0] and payload["medios_de_pago"] == [0]
            assert payload["latitud"] is None and payload["zona"] is None
            page = payload["numero_pagina"]
            items = [{"idBeneficio":1}] if page == 1 else []
            if mode == "empty":
                return httpx.Response(200,json={"cantidadTotalBeneficios":0,"beneficios":[]})
            if mode == "partial":
                return httpx.Response(200,json={"cantidadTotalBeneficios":2,"beneficios":items})
            if mode == "duplicate":
                items = [{"idBeneficio":1},{"idBeneficio":1}]
            return httpx.Response(200,json={"cantidadTotalBeneficios":1,"beneficios":items})
        if mode == "detail-error":
            return httpx.Response(404)
        return httpx.Response(200,json={"beneficio":{"id":1,"legales":"Oferta legal"},"googleMapsKey":"not-promotion-data"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BueppScraper(client=client,output_path=tmp_path / "buepp_promotions.json")


def test_complete_boundary_atomic_snapshot(tmp_path):
    s = scraper(tmp_path)
    r = s.scrape()
    assert r.complete and r.catalog_count == 1 and len(r.promotions) == 1
    assert s.coverage["pagination"] == {
        "pages_fetched": 2,
        "terminal_page_empty": True,
    }

    assert "pages" not in s.coverage
    assert "googleMapsKey" not in r.promotions[0]["detail"]
    assert s.coverage["safe_to_deactivate"] is False
    s.save_raw_promotions(r.promotions)
    coverage_path = s.output_path.with_name("buepp_coverage.json")

    saved_coverage = json.loads(
        coverage_path.read_text(encoding="utf-8")
    )

    assert saved_coverage["pagination"]["terminal_page_empty"] is True
    assert "pages" not in saved_coverage
    assert json.loads(s.output_path.read_text())[0]["source_id"] == "1"
    assert "+00:00" in r.promotions[0]["scraped_at"]


@pytest.mark.parametrize("mode",["empty","partial","duplicate","detail-error"])
def test_incomplete_preserves_previous_snapshot(tmp_path,mode):
    s = scraper(tmp_path,mode)
    s.output_path.write_text('[{"previous":"good"}]')
    r = s.scrape()
    assert not r.complete and r.failed_ids
    with pytest.raises(ValueError,match="verified complete"):
        s.save_raw_promotions(r.promotions)
    assert json.loads(s.output_path.read_text()) == [{"previous":"good"}]


def test_anomalous_decline_is_blocked(tmp_path):
    s = scraper(tmp_path)
    s.output_path.write_text(json.dumps([{}, {}, {}]))
    r = s.scrape()
    assert r.complete
    with pytest.raises(ValueError,match="Severe catalog decline"):
        s.save_raw_promotions(r.promotions)


def test_save_without_verified_scrape_is_blocked(tmp_path):
    s = scraper(tmp_path)
    with pytest.raises(ValueError):
        s.save_raw_promotions([])
