import httpx

from scraping.sources.patagonia.scraper import PatagoniaScraper


def test_fetch_normal_category_urls():
    html = """
    <html>
        <body>
            <nav class="navigation">
                <a href="/ahorrosybeneficios/supermercados.html">Supermercados</a>
                <a href="/ahorrosybeneficios/gastronomia.html">Gastronomía</a>
                <a href="/on/indumentaria-y-deportes.html">Indumentaria ON</a>
            </nav>
        </body>
    </html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    categories = scraper.fetch_category_urls(
        scraper.HOME_URL,
        "/ahorrosybeneficios/",
    )

    assert categories == [
        (
            "Supermercados",
            "https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/supermercados.html",
        ),
        (
            "Gastronomía",
            "https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/gastronomia.html",
        ),
    ]


def test_fetch_on_category_urls():
    html = """
    <html>
        <body>
            <nav class="navigation">
                <a href="/on/indumentaria-y-deportes.html">Indumentaria y Deportes</a>
                <a href="/on/gastronomia.html">Gastronomía</a>
                <a href="/ahorrosybeneficios/supermercados.html">Supermercados normal</a>
            </nav>
        </body>
    </html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    categories = scraper.fetch_category_urls(
        scraper.ON_URL,
        "/on/",
    )

    assert categories == [
        (
            "Indumentaria y Deportes",
            "https://ahorrosybeneficios.bancopatagonia.com.ar/on/indumentaria-y-deportes.html",
        ),
        (
            "Gastronomía",
            "https://ahorrosybeneficios.bancopatagonia.com.ar/on/gastronomia.html",
        ),
    ]


def test_fetch_category_page_extracts_products():
    html = """
    <html>
        <body>
            <div class="product-item-info">
                <a class="product-item-link" href="/on/vans2.html">
                    Vans
                </a>
            </div>

            <div class="product-item-info">
                <a class="product-item-link" href="/on/adidas.html">
                    Adidas
                </a>
            </div>
        </body>
    </html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    items, next_url = scraper.fetch_category_page(
        "https://ahorrosybeneficios.bancopatagonia.com.ar/on/indumentaria-y-deportes.html",
        "Indumentaria y Deportes",
    )

    assert len(items) == 2

    assert items[0]["source_id"] == "vans2"
    assert items[0]["value"] == "Vans"
    assert items[0]["c"] == ["Indumentaria y Deportes"]
    assert items[0]["u"] == "https://ahorrosybeneficios.bancopatagonia.com.ar/on/vans2.html"

    assert items[1]["source_id"] == "adidas"
    assert items[1]["value"] == "Adidas"

    assert next_url is None


def test_fetch_category_page_detects_next_page():
    html = """
    <html>
        <body>
            <div class="product-item-info">
                <a class="product-item-link" href="/on/vans2.html">
                    Vans
                </a>
            </div>

            <a class="action next" href="/on/indumentaria-y-deportes.html?p=2">
                Siguiente
            </a>
        </body>
    </html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    _, next_url = scraper.fetch_category_page(
        "https://ahorrosybeneficios.bancopatagonia.com.ar/on/indumentaria-y-deportes.html",
        "Indumentaria y Deportes",
    )

    assert next_url == "https://ahorrosybeneficios.bancopatagonia.com.ar/on/indumentaria-y-deportes.html?p=2"


def test_fetch_catalog_includes_normal_and_on_promotions():
    def handler(request: httpx.Request):
        path = request.url.path

        if path == "/ahorrosybeneficios/":
            return httpx.Response(
                200,
                text="""
                <nav class="navigation">
                    <a href="/ahorrosybeneficios/supermercados.html">
                        Supermercados
                    </a>
                </nav>
                """,
            )

        if path == "/on/inicio-on":
            return httpx.Response(
                200,
                text="""
                <nav class="navigation">
                    <a href="/on/indumentaria-y-deportes.html">
                        Indumentaria y Deportes
                    </a>
                </nav>
                """,
            )

        if path == "/ahorrosybeneficios/supermercados.html":
            return httpx.Response(
                200,
                text="""
                <div class="product-item-info">
                    <a class="product-item-link" href="/ahorrosybeneficios/carrefour4.html">
                        Carrefour
                    </a>
                </div>
                """,
            )

        if path == "/on/indumentaria-y-deportes.html":
            return httpx.Response(
                200,
                text="""
                <div class="product-item-info">
                    <a class="product-item-link" href="/on/vans2.html">
                        Vans
                    </a>
                </div>
                """,
            )

        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    catalog = scraper.fetch_catalog()

    assert len(catalog) == 2

    carrefour = next(
        item
        for item in catalog
        if item["value"] == "Carrefour"
    )

    vans = next(
        item
        for item in catalog
        if item["value"] == "Vans"
    )

    assert carrefour["segment"] is None
    assert carrefour["c"] == ["Supermercados"]

    assert vans["segment"] == "on"
    assert vans["c"] == ["Indumentaria y Deportes"]


