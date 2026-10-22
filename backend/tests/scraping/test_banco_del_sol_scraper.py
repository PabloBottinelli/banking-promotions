import json

import httpx
import pytest

from scraping.sources.banco_del_sol.scraper import BancoDelSolScraper


_FIRST_PAGE_IDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_COMPLETE_IDS = _FIRST_PAGE_IDS + ("ten",)


def _page(slugs, wrapper='id="id-productos-vigentes"'):
    cards = "".join(f'<div><a class="card_link" href="/beneficios/{slug}" data-inicio="October 13, 2026">{slug}</a></div>' for slug in slugs)
    return f'<section {wrapper}><div class="collection-list">{cards}</div></section>'


def _detail(title):
    return f'<main><h1>{title}</h1><p class="text-size-small text-align-left">Beneficio legal de {title}</p></main>'


def _scraper(tmp_path, states, failed_detail=None):
    def handler(request):
        slug = request.url.path.rsplit("/", 1)[-1]
        if slug == failed_detail:
            return httpx.Response(404)
        return httpx.Response(200, text=_detail(slug))

    return BancoDelSolScraper(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        output_path=tmp_path / "banco_del_sol_promotions.json",
        catalog_states=lambda: iter(states),
    )


@pytest.mark.parametrize("counts", [(9, 10), (9, 18), (9, 18, 20)])
def test_complete_browser_states_and_atomic_snapshot(tmp_path, counts):
    ids = _COMPLETE_IDS + tuple(f"promo-{n}" for n in range(10, counts[-1]))
    states = [(_page(ids[:count]), index < len(counts) - 1)
              for index, count in enumerate(counts)]
    scraper = _scraper(tmp_path, states)
    result = scraper.scrape()
    assert result.complete and scraper.coverage["catalog_complete"]
    assert [p["source_id"] for p in result.promotions] == list(ids)
    assert scraper.coverage["pagination"]["terminal_verified"] is True
    assert scraper.coverage["snapshot_replace_allowed"] is True
    assert not scraper.output_path.exists()
    scraper.save_raw_promotions(result.promotions)
    saved = json.loads(scraper.output_path.read_text(encoding="utf-8"))
    assert saved[0]["detail"]["terms"] == "Beneficio legal de one"
    coverage = json.loads(scraper.output_path.with_name("banco_del_sol_coverage.json").read_text(encoding="utf-8"))
    assert coverage["pagination"]["cumulative_counts"] == list(counts)
    assert coverage["catalog_complete"] is True
    assert "html" not in coverage


