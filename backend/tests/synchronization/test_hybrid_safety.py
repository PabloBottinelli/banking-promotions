import json

import httpx
import pytest

from scraping.sources.bbva import scraper as bbva_scraper_module
from scraping.sources.bbva.scraper import BBVAScraper
from synchronization import runner as runner_module


def test_bbva_missing_promotion_blocks_hybrid_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(bbva_scraper_module, "DATA_DIR", tmp_path)

    previous = [
        {"source": "bbva", "source_id": "88970"},
    ]

    snapshot = tmp_path / "bbva_promotions.json"
    snapshot.write_text(json.dumps(previous), encoding="utf-8")

    def handler(request):
        if request.url.path.endswith("/communications"):
            page = int(request.url.params["pager"])

            items = [{"id": 123}] if page == 0 else []

            return httpx.Response(200, json={"data": items})

        if request.url.path.endswith("/communication/123"):
            return httpx.Response(
                200,
                json={"data": {"id": 123, "cabecera": "Promoción"}},
            )

        return httpx.Response(404)

    calls = []

    class FakeRepository:
        def __init__(self, base_url, headers):
            pass

        def get_existing_promotions(self, source):
            calls.append("read")
            return {}

        def upsert_many(self, *args, **kwargs):
            calls.append("upsert")
            raise AssertionError("No debería escribir promociones")

        def touch_unchanged(self, *args, **kwargs):
            calls.append("touch")
            raise AssertionError("No debería actualizar promociones")

    monkeypatch.setattr(
        runner_module,
        "HybridPromotionRepository",
        FakeRepository,
    )

    monkeypatch.setattr(
        runner_module,
        "SUPABASE_URL",
        "https://supabase.invalid",
    )

    monkeypatch.setattr(
        runner_module,
        "get_headers",
        lambda: {"apikey": "test"},
    )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        scraper = BBVAScraper(client=client)

        runner = runner_module.SyncRunner(
            source="bbva",
            scraper_class=lambda: scraper,
            normalizer_class=None,
            storage_mode="hybrid",
        )

        with pytest.raises(
            ValueError,
            match="Desaparecieron promociones sin aprobación",
        ):
            runner.run()

    assert calls == ["read"]

    assert json.loads(snapshot.read_text(encoding="utf-8")) == previous

    assert not (tmp_path / "bbva_coverage.json").exists()