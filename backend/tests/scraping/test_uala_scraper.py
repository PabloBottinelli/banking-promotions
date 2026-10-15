"""Official SSR excerpts plus synthetic transport/acceptance failures."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from scraping.sources.uala.scraper import UalaScraper, validate_records

FIXTURE = Path(__file__).parents[1] / "fixtures/uala/official_promotions.json"


def records():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def html(props):
    return '<script src="/_next/static/chunks/catalog.js"></script><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": props}}) + '</script>'


def scraper(tmp_path, data=None, *, blank=False, pagination=True):
    data = copy.deepcopy(records() if data is None else data)
    def handle(request):
        path = request.url.path
        if path.endswith("catalog.js"):
            code = 'l.slice(0,t).map(e=>e);onClick:()=>v(e=>e+9);"Cargar m\\xe1s promociones"' if pagination else 'changed UI'
            return httpx.Response(200, text=code)
        if path == "/promociones":
            return httpx.Response(200, text=html({"page": {"components": [{"promociones": [r["catalog"] for r in data]}]}}))
        raw = next(r for r in data if r["source_url"].endswith(path))
        detail = copy.deepcopy(raw["detail"])
        if blank: detail["specs"][0]["legalDisclaimer"] = "   "
        return httpx.Response(200, text=html({"promotion": detail}))
    return UalaScraper(httpx.Client(transport=httpx.MockTransport(handle)), tmp_path / "raw.json")


def test_complete_without_side_effect_then_atomic_save(tmp_path):
    s = scraper(tmp_path)
    result = s.scrape()
    assert result.complete and len(result.promotions) == 11
    assert not s.output_path.exists()
    assert s.coverage["catalog_complete"] is True
    assert s.coverage["safe_to_deactivate"] is False
    s.save_raw_promotions(result.promotions)
    assert len(json.loads(s.output_path.read_text(encoding="utf-8"))) == 11


@pytest.mark.parametrize("kwargs", [{"blank": True}, {"pagination": False}, {"data": []}])
def test_incomplete_preserves_valid_baseline(tmp_path, kwargs):
    s = scraper(tmp_path, **kwargs)
    previous = json.dumps(records(), ensure_ascii=False).encode("utf-8")
    s.output_path.write_bytes(previous)
    result = s.scrape()
    assert not result.complete
    with pytest.raises(ValueError): s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes() == previous


@pytest.mark.parametrize("same_count", [False, True])
def test_missing_or_substituted_historical_id_blocks_snapshot(tmp_path, same_count):
    old = records()
    incoming = old[1:]
    if same_count:
        extra = copy.deepcopy(old[0])
        extra["source_id"] = extra["catalog"]["sys"]["id"] = extra["detail"]["id"] = "new-campaign"
        extra["source_url"] += "-new"
        extra["catalog"]["fields"]["urlDeLaPromocion"] += "-new"
        incoming.append(extra)
    s = scraper(tmp_path, incoming)
    baseline = json.dumps(old).encode()
    s.output_path.write_bytes(baseline)
    result = s.scrape()
    assert result.complete
    assert s.coverage["requires_review"] is True
    assert s.coverage["snapshot_replace_allowed"] is False
    with pytest.raises(ValueError): s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes() == baseline


def test_updates_and_additions_accepted(tmp_path):
    data = records()
    s = scraper(tmp_path, data)
    old = copy.deepcopy(data[:-1])
    old[0]["detail"]["specs"][0]["description"] = "Earlier copy"
    s.output_path.write_text(json.dumps(old), encoding="utf-8")
    result = s.scrape()
    s.save_raw_promotions(result.promotions)
    assert len(json.loads(s.output_path.read_text(encoding="utf-8"))) == 11


@pytest.mark.parametrize("substitute", [False, True])
@pytest.mark.parametrize("baseline_stage", ["scrape", "save"])
def test_historical_sportclub_variant_loss_or_replacement(tmp_path, substitute, baseline_stage):
    """QA-001: same 11 campaigns must not hide lost/replaced Plus spec identity."""
    old = records()
    incoming = copy.deepcopy(old)
    sport = next(r for r in incoming if r["source_id"] == "6CReo7313gFFfYZ1SzdZ2j")
    old_plus = "7nlFAU5cWk0cMRVO5ecm6U"
    if substitute:
        sport["detail"]["specs"][1]["id"] = "new-plus-spec"
        sport["catalog"]["fields"]["PromotionSpecs"][1]["sys"]["id"] = "new-plus-spec"
    else:
        sport["detail"]["specs"].pop()
        sport["catalog"]["fields"]["PromotionSpecs"].pop()
    s = scraper(tmp_path, incoming)
    baseline = json.dumps(old, ensure_ascii=False).encode("utf-8")
    if baseline_stage == "scrape": s.output_path.write_bytes(baseline)
    result = s.scrape()
    assert result.complete and len(result.promotions) == 11
    if baseline_stage == "scrape":
        assert s.coverage["catalog_complete"] is True
        assert s.coverage["requires_review"] is True
        assert s.coverage["snapshot_replace_allowed"] is False
        assert s.coverage["missing_previous_ids"] == []
        assert s.coverage["missing_previous_variant_ids"] == [sport["source_id"] + ":" + old_plus]
    else:
        # History may appear/change after capture; save must independently recheck it.
        assert s.coverage["snapshot_replace_allowed"] is True
        s.output_path.write_bytes(baseline)
    with pytest.raises(ValueError): s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes() == baseline
    assert s.coverage["snapshot_replace_allowed"] is False
    assert s.coverage["requires_review"] is True
    assert s.coverage["missing_previous_variant_ids"] == [sport["source_id"] + ":" + old_plus]


def test_existing_variant_copy_date_changes_and_new_spec_accepted(tmp_path):
    old = records()
    incoming = copy.deepcopy(old)
    sport = next(r for r in incoming if r["source_id"] == "6CReo7313gFFfYZ1SzdZ2j")
    spec = sport["detail"]["specs"][0]
    spec["title"] = "Presentación actualizada"
    spec["date"] = "31 de agosto 2027"
    spec["legalDisclaimer"] = spec["legalDisclaimer"].replace("31/07/2027", "31/08/2027")
    sport["catalog"]["fields"]["PromotionSpecs"][0]["fields"]["promotionLegal"] = spec["legalDisclaimer"]
    new_spec = copy.deepcopy(sport["detail"]["specs"][1])
    new_spec["id"] = "additional-plan-spec"
    sport["detail"]["specs"].append(new_spec)
    new_catalog_spec = copy.deepcopy(sport["catalog"]["fields"]["PromotionSpecs"][1])
    new_catalog_spec["sys"]["id"] = new_spec["id"]
    sport["catalog"]["fields"]["PromotionSpecs"].append(new_catalog_spec)
    s = scraper(tmp_path, incoming)
    s.output_path.write_text(json.dumps(old), encoding="utf-8")
    result = s.scrape()
    assert result.complete and s.coverage["snapshot_replace_allowed"] is True
    assert s.coverage["requires_review"] is False
    assert s.coverage["missing_previous_variant_ids"] == []
    s.save_raw_promotions(result.promotions)
    saved = json.loads(s.output_path.read_text(encoding="utf-8"))
    assert sum(len(r["detail"]["specs"]) for r in saved) == 13


def test_atomic_failure_preserves_prior_bytes(tmp_path, monkeypatch):
    s = scraper(tmp_path)
    before = json.dumps(records()).encode()
    s.output_path.write_bytes(before)
    result = s.scrape()
    def reject(*args): raise OSError("interrupted replacement")
    monkeypatch.setattr("scraping.sources.uala.scraper.os.replace", reject)
    with pytest.raises(OSError): s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_candidate_tampering_is_rejected(tmp_path):
    s = scraper(tmp_path)
    result = s.scrape()
    result.promotions[0]["detail"]["specs"][0]["description"] = "modified"
    with pytest.raises(ValueError, match="changed"): s.save_raw_promotions(result.promotions)
    assert not s.output_path.exists()


@pytest.mark.parametrize("mutation", ["duplicate", "blank", "legal", "title", "spec"])
def test_raw_identity_and_essential_content(mutation):
    data = records()
    if mutation == "duplicate": data.append(copy.deepcopy(data[0]))
    if mutation == "blank": data[0]["source_id"] = " "
    if mutation == "legal": data[0]["detail"]["specs"][0]["legalDisclaimer"] = " "
    if mutation == "title": data[0]["detail"]["specs"][0]["title"] = " "
    if mutation == "spec": data[0]["detail"]["specs"] = []
    with pytest.raises(ValueError): validate_records(data)
