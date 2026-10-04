from datetime import datetime

from normalization.models import NormalizedPromotion, PaymentMethod


class GaliciaNormalizer:
    DAYS = {
        "Lu": "monday",
        "Ma": "tuesday",
        "Mi": "wednesday",
        "Ju": "thursday",
        "Vi": "friday",
        "Sa": "saturday",
        "Do": "sunday",
    }

    SCOPE_TYPES = {
        "Marca": "merchant",
        "Categoria": "category",
        "Shopping": "shopping",
    }

    CARD_TYPES = {
        "Credito": "credit",
        "Debito": "debit",
    }

    CAP_SCOPES = {
        "Cliente": "customer",
        "Compra": "purchase",
    }

    CAP_PERIODS = {
        "Mensual": "monthly",
        "Semanal": "weekly",
        "Unico": "one_time",
    }

    CUSTOMER_SEGMENTS = {
        "Eminent": "eminent",
        "Eminent Black": "eminent_black",
    }

    def normalize(self, raw: dict) -> NormalizedPromotion:
        catalog = raw["catalog"]
        detail = raw["detail"]
        brand = detail.get("marca")
        scope = catalog.get("tipoPromocion")

        cap_amount, cap_scope, cap_period = self._normalize_cap(detail)

        return NormalizedPromotion(
            source=raw["source"],
            source_id=str(raw["source_id"]),
            scraped_at=datetime.fromisoformat(raw["scraped_at"]),
            title=catalog["titulo"],
            scope=self._normalize_scope(scope),
            merchant=brand.get("nombre") if brand else None,
            category=self._extract_category(catalog, detail, scope),
            merchant_url=brand.get("urlTiendaOnline") if brand else None,
            discount_percentage=self._normalize_discount(detail.get("porcentajeAhorro")),
            installments=detail.get("cuotaSinInteresHasta"),
            valid_from=self._parse_date(detail["fechaDesde"]),
            valid_to=self._parse_date(detail["fechaHasta"]),
            days_of_week=self._normalize_days(detail.get("diasAplicacion")),
            cap_amount=cap_amount,
            cap_scope=cap_scope,
            cap_period=cap_period,
            minimum_purchase=detail.get("minimoCompra"),
            payment_methods=self._normalize_payment_methods(detail.get("mediosDePago", [])),
            online=detail.get("tiendaOnline", False),
            physical=detail.get("tiendaFisica", False),
            qr=catalog.get("pagoQR", False),
            nfc=catalog.get("pagoNFC", False),
            contactless=catalog.get("contactLess", False),
            customer_segments=self._normalize_customer_segments(detail),
            eligibility_requirements=[],
            terms=detail.get("legales"),
        )

    def _parse_date(self, value: str):
        return datetime.strptime(value, "%d/%m/%Y").date()

    def _normalize_days(self, value: str | None) -> list[str]:
        if not value:
            return []

        return [self.DAYS[day] for day in value.split(";") if day in self.DAYS]

    def _normalize_discount(self, value: float | int | None) -> float | None:
        if not value:
            return None

        return float(value)

    def _normalize_scope(self, value: str | None) -> str:
        return self.SCOPE_TYPES.get(value, "other")

    def _extract_category(self, catalog: dict, detail: dict, scope: str | None) -> str | None:
        if scope == "Categoria":
            category = detail.get("categoria")
        else:
            brand = detail.get("marca")
            category = brand.get("categoria") if brand else None

        if category:
            return category.get("descripcion")

        return catalog.get("subtitulo")

    def _normalize_cap(self, detail: dict) -> tuple[float | None, str | None, str | None]:
        cap_type = detail.get("tipoTope")

        if not cap_type or cap_type.strip().lower() == "sin tope":
            return None, None, None

        amount = detail.get("topeReintegro")
        period = detail.get("periodicidad")

        return (
            float(amount) if amount else None,
            self.CAP_SCOPES.get(cap_type, cap_type.lower()),
            self.CAP_PERIODS.get(period, period.lower() if period else None),
        )

    def _normalize_payment_methods(self, methods: list[dict]) -> list[PaymentMethod]:
        return [
            PaymentMethod(
                raw_name=method["tarjeta"],
                network=self._extract_network(method["tarjeta"]),
                card_type=self.CARD_TYPES.get(method.get("tipoTarjeta")),
            )
            for method in methods
        ]

    def _extract_network(self, card_name: str) -> str | None:
        name = card_name.lower()

        if "american express" in name:
            return "american_express"

        if "mastercard" in name:
            return "mastercard"

        if "visa" in name:
            return "visa"

        return None

    def _normalize_customer_segments(self, detail: dict) -> list[str]:
        segments = []

        if detail.get("haberes", False):
            segments.append("salary")

        raw_segment = detail.get("modeloAtencion", {}).get("nombre")
        segment = self.CUSTOMER_SEGMENTS.get(raw_segment)

        if segment:
            segments.append(segment)

        return segments