import httpx

from scraping.sources.bbva.scraper import BBVAScraper


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

    promotions = scraper.scrape()

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion["source"] == "bbva"
    assert promotion["source_id"] == 2
    assert promotion["detail"]["id"] == 2
    assert "scraped_at" in promotion