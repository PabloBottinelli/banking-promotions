import copy
import json
from pathlib import Path

import httpx
import pytest

from scraping.models import ScrapeResult
from scraping.sources.cuenta_dni.scraper import CuentaDNIScraper


@pytest.fixture
def raw():
    rows = json.loads((Path(__file__).parents[1] / "fixtures/cuenta_dni/official_examples.json").read_text(encoding="utf8"))
    return next(r for r in rows if r["source_id"] == "1077")


def client_for(raw, *, blank=False, duplicate=False, partial=False, pagination=False):
    def handler(request):
        if "cuentaDNI_v2.js" in request.url.path:
            return httpx.Response(200, text="getBeneficioData(); elements[i].style.display = 'none';")
        if "GetBeneficioData2" in request.url.path:
            payload = copy.deepcopy(raw["payload"])
            if partial:
                return httpx.Response(200, json={"Success": False})
            if blank:
                payload["Entity"]["Beneficio"]["titulo"] = "  "
            return httpx.Response(200, json=payload)
        if raw.get("linked_page") and str(request.url) == raw["linked_page"]["url"]:
            return httpx.Response(200, text=raw["linked_page"]["html"])
        card = '<div class="callModalCDNI BEN_filterDiv" id="campaign-' + raw["source_id"] + '">Campaign</div>'
        return httpx.Response(200, text=card * (2 if duplicate else 1) + ('<a rel="next">Next</a>' if pagination else ''))
    return httpx.Client(transport=httpx.MockTransport(handler))


def candidate(scraper, rows):
    scraper.result = ScrapeResult(rows, len(rows), [])
    scraper._candidate_digest = scraper._digest(rows)
    scraper.coverage = {"snapshot_replace_allowed": True, "requires_review": False, "safe_to_deactivate": False}


def test_candidate_scrape_no_snapshot(raw, tmp_path):
    path = tmp_path / "raw.json"
    scraper = CuentaDNIScraper(client_for(raw), path)
    result = scraper.scrape()
    assert result.complete and not path.exists()
    assert scraper.coverage["catalog_complete"] is True
    assert scraper.coverage["safe_to_deactivate"] is False
    assert "unknown" in scraper.coverage["historical_baseline"]


@pytest.mark.parametrize("problem", ["blank", "duplicate", "partial", "pagination"])
def test_invalid_live_candidates_preserve_snapshot(raw, tmp_path, problem):
    path = tmp_path / "raw.json"
    path.write_text(json.dumps([raw]), encoding="utf8")
    before = path.read_bytes()
    scraper = CuentaDNIScraper(client_for(raw, **{problem: True}), path)
    result = scraper.scrape()
    assert not result.complete
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before


def test_empty_catalog(raw, tmp_path):
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="empty")))
    scraper = CuentaDNIScraper(c, tmp_path / "raw.json")
    assert not scraper.scrape().complete


def test_marcas_cap_contradiction_requires_review(tmp_path):
    rows = json.loads((Path(__file__).parents[1] / "fixtures/cuenta_dni/official_examples.json").read_text(encoding="utf8"))
    raw = next(r for r in rows if r["source_id"] == "1063")
    scraper = CuentaDNIScraper(client_for(raw), tmp_path / "raw.json")
    assert scraper.scrape().complete
    assert any(reason.startswith("1063:") and "cap scope" in reason for reason in scraper.coverage["review_reasons"])
    assert scraper.coverage["requires_review"] is True
    assert scraper.coverage["snapshot_replace_allowed"] is False
    with pytest.raises(ValueError, match="review"):
        scraper.save_raw_promotions(scraper.result.promotions)


@pytest.mark.parametrize("replacement_ids", [["other"], []])
def test_missing_previous_ids_same_count_or_fewer(raw, tmp_path, replacement_ids):
    path = tmp_path / "raw.json"
    path.write_text(json.dumps([raw]), encoding="utf8")
    before = path.read_bytes()
    rows = []
    for identifier in replacement_ids:
        r = copy.deepcopy(raw)
        r["source_id"] = identifier
        r["payload"]["Entity"]["Beneficio"]["id"] = identifier
        rows.append(r)
    scraper = CuentaDNIScraper(output_path=path)
    candidate(scraper, rows)
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(rows)
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["add", "update"])
def test_valid_additions_updates(raw, tmp_path, change):
    path = tmp_path / "raw.json"
    path.write_text(json.dumps([raw]), encoding="utf8")
    rows = [copy.deepcopy(raw)]
    if change == "add":
        new = copy.deepcopy(raw)
        new["source_id"] = "9999"
        new["payload"]["Entity"]["Beneficio"]["id"] = 9999
        rows.append(new)
    else:
        rows[0]["payload"]["Entity"]["Beneficio"]["titulo"] = "Updated official title"
    scraper = CuentaDNIScraper(output_path=path)
    candidate(scraper, rows)
    scraper.save_raw_promotions(rows)
    assert json.loads(path.read_text(encoding="utf8")) == rows


def test_tampering_review_and_atomic_failure(raw, tmp_path, monkeypatch):
    path = tmp_path / "raw.json"
    path.write_text(json.dumps([raw]), encoding="utf8")
    before = path.read_bytes()
    scraper = CuentaDNIScraper(output_path=path)
    rows = [copy.deepcopy(raw)]
    candidate(scraper, rows)
    rows[0]["scraped_at"] = "changed"
    with pytest.raises(ValueError, match="candidate"):
        scraper.save_raw_promotions(rows)
    candidate(scraper, rows)
    scraper.coverage["requires_review"] = True
    with pytest.raises(ValueError, match="review"):
        scraper.save_raw_promotions(rows)
    scraper.coverage["requires_review"] = False
    def fail(*args):
        raise OSError("interrupted atomic replace")
    monkeypatch.setattr("scraping.sources.cuenta_dni.scraper.os.replace", fail)
    with pytest.raises(OSError):
        scraper.save_raw_promotions(rows)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["titulo", "legal"])
def test_blank_detail_cannot_pass_save(raw, tmp_path, field):
    raw["payload"]["Entity"]["Beneficio"][field] = "  "
    scraper = CuentaDNIScraper(output_path=tmp_path / "raw.json")
    candidate(scraper, [raw])
    with pytest.raises(ValueError):
        scraper.save_raw_promotions([raw])
