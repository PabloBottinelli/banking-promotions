from synchronization.runner import SyncRunner
from normalization.sources.patagonia import PatagoniaNormalizer
from scraping.sources.patagonia.scraper import PatagoniaScraper


def main():
    runner = SyncRunner(
        source="patagonia",
        scraper_class=PatagoniaScraper,
        normalizer_class=PatagoniaNormalizer,
        normalize_many=True,
    )
    runner.main()


if __name__ == "__main__":
    main()