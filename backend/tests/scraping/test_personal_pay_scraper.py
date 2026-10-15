import copy
import json
from pathlib import Path

import httpx
import pytest

from scraping.sources.personal_pay.scraper import API_URL, PAGE_URL, RECHARGE_URL, TERMS_URL, PersonalPayScraper

FIXTURE = Path(__file__).parents[1] / "fixtures/personal_pay/official_examples.json"


def examples():
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [next(x for x in source if x["source_id"] == identity) for identity in ["9132", "9357"]]


def mocked_scraper(tmp_path, *, kind=None, bootstrap=True, prior=None):
    records = examples()
    if kind == "legal-conflict":
        records[1] = next(x for x in json.loads(FIXTURE.read_text(encoding="utf-8")) if x["source_id"] == "9473")
    path = tmp_path / "accepted.json"
    if prior is not None:
        path.write_text(json.dumps(prior), encoding="utf-8")
    props = {"model": {}, "onDemandProps": {
        "initialBenefits": {"data": {"benefits": [records[0]["listing"]]}},
        "initialCategories": {"data": [{"_id": 1, "name": "Salud"}]}}}
    recharge = {"model": {"cqItems": {"seo": {"metadescription": "20% de crédito extra"}}}}
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == TERMS_URL:
            data = {"model": {"cqItems": {"tycmenu": {"tycMenu": [{"title": "Niveles", "url": "/content/cms-personal-pay/ar/es/tycp/niveles", "tycModel": {"description": "Contexto de niveles."}}]}}}}
            if kind == "legal-conflict":
                data["model"]["cqItems"]["tycmenu"]["tycMenu"] = json.loads((FIXTURE.parent / "global_terms_subset.json").read_text(encoding="utf-8"))
            return httpx.Response(200, text='<script id="__NEXT_DATA__">' + json.dumps({"props": {"pageProps": data}}) + '</script>')
        if str(request.url) in (PAGE_URL, RECHARGE_URL):
            data = props if str(request.url) == PAGE_URL else recharge
            html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": data}}) + "</script>"
            return httpx.Response(200, text=html)
        if request.url.path == "/pay/api/benefits":
            cursor = int(request.url.params.get("offset", 0))
            if kind == "empty":
                batch, next_cursor = [], cursor
            elif cursor == 0:
                batch, next_cursor = [records[0]["listing"]], 100
            elif cursor == 100:
                batch, next_cursor = [records[1]["listing"]], 200
            else:
                batch, next_cursor = [], cursor
            if kind == "duplicate" and cursor == 100:
                batch = [records[0]["listing"]]
            if kind == "cursor" and batch:
                next_cursor = cursor
            if kind == "changed" and sum("/api/benefits?" in c and "category=" not in c for c in calls) > 3 and cursor == 100:
                batch = []
            if request.url.params.get("category") and kind == "extra-category":
                batch = [{"id": "unknown"}] if cursor == 0 else []
                next_cursor = 100
            return httpx.Response(200, json={"data": {"benefits": batch, "meta": {"offset": next_cursor}}})
        identity = request.url.path.split("/")[-1]
        detail = copy.deepcopy(next(x["detail"] for x in records if x["source_id"] == identity))
        if kind == "detail-error" and identity == "9357":
            return httpx.Response(404)
        if kind in ["blank-legal", "blank-title", "blank-description"] and identity == "9357":
            key = {"blank-legal": "legal", "blank-title": "title", "blank-description": "description"}[kind]
            detail[key] = " \n "
            if key == "legal":
                detail["documentTyc"] = " \n "
        return httpx.Response(200, json={"data": detail})

    return PersonalPayScraper(httpx.Client(transport=httpx.MockTransport(handler)), path,
                              allow_initial_snapshot=bootstrap), path, calls


def test_complete_cursor_exhaustion_recheck_categories_and_no_save(tmp_path):
    scraper, path, calls = mocked_scraper(tmp_path)
    result = scraper.scrape()
    assert result.complete and len(result.promotions) == 2
    assert not path.exists()
    assert scraper.coverage["catalog_complete"] is True
    assert scraper.coverage["safe_to_deactivate"] is False
    assert [p["offset"] for p in scraper.coverage["pagination"]] == [0, 100, 200]
    assert scraper.coverage["verification_pagination"] == scraper.coverage["pagination"]
    assert scraper.coverage["category_checks"][0]["count"] == 2
    assert any("category=Salud" in c for c in calls)
    scraper.save_raw_promotions(result.promotions)
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2


@pytest.mark.parametrize("kind", ["empty", "duplicate", "cursor", "changed", "extra-category", "detail-error", "blank-legal", "blank-title", "blank-description"])
def test_partial_or_blank_200_detail_cannot_replace_good_snapshot(tmp_path, kind):
    prior = examples()
    scraper, path, _ = mocked_scraper(tmp_path, kind=kind, prior=prior)
    before = path.read_bytes()
    result = scraper.scrape()
    assert not result.complete or scraper.coverage["catalog_complete"] is False
    assert scraper.coverage["snapshot_replace_allowed"] is False
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before


