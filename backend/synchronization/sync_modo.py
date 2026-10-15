"""MODO synchronization entry point. Running it requires explicit authorization."""
from normalization.sources.modo import ModoNormalizer
from scraping.sources.modo.scraper import ModoScraper
from synchronization.runner import SyncRunner


def main():
    SyncRunner("modo", ModoScraper, ModoNormalizer, normalize_many=True,
               allow_deactivation=False).main()


if __name__ == "__main__":
    main()
