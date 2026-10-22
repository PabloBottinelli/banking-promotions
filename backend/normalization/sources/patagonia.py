import html
import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from normalization.models import NormalizedPromotion, PaymentMethod, Benefit, PromotionLimit
from normalization.structure import make_benefits, make_limits, conditions, requires_merchant_check
from scraping.sources.patagonia.text import legal_header_segments, strip_legal_headers


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
        rows = self._normalize_detail(raw)
        represented = {segment for row in rows for segment in self._segments_from_conditions(row.specific_conditions)}
        for extra in raw.get("storefront_details", []):
            target = extra["catalog"].get("segment")
            if target in represented:
                continue
            candidate = {**raw, **extra}
            candidate.pop("storefront_details", None)
            for row in self._normalize_detail(candidate):
                segments = self._segments_from_conditions(row.specific_conditions)
                if target in segments:
                    rows.append(row)
                    represented.update(segments)
        conflicts = self._storefront_conflicts(raw)
        if conflicts:
            for row in rows:
                if set(self._segments_from_conditions(row.specific_conditions)) & set(conflicts):
                    row.benefits = [Benefit(type=b.type, description="Condiciones oficiales contradictorias entre storefronts; consultar ambas fichas y solicitar revisión humana") for b in row.benefits]
                    row.limits = []
                    row.payment_methods = []
                    row.days_of_week = []
                    row.applies_every_day = None
                    row.online = row.physical = None
                    row.valid_from = row.valid_to = None
                    row.specific_conditions = (row.specific_conditions or "") + "\nRevisión humana: condiciones contradictorias entre storefronts oficiales"
        if raw.get("storefront_details"):
            terms = [raw["detail"].get("description_text") or self._extract_terms_from_main(raw["detail"].get("main_text") or "")]
            for extra in raw["storefront_details"]:
                detail = extra["detail"]
                terms.append(detail["url"] + "\n" + (detail.get("description_text") or self._extract_terms_from_main(detail.get("main_text") or "")))
            for row in rows:
                row.terms = "\n\n".join(terms)
                row.promotion_group_id = str(raw["source_id"]) if len(rows) > 1 else row.promotion_group_id
        return rows

    def _segments_from_conditions(self, text):
        first = (text or "").splitlines()[0] if text else ""
        return [segment for segment in ("clasica", "plus", "singular", "on") if re.search(rf"\b{segment}\b", first)]

    def _segment_signatures(self, raw):
        detail = raw["detail"]
        summary = detail.get("summary_text") or ""
        legal = detail.get("description_text") or self._extract_terms_from_main(detail.get("main_text") or "")
        groups = self._build_variants(self._extract_summary_groups(summary), self._extract_legal_groups(legal), summary, legal)
        result = {}
        for group in groups:
            terms = strip_legal_headers(group["terms"] or "")
            header_requirements = set()
            for line in (group["terms"] or "").splitlines():
                if legal_header_segments(line) is not None:
                    normalized_header = self._ascii(line)
                    if re.search(r"\bplan\s+sueldos?\b", normalized_header):
                        header_requirements.add("plan sueldo")
                    if re.search(r"\bjubilados?\b", normalized_header):
                        header_requirements.add("jubilados")
            signature = (self._clean_text(group["benefit_text"]), self._clean_text(terms), tuple(sorted(header_requirements)), tuple(self._extract_days(summary)), tuple(self._validity_candidates(summary, raw["scraped_at"], legal, detail.get("main_text") or "")))
            for segment in group["segments"]:
                result[segment] = signature
        return result

    def _storefront_conflicts(self, raw):
        observed = self._segment_signatures(raw)
        conflicts = []
        for extra in raw.get("storefront_details", []):
            candidate = {**raw, **extra}
            candidate.pop("storefront_details", None)
            for segment, signature in self._segment_signatures(candidate).items():
                if segment in observed and observed[segment] != signature:
                    conflicts.append(segment)
                observed.setdefault(segment, signature)
        return list(dict.fromkeys(conflicts))

    def _normalize_detail(self, raw: dict) -> list[NormalizedPromotion]:
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
        variants = self._split_numbered_benefits(variants)

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
            if variant.get("benefit_identity"):
                source_id += ":" + variant["benefit_identity"]

            cap_amount = self._extract_cap_amount(variant_text)
            requirements = self._extract_requirements(summary_text)
            segments_and_requirements = self._customer_segments(segments, variant_text + "\n" + "\n".join(requirements))
            qr = self._detect_qr(variant_text)
            nfc = self._contains(variant_text, "nfc")
            contactless = self._contains(variant_text, "contactless") or self._contains(variant_text, "sin contacto")
            days = self._extract_days(summary_text or variant_text)
            legal_days = self._extract_days(terms or "")
            if days and legal_days and set(days) != set(legal_days):
                days = []
            payment_methods = self._extract_payment_methods(variant_text + "\n" + "\n".join(requirements), detail.get("image_alts", []))
            nfc = nfc or any(method.payment_rail == "nfc" for method in payment_methods)
            review = self.review_issues(raw)
            legal_discount = self._extract_discount(terms or "")
            conflict = discount is not None and legal_discount is not None and discount != legal_discount
            benefits = make_benefits(
                percentage=None if conflict else discount, installments=installments,
                benefit_text=variant_text,
                fallback_description=benefit_text or terms or title,
            )
            mechanism = self._benefit_mechanism(variant_text)
            for benefit in benefits:
                if benefit.type in ("discount", "cashback"):
                    benefit.type = mechanism
            if variant.get("benefit_identity"):
                for benefit in benefits:
                    benefit.description = " ".join(clause for clause in self._clauses(benefit_text) if re.search(r"descuento|hotel|actividad|codigo|financiacion|cuotas sin interes", self._ascii(clause)) and not re.search(r"tasa|c[.]?f[.]?t", self._ascii(clause)))
            if conflict:
                benefits = [b for b in benefits if b.type != "other"]
                benefits.insert(0, Benefit(type="cashback" if re.search(r"reintegro|devoluci[oó]n", variant_text, re.I) else "discount", description=f"Porcentaje contradictorio: resumen {discount}%; legales {legal_discount}%. Requiere revisión humana."))
            summary_cap = self._extract_cap_amount(benefit_text)
            legal_cap = self._extract_cap_amount(terms or "")
            cap_conflict = summary_cap is not None and legal_cap is not None and summary_cap != legal_cap
            if cap_conflict:
                cap_amount = None
            if conflict or cap_conflict:
                review.append("Beneficio o tope contradictorio entre resumen y condiciones legales")
            if installments is not None and self._extract_installments(terms or "") is not None and self._extract_installments(terms or "") != installments:
                benefits = [b for b in benefits if b.type != "installments"]
                benefits.append(Benefit(type="installments", description="Cantidad de cuotas contradictoria entre resumen y legales; requiere revisión humana"))
            merchant_check = bool(detail.get("url") and (requires_merchant_check(terms) or re.search(r"\b(?:locales|sucursales|comercios)\s+adheridios\b", terms or "", re.I)))
            limits = make_limits(cap_amount=cap_amount, cap_scope=self._extract_cap_scope(variant_text), cap_period=self._extract_cap_period(variant_text), minimum_purchase=self._extract_minimum_purchase(variant_text))
            stock = re.search(r"\bstock\s+(?:de\s+)?(\d+)\s+unidades\b", variant_text, re.I)
            if stock:
                limits.append(PromotionLimit(type="stock", quantity=int(stock.group(1)), period="promotion", scope="campaign", description=stock.group(0)))
            for clause in self._clauses(variant_text):
                normalized_clause = self._ascii(clause)
                if re.search(r"\b(?:unica|una sola)\s+vez\b", normalized_clause):
                    period = "promotion" if re.search(r"durante[^.;]{0,80}(?:vigencia|promocion)", normalized_clause) else None
                    limits.append(PromotionLimit(type="usage_count", quantity=1, period=period, description=clause))
            limits.extend(self._extract_ticket_limits(variant_text))
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
                    benefits=benefits,
                    limits=limits,
                    payment_methods=payment_methods,
                    days_of_week=days,
                    applies_every_day=(len(days) == 7) if days else None,
                    online=self._detect_online(variant_text),
                    physical=self._detect_physical(variant_text),
                    specific_conditions=conditions(
                        ("Segmentos", ", ".join(segments_and_requirements)) if segments_and_requirements else None,
                        ("Requisitos", "; ".join(requirements)) if requirements else None,
                        ("Modalidades indicadas", ", ".join(x for x, enabled in (("QR", qr), ("NFC", nfc), ("contactless", contactless)) if enabled)) if (qr or nfc or contactless) else None,
                        ("Restricciones", "; ".join(self._restriction_clauses(terms or ""))) if terms else None,
                        ("Comercios", "Consultar locales/sucursales adheridos en la ficha oficial") if merchant_check else None,
                        ("Revisión humana", "; ".join(dict.fromkeys(review))) if review else None,
                    ),
                    requires_merchant_verification=merchant_check,
                    terms=legal_text or None,
                )
            )

        return promotions

    def _split_numbered_benefits(self, variants):
        result = []
        for variant in variants:
            parts = re.split(r"\(\d+\)\s*", variant.get("terms") or "")[1:]
            offers = []
            for part in parts:
                discount = self._extract_discount(part)
                installments = self._extract_installments(part)
                if discount is None and installments is None:
                    continue
                identity = "discount-installments" if discount is not None and installments is not None else "discount" if discount is not None else "installments"
                offers.append({**variant, "benefit_text": part, "terms": part, "benefit_identity": identity})
            identities = [offer["benefit_identity"] for offer in offers]
            result.extend(offers if len(offers) > 1 and len(set(identities)) == len(identities) else [variant])
        return result

    def _benefit_mechanism(self, text):
        normalized = self._ascii(text)
        if re.search(r"descuento[^.;]{0,100}(?:carrito|en el acto|inmediato)|aplica en el momento de la compra", normalized):
            return "discount"
        if re.search(r"reintegros? correspondientes|bonificaciones se acreditaran|importe ahorrado[^.;]*acreditado", normalized):
            return "cashback"
        for clause in self._clauses(text):
            normalized_clause = self._ascii(clause)
            if re.search(r"\d\s*%[^.;]{0,25}(?:de )?(?:reintegro|cashback|devolucion)|(?:reintegro|cashback|devolucion)[^.;]{0,25}\d+\s*%", normalized_clause) and "tope" not in normalized_clause:
                return "cashback"
        return "discount"

    def _build_variants(self, summary_groups: list[dict], legal_groups: list[dict], summary_text: str, legal_text: str) -> list[dict]:
        if summary_groups:
            variants = []

            for group in summary_groups:
                matching_groups = [g for g in legal_groups if set(group["segments"]) & set(g["segments"])]
                if len(matching_groups) > 1:
                    for legal_group in matching_groups:
                        variants.append({"segments": [s for s in group["segments"] if s in legal_group["segments"]], "benefit_text": group["text"], "terms": legal_group["text"]})
                    continue
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

            header_segments = legal_header_segments(line)
            if header_segments is not None:
                if current is not None:
                    groups.append(current)

                current = {
                    "segments": header_segments,
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

        ordered = [s for s in ("clasica", "plus", "singular", "on") if s in segments]
        return f"{source_id}:{'-'.join(ordered)}"

    def _extract_validity(self, summary_text: str, scraped_at: str, legal_text: str = "", main_text: str = ""):
        candidates = self._validity_candidates(summary_text, scraped_at, legal_text, main_text)
        return candidates[0] if len(set(candidates)) == 1 else (None, None)

    def _validity_candidates(self, summary_text, scraped_at, legal_text="", main_text=""):
        values = []
        for text in (summary_text, legal_text):
            result = self._extract_validity_value(text, scraped_at)
            if result != (None, None):
                values.append(result)
        labeled = self._extract_labeled_text_dates(main_text)
        if labeled is not None:
            values.append(labeled)
        return values

    def review_issues(self, raw: dict) -> list[str]:
        detail = raw["detail"]
        summary = detail.get("summary_text") or ""
        main = detail.get("main_text") or ""
        legal = detail.get("description_text") or self._extract_terms_from_main(main)
        issues = []
        if self._storefront_conflicts(raw):
            issues.append("Condiciones contradictorias entre storefronts oficiales")
        for extra in raw.get("storefront_details", []):
            candidate = {**raw, **extra}
            candidate.pop("storefront_details", None)
            issues.extend(self.review_issues(candidate))
        dates = self._validity_candidates(summary, raw["scraped_at"], legal, main)
        if len(set(dates)) > 1:
            issues.append("Vigencias contradictorias entre resumen, tabla y legales; consultar ficha oficial")
        groups = self._build_variants(self._extract_summary_groups(summary), self._extract_legal_groups(legal), summary, legal)
        for group in groups:
            days_a, days_b = self._extract_days(summary), self._extract_days(group["terms"] or "")
            if days_a and days_b and set(days_a) != set(days_b):
                issues.append("Días contradictorios entre resumen y legales")
            for name, parser in (("porcentaje", self._extract_discount), ("tope", self._extract_cap_amount), ("cuotas", self._extract_installments)):
                a, b = parser(group["benefit_text"]), parser(group["terms"] or "")
                if a is not None and b is not None and a != b:
                    issues.append(f"{name.capitalize()} contradictorio entre resumen y legales")
        return list(dict.fromkeys(issues))

    def _extract_validity_value(self, summary_text: str, scraped_at: str, legal_text: str = "", main_text: str = ""):
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

        summary_dates = list(dict.fromkeys(self._parse_date(value) for value in re.findall(full_date, summary_text)))

        if len(summary_dates) == 1:
            promotion_date = summary_dates[0]
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
        normalized = self._ascii(" ".join(clause for clause in self._clauses(text) if not re.search(r"no (?:aplica|valida?|incluye)|excepto|excluy", self._ascii(clause))))

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

    def _extract_discount(self, text: str) -> Decimal | None:
        for match in re.finditer(r"(\d{1,3}(?:[.,]\d+)?)\s*%", text or ""):
            clause_start = max((text or "").rfind("\n", 0, match.start()), (text or "").rfind(". ", 0, match.start())) + 1
            clause_end = (text or "").find("\n", match.end())
            clause = (text or "")[clause_start:clause_end if clause_end >= 0 else len(text)]
            context = self._ascii(text[max(clause_start, match.start() - 75):match.end() + 65])
            preceding = self._ascii(text[max(clause_start, match.start() - 65):match.start()])
            if re.search(r"c[.]?f[.]?t|tasa|ejemplo|seguro de vida|interes anual|iva|\btna\b|\btea\b", preceding):
                continue
            if not (re.search(r"descuento|reintegro|devolucion|cashback|bonificacion|ahorro", context) or re.fullmatch(r"\s*\d{1,3}(?:[.,]\d+)?\s*%\s*", clause)):
                continue
            value = Decimal(match.group(1).replace(",", "."))

            if 0 < value <= 100:
                return value

        return None

    def _extract_installments(self, text: str) -> int | None:
        matches = re.findall(r"(?:hasta\s+)?(\d{1,2})\s*cuotas?", text or "", re.IGNORECASE)
        words = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "nueve": 9, "doce": 12, "dieciocho": 18, "veinticuatro": 24}
        matches += [str(value) for word, value in words.items() if re.search(rf"\b{word}\s+cuotas?\b", self._ascii(text))]

        if not matches:
            return None

        installments = max(int(value) for value in matches)

        return installments if installments > 1 else None

    def _extract_cap_amount(self, text: str) -> float | None:
        normalized = self._ascii(text)

        if "sin tope" in normalized:
            return None

        match = re.search(
            r"(?:tope(?:\s+(?:de\s+)?(?:devoluci[oó]n|reintegro))?)(?:\s+(?:por|de)\s+(?:cuenta|mes|cliente|persona|compra|plazo de vigencia)){0,4}\s*(?:de)?\s*:?\s*\$\s*([0-9][0-9.,]*)",
            text or "",
            re.IGNORECASE,
        )

        if not match:
            return None

        return self._parse_amount(match.group(1))

    def _extract_cap_scope(self, text: str) -> str | None:
        normalized = self._ascii(self._cap_clause(text))

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
        normalized = self._ascii(self._cap_clause(text))

        if "sin tope" in normalized:
            return None

        if "por mes" in normalized or "mensual" in normalized:
            return "monthly"

        if "por semana" in normalized or "semanal" in normalized:
            return "weekly"

        if "por dia" in normalized or "diario" in normalized:
            return "daily"

        if "por plazo de vigencia" in normalized or "por vigencia" in normalized:
            return "promotion"

        return None

    def _cap_clause(self, text: str) -> str:
        clauses = [clause for clause in self._clauses(text) if "tope" in self._ascii(clause) and "$" in clause]
        return clauses[-1] if clauses else ""

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
        methods = []
        normalized = self._ascii(text)
        networks = {"visa": "visa", "mastercard": "mastercard", "master": "mastercard", "american express": "american_express", "amex": "american_express"}
        wallet_names = {"modo": "MODO", "google pay": "Google Pay", "apple pay": "Apple Pay"}
        required_rail = "nfc" if re.search(r"\bexclusiv\w*\s+nfc\b", normalized) else "qr" if re.search(r"\bexclusiv\w*\s+qr\b", normalized) else None
        exclusive_wallets = set()
        exclusive_combinations = set()

        def add(clause, network, card_type, wallet=None, rail="card", issuer="Banco Patagonia"):
            method = PaymentMethod(raw_name=self._clean_text(clause), issuer=issuer, network=network, card_type=card_type, wallet=wallet, payment_rail=rail)
            identity = (network, card_type, wallet, rail)
            if not any((m.network, m.card_type, m.wallet, m.payment_rail) == identity for m in methods):
                methods.append(method)

        clauses = sorted(self._clauses(text), key=lambda clause: bool(re.search(r"reintegros? correspondientes|bonificaciones se acreditaran", self._ascii(clause))))
        for clause in clauses:
            n = self._ascii(clause)
            if not re.search(r"tarjetas?|patagonia 24", n):
                continue
            if re.search(r"no (?:aplica|valido|valida)|se excluye|no incluye", n):
                continue
            settlement = bool(re.search(r"reintegros? correspondientes|bonificaciones se acreditaran", n))
            holder_eligibility = bool(re.search(r"\b(?:titulares|tarjetahabientes)\b", n) and re.search(r"\b(?:exclusiv\w*|elegibles|reservad\w*|aplica solo|tienen acceso)\b", n))
            positive_eligibility = bool(re.search(r"\b(?:abonando|abonadas|pagando)\b|(?:recibir|descuento|financiacion|beneficio)[^.;]{0,160}\bcon\b|\bvalida?[^.;]{0,70}\bcon\b", n) or ("promocion valida" in n and "compras" in n) or holder_eligibility)
            if not positive_eligibility and not settlement:
                continue
            cards = []
            for match in re.finditer(r"\b(credito|debito)\b|patagonia 24", n):
                kind = "debit" if match.group(0) == "patagonia 24" or match.group(1) == "debito" else "credit"
                tail = n[match.end():]
                if re.match(r"\s+y\s+(?:mastercard|master|visa|american express)\b", tail):
                    tail = ""
                tail = re.split(r"\btarjetas?\b|\b(?:credito|debito|abonando|pagando|emitidas|del banco|de banco)\b", tail, maxsplit=1)[0]
                listed = list(dict.fromkeys(v for k, v in networks.items() if re.search(rf"\b{k}\b", tail)))
                cards.extend((network, kind) for network in (listed or [None]))
            for label, network in networks.items():
                for match in re.finditer(rf"\b{label}\s+(?:de\s+)?(credito|debito)\b", n):
                    cards.append((network, "credit" if match.group(1) == "credito" else "debit"))
            cards = list(dict.fromkeys(cards))
            if not cards and holder_eligibility:
                for label, network in networks.items():
                    if re.search(rf"\b{label}\b", n):
                        add(clause, network, None, rail=None, issuer="Banco Patagonia" if "banco patagonia" in n else None)
            if settlement:
                for network, kind in cards:
                    if network is not None:
                        for method in list(methods):
                            if method.network is None and method.card_type == kind:
                                add(clause, network, kind, method.wallet, method.payment_rail)
                continue
            wallets = [name for token, name in wallet_names.items() if re.search(rf"\b{token}\b", n)]
            rail = "nfc" if re.search(r"nfc|contactless|sin contacto", n) else "qr" if re.search(r"\bqr\b|codigos de respuesta rapida", n) else required_rail
            wallet_required = bool(wallets and re.search(r"(?:abonando|pagando|a traves|mediante|con) (?:exclusiv\w* )?(?:con |de )?(?:google pay|apple pay|modo)", n))
            if wallets and wallet_required and re.search(r"\bexclusiv\w*\b", n):
                exclusive_wallets.update(wallets)
                exclusive_combinations.update((network, kind, wallet) for network, kind in cards for wallet in wallets)
            for network, kind in cards:
                if wallet_required:
                    for wallet in wallets:
                        add(clause, network, kind, wallet, rail)
                else:
                    add(clause, network, kind, rail=rail or "card")

        for clause in clauses:
            n = self._ascii(clause)
            exception = re.search(r"ex(?:c)?epcion de", n)
            if not exception or "billeteras" not in n:
                continue
            wallets = [name for token, name in wallet_names.items() if token in n[exception.end():]]
            restricted_type = "credit" if "tarjetas de credito" in n else "debit" if "tarjetas de debito" in n else None
            for method in list(methods):
                if method.wallet is None and (restricted_type is None or method.card_type == restricted_type):
                    for wallet in wallets:
                        add(clause, method.network, method.card_type, wallet, None)
        if exclusive_wallets:
            methods = [method for method in methods if method.wallet in exclusive_wallets and (method.network, method.card_type, method.wallet) in exclusive_combinations]
            if required_rail:
                for method in methods:
                    method.payment_rail = required_rail
        return [method for index, method in enumerate(methods) if not (method.network is None and any(m.network is not None and (m.card_type, m.wallet, m.payment_rail) == (method.card_type, method.wallet, method.payment_rail) for m in methods)) and not any((m.network, m.card_type, m.wallet, m.payment_rail) == (method.network, method.card_type, method.wallet, method.payment_rail) for m in methods[:index])]

    def _clauses(self, text: str) -> list[str]:
        text = re.sub(r"\bS\.\s*A\.", "S․A․", text or "", flags=re.I)
        return [self._clean_text(s).replace("S․A․", "S.A.") for s in re.split(r"(?<=[.;])\s+|\n+", text) if self._clean_text(s)]

    def _restriction_clauses(self, text: str) -> list[str]:
        return [s for s in self._clauses(text) if re.search(r"exclusiv|se excluy|no (?:aplica|incluye|acumulable|valido|valida)|programando|compra minima|codigo|cupon|cuenta (?:abierta|activa)|precio corpor|(?:unica|una sola) vez|ciudad|provincia|stock|sucursales adher|locales adher|comercios adher|no deberan registrar mora|\bblack\b|world legend|priceless|\breserva\b|\bpalcos?\b|\basientos?\b|\bbutacas?\b|\btraslado\b|\bentradas\b|\bvisita\b|\bfamiliar(?:es)?\b|\btickets?\b", self._ascii(s))]

    def _extract_ticket_limits(self, text: str) -> list[PromotionLimit]:
        limits = []
        seen = set()
        for clause in self._clauses(text):
            match = re.search(r"\b(?:tope de venta|maximo(?: de)?)\s*:?\s*(\d+)\s*(?:\([^)]*\)\s*)?(?:tickets?|entradas?)\s+por\s+(persona|cliente|cuenta)\b", self._ascii(clause))
            if not match:
                continue
            quantity = int(match.group(1))
            scope = "account" if match.group(2) == "cuenta" else "person"
            identity = (quantity, scope, self._ascii(clause))
            if identity not in seen:
                limits.append(PromotionLimit(type="other", quantity=quantity, scope=scope, description=clause))
                seen.add(identity)
        return limits

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

    def _channel(self, text: str, channel: str) -> bool | None:
        positive = negative = False
        target = r"(?:online|on line|venta online|tienda online|compras web|www\.[a-z0-9.-]+|https?://[^\s,;]+)" if channel == "online" else r"(?:presenciales|presencial|locales|sucursales|tiendas fisicas)"
        for clause in self._clauses(text):
            n = self._ascii(clause)
            if not re.search(target, n):
                continue
            if re.search(r"billeteras|portales de pago|plataformas de pago", n):
                continue
            if re.search(rf"(?:no\s+(?:(?:es|son)\s+)?valid[oa]s?\b|no aplica\b|excluye\b)[^.;]{{0,65}}{target}", n):
                negative = True
            elif re.search(rf"(?:compras?|promocion valida|vigente|valida? (?:en|para)|abonando|descuento[^.;]{{0,70}}en)[^.;]{{0,150}}{target}", n):
                positive = True
            elif re.search(rf"promocion valida en[^;]{{0,150}}{target}", n):
                positive = True
            elif re.search(rf"\b(?:entradas|tickets|compras|productos)\b[^.;]{{0,80}}\b(?:adquirid[oa]s?|comprad[oa]s?)\s+(?:exclusiv\w+\s+|unicamente\s+)?en\s+{target}", n):
                positive = True
        if channel == "online" and re.search(r"exclusivamente[^.;]{0,60}(?:sucursales fisicas|compras presenciales|locales fisicos)", self._ascii(text)):
            negative = True
        return None if positive == negative else positive

    def _detect_online(self, text: str) -> bool | None:
        return self._channel(text, "online")

    def _detect_physical(self, text: str) -> bool | None:
        return self._channel(text, "physical")

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

    def _parse_amount(self, value: str) -> Decimal | None:
        text = self._clean_text(value).replace("$", "").replace(" ", "")

        if not text:
            return None

        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(".", "")

        try:
            amount = Decimal(text)
        except ArithmeticError:
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
