import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from normalization.models import NormalizedPromotion
from persistence.supabase_repository import SupabasePromotionRepository
from scraping.models import ScrapeResult


BACKEND_DIR = Path(__file__).resolve().parents[1]


class SyncRunner:
    def __init__(self, source: str, scraper_class: type, normalizer_class: type, normalize_many: bool = False):
        self.source = source
        self.scraper_class = scraper_class
        self.normalizer_class = normalizer_class
        self.normalize_many = normalize_many
        self.raw_path = BACKEND_DIR / "data" / f"{source}_promotions.json"

    def load_raw_promotions(self) -> list[dict]:
        with self.raw_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def scrape_promotions(self) -> ScrapeResult:
        scraper = self.scraper_class()
        result = scraper.scrape()
        scraper.save_raw_promotions(result.promotions)
        return result

    def normalize_promotions(self, raw_promotions: list[dict]) -> list[NormalizedPromotion]:
        normalizer = self.normalizer_class()
        promotions = []
        errors = []

        for raw in raw_promotions:
            try:
                if self.normalize_many:
                    promotions.extend(normalizer.normalize_many(raw))
                else:
                    promotions.append(normalizer.normalize(raw))
            except Exception as error:
                errors.append((raw.get("source_id"), error))

        if errors:
            print("\nErrores de normalización:")

            for source_id, error in errors:
                print(f"  {source_id}: {error}")

            raise RuntimeError(f"No se pudieron normalizar {len(errors)} promociones")

        return promotions

    def run(self, from_file: bool = False) -> None:
        scrape_complete = False

        if from_file:
            print(f"Leyendo promociones desde {self.raw_path}")
            raw_promotions = self.load_raw_promotions()
        else:
            print(f"Scrapeando promociones de {self.source.upper()}...")
            result = self.scrape_promotions()
            raw_promotions = result.promotions
            scrape_complete = result.complete

        print(f"\nPromociones crudas: {len(raw_promotions)}")

        if not raw_promotions:
            raise RuntimeError("El scraper no devolvió promociones. Se cancela la sincronización.")

        print("\nNormalizando...")
        promotions = self.normalize_promotions(raw_promotions)

        if not promotions:
            raise RuntimeError("No se generaron promociones normalizadas. Se cancela la sincronización.")

        print(f"Promociones normalizadas: {len(promotions)}")

        print("\nSincronizando con Supabase...")

        repository = SupabasePromotionRepository()
        sync_started_at = datetime.now(timezone.utc)

        total = repository.upsert_many(promotions, batch_size=200, seen_at=sync_started_at)

        if scrape_complete:
            deactivated = repository.deactivate_not_seen(self.source, sync_started_at)
        else:
            deactivated = 0
            print("\nScraping incompleto o carga desde archivo.")
            print(f"Se omite la desactivación de promociones de {self.source}.")

        print("\nSincronización finalizada:")
        print(f"  Promociones crudas: {len(raw_promotions)}")
        print(f"  Promociones normalizadas: {len(promotions)}")
        print(f"  Activas encontradas: {total}")
        print(f"  Desactivadas: {deactivated}")
        print(f"  Scraping completo: {'sí' if scrape_complete else 'no'}")

    def main(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--from-file", action="store_true")
        args = parser.parse_args()

        self.run(from_file=args.from_file)