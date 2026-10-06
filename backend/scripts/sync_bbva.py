import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from normalization.models import NormalizedPromotion
from normalization.sources.bbva import BBVANormalizer
from persistence.supabase_repository import SupabasePromotionRepository
from scraping.sources.bbva.scraper import BBVAScraper


BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_PATH = BACKEND_DIR / "data" / "bbva_promotions.json"


def load_raw_promotions() -> list[dict]:
    with RAW_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_promotions(raw_promotions: list[dict]) -> list[NormalizedPromotion]:
    normalizer = BBVANormalizer()
    promotions = []
    errors = []

    for raw in raw_promotions:
        try:
            promotions.append(normalizer.normalize(raw))
        except Exception as error:
            errors.append((raw.get("source_id"), error))

    if errors:
        for source_id, error in errors:
            print(f"Error normalizando {source_id}: {error}")

        raise RuntimeError(f"No se pudieron normalizar {len(errors)} promociones")

    return promotions


def scrape_promotions() -> list[dict]:
    scraper = BBVAScraper()
    promotions = scraper.scrape()
    scraper.save_raw_promotions(promotions)

    return promotions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-file", action="store_true")
    args = parser.parse_args()

    if args.from_file:
        print(f"Leyendo promociones desde {RAW_PATH}")
        raw_promotions = load_raw_promotions()
    else:
        print("Scrapeando promociones de BBVA...")
        raw_promotions = scrape_promotions()

    print(f"Promociones crudas: {len(raw_promotions)}")

    print("Normalizando...")
    promotions = normalize_promotions(raw_promotions)

    print(f"Promociones normalizadas: {len(promotions)}")

    print("Sincronizando con Supabase...")

    repository = SupabasePromotionRepository()
    sync_started_at = datetime.now(timezone.utc)

    total = repository.upsert_many(promotions, batch_size=200, seen_at=sync_started_at)
    deactivated = repository.deactivate_not_seen("bbva", sync_started_at)

    print()
    print("Sincronización finalizada:")
    print(f"  Activas encontradas: {total}")
    print(f"  Desactivadas: {deactivated}")


if __name__ == "__main__":
    main()