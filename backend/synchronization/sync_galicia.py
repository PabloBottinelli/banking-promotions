from synchronization.runner import SyncRunner
from normalization.sources.galicia import GaliciaNormalizer
from scraping.sources.galicia.scraper import GaliciaScraper


def main():
    runner = SyncRunner(
        source="galicia",
        scraper_class=GaliciaScraper,
        normalizer_class=GaliciaNormalizer,
    )
    runner.main()


if __name__ == "__main__":
    main()