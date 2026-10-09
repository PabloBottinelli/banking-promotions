"""Helpers for representing existing bank offers with the structured V2 model.

Only promotes information supported by the source.  Unknown data stays unknown;
free-form conditions preserve details that the model does not yet encode.
"""

import re
from decimal import Decimal

from normalization.models import Benefit, PromotionLimit


def to_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def make_benefits(
    *,
    percentage: float | int | None,
    installments: int | None,
    benefit_text: str,
    fallback_description: str,
    fixed_discount: float | int | None = None,
    installments_interest_free: bool | None = None,
) -> list[Benefit]:
    """Keep combined discount/cashback and financing in one variant."""
    benefits: list[Benefit] = []
    if percentage is not None:
        # Interpret the *specific benefit text*, not unrelated legal clauses.
        kind = "cashback" if re.search(r"\breintegro\b|\bcashback\b|\bdevoluci[oó]n\b", benefit_text, re.I) else "discount"
        benefits.append(Benefit(type=kind, percentage=to_decimal(percentage)))
    if fixed_discount is not None:
        benefits.append(Benefit(type="discount", amount=to_decimal(fixed_discount), currency="ARS"))
    if installments is not None:
        interest_free = installments_interest_free if installments_interest_free is not None else (True if re.search(r"sin\s+inter[eé]s", benefit_text, re.I) else None)
        benefits.append(Benefit(type="installments", installment_options=[installments], interest_free=interest_free))
    if not benefits:
        if not fallback_description.strip():
            raise ValueError("No hay beneficio estructurable ni descripción fiel de la fuente")
        benefits.append(Benefit(type="other", description=fallback_description.strip()))
    return benefits


def make_limits(
    *,
    cap_amount: float | int | None = None,
    cap_scope: str | None = None,
    cap_period: str | None = None,
    minimum_purchase: float | int | None = None,
    currency: str | None = "ARS",
) -> list[PromotionLimit]:
    limits = []
    if cap_amount is not None:
        limits.append(PromotionLimit(
            type="monetary_cap", amount=to_decimal(cap_amount),
            currency=currency, scope=cap_scope, period=cap_period,
        ))
    if minimum_purchase is not None:
        limits.append(PromotionLimit(
            type="minimum_purchase", amount=to_decimal(minimum_purchase), currency=currency,
        ))
    return limits


def conditions(*groups: tuple[str, str] | None) -> str | None:
    """Produce displayable restrictions without inventing new eligibility rules."""
    parts = []
    for group in groups:
        if group is None:
            continue
        label, value = group
        if value.strip():
            parts.append(f"{label}: {value.strip()}")
    return "\n".join(parts) or None


def requires_merchant_check(text: str | None) -> bool:
    return bool(re.search(r"(?:comercios|locales|sucursales)\s+adherid[oa]s", text or "", re.I))
