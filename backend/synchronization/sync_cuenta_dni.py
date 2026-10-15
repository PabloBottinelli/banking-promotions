from normalization.sources.cuenta_dni import CuentaDNINormalizer
from scraping.sources.cuenta_dni.scraper import CuentaDNIScraper
from synchronization.runner import SyncRunner


def main():
    SyncRunner(source="cuenta_dni", scraper_class=CuentaDNIScraper,
               normalizer_class=CuentaDNINormalizer, normalize_many=True,
               allow_deactivation=False).main()


if __name__ == "__main__":
    main()
