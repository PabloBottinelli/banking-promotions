import html
import re
import unicodedata
from datetime import datetime

from normalization.models import NormalizedPromotion, PaymentMethod
from normalization.structure import make_benefits, make_limits, conditions, requires_merchant_check


class PatagoniaNormalizer:
    SEGMENT_PATTERN = re.compile(r"\b(CL[ÁA]SICA|PLUS|SINGULAR|PATAGONIA\s+ON)\b", re.IGNORECASE)

    DAY_NAMES = {
        "lunes": "monday",
        "martes": "tuesday",
        "miercoles": "wednesday",
        "jueves": "thursday",
        "viernes": "friday",
        "sabado": "saturday",
        "domingo": "sunday",
    }

    ALL_DAYS = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

    def normalize_many(self, raw: dict) -> list[NormalizedPromotion]:
        catalog = raw["catalog"]
        detail = raw["detail"]

        summary_text = detail.get("summary_text") or ""
        main_text = detail.get("main_text") or ""
        legal_text = detail.get("description_text") or self._extract_terms_from_main(main_text)

        all_text = "\n".join(text for text in [summary_text, legal_text, main_text] if text)

        title = self._clean_text(detail.get("title") or catalog.get("value"))

        if not title:
            raise ValueError(f"Promoción Patagonia {raw['source_id']} sin título")

        valid_from, valid_to = self._extract_validity(summary_text, raw["scraped_at"], legal_text, main_text)

        if valid_from is None or valid_to is None:
            raise ValueError(f"Promoción Patagonia {raw['source_id']} sin vigencia reconocible")

        catalog_segment = catalog.get("segment")

        if catalog_segment == "on":
            variants = [
                {
                    "segments": ["on"],
                    "benefit_text": summary_text or main_text or legal_text,
                    "terms": legal_text or None,
                }
            ]
        else:
            summary_groups = self._extract_summary_groups(summary_text)
            legal_groups = self._extract_legal_groups(legal_text)
            variants = self._build_variants(summary_groups, legal_groups, summary_text, legal_text)

        promotions = []

        for variant in variants:
            segments = variant["segments"]
            benefit_text = variant["benefit_text"]
            terms = variant["terms"]

            variant_text = "\n".join(text for text in [benefit_text, terms or ""] if text)

            discount = self._extract_discount(benefit_text)

            if discount is None:
                discount = self._extract_discount(terms or "")

            installments = self._extract_installments(benefit_text)

            if installments is None:
                installments = self._extract_installments(terms or "")

            source_id = self._variant_source_id(str(raw["source_id"]), segments)

            cap_amount = self._extract_cap_amount(variant_text)
            segments_and_requirements = self._customer_segments(segments, all_text)
            requirements = self._extract_requirements(summary_text)
            qr = self._detect_qr(all_text)
            nfc = self._contains(all_text, "nfc")
            contactless = self._contains(all_text, "contactless") or self._contains(all_text, "sin contacto")
            days = self._extract_days(summary_text or all_text)
            payment_methods = self._extract_payment_methods(variant_text, detail.get("image_alts", []))
            promotions.append(
                NormalizedPromotion(
                    source=raw["source"],
                    source_id=source_id,
                    promotion_group_id=(str(raw["source_id"]) if len(variants) > 1 else None),
                    scraped_at=datetime.fromisoformat(raw["scraped_at"]),
                    title=title,
                    scope="merchant",
                    merchant=title,
                    category=self._extract_category(catalog),
                    promotion_url=detail.get("url"),
                    valid_from=valid_from,
                    valid_to=valid_to,
                    benefits=make_benefits(
                        percentage=discount, installments=installments,
                        benefit_text=benefit_text,
                        fallback_description=benefit_text or terms or title,
                    ),
                    limits=make_limits(
                        cap_amount=cap_amount,
                        cap_scope=self._extract_cap_scope(variant_text),
                        cap_period=self._extract_cap_period(variant_text),
                        minimum_purchase=self._extract_minimum_purchase(variant_text),
                    ),
                    payment_methods=payment_methods,
                    days_of_week=days,
                    applies_every_day=(len(days) == 7) if days else None,
                    online=self._detect_online(all_text),
                    physical=self._detect_physical(all_text),
                    specific_conditions=conditions(
                        ("Segmentos", ", ".join(segments_and_requirements)) if segments_and_requirements else None,
                        ("Requisitos", "; ".join(requirements)) if requirements else None,
                        ("Modalidades indicadas", ", ".join(x for x, enabled in (("QR", qr), ("NFC", nfc), ("contactless", contactless)) if enabled)) if (qr or nfc or contactless) else None,
                    ),
                    requires_merchant_verification=bool(detail.get("url") and requires_merchant_check(terms)),
                    terms=self._clean_text(terms) or None,
                )
            )

        return promotions

    def _build_variants(self, summary_groups: list[dict], legal_groups: list[dict], summary_text: str, legal_text: str) -> list[dict]:
        if summary_groups:
            variants = []

            for group in summary_groups:
                matching_terms = [
                    legal_group["text"]
                    for legal_group in legal_groups
                    if set(group["segments"]) & set(legal_group["segments"])
                ]

                variants.append(
                    {
                        "segments": group["segments"],
                        "benefit_text": group["text"],
                        "terms": "\n".join(matching_terms) or legal_text or None,
                    }
                )

            return variants

        if legal_groups:
            return [
                {
                    "segments": group["segments"],
                    "benefit_text": group["text"],
                    "terms": group["text"],
                }
                for group in legal_groups
            ]

        return [
            {
                "segments": [],
                "benefit_text": summary_text or legal_text,
                "terms": legal_text or None,
            }
        ]

    def _extract_summary_groups(self, text: str) -> list[dict]:
        lines = self._lines(text)
        groups = []
        current = None

        for line in lines:
            segments = self._segment_header(line)

            if segments:
                if current is not None and not current["lines"]:
                    for segment in segments:
                        if segment not in current["segments"]:
                            current["segments"].append(segment)

                    continue

                if current is not None:
                    groups.append(current)

                current = {
                    "segments": segments,
                    "lines": [],
                }

                continue

            if current is None:
                continue

            normalized = self._ascii(line)

            if normalized.startswith(
                (
                    "mas informacion",
                    "vigencia desde",
                    "vigencia hasta",
                    "terminos y condiciones",
                    "cantidad",
                    "comprar",
                )
            ):
                groups.append(current)
                current = None
                continue

            current["lines"].append(line)

        if current is not None:
            groups.append(current)

        return [
            {
                "segments": group["segments"],
                "text": "\n".join(group["lines"]),
            }
            for group in groups
            if group["segments"] and group["lines"]
        ]

    def _extract_legal_groups(self, text: str) -> list[dict]:
        lines = self._lines(text)
        groups = []
        current = None

        for line in lines:
            normalized = self._ascii(line)

            if normalized.startswith("legales patagonia"):
                if current is not None:
                    groups.append(current)

                current = {
                    "segments": self._segments_from_text(line),
                    "lines": [line],
                }

                continue

            if current is not None:
                current["lines"].append(line)

        if current is not None:
            groups.append(current)

        return [
            {
                "segments": group["segments"],
                "text": "\n".join(group["lines"]),
            }
            for group in groups
            if group["segments"]
        ]

    def _segment_header(self, line: str) -> list[str]:
        segments = self._segments_from_text(line)

        if not segments:
            return []

        remaining = self.SEGMENT_PATTERN.sub("", line)
        remaining = re.sub(r"[\s/|,+&-]+", "", remaining)

        return segments if not remaining else []

    def _segments_from_text(self, text: str) -> list[str]:
        segments = []

        for match in self.SEGMENT_PATTERN.finditer(text):
            value = self._ascii(match.group(1))

            if value == "clasica":
                segment = "clasica"
            elif value == "plus":
                segment = "plus"
            elif value == "singular":
                segment = "singular"
            elif value == "patagonia on":
                segment = "on"
            else:
                continue

            if segment not in segments:
                segments.append(segment)

        return segments

    def _variant_source_id(self, source_id: str, segments: list[str]) -> str:
        if not segments:
            return source_id

        return f"{source_id}:{'-'.join(segments)}"

    def _extract_validity(self, summary_text: str, scraped_at: str, legal_text: str = "", main_text: str = ""):
        full_date = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"

        range_patterns = [
            rf"(?:del|desde(?:\s+el)?)\s+({full_date})\s+(?:al|hasta(?:\s+el)?|a)\s+({full_date})",
            rf"vigencia(?:\s+desde)?\s*:?\s*({full_date})\s+(?:al|hasta|a|-)\s+({full_date})",
            rf"promoci[oó]n\s+v[aá]lida.*?(?:desde(?:\s+el)?)?\s*({full_date})\s+(?:al|hasta(?:\s+el)?|a)\s+({full_date})",
        ]

        for text in (summary_text, legal_text):
            clean = self._clean_text(text)

            for pattern in range_patterns:
                match = re.search(pattern, clean, re.IGNORECASE)

                if match:
                    return self._parse_date(match.group(1)), self._parse_date(match.group(2))

        summary_dates = list(dict.fromkeys(re.findall(full_date, summary_text)))

        if len(summary_dates) == 1:
            promotion_date = self._parse_date(summary_dates[0])
            return promotion_date, promotion_date

        single_day_patterns = [
            rf"promoci[oó]n.*?(?:estar[aá]\s+vigente|ser[aá]\s+v[aá]lida).*?({full_date})",
            rf"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)[,\s]+({full_date})",
        ]

        clean_legal = self._clean_text(legal_text)

        for pattern in single_day_patterns:
            match = re.search(pattern, clean_legal, re.IGNORECASE)

            if match:
                promotion_date = self._parse_date(match.group(1))
                return promotion_date, promotion_date

        textual_dates = self._extract_labeled_text_dates(main_text)

        if textual_dates is not None:
            return textual_dates

        short_date = r"\d{1,2}[./-]\d{1,2}"

        short_range_patterns = [
            rf"(?:del|desde(?:\s+el)?)\s+({short_date})\s+(?:al|hasta(?:\s+el)?|a)\s+({short_date})",
            rf"vigencia(?:\s+desde)?\s*:?\s*({short_date})\s+(?:al|hasta|a|-)\s+({short_date})",
        ]

        reference_year = datetime.fromisoformat(scraped_at).year

        for text in (summary_text, legal_text, main_text):
            clean = self._clean_text(text)

            for pattern in short_range_patterns:
                match = re.search(pattern, clean, re.IGNORECASE)

                if not match:
                    continue

                valid_from = self._parse_short_date(match.group(1), reference_year)
                valid_to = self._parse_short_date(match.group(2), reference_year)

                if valid_to < valid_from:
                    valid_to = self._parse_short_date(match.group(2), reference_year + 1)

                return valid_from, valid_to

        return None, None

    def _extract_labeled_text_dates(self, text: str):
        months = {
            "ene": 1,
            "feb": 2,
            "mar": 3,
            "abr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "ago": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dic": 12,
        }

        date_pattern = r"(\d{1,2})\s+([a-záéíóú]{3,})\.?\s+(\d{4})"

        from_match = re.search(rf"VIGENCIA\s+DESDE\s+{date_pattern}", text, re.IGNORECASE)
        to_match = re.search(rf"VIGENCIA\s+HASTA\s+{date_pattern}", text, re.IGNORECASE)

        if not from_match or not to_match:
            return None

        def parse(match):
            day = int(match.group(1))
            month_name = self._ascii(match.group(2))[:3]
            year = int(match.group(3))
            month = months.get(month_name)

            if month is None:
                return None

            return datetime(year, month, day).date()

        valid_from = parse(from_match)
        valid_to = parse(to_match)

        if valid_from is None or valid_to is None:
            return None

        return valid_from, valid_to

    def _parse_date(self, value: str):
        normalized = value.replace(".", "/").replace("-", "/")
        return datetime.strptime(normalized, "%d/%m/%Y").date()

    def _parse_short_date(self, value: str, year: int):
        normalized = value.replace(".", "/").replace("-", "/")
        return datetime.strptime(f"{normalized}/{year}", "%d/%m/%Y").date()

    def _extract_days(self, text: str) -> list[str]:
        normalized = self._ascii(text)

        if "todos los dias" in normalized:
            return self.ALL_DAYS.copy()

        range_match = re.search(
            r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+a\s+(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
            normalized,
        )

        if range_match:
            ordered_days = list(self.DAY_NAMES)
            start = ordered_days.index(range_match.group(1))
            end = ordered_days.index(range_match.group(2))

            if start <= end:
                return [self.DAY_NAMES[day] for day in ordered_days[start:end + 1]]

        return [
            english
            for spanish, english in self.DAY_NAMES.items()
            if re.search(rf"\b{spanish}s?\b", normalized)
        ]

    def _extract_discount(self, text: str) -> float | None:
        for match in re.finditer(r"(\d{1,3}(?:[.,]\d+)?)\s*%", text or ""):
            context_start = max(0, match.start() - 30)
            context = self._ascii((text or "")[context_start:match.end()])

            if "cft" in context:
                continue

            value = float(match.group(1).replace(",", "."))

            if 0 < value <= 100:
                return value

        return None

    def _extract_installments(self, text: str) -> int | None:
        matches = re.findall(r"(?:hasta\s+)?(\d{1,2})\s*cuotas?", text or "", re.IGNORECASE)

        if not matches:
            return None

        installments = max(int(value) for value in matches)

        return installments if installments > 1 else None

    def _extract_cap_amount(self, text: str) -> float | None:
        normalized = self._ascii(text)

        if "sin tope" in normalized:
            return None

        match = re.search(
            r"(?:tope(?:\s+de\s+(?:devoluci[oó]n|reintegro))?\s*:?\s*)\$\s*([0-9][0-9.,]*)",
            text or "",
            re.IGNORECASE,
        )

        if not match:
            return None

        return self._parse_amount(match.group(1))

    def _extract_cap_scope(self, text: str) -> str | None:
        normalized = self._ascii(text)

        if "sin tope" in normalized:
            return None

        if "por cuenta" in normalized:
            return "account"

        if "por cliente" in normalized or "por persona" in normalized:
            return "customer"

        if "por compra" in normalized:
            return "purchase"

        return None

    def _extract_cap_period(self, text: str) -> str | None:
        normalized = self._ascii(text)

        if "sin tope" in normalized:
            return None

        if "por mes" in normalized or "mensual" in normalized:
            return "monthly"

        if "por semana" in normalized or "semanal" in normalized:
            return "weekly"

        if "por dia" in normalized or "diario" in normalized:
            return "daily"

        return None

    def _extract_minimum_purchase(self, text: str) -> float | None:
        match = re.search(
            r"(?:compra\s+m[ií]nima|m[ií]nimo\s+de\s+compra)[^$]{0,40}\$\s*([0-9][0-9.,]*)",
            text or "",
            re.IGNORECASE,
        )

        if not match:
            return None

        return self._parse_amount(match.group(1))

    def _extract_payment_methods(self, text: str, image_alts: list[str]) -> list[PaymentMethod]:
        combined = self._ascii(text)
        normalized_alts = [self._ascii(alt) for alt in image_alts]
        methods = []

        def add(raw_name: str, network: str | None = None, card_type: str | None = None):
            method = PaymentMethod(
                raw_name=raw_name, network=network, card_type=card_type,
                issuer="Banco Patagonia" if card_type else None,
                wallet=raw_name if raw_name in {"MODO", "Google Pay", "Apple Pay"} else None,
                payment_rail="card" if card_type else None,
            )

            if method not in methods:
                methods.append(method)

        if "visa debito" in normalized_alts or "visa debito" in combined:
            add("Visa Débito", "visa", "debit")

        if "visa" in normalized_alts or "visa credito" in normalized_alts or "visa credito" in combined:
            add("Visa Crédito", "visa", "credit")

        if "mastercard debito" in normalized_alts or "mastercard debito" in combined:
            add("Mastercard Débito", "mastercard", "debit")

        if "mastercard" in normalized_alts or "mastercard credito" in normalized_alts or "mastercard credito" in combined:
            add("Mastercard Crédito", "mastercard", "credit")

        if (
            "amex" in normalized_alts
            or "american express" in normalized_alts
            or "amex" in combined
            or "american express" in combined
        ):
            add("American Express", "american_express", "credit")

        if "modo" in normalized_alts or "modo" in combined:
            add("MODO")

        if "google pay" in normalized_alts or "google pay" in combined:
            add("Google Pay")

        if "apple pay" in normalized_alts or "apple pay" in combined:
            add("Apple Pay")

        return methods

    def _extract_category(self, catalog: dict) -> str | None:
        categories = catalog.get("c")

        if isinstance(categories, list):
            for category in categories:
                clean = self._clean_text(category)

                if clean:
                    return clean

        if isinstance(categories, str):
            clean = self._clean_text(categories)

            if clean:
                return clean

        return None

    def _customer_segments(self, segments: list[str], text: str) -> list[str]:
        result = list(segments)
        normalized = self._ascii(text)

        salary_patterns = [
            "acreditar tu sueldo",
            "acrediten el sueldo",
            "acreditacion de haberes",
            "plan sueldo",
        ]

        if any(pattern in normalized for pattern in salary_patterns) and "salary" not in result:
            result.append("salary")

        return result

    def _extract_requirements(self, summary_text: str) -> list[str]:
        requirements = []

        for line in self._lines(summary_text):
            normalized = self._ascii(line)

            if normalized.startswith("exclusiv"):
                requirements.append(line)

        return requirements

    def _extract_terms_from_main(self, main_text: str) -> str:
        if not main_text:
            return ""

        match = re.search(r"T[eé]rminos\s+y\s+Condiciones\s*(.*)", main_text, re.IGNORECASE | re.DOTALL)

        if not match:
            return ""

        terms = match.group(1)

        stop_markers = [
            "Available stores are loading",
            "Ver todas las tiendas disponibles",
        ]

        for marker in stop_markers:
            position = terms.find(marker)

            if position != -1:
                terms = terms[:position]

        return terms.strip()

    def _detect_online(self, text: str) -> bool:
        normalized = self._ascii(text)

        negative_patterns = [
            r"no valido.{0,80}(?:online|venta online|tienda online)",
            r"no valida.{0,80}(?:online|venta online|tienda online)",
            r"no aplica.{0,80}(?:online|venta online|tienda online)",
            r"exclusivamente.{0,150}sucursales fisicas",
        ]

        if any(re.search(pattern, normalized) for pattern in negative_patterns):
            return False

        if "www." in normalized or "http://" in normalized or "https://" in normalized:
            return True

        return bool(
            re.search(
                r"\b(?:online|sitio web|pagina web|tienda online|venta online)\b",
                normalized,
            )
        )

    def _detect_physical(self, text: str) -> bool:
        normalized = self._ascii(text)

        return bool(
            re.search(
                r"\b(?:local|locales|comercio|comercios|sucursal|sucursales|tienda|tiendas)\b",
                normalized,
            )
        )

    def _detect_qr(self, text: str) -> bool:
        normalized = self._ascii(text)

        for match in re.finditer(r"\bqr\b", normalized):
            context = normalized[max(0, match.start() - 150):match.end() + 50]

            negative_terms = [
                "no aplica",
                "no aplicable",
                "no valido",
                "no valida",
                "excepto",
                "excluye",
            ]

            if any(term in context for term in negative_terms):
                continue

            return True

        return False

    def _contains(self, text: str, term: str) -> bool:
        return self._ascii(term) in self._ascii(text)

    def _parse_amount(self, value: str) -> float | None:
        text = self._clean_text(value).replace("$", "").replace(" ", "")

        if not text:
            return None

        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(".", "")

        try:
            amount = float(text)
        except ValueError:
            return None

        return amount if amount else None

    def _lines(self, text: str) -> list[str]:
        return [line for raw_line in (text or "").splitlines() if (line := self._clean_text(raw_line))]

    def _clean_text(self, value) -> str:
        if value is None:
            return ""

        text = html.unescape(str(value))
        text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")

        return re.sub(r"\s+", " ", text).strip()

    def _ascii(self, value) -> str:
        text = self._clean_text(value).lower()

        return "".join(
            character
            for character in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(character)
        )