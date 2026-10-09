from datetime import datetime
from urllib.parse import urlencode
from normalization.models import NormalizedPromotion, PaymentMethod
from normalization.structure import make_benefits, make_limits, conditions, requires_merchant_check


class GaliciaNormalizer:
    PROMOTIONS_URL = "https://www.galicia.ar/personas/buscador-de-promociones"
    
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
        title = catalog["titulo"]
        url = self._build_promotion_url(raw["source_id"], title, scope)
        terms = detail.get("legales")
        discount = self._normalize_discount(detail.get("porcentajeAhorro"))
        installments = detail.get("cuotaSinInteresHasta")
        installment_start = detail.get("cuotaSinInteresDesde")
        segments = self._normalize_customer_segments(detail)
        qr, nfc, contactless = (
            bool(catalog.get("pagoQR")), bool(catalog.get("pagoNFC")), bool(catalog.get("contactLess"))
        )
        payment_methods = self._normalize_payment_methods(detail.get("mediosDePago", []))
        # Catalog flags may indicate several accepted rails. Do not incorrectly
        # pair a specific card with QR/NFC unless the offer establishes it.
        payment_rails = ", ".join(name for name, flag in (("QR", qr), ("NFC", nfc), ("contactless", contactless)) if flag)
        return NormalizedPromotion(
            source=raw["source"],
            source_id=str(raw["source_id"]),
            scraped_at=datetime.fromisoformat(raw["scraped_at"]),
            title=title,
            scope=self._normalize_scope(scope),
            merchant=brand.get("nombre") if brand else None,
            category=self._extract_category(catalog, detail, scope),
            promotion_url=url,
            valid_from=self._parse_date(detail["fechaDesde"]),
            valid_to=self._parse_date(detail["fechaHasta"]),
            benefits=make_benefits(
                percentage=discount,
                installments=int(installments) if installments and int(installments) > 1 else None,
                benefit_text=" ".join(str(x or "") for x in (title, catalog.get("subtitulo"), terms)),
                fallback_description=str(catalog.get("subtitulo") or title),
                installments_interest_free=True if installments else None,
            ),
            limits=make_limits(
                cap_amount=cap_amount, cap_scope=cap_scope, cap_period=cap_period,
                minimum_purchase=detail.get("minimoCompra"),
            ),
            payment_methods=payment_methods,
            days_of_week=self._normalize_days(detail.get("diasAplicacion")),
            applies_every_day=self._all_days(detail.get("diasAplicacion")),
            online=detail.get("tiendaOnline"),
            physical=detail.get("tiendaFisica"),
            specific_conditions=conditions(
                ("Segmentos/requisitos", ", ".join(segments)) if segments else None,
                ("Financiación", f"De {installment_start} a {installments} cuotas sin interés") if installment_start and installments and installment_start != installments else None,
                ("Modalidades admitidas", payment_rails) if payment_rails else None,
            ),
            requires_merchant_verification=bool(url and requires_merchant_check(terms)),
            terms=terms,
        )

    def _all_days(self, value: str | None) -> bool | None:
        if not value:
            return None
        days = self._normalize_days(value)
        return len(days) == 7 if days else None

    def _parse_date(self, value: str):
        return datetime.strptime(value, "%d/%m/%Y").date()

    def _build_promotion_url(self, source_id: str | int, title: str | None, promotion_type: str | None) -> str | None:
        if not source_id or not title or not promotion_type:
            return None

        path = f"/promocion/{source_id}|{title}|{promotion_type}"
        return f"{self.PROMOTIONS_URL}?{urlencode({'path': path})}"

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
                issuer="Banco Galicia",
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