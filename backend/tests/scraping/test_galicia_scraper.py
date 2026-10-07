import httpx

from scraping.sources.galicia.scraper import GaliciaScraper

def test_fetch_promotion_detail():
    def handler(request: httpx.Request):
        assert request.url.path.endswith(
            "/idPromocion/178932"
        )

        return httpx.Response(
            200,
            json={
                "data": {
                    "id": 178932,
                    "marca": {
                        "nombre": "Starbucks"
                    },
                }
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler)
    )

    scraper = GaliciaScraper(client=client)

    detail = scraper.fetch_promotion_detail(178932)

    assert detail["id"] == 178932
    assert detail["marca"]["nombre"] == "Starbucks"


def test_fetch_catalog_paginates():
    def handler(request: httpx.Request):
        page = int(request.url.params["page"])

        if page == 1:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "list": [
                            {"id": 1},
                            {"id": 2},
                        ],
                        "totalSize": 3,
                    }
                },
            )

        return httpx.Response(
            200,
            json={
                "data": {
                    "list": [
                        {"id": 3},
                    ],
                    "totalSize": 3,
                }
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler)
    )

    scraper = GaliciaScraper(
        page_size=2,
        client=client,
    )

    catalog = scraper.fetch_catalog()

    assert len(catalog) == 3
    assert [promo["id"] for promo in catalog] == [
        1,
        2,
        3,
    ]


def test_scrape_continues_when_detail_fails():
    def handler(request: httpx.Request):
        path = request.url.path

        if path.endswith("/promociones/catalogo"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "list": [
                            {"id": 1},
                            {"id": 2},
                        ],
                        "totalSize": 2,
                    }
                },
            )

        if path.endswith("/idPromocion/1"):
            return httpx.Response(
                500,
                json={"error": "Server error"},
            )

        if path.endswith("/idPromocion/2"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": 2,
                    }
                },
            )

        return httpx.Response(404)

    client = httpx.Client(
        transport=httpx.MockTransport(handler)
    )

    scraper = GaliciaScraper(client=client)

    result = scraper.scrape()
    promotions = result.promotions

    assert len(promotions) == 1
    assert result.catalog_count == 2
    assert result.failed_ids == ["1"]
    assert result.complete is False

    promotion = promotions[0]

    assert promotion["source"] == "galicia"
    assert promotion["source_id"] == 2
    assert promotion["detail"]["id"] == 2
    assert "scraped_at" in promotion