def test_unknown_historical_baseline_blocks_default_sync(tmp_path):
    scraper, path, _ = mocked_scraper(tmp_path, bootstrap=False)
    result = scraper.scrape()
    assert result.complete
    assert scraper.coverage["requires_review"] is True
    assert scraper.coverage["snapshot_replace_allowed"] is False
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert not path.exists()


@pytest.mark.parametrize("swap", [False, True])
def test_missing_old_ids_even_same_total_preserve_bytes(tmp_path, swap):
    former = examples()
    if not swap:
        former.append(copy.deepcopy(former[0]))
        former[-1]["source_id"] = "old-id"
        former[-1]["detail"]["id"] = "old-id"
    else:
        former[0]["source_id"] = "old-id"
        former[0]["detail"]["id"] = "old-id"
    scraper, path, _ = mocked_scraper(tmp_path, prior=former)
    before = path.read_bytes()
    result = scraper.scrape()
    assert result.complete and scraper.coverage["missing_prior_ids"] == ["old-id"]
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before


def test_malformed_baseline_is_not_treated_as_first_run(tmp_path):
    scraper, path, _ = mocked_scraper(tmp_path)
    path.write_text("{}", encoding="utf-8")
    result = scraper.scrape()
    assert result.complete and not scraper.coverage["snapshot_replace_allowed"]
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_text(encoding="utf-8") == "{}"


@pytest.mark.parametrize("addition", [False, True])
def test_legitimate_update_or_addition_allowed(tmp_path, addition):
    prior = examples()[:1] if addition else examples()
    prior[0]["detail"]["description"] = "Older accepted description"
    scraper, path, _ = mocked_scraper(tmp_path, prior=prior)
    result = scraper.scrape()
    assert scraper.coverage["snapshot_replace_allowed"]
    scraper.save_raw_promotions(result.promotions)
    assert json.loads(path.read_text(encoding="utf-8"))[0]["detail"]["description"] != "Older accepted description"


def test_candidate_tampering_and_atomic_failure_preserve_baseline(tmp_path, monkeypatch):
    scraper, path, _ = mocked_scraper(tmp_path, prior=examples())
    before = path.read_bytes()
    result = scraper.scrape()
    changed = copy.deepcopy(result.promotions)
    changed[0]["detail"]["title"] = "Tampered"
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(changed)
    def fail_replace(*args):
        raise OSError("simulated atomic replace failure")
    monkeypatch.setattr("scraping.sources.personal_pay.scraper.os.replace", fail_replace)
    with pytest.raises(OSError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before
    assert list(tmp_path.glob(".personal_pay_*.tmp")) == []


@pytest.mark.parametrize("mutate", ["blank-id", "duplicate-id", "blank-detail", "no-variant"])
def test_direct_save_revalidates_candidate(tmp_path, mutate):
    scraper, path, _ = mocked_scraper(tmp_path, prior=examples())
    before = path.read_bytes()
    result = scraper.scrape()
    if mutate == "blank-id":
        result.promotions[0]["source_id"] = " "
    elif mutate == "duplicate-id":
        result.promotions.append(copy.deepcopy(result.promotions[0]))
    elif mutate == "blank-detail":
        result.promotions[0]["detail"].update(legal="", documentTyc="")
    else:
        result.promotions[0]["detail"]["discounts"] = "unknown"
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert path.read_bytes() == before


def test_global_terms_add_plus_and_date_conflict_blocks_snapshot(tmp_path):
    scraper, path, _ = mocked_scraper(tmp_path, kind="legal-conflict")
    result = scraper.scrape()
    assert result.complete and len(result.promotions) == 3
    assert any(r.get("kind") == "legal_campaign" and r["source_id"] == "reintegro-plus" for r in result.promotions)
    assert scraper.coverage["catalog_complete"] is True
    assert scraper.coverage["unresolved_source_discrepancies"][0]["source_id"] == "9473"
    assert scraper.coverage["requires_review"] is True
    assert scraper.coverage["snapshot_replace_allowed"] is False
    assert scraper.coverage["safe_to_deactivate"] is False
    assert any(r.get("global_legal_campaign") for r in result.promotions)
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert not path.exists()


def test_unknown_new_global_campaign_fails_closed(tmp_path):
    def handle(request):
        model = {"cqItems": {"tycmenu": {"tycMenu": [{"title": "New offer", "url": "/content/cms-personal-pay/ar/es/tycp/new-offer", "tycModel": {"description": "Beneficio nuevo que debe revisarse."}}]}}}
        return httpx.Response(200, text='<script id="__NEXT_DATA__">' + json.dumps({"props": {"pageProps": {"model": model}}}) + '</script>')
    scraper = PersonalPayScraper(httpx.Client(transport=httpx.MockTransport(handle)), tmp_path / "raw.json")
    with pytest.raises(ValueError, match="Unclassified"):
        scraper._supplemental_legals([], "2026-10-15T15:00:00+00:00")
