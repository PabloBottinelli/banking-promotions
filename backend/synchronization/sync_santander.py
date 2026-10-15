"""Santander sync entry point. Execution requires explicit user authorization."""
from normalization.sources.santander import SantanderNormalizer
from scraping.sources.santander.scraper import SantanderScraper


def main():
    # Keep imports lazy here; shared runner still imports the repository eagerly.
    from synchronization.runner import SyncRunner
    SyncRunner(source="santander", scraper_class=SantanderScraper,
               normalizer_class=SantanderNormalizer, normalize_many=True,
               allow_deactivation=False).main()


if __name__ == "__main__":
    main()
