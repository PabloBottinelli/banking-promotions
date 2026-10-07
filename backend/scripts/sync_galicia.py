import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from normalization.models import NormalizedPromotion
from normalization.sources.galicia import GaliciaNormalizer
from persistence.supabase_repository import SupabasePromotionRepository
from scraping.models import ScrapeResult
from scraping.sources.galicia.scraper import GaliciaScraper


BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_PATH = BACKEND_DIR / "data" / "galicia_promotions.json"


def load_raw_promotions() -> list[dict]:
    with RAW_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_promotions(raw_promotions: list[dict]) -> list[NormalizedPromotion]:
    normalizer = GaliciaNormalizer()
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


def scrape_promotions() -> ScrapeResult:
    scraper = GaliciaScraper()
    result = scraper.scrape()
    scraper.save_raw_promotions(result.promotions)

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-file", action="store_true")
    args = parser.parse_args()

    scrape_complete = False

    if args.from_file:
        print(f"Leyendo promociones desde {RAW_PATH}")
        raw_promotions = load_raw_promotions()
    else:
        print("Scrapeando promociones de Galicia...")
        result = scrape_promotions()
        raw_promotions = result.promotions
        scrape_complete = result.complete

    print()
    print(f"Promociones crudas: {len(raw_promotions)}")

    if not raw_promotions:
        raise RuntimeError("El scraper no devolvió promociones. Se cancela la sincronización.")

    print("Normalizando...")
    promotions = normalize_promotions(raw_promotions)

    if not promotions:
        raise RuntimeError("No se generaron promociones normalizadas. Se cancela la sincronización.")

    print(f"Promociones normalizadas: {len(promotions)}")

    print()
    print("Sincronizando con Supabase...")

    repository = SupabasePromotionRepository()
    sync_started_at = datetime.now(timezone.utc)

    total = repository.upsert_many(promotions, batch_size=200, seen_at=sync_started_at)

    if scrape_complete:
        deactivated = repository.deactivate_not_seen("galicia", sync_started_at)
    else:
        deactivated = 0

        print()
        print("Scraping incompleto o carga desde archivo.")
        print("Se omite la desactivación de promociones de Galicia.")

    print()
    print("Sincronización finalizada:")
    print(f"  Promociones crudas: {len(raw_promotions)}")
    print(f"  Promociones normalizadas: {len(promotions)}")
    print(f"  Activas encontradas: {total}")
    print(f"  Desactivadas: {deactivated}")
    print(f"  Scraping completo: {'sí' if scrape_complete else 'no'}")


if __name__ == "__main__":
    main()