@pytest.mark.parametrize("states,failed_detail,error", [
    pytest.param([(_page([]), False)], None, "vacía", id="empty-catalog"),
    pytest.param([(_page(_FIRST_PAGE_IDS), True),
                  (_page(_FIRST_PAGE_IDS + ("two",)), False)],
                 None, "IDs repetidos", id="duplicate-id"),
    pytest.param([(_page(_FIRST_PAGE_IDS), True), (_page(_FIRST_PAGE_IDS), False)],
                 None, "lote nuevo y estable", id="no-growth"),
    pytest.param([(_page(["one", "two"]), False)],
                 None, "no verificable: [2]", id="short-single-state"),
    pytest.param([(_page(["one", "two"]), True),
                  (_page(["one", "two", "three", "four"]), False)],
                 None, "no verificable: [2, 4]", id="short-first-load"),
    pytest.param([(_page(_FIRST_PAGE_IDS), True)],
                 None, "sin límite verificado", id="missing-terminal-state"),
    pytest.param([(_page(_FIRST_PAGE_IDS), True), (_page(_COMPLETE_IDS), False)],
                 "ten", "ten:", id="detail-http-error"),
    pytest.param([('<section id="changed"></section>', False)],
                 None, "colección oficial", id="missing-current-section"),
    pytest.param([(_page(_FIRST_PAGE_IDS), False)],
                 None, "no verificable: [9]", id="unverified-single-full-load"),
    pytest.param([(_page(_FIRST_PAGE_IDS), True),
                  (_page(_COMPLETE_IDS + tuple(f"extra-{n}" for n in range(9))), False)],
                 None, "no verificable: [9, 19]", id="oversized-next-load"),
    pytest.param([(_page(_COMPLETE_IDS), True),
                  (_page(_COMPLETE_IDS + ("eleven",)), False)],
                 None, "no verificable: [10, 11]", id="oversized-first-load"),
    pytest.param([(_page(_FIRST_PAGE_IDS), True),
                  (_page(("replacement",) + _COMPLETE_IDS[1:]), False)],
                 None, "lote nuevo y estable", id="changed-prefix"),
    pytest.param([(_page(_FIRST_PAGE_IDS), True),
                  (_page(tuple(reversed(_FIRST_PAGE_IDS)) + ("ten",)), False)],
                 None, "lote nuevo y estable", id="reordered-prefix"),
    pytest.param([(_page(["one", "two", "three"]), True),
                  (_page(["one", "two", "three", "four"]), False)],
                 None, "no verificable: [3, 4]", id="former-short-positive"),
    pytest.param([(_page(["one", "two"]), True),
                  (_page(["one", "two", "three"]), False)],
                 None, "no verificable: [2, 3]", id="former-short-helper"),
])
def test_partial_or_unverifiable_catalog_never_replaces_snapshot(tmp_path, states, failed_detail, error):
    scraper = _scraper(tmp_path, states, failed_detail)
    original = _baseline(scraper, ("one",))
    result = scraper.scrape()
    assert not scraper.coverage["catalog_complete"]
    assert not result.complete
    assert any(error in failure for failure in result.failed_ids)
    assert scraper.coverage["snapshot_replace_allowed"] is False
    if failed_detail:
        assert result.catalog_count == 10 and len(result.promotions) == 9
        assert len(result.failed_ids) == 1
        assert scraper.coverage["pagination"]["terminal_verified"] is True
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == original


def test_html_variations_keep_current_section_boundary():
    html = '<div id="id-productos-no-vigentes"><a class="card_link" href="/beneficios/old">Old</a></div>'
    html += _page(["current"], wrapper='class="changed" id="id-productos-vigentes"')
    assert [card["slug"] for card in BancoDelSolScraper._active_cards(html)] == ["current"]


def test_truncated_short_last_page_does_not_replace_previous_snapshot(tmp_path):
    old_ids = [f"promo-{n}" for n in range(65)]
    new_ids = old_ids[:56]
    states = [(_page(new_ids[:n]), n != 56) for n in [9, 18, 27, 36, 45, 54, 56]]
    scraper = _scraper(tmp_path, states)
    original = _baseline(scraper, old_ids)

    result = scraper.scrape()

    assert result.catalog_count == 56
    assert len(result.promotions) == 56
    assert result.complete
    assert result.failed_ids == []
    assert scraper.coverage["catalog_complete"] is True
    assert scraper.coverage["snapshot_replace_allowed"] is False
    assert scraper.coverage["requires_review"] is True
    assert scraper.coverage["pagination"]["terminal_verified"] is True
    assert scraper.coverage["snapshot_comparison"]["missing_ids"] == sorted(old_ids[56:])
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == original


def test_adding_promotions_without_losing_old_ids_is_allowed(tmp_path):
    scraper = _complete_scraper(tmp_path)
    _baseline(scraper, _FIRST_PAGE_IDS)

    result = scraper.scrape()
    assert result.complete
    assert scraper.coverage["snapshot_comparison"]["missing_ids"] == []
    assert scraper.coverage["snapshot_comparison"]["new_ids"] == ["ten"]
    scraper.save_raw_promotions(result.promotions)
    assert len(json.loads(scraper.output_path.read_text(encoding="utf-8"))) == 10


