"""MODO native API fixtures and adversarial snapshot tests. No live requests."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from scraping.sources.modo.scraper import ModoScraper

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "modo" / "cardon.json"


def detail(identifier="one"):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    d["id"] = identifier
    d["offers"][0]["id"] = identifier
    d["offers"][0]["benefit_id"] = identifier
    return d


def scraper(tmp_path, details=None, mutation=None):
    details = details or [detail()]
    def handle(request):
        path = request.url.path
        if path.endswith("/v2/banks"):
            return httpx.Response(200, json={"banks": [{"id": "6a089c91-a7d3-4199-a578-2132a3733f69", "name": "Macro"}]})
        if path.endswith("/categories"):
            return httpx.Response(200, json=[{"id": 3, "title": "Indumentaria"}])
        if path.endswith("/v2/filter"):
            number = int(request.url.params["page"])
            payload = {"pagination": {"page": number, "limit": 100, "total_results": len(details), "total_pages": 1},
                       "cards": [{"card_id": d["id"], "benefit": {"id": d["id"]}, "offer": {"id": d["id"]}, "calculated_status": "RUNNING"} for d in details] if number == 1 else []}
            assert request.url.params["fcalcstatus"] == "RUNNING"
            return httpx.Response(200, json=mutation(payload) if mutation else payload)
        identifier = path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=next(d for d in details if d["id"] == identifier))
    return ModoScraper(httpx.Client(transport=httpx.MockTransport(handle)), tmp_path / "raw.json", request_delay=0)


def test_candidate_does_not_write_and_atomic_save(tmp_path):
    s = scraper(tmp_path)
    result = s.scrape()
    assert result.complete
    assert not s.output_path.exists()
    assert s.coverage["catalog_complete"] is True
    assert s.coverage["safe_to_deactivate"] is False
    s.save_raw_promotions(result.promotions)
    assert json.loads(s.output_path.read_text(encoding="utf-8")) == result.promotions


def test_terminal_zero_counts_are_the_official_api_convention(tmp_path):
    def mutate(p):
        if not p["cards"]:
            p["pagination"].update(total_results=0, total_pages=0)
        return p
    assert scraper(tmp_path, mutation=mutate).scrape().complete


@pytest.mark.parametrize("state", ["NEXT_FOR_PRODUCT", "FINISHED_FOR_PRODUCT"])
def test_user_scope_rejects_nonrunning_cards(tmp_path, state):
    def mutate(p):
        for card in p["cards"]:
            card["calculated_status"] = state
        return p
    s = scraper(tmp_path, mutation=mutate)
    assert not s.scrape().complete
    assert s.coverage["snapshot_replace_allowed"] is False


def test_get_the_look_legal_engine_conflict_blocks_isolated_snapshot(tmp_path):
    d = json.loads((FIXTURE.parent / "get_the_look.json").read_text(encoding="utf-8"))
    s = scraper(tmp_path, [d])
    result = s.scrape()
    assert result.complete
    assert s.coverage["requires_review"] is True
    assert len(s.coverage["legal_engine_conflicts"][d["id"]]) == 3
    with pytest.raises(ValueError):
        s.save_raw_promotions(result.promotions)


@pytest.mark.parametrize("name", ["tiendabna_motos", "macro_todos_pagos"])
def test_official_date_and_cap_conflicts_block_isolated_snapshot(tmp_path, name):
    old = baseline(tmp_path)
    d = json.loads((FIXTURE.parent / (name + ".json")).read_text(encoding="utf-8"))
    s = scraper(tmp_path, [d])
    # Use a distinct target: the conflict alone must refuse acceptance even with no baseline.
    s.output_path = tmp_path / "new.json"
    result = s.scrape()
    assert result.complete and s.coverage["catalog_complete"] is True
    assert s.coverage["requires_review"] is True
    assert s.coverage["snapshot_replace_allowed"] is False
    assert s.coverage["legal_engine_conflicts"][d["id"]]
    with pytest.raises(ValueError):
        s.save_raw_promotions(result.promotions)
    assert not s.output_path.exists()
    assert (tmp_path / "raw.json").read_bytes() == old


def test_conflicting_publication_without_legal_support_requires_review(tmp_path):
    d = detail()
    d["offers"][0]["outcomes"]["cashback"]["amount"] = 10
    d["terms_and_conditions"] = None
    d["details"]["faq"] = None
    s = scraper(tmp_path, [d])
    result = s.scrape()
    assert result.complete
    assert s.coverage["catalog_complete"] is True
    assert s.coverage["requires_review"] is True
    assert s.coverage["unresolved_publication_rate_conflict_ids"] == ["one"]
    with pytest.raises(ValueError):
        s.save_raw_promotions(result.promotions)


@pytest.mark.parametrize("field,value", [("name", "  "), ("terms_and_conditions", "<p><br></p>"), ("offers", [])])
def test_http_200_blank_essential_nodes_block(tmp_path, field, value):
    d = detail()
    d[field] = value
    s = scraper(tmp_path, [d])
    assert not s.scrape().complete
    with pytest.raises(ValueError):
        s.save_raw_promotions(s.result.promotions)
    assert not s.output_path.exists()


@pytest.mark.parametrize("mutation", [
    lambda p: {**p, "pagination": {**p["pagination"], "total_results": 101}},
    lambda p: {**p, "cards": p["cards"] * 2},
    lambda p: {**p, "pagination": {**p["pagination"], "page": 55}},
])
def test_pagination_and_duplicate_fail_closed(tmp_path, mutation):
    s = scraper(tmp_path, mutation=mutation)
    assert not s.scrape().complete
    assert s.coverage["snapshot_replace_allowed"] is False


def baseline(tmp_path):
    s = scraper(tmp_path, [detail("a"), detail("b")])
    result = s.scrape()
    s.save_raw_promotions(result.promotions)
    return s.output_path.read_bytes()


@pytest.mark.parametrize("ids", [["a"], ["a", "c"]])
def test_missing_prior_ids_even_same_count_reject(tmp_path, ids):
    old = baseline(tmp_path)
    s = scraper(tmp_path, [detail(i) for i in ids])
    result = s.scrape()
    assert result.complete
    assert s.coverage["requires_review"] is True
    with pytest.raises(ValueError):
        s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes() == old


def test_addition_and_same_id_update_allowed(tmp_path):
    baseline(tmp_path)
    d = detail("a")
    d["name"] = "Updated title"
    s = scraper(tmp_path, [d, detail("b"), detail("c")])
    result = s.scrape()
    assert s.coverage["snapshot_replace_allowed"]
    s.save_raw_promotions(result.promotions)
    assert len(json.loads(s.output_path.read_text(encoding="utf-8"))) == 3


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(terms_and_conditions=None),
    lambda d: d["details"].update(faq=None),
])
def test_lost_prior_detail_blocks(tmp_path, mutation):
    old = baseline(tmp_path)
    d = detail("a")
    mutation(d)
    s = scraper(tmp_path, [d, detail("b")])
    result = s.scrape()
    assert s.coverage["lost_detail_ids"] == ["a"]
    with pytest.raises(ValueError):
        s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes() == old


def test_candidate_tampering_and_atomic_failure_preserve_bytes(tmp_path, monkeypatch):
    old = baseline(tmp_path)
    s = scraper(tmp_path, [detail("a"), detail("b")])
    result = s.scrape()
    changed = copy.deepcopy(result.promotions)
    changed[0]["detail"]["name"] = "tampered"
    with pytest.raises(ValueError):
        s.save_raw_promotions(changed)
    monkeypatch.setattr("scraping.sources.modo.scraper.os.replace", lambda *_: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        s.save_raw_promotions(result.promotions)
    assert s.output_path.read_bytes() == old
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("value", [None, ""])
def test_source_explicitly_missing_optional_legal_is_retained(tmp_path, value):
    d = detail()
    d["terms_and_conditions"] = value
    s = scraper(tmp_path, [d])
    assert s.scrape().complete
    assert s.result.promotions[0]["detail"]["terms_and_conditions"] == value


@pytest.mark.parametrize("ids", [["a", "a"], [" "]])
def test_raw_identity_validation(tmp_path, ids):
    s = scraper(tmp_path, [detail(i) for i in ids])
    assert not s.scrape().complete
