"""Deterministic V2 mapping; legal conditions outrank catalog display defaults."""
import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit


def folded(text):
    return "".join(c for c in unicodedata.normalize("NFD", str(text).lower()) if unicodedata.category(c) != "Mn")


def money(value):
    value = re.sub(r"[^\d,.]", "", str(value))
    if not value:
        raise ValueError("Unparseable monetary value")
    return Decimal(value.replace(".", "").replace(",", "."))


def integer_quantity(value):
    """An integer count, optionally grouped in thousands; never money/decimals."""
    if re.fullmatch(r"\d+", value):
        return int(value)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        return int(value.replace(".", ""))
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", value):
        return int(value.replace(",", ""))
    raise ValueError(f"Malformed integer quantity: {value!r}")


NUMBER = r"\d[\d.,]*"
CURRENCY = r"(?:u\$s|us\$|usd|\$)"
MONEY = rf"{CURRENCY}\s*({NUMBER})"


def sentences(text):
    # Preserve monetary periods, domain names, abbreviations and original text.
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ])|[\r\n]+", text) if s.strip()]


def period(text):
    text = folded(text)
    for pattern, result in [(r"por transacci|por viaje|por uso|por compra", "transaction"),
                            (r"por semana|semanal", "weekly"), (r"por mes|mensual|mes calendario", "monthly"),
                            (r"por dia|diario", "daily"), (r"vigencia|promocion", "promotion")]:
        if re.search(pattern, text):
            return result
    return None


def currency(text):
    return "USD" if re.search(r"u\$s|us\$|\busd\b|dolares", folded(text)) else "ARS"


def legal_limits(terms, *, group):
    limits = []
    # A cap's period is taken from its own legal sentence; never the API renewal.
    for sentence in sentences(terms):
        text = folded(sentence)
        if "tope" in text and not re.search(r"sin tope", text):
            # Match money only after 'tope', including amounts written in words
            # followed by their numeric parenthesis (YPF). Avoid unrelated spend.
            for found in re.finditer(rf"tope\b[^$\n]{{0,130}}?({MONEY})", text):
                limits.append(PromotionLimit(type="monetary_cap", amount=money(found.group(2)),
                    currency=currency(found.group(1)), period=period(text[found.start():]),
                    scope="account" if re.search(r"usuario|titular|cuenta|cliente|persona", text) else None,
                    description=sentence))
                # Independently expressed aggregate periods apply alongside the
                # transaction cap. Stop before a separate usage-count clause:
                # max 2 transactions/month does not make a per-use cap monthly.
                tail = re.split(r"maximo|con un maximo", text[found.end():], maxsplit=1)[0]
                if "por transaccion" in tail:
                    for pattern, aggregate in [(r"\by por semana\b", "weekly"), (r"\by por mes\b", "monthly"), (r"\by por dia\b", "daily")]:
                        if re.search(pattern, tail):
                            limits.append(PromotionLimit(type="monetary_cap", amount=money(found.group(2)), currency=currency(found.group(1)),
                                period=aggregate, scope="account" if re.search(r"usuario|titular|cuenta|cliente|persona", text) else None, description=sentence))
        minimum = re.search(rf"(?:minim[oa](?: de)? (?:compra|consumo)|compra minim[oa]|(?:compras? )?(?:mayores|superiores) a|monto sea igual o superior a)[^$]{{0,30}}?({MONEY})", text)
        if minimum:
            limits.append(PromotionLimit(type="minimum_purchase", amount=money(minimum.group(2)),
                                         currency=currency(minimum.group(1)), period="transaction", description=sentence))
        # Quantities are not money. Counts in words are supported explicitly.
        count = re.search(r"(?:maximo(?: de)?|hasta)\s+(\d+|una?|dos|tres|cuatro)\s*(?:\([^)]*\)\s*)?(?:reintegros?|transacci(?:on|ones)|facturas?|usos?|beneficios?)", text)
        if count:
            words = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4}
            token = count.group(1)
            quantity = int(token) if token.isdigit() else words[token]
            limits.append(PromotionLimit(type="usage_count", quantity=quantity,
                                         period=period(text[count.start():]), scope="account", description=sentence))
        bare_count = re.search(r"maximo(?: de)?\s+(\d+)\s+por\s+(mes|semana|dia)\b", text)
        if bare_count:
            limits.append(PromotionLimit(type="usage_count", quantity=int(bare_count.group(1)), period={"mes": "monthly", "semana": "weekly", "dia": "daily"}[bare_count.group(2)],
                scope="benefit_discount" if "por beneficio y por descuento" in text else None, description=sentence))
        if re.search(r"(?:solo|unicamente).{0,35}\bprimer(?:a)? compra.{0,50}\bsemana\b", text):
            limits.append(PromotionLimit(type="usage_count", quantity=1, period="weekly", scope="account", description=sentence))
        # Capture the entire numeric token before validating grouping. Matching
        # only '\d+' silently truncated '10.000' into ten coupons.
        stock = re.search(r"(?:stock|cupos?)\s+(?:de\s+)?(\d+(?:[.,]\d+)*)\s*(?:cupos?|unidades?)?", text)
        if stock:
            limits.append(PromotionLimit(type="stock", quantity=integer_quantity(stock.group(1)), period=period(text) or "promotion", scope="campaign", description=sentence))
        tickets = re.search(r"maximo(?: de)?\s+(\d+)\s*(?:\([^)]*\)\s*)?entradas por usuario", text)
        if tickets:
            limits.append(PromotionLimit(type="other", quantity=int(tickets.group(1)), period="promotion", scope="person", description=sentence))
        first = re.search(r"primeros\s+(\d+)\s+viajes", text)
        if first:
            limits.append(PromotionLimit(type="usage_count", quantity=int(first.group(1)),
                                         period="promotion", scope="person", description=sentence))
        if "primera transaccion realizada durante la vigencia" in text:
            limits.append(PromotionLimit(type="usage_count", quantity=1, period="promotion", scope="account", description=sentence))
    # Preserve additional bounded/unknown restrictions without inventing numbers.
    unique = []
    seen = set()
    for limit in limits:
        key = (limit.type, limit.amount, limit.quantity, limit.currency, limit.period, limit.scope)
        if key not in seen:
            seen.add(key)
            unique.append(limit)
    return unique


