from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PaymentMethod(BaseModel):
    # Cada objeto describe una combinación de pago admitida, no piezas combinables.
    raw_name: str
    issuer: str | None = None
    network: str | None = None
    card_type: Literal["credit", "debit", "prepaid"] | None = None
    wallet: str | None = None
    payment_rail: Literal[
        "card", "qr", "nfc", "transfer", "account_balance", "other"
    ] | None = None


class Benefit(BaseModel):
    # Un beneficio puede ser un descuento, una bonificación de comisión, un regalo, etc.
    type: Literal[
        "discount", "cashback", "installments", "fee_waiver",
        "free_service", "points", "gift", "other",
    ]
    percentage: Decimal | None = None
    amount: Decimal | None = None
    currency: str | None = None
    reward_currency: str | None = None  # Ej.: BTC en cashback cripto.
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
    period: str | None = None  # Ej.: transaction, weekly, monthly, promotion.
    scope: str | None = None  # Ej.: person, account, card, merchant, campaign.
    shared_group_id: str | None = None
    description: str | None = None


class NormalizedPromotion(BaseModel):
    # Identidad y trazabilidad.
    source: str
    source_id: str  # Identificador único y estable POR VARIANTE, dentro de source.
    scraped_at: datetime
    title: str
    scope: Literal["merchant", "category", "shopping", "other"]

    # Fechas obligatorias como campos, pero pueden ser desconocidas.
    valid_from: date | None
    valid_to: date | None

    # Variantes de una misma publicación: nivel, tarjeta, categoría, etc.
    promotion_group_id: str | None = None

    # Presentación y ámbito comercial.
    merchant: str | None = None  # Admite «Comercios de barrio» o «Comercios adheridos».
    category: str | None = None
    promotion_url: str | None = None
    requires_merchant_verification: bool = False

    # TODOS los tipos de beneficios; una variante puede tener varios acumulables.
    benefits: list[Benefit] = Field(min_length=1)
    limits: list[PromotionLimit] = Field(default_factory=list)

    # Cada PaymentMethod representa una alternativa completa y válida.
    payment_methods: list[PaymentMethod] = Field(default_factory=list)

    # [] no significa automáticamente «todos los días».
    days_of_week: list[
        Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    ] = Field(default_factory=list)
    applies_every_day: bool | None = None

    # Canales: None significa que la fuente no permite afirmarlo.
    online: bool | None = None
    physical: bool | None = None

    # Restricciones especiales: regiones, planes, segmentos, adheridos, exclusiones, etc.
    specific_conditions: str | None = None
    terms: str | None = None  # Texto legal original, sin reinterpretar.

    @model_validator(mode="after")
    def merchant_verification_needs_url(self):
        if self.requires_merchant_verification and not self.promotion_url:
            raise ValueError(
                "Una promoción que requiere consultar comercios adheridos "
                "necesita promotion_url."
            )
        return self
