from synchronization.runner import SyncRunner
from normalization.sources.bbva import BBVANormalizer
from scraping.sources.bbva.scraper import BBVAScraper


def main():
    runner = SyncRunner(
        source="bbva",
        scraper_class=BBVAScraper,
        normalizer_class=BBVANormalizer,
    )
    runner.main()


if __name__ == "__main__":
    main()