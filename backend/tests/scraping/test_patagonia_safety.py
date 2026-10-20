import copy
import json
from pathlib import Path

import httpx
import pytest

from scraping.sources.patagonia.scraper import PatagoniaScraper


def record(source_id="a"):
    url = PatagoniaScraper.SITE_URL + "/ahorrosybeneficios/" + source_id + ".html"
    return {"source": "patagonia", "source_id": source_id, "scraped_at": "2026-10-19T18:00:00+00:00", "catalog": {"source_id": source_id, "u": url, "value": "Shop", "c": ["Category"], "segment": None}, "detail": {"sku": source_id, "url": url, "title": "Shop", "summary_text": "20% de descuento", "description_text": "Promoción válida: 20% de descuento"}}


def prepare(tmp_path, monkeypatch, previous=("a",), current=("a",)):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps([record(i) for i in previous]), encoding="utf-8")
    scraper = PatagoniaScraper(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))), output_path=path)
    def catalog(limit=None):
        scraper.coverage = {"catalog_complete": limit is None, "limited": limit is not None, "errors": [], "categories": []}
        return [record(i)["catalog"] for i in current][:limit]
    monkeypatch.setattr(scraper, "fetch_catalog", catalog)
    monkeypatch.setattr(scraper, "fetch_promotion_detail", lambda url: record(Path(url).stem)["detail"])
    return scraper, path


@pytest.mark.parametrize("previous,current", [(("a", "b", "c"), ("a", "b")), (("a", "b"), ("a", "c"))])
def test_missing_ids_block_even_same_count(tmp_path, monkeypatch, previous, current):
    scraper, path = prepare(tmp_path, monkeypatch, previous, current)
    before = path.read_bytes()
    result = scraper.scrape()
    assert result.complete
    assert scraper.coverage["catalog_complete"]
    assert scraper.coverage["missing_previous_ids"]
    assert scraper.coverage["requires_review"]
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before


def test_valid_additions_and_same_id_updates_can_save_atomically(tmp_path, monkeypatch):
    scraper, path = prepare(tmp_path, monkeypatch, ("a",), ("a", "b"))
    before = path.read_bytes()
    result = scraper.scrape()
    assert path.read_bytes() == before  # scrape has no write side effect
    assert scraper.coverage["snapshot_replace_allowed"]
    scraper.save_raw_promotions(result.promotions)
    assert len(json.loads(path.read_bytes())) == 2
    assert scraper.coverage["safe_to_deactivate"] is False