DAY_NAMES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DAY_CODES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_SHORT = dict(zip(["lu", "ma", "mi", "ju", "vi", "sa", "do"], DAY_NAMES))


def weekdays(values):
    result = set()
    for value in values:
        value = folded(value).strip().rstrip(".")
        if re.fullmatch(r"todos los dias", value):
            return [], True
        value = DAY_SHORT.get(value, value)
        span = re.fullmatch(r"(" + "|".join(DAY_NAMES) + r") a (" + "|".join(DAY_NAMES) + r")", value)
        if span:
            i, end = DAY_NAMES.index(span.group(1)), DAY_NAMES.index(span.group(2))
            while True:
                result.add(i)
                if i == end:
                    break
                i = (i + 1) % 7
        elif value in DAY_NAMES:
            result.add(DAY_NAMES.index(value))
        else:
            raise ValueError(f"Unrecognized positive weekday phrase: {value!r}")
    return [DAY_CODES[i] for i in sorted(result)], None


def validity(detail, terms):
    # Date clauses in the binding legal text take precedence over display fields.
    match = re.search(r"(?:desde(?: el)?|vigencia(?: desde)?|valido del)\s*(\d{1,2}/\d{1,2}/\d{4}).{0,30}?(?:hasta(?: el)?|al)\s*(\d{1,2}/\d{1,2}/\d{4})", folded(terms))
    if match:
        return tuple(datetime.strptime(x, "%d/%m/%Y").date() for x in match.groups())
    short = re.search(r"(?:del|desde(?: el)?)\s*(\d{1,2}/\d{1,2}/\d{2})\s+(?:al|hasta(?: el)?)\s*(\d{1,2}/\d{1,2}/\d{2})\b", folded(terms))
    if short:
        return tuple(datetime.strptime(x, "%d/%m/%y").date() for x in short.groups())
    months = dict(zip(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"], range(1, 13)))
    verbose = re.search(r"desde el (\d{1,2}) de (\w+) de (\d{4}) hasta el (\d{1,2}) de (\w+) de (\d{4})", folded(terms))
    if verbose:
        from datetime import date
        a, b, c, d, e, f = verbose.groups()
        return date(int(c), months[b], int(a)), date(int(f), months[e], int(d))
    return tuple(datetime.fromisoformat(detail[k].replace("Z", "+00:00")).date() if detail.get(k) else None for k in ["startDate", "dueDate"])


def methods(detail, terms):
    output = []
    text = folded(terms)
    if ('"pago de servicios" de personal pay' in text and '"mi personal"' in text and "debito automatico" in text):
        return [PaymentMethod(raw_name='Pago de servicios desde la app Personal Pay', wallet="Personal Pay"),
                PaymentMethod(raw_name='Pago de factura desde la app Mi Personal', wallet="Mi Personal"),
                PaymentMethod(raw_name='Débito automático asociado a Personal Pay', wallet="Personal Pay", payment_rail="other")]
    if re.search(r"recargas personal realizadas desde la app de personal pay o mi personal flow con tarjeta prepaga visa personal pay o dinero en cuenta", text):
        # Here both app alternatives explicitly share both funding alternatives
        # in the same positive clause; these four combinations are source-bound.
        return [method for app in ["Personal Pay", "Mi Personal Flow"] for method in [
            PaymentMethod(raw_name=f"Recarga desde {app} con tarjeta prepaga Visa Personal Pay", issuer="Personal Pay", network="Visa", card_type="prepaid", wallet=app, payment_rail="card"),
            PaymentMethod(raw_name=f"Recarga desde {app} con dinero en cuenta", wallet=app, payment_rail="account_balance")]]
    if "entidades emisoras habilitadas" in text and "para apple pay:" in text:
        # Each issuer is paired only with the wallet listed in its legal
        # subsection. The source permits debit/prepaid as a group; don't invent
        # an individual issuer's product type or a cross-wallet Cartesian product.
        matrix = re.finditer(r"PARA (APPLE PAY|GOOGLE PAY|MODO CONTACTLESS):\s*(.*?)(?=(?:[•●]\s*)?PARA (?:APPLE PAY|GOOGLE PAY|MODO CONTACTLESS):|BILLETERAS DE ENTIDADES EMISORAS:)", terms, re.S | re.I)
        for section in matrix:
            wallet = {"APPLE PAY": "Apple Pay", "GOOGLE PAY": "Google Pay", "MODO CONTACTLESS": "MODO Contactless"}[section.group(1).upper()]
            for value in section.group(2).split(","):
                issuer = re.sub(r"\s+", " ", value).strip(" .•\r\n")
                if issuer:
                    output.append(PaymentMethod(raw_name=f"Visa débito/prepaga de {issuer}, mediante {wallet}, NFC", issuer=issuer, network="Visa", wallet=wallet, payment_rail="nfc"))
        native = re.search(r"BILLETERAS DE ENTIDADES EMISORAS:\s*(.*?)(?:\n\s*5\.|\n\s*Mec[aá]nica)", terms, re.S | re.I)
        if native:
            for value in native.group(1).split(","):
                name = re.sub(r"^APLICACI[OÓ]N\s+", "", value.strip(), flags=re.I).strip(" .")
                issuer = {"BANCO GALICIA": "Banco Galicia", "BUEPP": "Banco Ciudad", "PERSONAL PAY": "Personal Pay"}.get(name.upper())
                if issuer:
                    wallet = {"BANCO GALICIA": "Galicia", "BUEPP": "Buepp", "PERSONAL PAY": "Personal Pay"}[name.upper()]
                    output.append(PaymentMethod(raw_name=f"Visa débito/prepaga mediante aplicación {name}, NFC", issuer=issuer, network="Visa", wallet=wallet, payment_rail="nfc"))
        if not output:
            raise ValueError("Unparseable legal issuer/wallet NFC matrix")
        return output
    if re.search(r"app de personal pay con dinero en cuenta.*?mi movistar.*?tuenti.*?tarjeta prepaga visa personal pay", text, re.S):
        return [PaymentMethod(raw_name="Recarga desde Personal Pay con dinero en cuenta", wallet="Personal Pay", payment_rail="account_balance"),
                PaymentMethod(raw_name="Recarga desde Mi Movistar con tarjeta prepaga Visa Personal Pay", issuer="Personal Pay", network="Visa", card_type="prepaid", wallet="Mi Movistar", payment_rail="card"),
                PaymentMethod(raw_name="Recarga desde Tuenti con tarjeta prepaga Visa Personal Pay", issuer="Personal Pay", network="Visa", card_type="prepaid", wallet="Tuenti", payment_rail="card")]
    exclusive_card = any(re.search(r"medios de pago exclusivo(?:s)?(?: con)? (?:cupon\s*\+\s*)?tarjeta (?:prepaga )?visa personal pay", folded(s))
                         and not re.search(r"\bqr\b|\bnfc\b|dinero en cuenta|saldo en cuenta", folded(s)) for s in sentences(terms))
    for item in detail.get("paymentMethods", []):
        name = str(item.get("name", "")).strip()
        t = folded(name)
        if "cupon" in t:  # Coupon is an eligibility condition, not a payment rail.
            continue
        if "qr" in t:
            if exclusive_card or re.search(r"no (?:valido|aplicable).*?pago qr", text):
                continue
            output.append(PaymentMethod(raw_name=name, wallet="Personal Pay", payment_rail="qr"))
        elif "nfc" in t:
            output.append(PaymentMethod(raw_name=name, wallet="Personal Pay", payment_rail="nfc"))
        elif "visa" in t and "tarjeta" in t:
            output.append(PaymentMethod(raw_name=name, issuer="Personal Pay", network="Visa", card_type="prepaid", payment_rail="card"))
        elif "dinero en cuenta" in t:
            output.append(PaymentMethod(raw_name=name, wallet="Personal Pay", payment_rail="account_balance"))
        else:
            output.append(PaymentMethod(raw_name=name, wallet="Personal Pay"))
    # Helper lists can omit a valid rail stated in legal text. Bind NFC to the
    # actual named card in the same positive clause, without inventing a wallet
    # or card type. Explicit API app/wallet evidence, when present, is retained.
    for clause in sentences(terms):
        local = folded(clause)
        if not re.search(r"tarjeta\s+(?:prepaga\s+)?visa\s+(?:de\s+)?personal pay.{0,180}?\bnfc\b", local):
            continue
        if re.search(r"no (?:aplica|aplicable|valido|valida|admite|permite).{0,35}\bnfc\b|sin nfc\b", local):
            continue
        card_type = "prepaid" if re.search(r"tarjeta prepaga visa\s+(?:de\s+)?personal pay", local) else None
        existing = next((method for method in output if method.payment_rail == "nfc"), None)
        if existing:
            existing.issuer, existing.network = "Personal Pay", "Visa"
            if card_type:
                existing.card_type = card_type
        else:
            output.append(PaymentMethod(raw_name=clause, issuer="Personal Pay", network="Visa", card_type=card_type, payment_rail="nfc"))
        break
    if "app ypf" in text:
        output = [PaymentMethod(raw_name="App YPF con tarjeta prepaga Visa Personal Pay", issuer="Personal Pay", network="Visa", card_type="prepaid", wallet="YPF", payment_rail="card")]
    return output


class PersonalPayNormalizer:
    def normalize_many(self, raw):
        from scraping.sources.personal_pay.scraper import validate_records
        validate_records([raw])
        if raw.get("kind") == "legal_campaign":
            return self._legal_campaign(raw)
        detail = raw["detail"]
        terms = detail.get("legal") or detail["documentTyc"]
        text = folded(terms)
        group = str(raw["source_id"])
        levels = detail.get("levels", [])
        has_segment = any(str(level.get("code", "")).upper() != "LVL00" for level in levels)
        contexts = [(str(level["code"]).lower(), level) for level in levels] if has_segment else [(None, levels[0] if levels else None)]
        if len({key for key, _ in contexts}) != len(contexts):
            raise ValueError("Duplicate level variant")
        output = []
        for suffix, level in contexts:
            benefit_text = level["discountValue"] if suffix else detail["discounts"]
            pct = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%\s*(?:reintegro|descuento)?\s*", folded(benefit_text))
            benefit_type = {"Cashback": "cashback", "Discount": "discount"}.get(detail["typeCode"])
            if pct:
                if benefit_type is None:
                    raise ValueError("Unknown percentage benefit type")
                benefits = [Benefit(type=benefit_type, percentage=Decimal(pct.group(1).replace(",", ".")), description=detail["description"])]
            elif folded(benefit_text).strip() == "gratis":
                benefits = [Benefit(type="gift", description=detail["description"])]
            elif re.fullmatch(r"\s*\d+\s*x\s*\d+\s*", folded(benefit_text)):
                benefits = [Benefit(type="other", description=f"{benefit_text.strip()}: {detail['description']}")]
            elif folded(benefit_text).strip() == "exclusivo":
                fixed = re.search(rf"descuento de ({MONEY})", text)
                if not fixed:
                    raise ValueError("Exclusive benefit has no supported evidence")
                benefits = [Benefit(type="discount", amount=money(fixed.group(2)), currency=currency(fixed.group(1)), description=detail["description"])]
            else:
                raise ValueError(f"Unparsed advertised benefit: {benefit_text!r}")
            # A shipping benefit is simultaneous when explicitly offered. Sony's
            # incidental examples of other active commercial terms stay conditions.
            if "envio sin cargo a todo el pais" in text:
                benefits.append(Benefit(type="free_service", description="Envío sin cargo a todo el país, sujeto a las condiciones y disponibilidad del sitio."))
            # Secondary services in descriptions are evidence too, even where
            # legal focuses on the primary subscription discount.
            extra_service = re.search(r"(?:adem[aá]s\s+obten[eé]\s+)(.+?)(?:[¡!]\s*)?gratis[!¡\s]*\s*(?:por\s+)?(\d+)\s+d[ií]as", detail["description"], re.I | re.S)
            if extra_service:
                benefits.append(Benefit(type="free_service", description=f"{extra_service.group(1).strip(' ¡!')} gratis por {extra_service.group(2)} días, sujeto a las condiciones del beneficio y cupón."))
            chosen_terms = terms
            if suffix:
                number = re.search(r"\d+", level["code"])
                if not number:
                    raise ValueError("Level has no stable numeric identity")
                clauses = [s for s in sentences(terms) if re.search(rf"nivel\s+{int(number.group())}\b", folded(s)) and "%" in s]
                if len(clauses) != 1:
                    raise ValueError("Level legal clause missing/ambiguous")
                chosen_terms = clauses[0] + "\n" + "\n".join(s for s in sentences(terms) if "%" not in s and not re.search(r"nivel\s+\d", folded(s)))
            limits = legal_limits(chosen_terms, group=group)
            # Descriptions are explicit source facts, not parser-error defaults.
            # Only add absent typed restrictions; legal wins conflicting values.
            description_limits = legal_limits(detail["description"], group=group)
            for limit in description_limits:
                if limit.type in ["minimum_purchase", "stock", "usage_count"] and not any(x.type == limit.type for x in limits):
                    limits.append(limit)
            # Explicit API cap is source evidence when legal text is silent,
            # never a numeric fallback for a failed legal parser.
            if (not any(l.type == "monetary_cap" for l in limits)
                    and not re.search(r"sin tope", text)
                    and detail.get("limitAmount") not in (None, "", 0, "0")):
                limits.append(PromotionLimit(type="monetary_cap", amount=money(detail["limitAmount"]),
                    currency=currency(detail["limitAmount"]), description="Tope publicado en el detalle de Personal Pay; período y alcance no especificados."))
            days, every = weekdays(detail.get("days", []))
            start, end = validity(detail, terms)
            condition_parts = [detail["description"]]
            # Keep legal restrictions, omit financial-regulatory boilerplate.
            for sentence in sentences(chosen_terms):
                t = folded(sentence)
                if any(x in t for x in ["micro sistema", "microsistema", "no se encuentra autorizad", "fondos depositados", "fondos de las cuentas", "para mas informacion", "cuit", "general hornos"]):
                    continue
                if suffix and re.search(r"nivel\s+\d", t) and sentence not in clauses:
                    continue
                if len(sentence) > 450:
                    # Extensive issuer/wine SKU lists remain verbatim in terms.
                    if re.search(r"para apple pay|para google pay|para modo|emisoras|billeteras de entidades", t):
                        sentence = "Solo emisores y billeteras habilitados en las combinaciones que detalla el legal oficial."
                    elif re.search(r"no incluye|no validos|descuentos no|no aplica|exclu", t):
                        sentence = "Aplican exclusiones de productos y marcas: consultar el listado completo del detalle legal oficial."
                if re.fullmatch(r"\d+\.", sentence) or t in ["promocion:", "vigencia:", "los participantes:", "mecanica:", "contacto:", "exclusiones:"]:
                    continue
                if re.search(r"organizador|auspiciante|oferta nula|impuesto es responsabilidad|nula donde|suspension, modificacion|circunstancias no imputables|contacto:|en caso de dudas", t):
                    continue
                if sentence not in condition_parts:
                    condition_parts.append(sentence)
            verify = bool(detail.get("locations")) or bool(re.search(r"adherid|habilitad|seleccionad[oa]s?", text))
            if verify:
                condition_parts.append("Consultá las sucursales/comercios y productos adheridos en el detalle oficial (Consultar sucursales) o la app Personal Pay.")
            if suffix:
                condition_parts.insert(0, f"Exclusivo {level['name']}; el nivel depende del consumo del mes anterior: consultar tabla oficial de niveles.")
            if len("\n".join(condition_parts)) > 3000 and "entidades emisoras habilitadas" in text:
                # Lengthy network-wide terms contain issuer/wallet matrices and
                # SKU lists. Summarize their categories, preserving full terms.
                keep = [detail["description"]]
                for sentence in sentences(terms):
                    t = folded(sentence)
                    if (t.startswith("la promocion estara vigente") or
                        re.match(r"no valido para venta online|no acumulable|descuentos no validos para compras|no incluye electrodomesticos|no incluye cortes de carnes", t)):
                        keep.append(sentence)
                keep.extend(["Solo personas humanas con tarjetas Visa débito/prepaga emitidas en Argentina y billeteras NFC habilitadas. Consultar la combinación de emisor y billetera en el legal oficial; no aplica QR.",
                    "Se excluyen productos de programas de precios, carnes y pollo, leches infantiles, harinas, azúcar, aceites y determinadas marcas de bebidas/vinos/espumantes: consultar el listado completo en términos.",
                    "Consultá las sucursales/comercios adheridos en el detalle oficial o la app Personal Pay."])
                condition_parts = keep
            online = True if re.search(r"modalidad online|presencial y online|fisicas y (?:el )?sitio web|tienda ecommerce|compras realizadas en el sitio web|compra presencial y online|en (?:el sitio web|la pagina web)", text) else None
            physical = True if re.search(r"modalidad (?:presencial|fisica)|presencial y online|compra presencial|compras presenciales|tiendas fisicas|sucursales fisicas|compra presencial y online|o en las sucursales", text) else None
            for clause in sentences(terms):
                local = folded(clause)
                if re.search(r"\b(?:tienda|compras?|entradas|pago)\s+on\s*line\b|modalidad\s+(?:exclusivamente\s+)?online\b|a traves de mas online\b", local):
                    if re.search(r"no valid[oa] para (?:tienda|venta|compras?)\s+online", local):
                        online = False
                    else:
                        online = True
                if re.search(r"forma presencial|boleteria fisica|en linea de cajas|beneficio para sucursales adheridas", local):
                    physical = True
                if re.search(r"modalidad exclusivamente online|valid[oa] unicamente online|solo valid[oa] para compras online", local):
                    online, physical = True, False
            if re.search(r"(?:presencial\s*(?:/|y/o|y)\s*online|online\s*(?:/|y/o|y)\s*presencial)", text):
                online, physical = True, True
            if "unicamente bajo modalidad online" in text:
                online, physical = True, False
            if re.search(r"no valid[oa] para (?:venta|compra) online", text):
                online = False
            if "exclusivo para compras presenciales" in text:
                online, physical = False, True
            for clause in sentences(terms):
                local = folded(clause)
                if re.search(r"(?:exclusiv[oa](?:mente)?|unicamente)\s+(?:para compras )?(?:en )?(?:todas las )?(?:sucursales(?: fisicas)?|tiendas fisicas)", local):
                    physical = True
                    # 'Exclusivo en tiendas físicas Y el sitio web' restricts
                    # the eligible outlets; it does not exclude online purchases.
                    online = True if re.search(r"\by\s+(?:el\s+)?sitio web\b|\by\s+online\b", local) else False
            if re.search(r"(?:exclusiv[oa](?:mente)?|unicamente)\s+(?:a traves (?:del|de)|en)\s+(?:el )?(?:sitio web|nuestra pagina web|tienda ecommerce)", text):
                physical = False
            if raw.get("global_legal_conflict"):
                # Conflicting binding dates have no established hierarchy.
                # Do not claim eligibility in the disputed boundary interval.
                start = None
                condition_parts.append(raw["global_legal_conflict"]["note"])
            output.append(NormalizedPromotion(source="personal_pay", source_id=f"{group}:{suffix}" if suffix else group,
                promotion_group_id=group, scraped_at=raw["scraped_at"], title=detail["title"],
                merchant=detail["title"], category=detail.get("heading"), scope="merchant",
                promotion_url=f"https://www.personal.com.ar/pay/beneficios#details_{group}",
                requires_merchant_verification=verify, valid_from=start, valid_to=end,
                benefits=benefits, limits=limits, payment_methods=methods(detail, terms), days_of_week=days,
                applies_every_day=every, online=online, physical=physical,
                specific_conditions="\n".join(dict.fromkeys(condition_parts)), terms=terms))
        return self._recharge_variants(raw, output)

    def _legal_campaign(self, raw):
        from bs4 import BeautifulSoup
        entry = raw["legal_campaign"]
        title = BeautifulSoup(entry["title"], "html.parser").get_text(" ", strip=True)
        terms = BeautifulSoup(entry["tycModel"]["description"], "html.parser").get_text("\n", strip=True)
        text = folded(terms)
        if raw["source_id"] != "reintegro-plus":
            raise ValueError("Unrecognized standalone legal campaign; review required")
        offers = re.findall(r"para usuarios nivel\s+(\d+)\s*:\s*(\d+(?:[.,]\d+)?)\s*%", text)
        if not offers or len({level for level, _ in offers}) != len(offers):
            raise ValueError("Missing/duplicated Reintegro Plus level facts")
        start, end = validity({}, terms)
        conditions = terms[:text.index("micro sistemas se limita")].strip() if "micro sistemas se limita" in text else terms
        output = []
        for level, pct in offers:
            variant_conditions = re.sub(r"PARA USUARIOS NIVEL\s+\d+\s*:\s*\d+(?:[.,]\d+)?\s*%[;.]*", "", conditions, flags=re.I)
            variant_conditions = re.sub(r"\s+", " ", variant_conditions).strip()
            output.append(NormalizedPromotion(source="personal_pay", source_id=f"{raw['source_id']}:lvl{int(level):02}",
                promotion_group_id=raw["source_id"], scraped_at=raw["scraped_at"], title=f"{title} — Nivel {level}", scope="other",
                merchant="Personal Flow", category="Servicios de telecomunicaciones", promotion_url=raw["source_url"],
                valid_from=start, valid_to=end,
                benefits=[Benefit(type="cashback", percentage=Decimal(pct.replace(",", ".")), description=f"Reintegro Plus para clientes Nivel {level}, calculado sobre el importe final de la factura elegible.")],
                specific_conditions=f"Exclusivo Nivel {level}. " + variant_conditions + " No se presume acumulación con otros beneficios de pago de factura. Consultar las condiciones de activación y servicios.",
                terms=terms))
        return output

    def _recharge_variants(self, raw, output):
        """Separate first recharge (balance only) from ordinary weekly eligibility."""
        detail = raw["detail"]
        terms = detail.get("legal") or detail["documentTyc"]
        text = folded(terms)
        match = re.search(r"ademas, en la primera recarga.+?un\s+(\d+(?:[.,]\d+)?)%[^.]*?reintegro con tope\s*" + MONEY, text)
        if not match:
            return output
        if len(output) != 1:
            raise ValueError("Unexpected level + recharge combination")
        ordinary = output[0]
        base_legal = terms[:folded(terms).index("ademas, en la primera recarga")]
        ordinary.source_id += ":weekly"
        ordinary.limits = legal_limits(base_legal, group=ordinary.promotion_group_id)
        for limit in ordinary.limits:
            if limit.type in ["monetary_cap", "usage_count"]:
                limit.shared_group_id = ordinary.promotion_group_id + ":weekly-base"
        ordinary.specific_conditions = "Reintegro semanal ordinario; el adicional de primera recarga solo aplica a dinero en cuenta.\n" + detail["description"]
        first = ordinary.model_copy(deep=True)
        first.source_id = raw["source_id"] + ":first-balance"
        first.payment_methods = [PaymentMethod(raw_name=f"Primera recarga desde {app} exclusivamente con dinero en cuenta", wallet=app, payment_rail="account_balance") for app in ["Personal Pay", "Mi Personal Flow"]]
        first.benefits.append(Benefit(type="cashback", percentage=Decimal(match.group(1).replace(",", ".")), description="Adicional exclusivamente en la primera recarga por usuario con dinero en cuenta, compatible con el reintegro base según sus condiciones."))
        first.limits.append(PromotionLimit(type="monetary_cap", amount=money(match.group(2)), currency="ARS", period="transaction", scope="account", description="Tope del componente adicional de primera recarga."))
        total = re.search(r"tope maximo de reintegro total:\s*" + MONEY, text)
        if total:
            first.limits.append(PromotionLimit(type="monetary_cap", amount=money(total.group(1)), currency="ARS", period="transaction", scope="account", description="Tope conjunto de reintegro base y adicional en la primera recarga."))
        first.limits.append(PromotionLimit(type="usage_count", quantity=1, period="promotion", scope="account", description="Adicional solo en la primera recarga del usuario."))
        first.specific_conditions = "Solo primera recarga por usuario con dinero en cuenta. Los componentes base y adicional tienen sus propios topes; no se suman porcentajes.\n" + ordinary.specific_conditions
        supplement = raw.get("recharge_context", {})
        seo = supplement.get("model", {}).get("cqItems", {}).get("seo", {}).get("metadescription", "")
        extra = re.search(r"(\d+(?:[.,]\d+)?)%\s+de credito extra", folded(seo))
        if extra:
            for row in [ordinary, first]:
                row.benefits.append(Benefit(type="other", percentage=Decimal(extra.group(1).replace(",", ".")), description="Crédito extra en la línea Personal, no dinero reintegrado en la billetera. Consultar las condiciones del Beneficio Prepago."))
                row.specific_conditions += "\nCrédito extra para la línea Personal: consultar Beneficio Prepago en https://www.personal.com.ar/pay/promocion-recarga-personal."
        return [ordinary, first]
