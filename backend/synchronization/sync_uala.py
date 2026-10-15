"""Ualá sync entry point. Running this module can write Supabase."""
from normalization.sources.uala import UalaNormalizer
from scraping.sources.uala.scraper import UalaScraper
from synchronization.runner import SyncRunner


if __name__ == "__main__":
    SyncRunner("uala", UalaScraper, UalaNormalizer, normalize_many=True).main()