def test_atomic_replace_failure_preserves_baseline(tmp_path, monkeypatch):
    scraper, path = prepare(tmp_path, monkeypatch)
    before = path.read_bytes()
    result = scraper.scrape()
    def fail(*args):
        raise OSError("interrupted atomic replace")
    monkeypatch.setattr("scraping.sources.patagonia.scraper.os.replace", fail)
    with pytest.raises(OSError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before
    assert list(tmp_path.glob(".patagonia-*.tmp")) == []


@pytest.mark.parametrize("case", ["limited", "mutated", "baseline_changed", "baseline_duplicate", "baseline_missing", "blank_detail"])
def test_acceptance_is_bound_to_candidate_and_valid_baseline(tmp_path, monkeypatch, case):
    scraper, path = prepare(tmp_path, monkeypatch)
    if case == "baseline_duplicate":
        path.write_text(json.dumps([record(), record()]), encoding="utf-8")
    elif case == "baseline_missing":
        path.unlink()
    elif case == "blank_detail":
        monkeypatch.setattr(scraper, "fetch_promotion_detail", lambda url: {"sku": "a", "title": " ", "summary_text": "20%", "description_text": " "})
    result = scraper.scrape(limit=1 if case == "limited" else None)
    if case == "mutated":
        result.promotions[0]["detail"]["summary_text"] = "99%"
    elif case == "baseline_changed":
        path.write_text(json.dumps([record("b")]), encoding="utf-8")
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert (path.read_bytes() if path.exists() else None) == before


def test_official_contradictions_block_snapshot(tmp_path, monkeypatch):
    scraper, path = prepare(tmp_path, monkeypatch)
    detail = record()["detail"]
    detail.update(summary_text="Del 01/10/2026 al 31/10/2026\n20%", description_text="Promoción válida desde el 02/10/2026 al 31/10/2026. 20% de descuento")
    monkeypatch.setattr(scraper, "fetch_promotion_detail", lambda url: detail)
    result = scraper.scrape()
    assert result.complete
    assert scraper.coverage["requires_review"]
    assert not scraper.coverage["snapshot_replace_allowed"]
    assert result.promotions[0]["review_reasons"]


@pytest.mark.parametrize("mode", ["empty", "cycle", "repeat", "total"])
def test_catalog_coverage_detects_empty_cycle_duplicate_and_mismatched_totals(mode):
    def handler(request):
        if request.url.path in ("/ahorrosybeneficios/", "/on/inicio-on"):
            prefix = "/on/" if "/on/" in request.url.path else "/ahorrosybeneficios/"
            return httpx.Response(200, text=f'<nav class="navigation"><a href="{prefix}cat.html">Category</a></nav>')
        prefix = "/on/" if "/on/" in request.url.path else "/ahorrosybeneficios/"
        product = f'<div class="product-item-info"><a class="product-item-link" href="{prefix}a.html">A</a></div>'
        if mode == "empty":
            return httpx.Response(200, text="<main> </main>")
        next_url = str(request.url) if mode == "cycle" else str(request.url.copy_set_param("p", "2"))
        pager = f'<a class="action next" href="{next_url}">Next</a>' if mode in ("cycle", "repeat") else ''
        total = '<p class="toolbar-amount"><span class="toolbar-number">20</span></p>' if mode == "total" else ''
        return httpx.Response(200, text=product + pager + total)
    scraper = PatagoniaScraper(client=httpx.Client(transport=httpx.MockTransport(handler)))
    scraper.fetch_catalog()
    assert scraper.coverage["errors"]
    assert scraper.coverage["catalog_complete"] is False


@pytest.mark.parametrize("status", [403, 404])
def test_permanent_http_refusals_are_not_retried(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status)
    scraper = PatagoniaScraper(client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("scraping.sources.patagonia.scraper.time.sleep", lambda seconds: pytest.fail("permanent failure retried"))
    with pytest.raises(httpx.HTTPStatusError):
        scraper._get(scraper.HOME_URL)
    assert len(calls) == 1


def test_tls_certificate_failure_is_not_retried(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", request=request)
    scraper = PatagoniaScraper(client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("scraping.sources.patagonia.scraper.time.sleep", lambda seconds: pytest.fail("certificate failure retried"))
    with pytest.raises(httpx.ConnectError):
        scraper._get(scraper.HOME_URL)


def test_transient_timeout_and_503_use_source_timeout_and_bounded_retries(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.extensions["timeout"]["connect"] == 30
        assert request.extensions["timeout"]["read"] == 45
        if len(calls) == 1:
            raise httpx.ConnectTimeout("handshake timed out", request=request)
        return httpx.Response(503 if len(calls) == 2 else 200)
    delays = []
    monkeypatch.setattr("scraping.sources.patagonia.scraper.time.sleep", delays.append)
    scraper = PatagoniaScraper(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert scraper._get(scraper.HOME_URL).status_code == 200
    assert len(calls) == 3 and delays == [1, 2]


def test_storefront_aggregation_preserves_distinct_on_and_reused_skus():
    scraper = PatagoniaScraper()
    general = record("offer")
    plus = copy.deepcopy(general)
    plus["catalog"]["segment"] = "plus"
    plus["detail"]["url"] = plus["detail"]["url"].replace("/ahorrosybeneficios/", "/plus/")
    on = copy.deepcopy(general)
    on["catalog"]["segment"] = "on"
    on["detail"]["url"] = on["detail"]["url"].replace("/ahorrosybeneficios/", "/on/")
    unrelated = copy.deepcopy(general)
    unrelated["detail"]["url"] = unrelated["detail"]["url"].replace("offer.html", "different.html")
    rows = scraper._aggregate_storefronts([plus, on, general, unrelated])
    assert len(rows) == 3
    merged = next(r for r in rows if r["catalog"]["segment"] is None and "storefront_details" in r)
    assert merged["storefront_details"][0]["catalog"]["segment"] == "plus"
    assert merged["detail"]["url"] == general["detail"]["url"]


@pytest.mark.parametrize("case", ["blank_id", "duplicate_id", "blank_legal_heading", "description_header_only", "storefront_header_only"])
def test_malformed_raw_is_rejected(case):
    scraper = PatagoniaScraper()
    records = [record()]
    if case == "blank_id":
        records[0]["source_id"] = " "
    elif case == "duplicate_id":
        records.append(copy.deepcopy(records[0]))
    elif case == "blank_legal_heading":
        records[0]["detail"]["description_text"] = " "
        records[0]["detail"]["main_text"] = "Términos y Condiciones\n \nAvailable stores are loading ..."
    elif case == "description_header_only":
        records[0]["detail"]["description_text"] = "Legales Patagonia Clásica, Plus y Singular"
        records[0]["detail"]["main_text"] = ""
    else:
        detail = {**records[0]["detail"], "description_text": "Legales Patagonia Plus Plan Sueldo"}
        records[0]["storefront_details"] = [{"detail": detail}]
    with pytest.raises(ValueError):
        scraper._validate_records(records)


@pytest.mark.parametrize("heading,storefront", [("Legales Patagonia Clásica, Plus y Singular", False), ("Patagonia Clásica Y Plus", False), ("Patagonia Plus", False), ("Patagonia Plus", True), ("Legales Patagonia Plus Plan Sueldo y Jubilados", True)])
def test_http200_legal_heading_only_cannot_reach_writer(tmp_path, monkeypatch, heading, storefront):
    scraper, path = prepare(tmp_path, monkeypatch)
    before = path.read_bytes()
    detail = record()["detail"]
    detail.update(title="Havanna", summary_text="CLASICA\nPLUS\nSINGULAR\n30%", description_text=heading, main_text="")
    if storefront:
        # Independently validate extra storefront content, without trusting a
        # nonempty primary legal body or a manually flipped coverage flag.
        candidate = record()
        candidate["storefront_details"] = [{"detail": detail}]
        scraper.coverage = {"catalog_complete": True, "snapshot_replace_allowed": True, "requires_review": False}
        with pytest.raises(ValueError):
            scraper.save_raw_promotions([candidate])
        assert path.read_bytes() == before
        return
    monkeypatch.setattr(scraper, "fetch_promotion_detail", lambda url: detail)
    monkeypatch.setattr("scraping.sources.patagonia.scraper.tempfile.NamedTemporaryFile", lambda **kwargs: pytest.fail("invalid legal body reached writer"))
    result = scraper.scrape()
    assert not result.complete and result.promotions == []
    assert scraper.coverage["requires_review"]
    assert not scraper.coverage["snapshot_replace_allowed"]
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before
