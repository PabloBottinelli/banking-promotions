"""Normalize each official Ualá PromotionSpec; legal terms override card summaries."""
import re
import unicodedata
from datetime import date
from decimal import Decimal

from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit
from scraping.sources.uala.scraper import validate_records


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def money(text):
    return Decimal(text.replace(".", "").replace(",", "."))


MONTHS = {name: i for i, name in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"], 1)}
DAYS = dict(lunes="monday", martes="tuesday", miercoles="wednesday", jueves="thursday",
            viernes="friday", sabado="saturday", domingo="sunday")


def validity(terms):
    # Only the leading validity clause, never later settlement/legal deadlines.
    text = fold(terms)
    clause = re.search(r"\bdesde\b|\bcomprendidos entre\b", text)
    lead = text[clause.start():clause.start()+450] if clause else ""
    dates = []
    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b|\b(\d{1,2}) de (\w+) (?:de|del) (\d{4})\b", lead):
        if match[1]:
            dates.append(date(int(match[3]), int(match[2]), int(match[1])))
        elif match[5] in MONTHS:
            dates.append(date(int(match[6]), MONTHS[match[5]], int(match[4])))
    return (dates[0], dates[1]) if len(dates) >= 2 else (None, None)


def period(text):
    t = fold(text)
    if re.search(r"seman|por (?:cada )?martes", t): return "weekly"
    if re.search(r"mensual|por mes|mes calendario", t): return "monthly"
    if re.search(r"cada.*viaj|por viaje|proximo viaje", t): return "transaction"
    return None


def benefits(terms, spec):
    text = fold(terms)
    rates = list(dict.fromkeys(re.findall(r"\b(\d+(?:[.,]\d+)?)\s*%", text)))
    if rates:
        if len(rates) != 1:
            raise ValueError("Multiple rates require a reviewed benefit/variant parser")
        direct = "aplicado de forma directa" in text or "descuento directo" in text
        kind = "cashback" if "reintegro" in text and not direct else "discount"
        return [Benefit(type=kind, percentage=Decimal(rates[0].replace(",", ".")),
                        description=spec["title"].strip() + ". " + spec.get("description", "").strip())]
    # Real non-percentage benefits are supported only when positively evidenced.
    if re.search(r"sin comision|comision bonificada", text):
        return [Benefit(type="fee_waiver", description=spec["title"] + ". " + spec.get("description", ""))]
    if re.search(r"servicio gratuito|servicio sin cargo", text):
        return [Benefit(type="free_service", description=spec["title"] + ". " + spec.get("description", ""))]
    raise ValueError("No supported source-evidenced benefit; parser review required")


def limits(terms):
    text = fold(terms)
    result = []
    cap_patterns = [r"(?:tope de reintegro|importe maximo de descuento|monto maximo)\s*(?:semanal|mensual)?\s*(?:de)?\s*\$\s*([\d.,]+)",
                    r"por hasta un importe de ars\s*([\d.,]+)"]
    for pattern in cap_patterns:
        match = re.search(pattern, text)
        if match:
            context = text[max(0, match.start()-100):match.end()+170]
            scope = "person" if "por usuario" in context else "card" if "por tarjeta" in context else "person" if "cada tarjeta" in context else None
            result.append(PromotionLimit(type="monetary_cap", amount=money(match[1]), currency="ARS",
                                         period=period(context), scope=scope,
                                         description=terms[match.start():match.end()+100].split("\n")[0]))
            break
    minimum = re.search(r"monto minimo de compra de\s*\$\s*([\d.,]+)", text)
    if minimum:
        result.append(PromotionLimit(type="minimum_purchase", amount=money(minimum[1]), currency="ARS", period="transaction"))
    stock = re.search(r"stock de\s*(\d+)\s+redenciones|llegar a los\s+(\d+)\s+cupones", text)
    if stock:
        context = text[stock.start():stock.end()+100]
        result.append(PromotionLimit(type="stock", quantity=int(stock[1] or stock[2]),
                                     period=period(context) or "promotion", scope="campaign", description=context))
    usage = re.search(r"maximo de\s+(\d+)\s*\([^)]*\)\s*vouchers|proximos\s+(\d+)\s*\([^)]*\)\s*viajes", text)
    if usage:
        result.append(PromotionLimit(type="usage_count", quantity=int(usage[1] or usage[2]), period="promotion", scope="person"))
    if "por unica vez" in text or "por única vez" in terms.lower():
        result.append(PromotionLimit(type="usage_count", quantity=1, period="promotion", scope="person"))
    if "solo una vez por carrera, curso o diplomatura" in text:
        result.append(PromotionLimit(type="usage_count", quantity=1, period="promotion", scope="course",
                                     description="Una vez por carrera, curso o diplomatura; sin límite global de usos."))
    return result


def payment_methods(terms, spec):
    text = fold(terms)
    methods = list(spec.get("paymentMethods", []))
    # Explicit exclusive legal purchase eligibility takes priority over stale badges.
    if re.search(r"exclusivamente a compras realizadas con tarjetas de credito", text):
        methods = [m for m in methods if "credito" in fold(m)]
    result = []
    for raw in methods:
        kind = "credit" if "credito" in fold(raw) else "prepaid" if "prepaga" in fold(raw) else None
        if kind is None:
            raise ValueError("Unrecognized payment option")
        word = r"(?:de )?credito" if kind == "credit" else "prepaga"
        # Network must be tied to this card option, not merely appear somewhere.
        network = "Mastercard" if re.search(r"tarjetas? " + word + r"[^.;]{0,100}?mastercard", text) else None
        if re.search(r"tarjetas? (?:de )?credito[^.;]{0,60}prepaga[^.;]{0,60}mastercard", text):
            network = "Mastercard"
        result.append(PaymentMethod(raw_name=raw, issuer="Ualá", network=network, card_type=kind,
                                    wallet="App YPF" if "app ypf" in text else None,
                                    payment_rail="nfc" if "near field communication" in text else "card"))
    return result


def weekdays(terms, spec):
    t = fold(terms)
    if "aplicable de lunes a viernes" in t:
        return list(DAYS.values())[:5], False
    # Positive eligibility clause only: do not tokenize all legal prose.
    explicit = re.search(r"los dias (lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b|todos dias (lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", t)
    if explicit:
        return [DAYS[explicit[1] or explicit[2]]], False
    supplied = [fold(d) for d in spec.get("days", [])]
    if "todos los dias" in supplied: return [], True
    return [DAYS[d] for d in supplied if d in DAYS], False if supplied else None


def conditions(terms, spec, verification):
    pieces = [spec.get("description", "").strip()]
    # Keep actionable restrictions while omitting corporate/regulatory boilerplate.
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", terms.strip()):
        t = fold(sentence)
        if t.startswith("(en adelante"):
            continue
        if any(w in t for w in ("sera requisito", "sera condicion", "solo para usuarios", "usuarios nuevos", "no hayan", "no incluye", "excepto ", "cupon", "codigo promocional", "cargado el codigo", "maximo de", "solo una vez", "unica vez", "no combinable", "no acumulable", "sujeto a disponibilidad", "categorias", "manualmente", "mismo dia", "misma cuenta", "no valida para pagos", "por tarjeta", "por usuario")):
            # The phrase before these boilerplate sections contains the restriction.
            if "es el exclusivo responsable" not in t and "para mas informacion" not in t:
                if "promocion ofrecida" in t:
                    if "aplicable de" in t:
                        sentence = sentence[t.index("aplicable de"):]
                    else:
                        continue
                elif "durante el plazo de vigencia, los tarjetahabientes" in t and "que utilicen" in t:
                    sentence = sentence[t.index("que utilicen"):]
                # Stop before issuer addresses, which are retained in full terms.
                sentence = re.split(r",?\s+(?:emitid[ao]s? por Ualá|ofrecid[ao]s? por Ualá)", sentence, maxsplit=1, flags=re.I)[0]
                if not sentence.endswith((".", "!", "?")):
                    sentence += "."
                pieces.append(sentence.strip())
    if verification:
        pieces.append("Consultar comercios, líneas o sedes adheridas y sus condiciones en la página oficial de la promoción antes de operar.")
    return " ".join(dict.fromkeys(p for p in pieces if p))


class UalaNormalizer:
    def normalize_many(self, raw):
        validate_records([raw])
        campaign = raw["catalog"]["fields"]
        result = []
        for spec in raw["detail"]["specs"]:
            terms = spec["legalDisclaimer"]
            text = fold(terms)
            start, end = validity(terms)
            days, every = weekdays(terms, spec)
            verification = any(w in text for w in ("comercios adheridos", "sedes adheridas", "lineas de colectivos"))
            place = [fold(p) for p in spec.get("place", [])]
            benefit_list = benefits(terms, spec)
            # Correct a misleading marketing title when binding terms say direct discount.
            title = spec["title"].strip()
            if benefit_list[0].type == "discount" and "reintegro" in fold(title):
                title = re.sub("reintegro", "descuento", title, flags=re.I)
                benefit_list[0].description = title + ". " + spec.get("description", "")
            result.append(NormalizedPromotion(
                source="uala", source_id=raw["source_id"] + ":" + spec["id"],
                promotion_group_id=raw["source_id"], scraped_at=raw["scraped_at"],
                title=campaign["brand"] + " — " + title, scope="category" if campaign["brand"] == "Colectivos" else "merchant",
                merchant=campaign["brand"], category=", ".join(c["fields"]["Category"] for c in campaign.get("PromotionCategory", [])) or None,
                promotion_url=raw["source_url"], requires_merchant_verification=verification,
                valid_from=start, valid_to=end, benefits=benefit_list, limits=limits(terms),
                payment_methods=payment_methods(terms, spec), days_of_week=days, applies_every_day=every,
                online=True if "online" in place else None,
                physical=True if "fisico" in place or "sucursales fisicas" in text else None,
                specific_conditions=conditions(terms, spec, verification), terms=terms))
        return result
