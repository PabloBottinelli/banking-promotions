import argparse

from normalization.sources.bbva import BBVANormalizer
from normalization.sources.buepp import BueppNormalizer

from scraping.sources.bbva.scraper import BBVAScraper
from scraping.sources.buepp.scraper import BueppScraper

from synchronization.runner import SyncRunner


def create_runner(source: str) -> SyncRunner:
    if source == "bbva":
        return SyncRunner(
            source="bbva",
            scraper_class=BBVAScraper,
            normalizer_class=BBVANormalizer,
            normalize_many=False,
            allow_deactivation=False,
            storage_mode="hybrid",
        )

    if source == "buepp":
        return SyncRunner(
            source="buepp",
            scraper_class=BueppScraper,
            normalizer_class=BueppNormalizer,
            normalize_many=True,
            allow_deactivation=False,
            storage_mode="hybrid",
        )

    raise ValueError(f"Fuente no soportada: {source}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validar una captura híbrida sin escribir en Supabase"
    )

    parser.add_argument(
        "--source",
        required=True,
        choices=["bbva", "buepp"],
    )

    args = parser.parse_args(argv)

    runner = create_runner(args.source)

    runner.run(validate_only=True)


if __name__ == "__main__":
    main()