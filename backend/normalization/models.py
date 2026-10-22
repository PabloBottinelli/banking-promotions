from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PaymentMethod(BaseModel):
    raw_name: str
    issuer: str | None = None
    network: str | None = None
    card_type: Literal["credit", "debit", "prepaid"] | None = None
    wallet: str | None = None
    payment_rail: Literal[
        "card", "qr", "nfc", "transfer", "account_balance", "other"
    ] | None = None


class Benefit(BaseModel):
    type: Literal[
        "discount", "cashback", "installments", "fee_waiver",
        "free_service", "points", "gift", "other",
    ]
    percentage: Decimal | None = None
    amount: Decimal | None = None
    currency: str | None = None
    reward_currency: str | None = None
    installment_options: list[int] = Field(default_factory=list)
    interest_free: bool | None = None
    description: str | None = None


class PromotionLimit(BaseModel):
    type: Literal[
        "monetary_cap", "usage_count", "minimum_purchase", "stock", "other",
    ]
    amount: Decimal | None = None
    quantity: int | None = None
    currency: str | None = None
    period: str | None = None
    scope: str | None = None
    shared_group_id: str | None = None
    description: str | None = None


class NormalizedPromotion(BaseModel):
    source: str
    source_id: str
    scraped_at: datetime
    title: str
    scope: Literal["merchant", "category", "shopping", "other"]

    valid_from: date | None
    valid_to: date | None

    promotion_group_id: str | None = None

    merchant: str | None = None
    category: str | None = None
    promotion_url: str | None = None
    requires_merchant_verification: bool = False

    benefits: list[Benefit] = Field(min_length=1)
    limits: list[PromotionLimit] = Field(default_factory=list)

    payment_methods: list[PaymentMethod] = Field(default_factory=list)

    days_of_week: list[
        Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    ] = Field(default_factory=list)
    applies_every_day: bool | None = None

    online: bool | None = None
    physical: bool | None = None

    specific_conditions: str | None = None
    terms: str | None = None

    @model_validator(mode="after")
    def merchant_verification_needs_url(self):
        if self.requires_merchant_verification and not self.promotion_url:
            raise ValueError(
                "Una promoción que requiere consultar comercios adheridos "
                "necesita promotion_url."
            )
        return self
