from dataclasses import dataclass

@dataclass
class ScrapeResult:
    promotions: list[dict]
    catalog_count: int
    failed_ids: list[str]

    @property
    def complete(self) -> bool:
        return self.catalog_count > 0 and not self.failed_ids and len(self.promotions) == self.catalog_count