
from normalization.sources.banco_del_sol import BancoDelSolNormalizer
from scraping.sources.banco_del_sol.scraper import BancoDelSolScraper
from synchronization.runner import SyncRunner


def main() -> None:
    SyncRunner(source="banco_del_sol", scraper_class=BancoDelSolScraper,
               normalizer_class=BancoDelSolNormalizer, normalize_many=True,
               allow_deactivation=False).main()


if __name__ == "__main__":
    main()
