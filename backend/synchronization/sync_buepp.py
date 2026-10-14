from normalization.sources.buepp import BueppNormalizer
from scraping.sources.buepp.scraper import BueppScraper
from synchronization.runner import SyncRunner


def main():
    runner = SyncRunner(
        source="buepp",
        scraper_class=BueppScraper,
        normalizer_class=BueppNormalizer,
        normalize_many=True,
        allow_deactivation=False,
    )

    runner.main()


if __name__ == "__main__":
    main()