def _complete_scraper(tmp_path):
    return _scraper(tmp_path, [(_page(_FIRST_PAGE_IDS), True),
                               (_page(_COMPLETE_IDS), False)])


def _baseline(scraper, ids=_COMPLETE_IDS):
    original = json.dumps([{"source_id": slug, "detail": {"title": "Anterior",
                          "terms": "Texto legal anterior"}} for slug in ids])
    scraper.output_path.write_text(original, encoding="utf-8")
    return original


@pytest.mark.parametrize("title,terms", [
    ("", "Legal"), ("Título", ""), (" \n\t\u00a0 ", "Legal"),
    ("Título", " \n\t\u00a0 "), ("<span> </span>", "Legal"),
    ("Título", "<span> </span>"), ("Título", '&quot; &quot;'),
])
def test_http_200_with_empty_detail_is_incomplete_and_preserves_snapshot(tmp_path, title, terms):
    scraper = _complete_scraper(tmp_path)
    original = _baseline(scraper)
    html = f'<main><h1>{title}</h1><p class="text-size-small text-align-left">{terms}</p></main>'
    scraper.client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=html if request.url.path.endswith("/two") else _detail("Válido"))))
    result = scraper.scrape()
    assert result.catalog_count == 10 and len(result.promotions) == 9
    assert not result.complete
    assert len(result.failed_ids) == 1 and result.failed_ids[0].startswith("two:")
    assert scraper.coverage["pagination"]["terminal_verified"] is True
    assert scraper.coverage["catalog_complete"] is False
    assert scraper.coverage["snapshot_replace_allowed"] is False
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == original


def test_content_update_keeps_ids_and_can_replace(tmp_path):
    scraper = _complete_scraper(tmp_path)
    _baseline(scraper)
    result = scraper.scrape()
    assert result.complete
    assert scraper.coverage["snapshot_replace_allowed"] is True
    assert scraper.coverage["requires_review"] is False
    assert scraper.coverage["snapshot_comparison"]["new_ids"] == []
    scraper.save_raw_promotions(result.promotions)
    saved = json.loads(scraper.output_path.read_text(encoding="utf-8"))
    assert saved[0]["detail"]["terms"] == "Beneficio legal de one"


@pytest.mark.parametrize("invalid", [
    'not json', '{}', '[]', '[null]', '[{"prior":"valid"}]',
    '[{"source_id":" "}]', '[{"source_id":1}]',
    '[{"source_id":"one"},{"source_id":"one"}]',
])
def test_invalid_baseline_blocks_replacement_without_faking_scrape_errors(tmp_path, invalid):
    scraper = _complete_scraper(tmp_path)
    scraper.output_path.write_text(invalid, encoding="utf-8")
    result = scraper.scrape()
    assert result.complete and not result.failed_ids
    assert scraper.coverage["catalog_complete"] is True
    assert scraper.coverage["snapshot_replace_allowed"] is False
    assert scraper.coverage["requires_review"] is True
    assert scraper.coverage["snapshot_comparison"]["errors"]
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == invalid


@pytest.mark.parametrize("mutation", ["remove", "duplicate", "blank_id", "empty_title", "empty_terms", "content"])
def test_in_place_candidate_mutation_cannot_bypass_gate(tmp_path, mutation):
    scraper = _complete_scraper(tmp_path)
    original = _baseline(scraper)
    result = scraper.scrape()
    assert result.complete and scraper.coverage["snapshot_replace_allowed"] is True
    if mutation == "remove":
        result.promotions.pop()
    elif mutation == "duplicate":
        result.promotions[0]["source_id"] = "two"
    elif mutation == "blank_id":
        result.promotions[0]["source_id"] = " "
    else:
        field = "title" if mutation == "empty_title" else "terms"
        result.promotions[0]["detail"][field] = "changed" if mutation == "content" else ""
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("late_baseline", [
    '[{"source_id":"one"},{"source_id":"new-previous-id"}]', 'broken json',
])
def test_baseline_change_after_scrape_is_rechecked(tmp_path, late_baseline):
    scraper = _complete_scraper(tmp_path)
    _baseline(scraper)
    result = scraper.scrape()
    assert result.complete and scraper.coverage["snapshot_replace_allowed"] is True
    scraper.output_path.write_text(late_baseline, encoding="utf-8")
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == late_baseline
    assert scraper.coverage["snapshot_replace_allowed"] is False
    assert scraper.coverage["requires_review"] is True


