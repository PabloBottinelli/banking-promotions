from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class PaymentMethod(BaseModel):
    raw_name: str
    network: str | None = None
    card_type: Literal["credit", "debit"] | None = None


class NormalizedPromotion(BaseModel):
    source: str
    source_id: str
    scraped_at: datetime

    title: str
    scope: Literal["merchant", "category", "shopping", "other"] 

    merchant: str | None = None
    category: str | None = None
    merchant_url: str | None = None

    discount_percentage: float | None = None

    installments: int | None = None

    valid_from: date
    valid_to: date
    days_of_week: list[str]

    cap_amount: float | None = None
    cap_scope: str | None = None
    cap_period: str | None = None

    minimum_purchase: float | None = None

    payment_methods: list[PaymentMethod]

    online: bool
    physical: bool

    qr: bool
    nfc: bool
    contactless: bool

    customer_segments: list[str] = Field(default_factory=list)
    eligibility_requirements: list[str] = Field(default_factory=list)

    terms: str | None = None