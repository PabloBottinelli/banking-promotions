"""Deterministic normalization of MODO's native benefit / offer API.

Native offer IDs, not titles or percentages, identify conditional variants.
Unknown native outcome/limit types fail the candidate rather than disappearing.
"""
import json
import re
import copy
import hashlib
from datetime import date, datetime
from decimal import Decimal

from bs4 import BeautifulSoup

from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PERIODS = {"day": "daily", "week": "weekly", "month": "monthly", "promo": "promotion", "year": "yearly"}
SCOPES = {"user": "person", "account": "account", "card": "card", "bank": "bank", "promotion": "campaign"}
NETWORKS = {"visa": "Visa", "master": "Mastercard", "american_express": "American Express", "cabal": "Cabal",
            "maestro": "Maestro", "dinners_club": "Diners Club", "naranja": "Naranja", "confiable": "Confiable", "patagonia_365": "Patagonia 365"}
SPANISH_DAYS = {"lunes": "monday", "martes": "tuesday", "miércoles": "wednesday", "miercoles": "wednesday",
                "jueves": "thursday", "viernes": "friday", "sábado": "saturday", "sabado": "saturday", "domingo": "sunday"}


def plain(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def number(value):
    return Decimal(str(value)) if value is not None else None


def currency_for(detail):
    # The API omits currency. Do not turn an unknown denomination into ARS.
    s = plain(detail.get("terms_and_conditions")) + " " + plain(detail.get("description"))
    if re.search(r"\bUSD\b|US\$|d[oó]lares", s, re.I):
        return "USD" if not re.search(r"pesos|ARS", s, re.I) else None
    if re.search(r"\bARS\b|\bpesos\b|(?<!US)\$", s, re.I):
        return "ARS"
    return None


class ModoNormalizer:
    @staticmethod
    def legal_validity(detail):
        """Only explicit campaign validity, never publication or credit deadlines."""
        legal = plain(detail.get("terms_and_conditions"))
        match = re.search(
            r"promoci[oó]n\s+(?:v[aá]lida\b[^.;]*?|tendr[aá]\s+vigencia\s+)"
            r"(?:desde\s+el|del)\s+(\d{2}/\d{2}/\d{4})\s+(?:al|hasta\s+el)\s+(\d{2}/\d{2}/\d{4})", legal, re.I)
        if not match:
            return {}
        if re.search(r"\b(?:no|excepto)\s*$", legal[:match.start()], re.I):
            return {}
        return {key: datetime.strptime(value, "%d/%m/%Y").date().isoformat()
                for key, value in zip(("start_date", "stop_date"), match.groups())}

    @classmethod
    def validity_conflicts(cls, detail):
        schedule = (detail.get("conditions") or {}).get("schedule") or {}
        return {key: (value, schedule[key]) for key, value in cls.legal_validity(detail).items()
                if schedule.get(key) and value != schedule[key]}

    @staticmethod
    def legal_weekdays(detail):
        """Only an explicit positive 'Válida para ... comprendidos' clause.

        Do not search every weekday appearing in exclusions or generic boilerplate.
        """
        legal = plain(detail.get("terms_and_conditions"))
        clause = re.search(r"v[aá]lid[ao]\s+para\s+((?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)(?:\s*[,y]\s*|\s+)?)+)\s+comprendid[oa]s?", legal, re.I)
        if not clause:
            return None
        if re.search(r"\b(?:no|excepto)\s*$", legal[:clause.start()], re.I):
            return None
        return [SPANISH_DAYS[x.casefold()] for x in re.findall(r"\b(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b", clause[1], re.I)]

    @classmethod
    def evidence_conflicts(cls, detail):
        """Detect narrowly evidenced legal/engine contradictions; never repair rates by guessing."""
        legal = plain(detail.get("terms_and_conditions"))
        conflicts = []
        for key, (legal_date, native_date) in cls.validity_conflicts(detail).items():
            label = "inicio" if key == "start_date" else "fin"
            conflicts.append(f"Conflicto de vigencia ({label}): el legal publica {legal_date} y el calendario técnico {native_date}; vigencia pendiente de aclaración oficial.")
        tna = re.search(r"tasa\s+nominal\s+anual\s*\(TNA\)\s*(?:fija\s*)?(\d+(?:[.,]\d+)?)\s*%", legal, re.I)
        if tna:
            rates = {number(i["annual_nominal_rate"]) for o in detail["offers"]
                     for i in o.get("outcomes", {}).get("financing", {}).get("installments", [])
                     if i.get("annual_nominal_rate") is not None}
            if rates and Decimal(tna[1].replace(",", ".")) not in rates:
                conflicts.append("La TNA del legal (" + tna[1] + "%) difiere de la TNA técnica (" + ", ".join(str(x) + "%" for x in sorted(rates)) + "); consultar financiación oficial.")
        # An explicit reimbursement aggregation clause is independent of its amount.
        # Do not silently replace the native cap or extend the claim to usage counts.
        aggregation = re.search(r"(?:el\s+)?reintegro\s+es\s+por\s+(cuenta|usuario|tarjeta)\s+por\s+(mes|d[ií]a|semana)\b", legal, re.I)
        if aggregation:
            legal_scope = {"cuenta": "account", "usuario": "person", "tarjeta": "card"}[aggregation[1].casefold()]
            legal_period = {"mes": "monthly", "día": "daily", "dia": "daily", "semana": "weekly"}[aggregation[2].casefold()]
            caps = [o.get("limits", {}).get("period_cap") for o in detail["offers"] if o.get("limits")]
            if any(c and number(c.get("amount_by_period")) and
                   (SCOPES.get(c.get("aggregate_by"), c.get("aggregate_by")) != legal_scope or
                    PERIODS.get(c.get("reset_by"), c.get("reset_by")) != legal_period) for c in caps):
                conflicts.append("El legal indica «" + aggregation[0] + "»; el ámbito/período del tope técnico difiere. No se ha resuelto esta contradicción: verificar con el banco.")
        native_rates = {number(o.get("outcomes", {}).get("cashback", {}).get("amount")) for o in detail["offers"]
                        if o.get("outcomes", {}).get("cashback", {}).get("amount_type") == "percent"}
        for rate in re.findall(r"(?:promoci[oó]n(?:\s+del)?|beneficio(?:\s+del)?)\s+(\d+(?:[.,]\d+)?)\s*%\s+(?:de\s+)?(?:ahorro|reintegro|descuento)", legal, re.I):
            if Decimal(rate.replace(",", ".")) not in native_rates:
                conflicts.append("El legal publica " + rate + "% de ahorro/reintegro/descuento no representado por la oferta técnica.")
        days = cls.legal_weekdays(detail)
        if days is not None and set(days) != set(detail.get("conditions", {}).get("schedule", {}).get("days_of_week", [])):
            conflicts.append("Los días del legal y del calendario técnico difieren; consultar el legal antes de comprar.")
        marca_cap = re.search(r"(\d[\d.,]*)\s+en\s+total\s+por\s+marca\s+mientras\s+dure\s+la\s+promoci[oó]n", legal, re.I)
        native_caps = [o.get("limits") for o in detail["offers"] if o.get("limits")]
        if marca_cap and not native_caps:
            conflicts.append("El legal publica un tope total por marca de " + marca_cap[1] + " ausente en los límites técnicos.")
        return list(dict.fromkeys(conflicts))

    @staticmethod
    def _offers(detail):
        """Explicit FAQ segment tables can be richer than the engine's one offer.

        Recognize only complete rate + named eligibility + cap + period clauses.
        A segment's name identifies it independently of changing financial values.
        """
        faq = plain((detail.get("details") or {}).get("faq"))
        clauses = re.findall(r"(\d+(?:[.,]\d+)?)%\s+de\s+reintegro\s+para\s+(.+?)\.\s*Tope\s*\$\s*([\d.,]+)\s+por\s+usuario\s+por\s+(mes|d[ií]a)", faq, re.I)
        if len(clauses) < 2:
            return detail["offers"]
        if len(detail["offers"]) != 1:
            raise ValueError("MODO: segmentación FAQ ambigua con múltiples ofertas nativas")
        result = []
        for percentage, segment, cap, period in clauses:
            offer = copy.deepcopy(detail["offers"][0])
            key = hashlib.sha256(segment.casefold().strip().encode("utf-8")).hexdigest()[:16]
            offer.update(id=offer["id"] + ":segment:" + key, name=segment)
            if "cashback" not in offer["outcomes"]:
                raise ValueError("MODO: segmentación FAQ sin reintegro nativo")
            offer["outcomes"]["cashback"].update(amount=Decimal(percentage.replace(",", ".")), amount_type="percent")
            amount = Decimal(cap.replace(".", "").replace(",", "."))
            offer["limits"] = {**(offer.get("limits") or {}), "period_cap": {"reset_by": "month" if period.lower() == "mes" else "day", "aggregate_by": "user", "amount_by_period": amount}}
            result.append(offer)
        return result

    @staticmethod
    def _benefits(detail, offer):
        result = []
        outcomes = offer.get("outcomes")
        if not isinstance(outcomes, dict) or not outcomes:
            raise ValueError("MODO: oferta sin resultados")
        for kind, value in outcomes.items():
            if kind == "cashback":
                benefit_type = "discount" if value.get("cashback_mode") == "descuento_en_pdv" else "cashback"
                amount = number(value.get("amount"))
                if amount is None or amount <= 0:
                    raise ValueError("MODO: reintegro sin valor positivo")
                if value.get("amount_type") == "percent":
                    result.append(Benefit(type=benefit_type, percentage=amount))
                elif value.get("amount_type") in {"fixed", "amount"}:
                    result.append(Benefit(type=benefit_type, amount=amount, currency=value.get("currency") or currency_for(detail)))
                else:
                    raise ValueError("MODO: tipo de importe de reintegro desconocido")
            elif kind == "financing":
                # Separate different interest conditions rather than marking all free.
                groups = {}
                for installment in value.get("installments", []):
                    n = installment.get("number")
                    if not isinstance(n, int) or n <= 0:
                        raise ValueError("MODO: cantidad de cuotas inválida")
                    interest = True if installment.get("type") in {"sin_interes", "simple_sin_interes"} else False if installment.get("type") == "con_interes_preferencial" else None
                    groups.setdefault(interest, []).append(n)
                for interest, options in groups.items():
                    result.append(Benefit(type="installments", installment_options=sorted(set(options)), interest_free=interest))
            elif kind == "payment_scratch":
                # Source documents a random-prize game; engine may return only a zero
                # probability placeholder. Neither zero nor advertised maximum is a guaranteed reward.
                result.append(Benefit(type="other", description="Raspá y Ganá: participación en premios aleatorios. " + plain((detail.get("card") or {}).get("benefit"))))
            else:
                raise ValueError(f"MODO: outcome no soportado: {kind}")
        if not result:
            raise ValueError("MODO: oferta sin beneficio verificable")
        return result

    @staticmethod
    def _limits(detail, offer):
        result = []
        currency = currency_for(detail)
        limits = offer.get("limits") or {}
        for kind, value in limits.items():
            if kind == "transaction_cap":
                amount = number(value.get("amount_by_transaction"))
                if amount is not None and amount > 0:
                    result.append(PromotionLimit(type="monetary_cap", amount=amount, currency=currency, period="transaction"))
            elif kind == "period_cap":
                period = PERIODS.get(value.get("reset_by"), value.get("reset_by"))
                scope = SCOPES.get(value.get("aggregate_by"), value.get("aggregate_by"))
                amount = number(value.get("amount_by_period"))
                if amount is not None and amount > 0:
                    result.append(PromotionLimit(type="monetary_cap", amount=amount, currency=currency, period=period,
                                                 scope=scope, shared_group_id="modo:" + detail["id"],
                                                 description="Tope agregado de la campaña; consultar condiciones y comercios adheridos."))
                quantity = value.get("amount_of_transactions_by_period")
                if quantity and quantity > 0:
                    result.append(PromotionLimit(type="usage_count", quantity=quantity, period=period, scope=scope,
                                                 shared_group_id="modo:" + detail["id"]))
            elif kind == "winning_cap":
                quantity = value.get("max_wins")
                if quantity and quantity > 0:
                    result.append(PromotionLimit(type="usage_count", quantity=quantity, period="promotion", description="Cantidad máxima de premios ganadores"))
            else:
                raise ValueError(f"MODO: límite no soportado: {kind}")
        minimum = number((offer.get("requirements") or {}).get("amount_range", {}).get("min"))
        if minimum is not None and minimum > 0:
            result.append(PromotionLimit(type="minimum_purchase", amount=minimum, currency=currency, period="transaction"))
        if offer.get("offer_caps"):
            raise ValueError("MODO: caps externos requieren interpretación independiente")
        if "payment_scratch" in offer.get("outcomes", {}):
            legal = plain(detail.get("terms_and_conditions"))
            participation = re.search(r"cada\s+participante\s+podr[aá]\s+acceder\s+a\s+una\s*\(\s*(\d+)\s*\)\s+[uú]nica\s+participaci[oó]n\s+por\s+d[ií]a", legal, re.I)
            stock = re.search(r"en\s+total,?\s+la\s+promoci[oó]n\s+contempla\s+la\s+entrega\s+de\s+hasta\s+([\d.]+)\s+premios", legal, re.I)
            if participation:
                result.append(PromotionLimit(type="usage_count", quantity=int(participation[1]), period="daily", scope="person", description="Participaciones diarias; distinto del máximo de premios ganadores"))
            if stock:
                result.append(PromotionLimit(type="stock", quantity=int(stock[1].replace(".", "")), period="promotion", scope="campaign", shared_group_id="modo:" + detail["id"], description="Stock total de premios aleatorios de la campaña"))
        return result

    @staticmethod
    def _scratch_conditions(detail):
        """Select actionable participation prose by semantic sections, without truncation.

        Organizer identity, advertising consent, security and liability remain in terms.
        Unknown game formats fall back to restrictive sentence extraction below.
        """
        legal = plain(detail.get("terms_and_conditions"))
        eligibility = re.search(r"2\.\s*¿Qui[eé]nes pueden participar\?\s*(.*?)\s*3\.\s*¿C[oó]mo se participa\?", legal, re.I)
        daily = re.search(r"Cada Participante podr[aá] acceder a .*?jornada\.", legal, re.I)
        exclusions = re.search(r"No participar[aá]n los pagos .*?comercio\.", legal, re.I)
        chance = re.search(r"Las probabilidades de resultar ganador .*?Promoci[oó]n\.", legal, re.I)
        nonpurchase = re.search(r"podr[aá]n hacerlo enviando un correo electr[oó]nico a:\s*([^\s]+)", legal, re.I)
        if not eligibility:
            return None
        parts = [eligibility[1]]
        parts.extend(m[0] for m in (daily, exclusions, chance) if m)
        if nonpurchase:
            parts.append("Participación sin obligación de compra: escribir a " + nonpurchase[1] + "; consultar documentación y requisitos completos del punto 7 del legal oficial.")
        return parts

    @staticmethod
    def _conditions(raw, offer, terms):
        d = raw["detail"]
        parts = []
        # Official prose, never internal engine identifiers or audience UUIDs.
        description = plain(d.get("publication_description") or d.get("description"))
        if description:
            parts.append(description)
        name = plain(offer.get("name"))
        if name and name != "." and name != d.get("name"):
            parts.append("Condición: " + name)
        bank_ids = (offer.get("requirements") or {}).get("banks", {}).get("list", [])
        banks = {b["id"]: b["name"] for b in raw.get("banks", [])}
        if bank_ids:
            names = [banks[k] for k in bank_ids if k in banks]
            if names:
                parts.append("Bancos identificados en el catálogo oficial: " + ", ".join(names))
            if len(names) != len(bank_ids):
                parts.append("La lista técnica incluye otros emisores sin nombre en el catálogo público; verificar bancos participantes en el detalle oficial.")
        label = plain((d.get("card") or {}).get("participating_bank"))
        if label:
            parts.append("Participantes según MODO: " + label)
        parts.extend(ModoNormalizer.evidence_conflicts(d))
        advertised = re.findall(r"(\d+(?:[.,]\d+)?)\s*%", plain((d.get("card") or {}).get("benefit")))
        cb = offer.get("outcomes", {}).get("cashback", {})
        if (advertised and cb.get("amount_type") == "percent" and Decimal(advertised[0].replace(",", ".")) != number(cb.get("amount"))):
            parts.append("La tarjeta publicitaria indica «" + plain(d["card"]["benefit"]) + "»; la oferta estructurada indica " + str(cb["amount"]) + "% para esta condición. Consultar el detalle y los términos oficiales.")
        faq = plain((d.get("details") or {}).get("faq"))
        scratch_parts = ModoNormalizer._scratch_conditions(d) if "payment_scratch" in offer.get("outcomes", {}) else None
        if scratch_parts is not None:
            parts.extend(scratch_parts)
        # Legal sentences containing eligibility/exclusions, not legal boilerplate.
        for sentence in re.split(r"(?<=[.;])\s+", terms or "") if scratch_parts is None else []:
            if re.search(r"exclusiv|excepto|exclu[ií]|no (?:aplica|v[aá]lid|acumul|incluy)|solo |s[oó]lo |segmento|nivel \d|c[oó]digo|cup[oó]n|stock|primera|primer |unific|compartid|clientes|m[ií]nimo|rasp|probab|premio|adherid", sentence, re.I):
                parts.append(sentence)
            elif "payment_scratch" in offer.get("outcomes", {}) and re.search(r"[uú]ltimos\s+\d+\s+d[ií]as|no\s+registren\s+deuda\s+en\s+mora|[uú]nica\s+participaci[oó]n\s+por\s+d[ií]a", sentence, re.I):
                parts.append(sentence)
        if faq and scratch_parts is None:
            # FAQ often contains segment and bank-card restrictions absent from API.
            for sentence in re.split(r"(?<=[.?])\s+", faq):
                if re.search(r"exclusiv|tarjeta|cliente|nivel|segment|adher|aplica|m[ií]nimo|tope|c[oó]digo|primera|premio", sentence, re.I):
                    if not sentence.lstrip().startswith("¿"):
                        parts.append(sentence)
        aggregation = re.search(r"(?:El\s+)?reintegro\s+es\s+por\s+(?:cuenta|usuario|tarjeta)\s+por\s+(?:mes|d[ií]a|semana)\b", terms or "", re.I)
        if aggregation:
            parts.append(aggregation[0] + ".")
        for label in ("primary_button", "secondary_button", "download_button"):
            button = (d.get("details") or {}).get(label)
            if button and button.get("url"):
                parts.append(f"{plain(button.get('text')) or 'Información oficial'}: {button['url']}")
        if d.get("terms_and_conditions_url"):
            parts.append("Términos oficiales: " + d["terms_and_conditions_url"])
        if not terms:
            parts.append("MODO no publica texto legal en este detalle; verificar condiciones con el banco y el comercio.")
        parts.append("Consultar comercios, sucursales y condiciones adheridas en la página oficial de la promoción.")
        return "\n".join(dict.fromkeys(x.strip() for x in parts if x.strip()))

    def normalize_many(self, raw):
        from scraping.sources.modo.scraper import ModoScraper
        ModoScraper.validate_records([raw])
        d = raw["detail"]
        schedule = (d.get("conditions") or {}).get("schedule") or {}
        date_conflicts = self.validity_conflicts(d)
        days = schedule.get("days_of_week") or []
        if any(x not in WEEKDAYS for x in days):
            raise ValueError("MODO: día de semana desconocido")
        flows = (d.get("conditions") or {}).get("payment_flow", {}).get("flows", [])
        physical = True if set(flows) & {"instore", "instore_nfc", "physical-card", "trip"} else None
        online = True if "online" in flows else None
        terms = plain(d.get("terms_and_conditions")) or None
        categories = ", ".join(x["title"] for x in raw.get("categories", [])) or None
        merchant = plain((d.get("card") or {}).get("validity_place")) or "Comercios adheridos"
        result = []
        for offer in self._offers(d):
            methods = []
            required_banks = (offer.get("requirements") or {}).get("banks", {}).get("list", [])
            banks = {b["id"]: b["name"] for b in raw.get("banks", [])}
            issuer = banks.get(required_banks[0]) if len(required_banks) == 1 else None
            for method in (d.get("conditions") or {}).get("payment_methods", {}).get("methods", []):
                native_type = method.get("type")
                if native_type == "pct":
                    methods.append(PaymentMethod(raw_name="Pago con transferencia (PCT) por MODO", issuer=issuer, wallet="MODO", payment_rail="transfer"))
                elif native_type in {"credit_card", "debit_card"}:
                    network = NETWORKS.get(method.get("issuer"), method.get("issuer"))
                    rails = [rail for flow, rail in [("instore", "qr"), ("instore_nfc", "nfc"), ("physical-card", "card")] if flow in flows]
                    # Online or unspecified rails remain an explicit unspecified alternative.
                    if "online" in flows or not rails:
                        rails.append(None)
                    for rail in rails:
                        methods.append(PaymentMethod(raw_name=f"{native_type}: {method.get('issuer', '')} por MODO" + (f" ({rail})" if rail else ""),
                                                     issuer=issuer, network=network, card_type="credit" if native_type == "credit_card" else "debit",
                                                     wallet="MODO", payment_rail=rail))
                else:
                    raise ValueError("MODO: medio de pago no soportado")
            days_conflict = self.legal_weekdays(d) is not None and set(self.legal_weekdays(d)) != set(days)
            result.append(NormalizedPromotion(
                source="modo", source_id=raw["source_id"] + ":offer:" + offer["id"], promotion_group_id=raw["source_id"],
                scraped_at=datetime.fromisoformat(raw["scraped_at"]), title=plain((d.get("details") or {}).get("name")) or plain(d["name"]),
                scope="category" if re.search(r"adherid|comercios|supermercados", merchant, re.I) else "merchant",
                merchant=merchant, category=categories, promotion_url=raw["promotion_url"], requires_merchant_verification=True,
                valid_from=date.fromisoformat(schedule["start_date"]) if schedule.get("start_date") and "start_date" not in date_conflicts else None,
                valid_to=date.fromisoformat(schedule["stop_date"]) if schedule.get("stop_date") and "stop_date" not in date_conflicts else None,
                benefits=self._benefits(d, offer), limits=self._limits(d, offer), payment_methods=methods,
                days_of_week=[x for x in WEEKDAYS if x in days] if len(set(days)) != 7 and not days_conflict else [],
                applies_every_day=True if set(days) == set(WEEKDAYS) and not days_conflict else None,
                online=online, physical=physical, specific_conditions=self._conditions(raw, offer, terms), terms=terms,
            ))
        return result