def test_same_count_with_replaced_id_requires_review(tmp_path):
    scraper = _complete_scraper(tmp_path)
    original = _baseline(scraper, _FIRST_PAGE_IDS + ("removed",))
    result = scraper.scrape()
    assert result.complete
    assert scraper.coverage["catalog_complete"] is True
    assert result.catalog_count == scraper.coverage["snapshot_comparison"]["previous_count"] == 10
    assert scraper.coverage["snapshot_comparison"]["missing_ids"] == ["removed"]
    assert scraper.coverage["snapshot_comparison"]["new_ids"] == ["ten"]
    assert scraper.coverage["snapshot_replace_allowed"] is False
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == original


def test_baseline_rechecked_after_raw_serialization(tmp_path, monkeypatch):
    scraper = _complete_scraper(tmp_path)
    _baseline(scraper)
    result = scraper.scrape()
    assert result.complete and scraper.coverage["snapshot_replace_allowed"] is True
    late_baseline = '[{"source_id":"added-by-other-process"}]'
    real_dump = json.dump

    def dump_then_change_baseline(data, file, **kwargs):
        real_dump(data, file, **kwargs)
        if data is result.promotions:
            scraper.output_path.write_text(late_baseline, encoding="utf-8")

    monkeypatch.setattr(json, "dump", dump_then_change_baseline)
    with pytest.raises(ValueError):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == late_baseline
    assert scraper.coverage["snapshot_replace_allowed"] is False
    assert scraper.coverage["requires_review"] is True
    assert sorted(p.name for p in tmp_path.iterdir()) == ["banco_del_sol_coverage.json", "banco_del_sol_promotions.json"]


@pytest.mark.parametrize("failure", ["raw_replace", "metadata_replace", "serialize", "write"])
def test_write_failures_preserve_raw_and_cleanup_temporary_files(tmp_path, monkeypatch, failure):
    scraper = _complete_scraper(tmp_path)
    original = _baseline(scraper)
    result = scraper.scrape()
    assert result.complete and scraper.coverage["snapshot_replace_allowed"] is True
    if failure in {"raw_replace", "metadata_replace"}:
        import os
        real_replace = os.replace

        def replace(source, destination):
            is_raw = destination == scraper.output_path
            if is_raw == (failure == "raw_replace"):
                raise OSError("synthetic replace failure")
            real_replace(source, destination)

        monkeypatch.setattr(os, "replace", replace)
    else:
        def fail_dump(data, file, **kwargs):
            file.write("partial")
            if failure == "serialize":
                raise TypeError("synthetic serialization failure")
            raise OSError("synthetic disk failure")

        monkeypatch.setattr(json, "dump", fail_dump)
    with pytest.raises((OSError, TypeError)):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == original
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("tmp")]


def test_explicit_replacement_permission_required_even_if_catalog_complete(tmp_path):
    scraper = _complete_scraper(tmp_path)
    original = _baseline(scraper)
    result = scraper.scrape()
    assert result.complete and scraper.coverage["snapshot_replace_allowed"] is True
    del scraper.coverage["snapshot_replace_allowed"]
    with pytest.raises(ValueError, match="autorizado"):
        scraper.save_raw_promotions(result.promotions)
    assert scraper.output_path.read_text(encoding="utf-8") == original
