import html
import re
from datetime import datetime

from normalization.models import NormalizedPromotion, PaymentMethod


class BBVANormalizer:
    PROMOTIONS_URL = "https://www.bbva.com.ar/beneficios/"

    DAYS = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

    def normalize(self, raw: dict) -> NormalizedPromotion:
        catalog = raw["catalog"]
        detail = raw["detail"]

        benefits = detail.get("beneficios", [])
        benefit = benefits[0] if benefits and isinstance(benefits[0], dict) else {}

        title = self._clean_text(detail.get("cabecera") or catalog.get("cabecera"))
        subtitle = self._clean_text(catalog.get("subcabecera"))

        requirements = self._normalize_requirements(benefit.get("requisitos"))
        terms = self._clean_text(detail.get("basesCondiciones")) or None

        channels = detail.get("canalesVenta", {})

        return NormalizedPromotion(
            source=raw["source"],
            source_id=str(raw["source_id"]),
            scraped_at=datetime.fromisoformat(raw["scraped_at"]),
            title=title,
            scope="merchant",
            merchant=title or None,
            category=None,
            promotion_url=self.PROMOTIONS_URL,
            discount_percentage=self._extract_discount(title, subtitle, requirements, terms),
            installments=self._normalize_installments(benefit.get("cuota")),
            valid_from=self._parse_date(catalog["fechaDesde"]),
            valid_to=self._parse_date(catalog["fechaHasta"]),
            days_of_week=self._normalize_days(detail.get("diasPromo") or catalog.get("diasPromo")),
            cap_amount=self._normalize_amount(benefit.get("tope") or catalog.get("montoTope")),
            cap_scope=self._normalize_cap_scope(benefit.get("tipoTope")),
            cap_period=self._normalize_cap_period(benefit.get("frecuenciaTope")),
            minimum_purchase=None,
            payment_methods=self._normalize_payment_methods(detail.get("grupoTarjeta") or catalog.get("grupoTarjeta")),
            online=self._has_online_channels(channels),
            physical=self._has_physical_channels(channels),
            qr=self._contains_requirement(requirements, "qr"),
            nfc=self._contains_requirement(requirements, "nfc"),
            contactless=self._contains_requirement(requirements, "contactless"),
            customer_segments=["black"] if "black" in (terms or "").lower() else [],
            eligibility_requirements=requirements,
            terms=terms,
        )

    def _clean_text(self, value) -> str:
        if value is None:
            return ""

        text = html.unescape(str(value))
        text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        return re.sub(r"\s+", " ", text).strip()

    def _parse_date(self, value: str):
        for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value[:19], date_format).date()
            except ValueError:
                continue

        raise ValueError(f"Formato de fecha BBVA desconocido: {value}")

    def _normalize_days(self, value: str | None) -> list[str]:
        if not value:
            return []

        parts = [part.strip() for part in str(value).split(",")]

        if len(parts) != 7:
            return []

        return [day for day, active in zip(self.DAYS, parts) if active == "1"]

    def _extract_discount(self, title: str, subtitle: str, requirements: list[str], terms: str | None) -> float | None:
        text = " ".join([title, subtitle, *requirements, terms or ""])

        match = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*%", text)

        if not match:
            return None

        value = float(match.group(1).replace(",", "."))

        if value < 0 or value > 100:
            return None

        return value

    def _normalize_installments(self, value) -> int | None:
        if value in (None, "", 0, "0"):
            return None

        try:
            installments = int(value)
        except (TypeError, ValueError):
            return None

        return installments if installments > 1 else None

    def _normalize_amount(self, value) -> float | None:
        if value in (None, ""):
            return None

        if isinstance(value, (int, float)):
            return float(value) if value else None

        text = str(value).strip()
        text = text.replace("$", "").replace(" ", "")

        if "," in text:
            text = text.replace(".", "").replace(",", ".")

        try:
            amount = float(text)
        except ValueError:
            return None

        return amount if amount else None

    def _normalize_cap_scope(self, value: str | None) -> str | None:
        if not value:
            return None

        value = self._clean_text(value).lower()

        if "compra" in value:
            return "purchase"

        if "cliente" in value or "persona" in value:
            return "customer"

        if "sin tope" in value:
            return None

        return value

    def _normalize_cap_period(self, value: str | None) -> str | None:
        if not value:
            return None

        value = self._clean_text(value).lower()

        if "mensual" in value or "mes" == value:
            return "monthly"

        if "semanal" in value or "semana" == value:
            return "weekly"

        if "diario" in value or "día" in value or "dia" in value:
            return "daily"

        if "único" in value or "unico" in value:
            return "one_time"

        return value

    def _normalize_requirements(self, requirements) -> list[str]:
        if not isinstance(requirements, list):
            return []

        return [text for requirement in requirements if (text := self._clean_text(requirement))]

    def _normalize_payment_methods(self, card_group: str | None) -> list[PaymentMethod]:
        if not card_group:
            return []

        raw_name = self._clean_text(card_group)
        name = raw_name.lower()

        network = None

        if "visa" in name:
            network = "visa"
        elif "mastercard" in name or "master" in name:
            network = "mastercard"
        elif "american express" in name or "amex" in name:
            network = "american_express"

        card_type = None

        if "débito" in name or "debito" in name:
            card_type = "debit"
        elif "crédito" in name or "credito" in name:
            card_type = "credit"

        return [
            PaymentMethod(
                raw_name=raw_name,
                network=network,
                card_type=card_type,
            )
        ]

    def _has_online_channels(self, channels: dict) -> bool:
        if not isinstance(channels, dict):
            return False

        web = channels.get("web", [])

        return isinstance(web, list) and len(web) > 0

    def _has_physical_channels(self, channels: dict) -> bool:
        if not isinstance(channels, dict):
            return False

        branches = channels.get("sucursales", [])

        return isinstance(branches, list) and len(branches) > 0

    def _contains_requirement(self, requirements: list[str], term: str) -> bool:
        term = term.lower()

        return any(term in requirement.lower() for requirement in requirements)