def test_fetch_catalog_paginates_on_categories():
    def handler(request: httpx.Request):
        path = request.url.path
        page = request.url.params.get("p")

        if path == "/ahorrosybeneficios/":
            return httpx.Response(
                200,
                text="<nav class='navigation'></nav>",
            )

        if path == "/on/inicio-on":
            return httpx.Response(
                200,
                text="""
                <nav class="navigation">
                    <a href="/on/indumentaria-y-deportes.html">
                        Indumentaria y Deportes
                    </a>
                </nav>
                """,
            )

        if path == "/on/indumentaria-y-deportes.html" and page is None:
            return httpx.Response(
                200,
                text="""
                <div class="product-item-info">
                    <a class="product-item-link" href="/on/vans2.html">
                        Vans
                    </a>
                </div>

                <a class="action next" href="/on/indumentaria-y-deportes.html?p=2">
                    Siguiente
                </a>
                """,
            )

        if path == "/on/indumentaria-y-deportes.html" and page == "2":
            return httpx.Response(
                200,
                text="""
                <div class="product-item-info">
                    <a class="product-item-link" href="/on/adidas.html">
                        Adidas
                    </a>
                </div>
                """,
            )

        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    catalog = scraper.fetch_catalog()

    assert len(catalog) == 2

    assert [item["value"] for item in catalog] == [
        "Vans",
        "Adidas",
    ]

    assert all(
        item["segment"] == "on"
        for item in catalog
    )


def test_fetch_promotion_detail_extracts_sku_and_content():
    html = """
    <html>
        <body>
            <main>
                <div class="product-info-main">
                    <h1>Vans</h1>

                    <div class="product attribute sku">
                        <div class="value">
                            2026_05_05_Vans_ON
                        </div>
                    </div>

                    <div>TODOS LOS JUEVES</div>
                    <div>PATAGONIA ON</div>
                    <div>15%</div>
                    <div>3 cuotas sin interés</div>

                    <img alt="Visa">
                    <img alt="Modo">
                </div>

                <div class="product attribute description">
                    Legales Patagonia ON
                </div>
            </main>
        </body>
    </html>
    """

    def handler(request: httpx.Request):
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    detail = scraper.fetch_promotion_detail(
        "https://ahorrosybeneficios.bancopatagonia.com.ar/on/vans2.html"
    )

    assert detail["sku"] == "2026_05_05_Vans_ON"
    assert detail["title"] == "Vans"

    assert "TODOS LOS JUEVES" in detail["summary_text"]
    assert "PATAGONIA ON" in detail["summary_text"]

    assert "Legales Patagonia ON" in detail["description_text"]

    assert detail["image_alts"] == [
        "Visa",
        "Modo",
    ]


def test_scrape_uses_real_sku_and_preserves_on_segment():
    def handler(request: httpx.Request):
        path = request.url.path

        if path == "/ahorrosybeneficios/":
            return httpx.Response(
                200,
                text="<nav class='navigation'></nav>",
            )

        if path == "/on/inicio-on":
            return httpx.Response(
                200,
                text="""
                <nav class="navigation">
                    <a href="/on/indumentaria-y-deportes.html">
                        Indumentaria y Deportes
                    </a>
                </nav>
                """,
            )

        if path == "/on/indumentaria-y-deportes.html":
            return httpx.Response(
                200,
                text="""
                <div class="product-item-info">
                    <a class="product-item-link" href="/on/vans2.html">
                        Vans
                    </a>
                </div>
                """,
            )

        if path == "/on/vans2.html":
            return httpx.Response(
                200,
                text="""
                <main>
                    <div class="product-info-main">
                        <h1>Vans</h1>

                        <div class="product attribute sku">
                            <div class="value">
                                2026_05_05_Vans_ON
                            </div>
                        </div>

                        <div>PATAGONIA ON</div>
                        <div>15%</div>
                    </div>
                </main>
                """,
            )

        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    result = scraper.scrape()
    promotions = result.promotions

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion["source"] == "patagonia"
    assert promotion["source_id"] == "2026_05_05_Vans_ON"

    assert promotion["catalog"]["value"] == "Vans"
    assert promotion["catalog"]["segment"] == "on"

    assert promotion["catalog"]["c"] == [
        "Indumentaria y Deportes"
    ]

    assert promotion["detail"]["sku"] == "2026_05_05_Vans_ON"

    assert "scraped_at" in promotion

def test_fetch_promotion_detail_retries_after_timeout(monkeypatch):
    attempts = 0

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            raise httpx.ConnectTimeout("timeout", request=request)

        return httpx.Response(
            200,
            text="""
            <main>
                <div class="product-info-main">
                    <h1>Vans</h1>
                </div>
            </main>
            """,
        )

    monkeypatch.setattr(
        "scraping.http_client.time.sleep",
        lambda _: None,
    )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = PatagoniaScraper(client=client)

    detail = scraper.fetch_promotion_detail(
        "https://ahorrosybeneficios.bancopatagonia.com.ar/on/vans2.html"
    )

    assert attempts == 3
    assert detail["title"] == "Vans"

def test_scrape_marks_result_as_incomplete_when_detail_fails(monkeypatch):
    scraper = PatagoniaScraper()

    monkeypatch.setattr(
        scraper,
        "fetch_catalog",
        lambda limit=None: [
            {
                "source_id": "ok",
                "u": "https://example.com/ok.html",
                "value": "OK",
                "c": [],
                "segment": None,
            },
            {
                "source_id": "failed",
                "u": "https://example.com/failed.html",
                "value": "Failed",
                "c": [],
                "segment": None,
            },
        ],
    )

    def fetch_detail(url):
        if "failed" in url:
            raise httpx.ConnectTimeout("timeout")

        return {
            "sku": "ok",
            "title": "OK",
        }

    monkeypatch.setattr(
        scraper,
        "fetch_promotion_detail",
        fetch_detail,
    )

    result = scraper.scrape()

    assert len(result.promotions) == 1
    assert result.catalog_count == 2
    assert result.failed_ids == ["failed"]
    assert result.complete is False