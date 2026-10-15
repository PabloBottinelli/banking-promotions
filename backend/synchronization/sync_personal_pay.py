from normalization.sources.personal_pay import PersonalPayNormalizer
from scraping.sources.personal_pay.scraper import PersonalPayScraper
from synchronization.runner import SyncRunner


def main():
    SyncRunner("personal_pay", PersonalPayScraper, PersonalPayNormalizer,
               normalize_many=True, allow_deactivation=False).main()


if __name__ == "__main__":
    main()
