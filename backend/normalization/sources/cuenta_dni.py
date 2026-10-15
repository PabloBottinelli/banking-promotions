"""Deterministic Cuenta DNI V2 normalization from official legal clauses.

API display dates/rates can differ from legal eligibility. Legal clauses take
precedence; unresolved source contradictions are retained, never guessed away.
"""
import calendar
import re
import unicodedata
from datetime import date
from decimal import Decimal

from bs4 import BeautifulSoup

from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit


def plain(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def fold(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn")


MONTHS = {name: i for i, name in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"], 1)}
WEEKDAYS = dict(zip(["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"],
                    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]))


def decimal(value):
    return Decimal(value.replace(".", "").replace(",", "."))


def conflicting_cap_scope(legal):
    s = fold(legal)
    return "por cuit" in s and "unificado significa" in s and "en todos los comercios adheridos" in s


def validity(legal):
    normalized = fold(legal)
    match = re.search(r"(?:promocion|beneficio) valid[ao](.+?)(?:para (?:las )?compras|a traves|en el ambito)", normalized)
    if not match:
        return None, None
    clause = match.group(1)
    years = re.findall(r"\b(20\d\d)\b", clause)
    months = list(re.finditer(r"\b(" + "|".join(MONTHS) + r")\b", clause))
    if not years or not months:
        return None, None
    year = int(years[-1])
    first, last = months[0], months[-1]
    start_month, end_month = MONTHS[first.group()], MONTHS[last.group()]
    before_first = clause[:first.start()]
    before_last = clause[:last.start()]
    start_days = re.findall(r"\b(\d{1,2})\b", before_first)
    end_days = re.findall(r"\b(\d{1,2})\b", before_last[first.end():] if len(months) > 1 else before_last)
    start_day = int(start_days[0]) if start_days else 1
    end_day = int(end_days[-1]) if end_days else calendar.monthrange(year, end_month)[1]
    # A single explicit date in one month describes a start, not a one-day offer.
    if len(months) == 1 and len(start_days) == 1:
        end_day = calendar.monthrange(year, end_month)[1]
    return date(year, start_month, start_day), date(year, end_month, end_day)


def weekdays(legal, display):
    # Only the positive validity clause, never exclusions or examples.
    s = fold(legal)
    m = re.search(r"(?:promocion|beneficio) valid[ao](.+?)(?:para (?:las )?compras|a traves|en el ambito)", s)
    clause = m.group(1) if m else fold(display)
    clause = re.split(r"\bno aplica\b|\bse excluy\w*\b|\bexcepto\b", clause, maxsplit=1)[0]
    if re.search(r"todos los dias\s*(?:de\b|del\b|desde\b|,|$)", clause):
        return [], True
    if re.search(r"lunes a viernes", clause):
        return list(WEEKDAYS.values())[:5], False
    return [english for spanish, english in WEEKDAYS.items() if re.search(r"\b" + spanish + r"s?\b", clause)], None


def limits_for(clause, group):
    normalized = fold(clause)
    # Referenced compatible campaigns have independent caps; do not import them.
    normalized = normalized.split("la presente promocion es acumulable")[0]
    result = []
    cap = re.search(r"\btope(?: de reintegro)?(?: unificado)?(?: de)?\s*\$\s*(?:pesos\s*)?([\d.,]+)", normalized)
    if cap:
        tail = normalized[cap.end():cap.end() + 150]
        period = "weekly" if "por semana" in tail else "monthly" if "por mes" in tail else "daily" if re.search(r"por (?:martes|miercoles|sabado|dia)", tail) else None
        scope = "person" if "por persona" in tail else "account" if "por cuenta" in tail else None
        if "por cuit" in tail:
            scope = "person_merchant_tax_id"
        ambiguous_scope = conflicting_cap_scope(clause)
        if ambiguous_scope:
            scope = None
        if "por sabado" in tail and "total de compras realizadas en el mes" in normalized:
            period = None
        result.append(PromotionLimit(type="monetary_cap", amount=decimal(cap.group(1)), currency="ARS",
                                     period=period, scope=scope, shared_group_id=group,
                                     description="Alcance del tope sin resolver: por CUIT de comercio versus total de todos los comercios de la campaña; consultar fuente" if ambiguous_scope else
                                     "Tope compartido entre comercios de la campaña; consultar términos" if scope != "person_merchant_tax_id" else
                                     "Tope por CUIT de comercio y por persona; no por sucursal"))
    minimum = re.search(r"minimo de compra (?:sea )?(?:de )?\$\s*(?:pesos\s*)?([\d.,]+)", normalized)
    if minimum:
        result.append(PromotionLimit(type="minimum_purchase", amount=decimal(minimum.group(1)), currency="ARS", period="transaction"))
    return result


def payment_options(clause, installments=False):
    s = fold(clause)
    if installments:
        return [PaymentMethod(raw_name="Tarjeta de crédito " + network + " Banco Provincia adherida a Cuenta DNI mediante QR",
                              issuer="Banco Provincia", network=network, card_type="credit", wallet="Cuenta DNI", payment_rail="qr")
                for network in ["Visa", "Mastercard"] if network.lower() in s]
    if "nfc" in s or "sin contacto" in s:
        methods = []
        for token, kind in [("credito", "credit"), ("debito", "debit")]:
            if re.search(r"visa\s+" + token, s):
                methods.append(PaymentMethod(raw_name="Visa " + token + " habilitada en Cuenta DNI NFC (Android)",
                                             network="Visa", card_type=kind, wallet="Cuenta DNI", payment_rail="nfc"))
        if not methods:
            raise ValueError("NFC clause without verified Visa card type")
        return methods
    methods = []
    if re.search(r'"pagar qr"|"pago clave dni" y/o qr|con qr o clave dni', s):
        methods.append(PaymentMethod(raw_name="Cuenta DNI QR con dinero en cuenta", wallet="Cuenta DNI", payment_rail="qr"))
    if "clave dni" in s:
        methods.append(PaymentMethod(raw_name="Cuenta DNI Clave DNI con dinero en cuenta", wallet="Cuenta DNI", payment_rail="other"))
    if '"link de pago"' in s:
        methods.append(PaymentMethod(raw_name="Cuenta DNI Link de pago con dinero en cuenta", wallet="Cuenta DNI", payment_rail="other"))
    return methods or [PaymentMethod(raw_name="Cuenta DNI con dinero en cuenta", wallet="Cuenta DNI", payment_rail="account_balance")]


class CuentaDNINormalizer:
    def normalize_many(self, raw):
        e = raw["payload"]["Entity"]
        b = e["Beneficio"]
        if not plain(b.get("titulo")):
            raise ValueError("Blank campaign title")
        legal = plain(b.get("legal"))
        conditions = [plain(c["texto"]) for c in sorted(e.get("Condiciones", []), key=lambda c: c["orden"])]
        group = str(raw["source_id"])
        localidades = bool(b.get("urlPagina")) and b["url"] == "especiallocalidades"
        sections = [("base", legal)]
        extra_conditions = []
        external = raw.get("external_terms")
        if external:
            legal = external["text"]
            offer = external["payload"]
            # Banco Provincia's own card specifies Cuenta DNI Visa debit only.
            sections = [("base", offer["offerShortDescription"]["text"])]
            extra_conditions = ["Solo Cuenta DNI NFC con Visa débito habilitada en Android. Consultar exclusiones y territorio del PDF oficial: " + external["pdf_url"],
                                "La fuente externa contiene una exclusión NFC contradictoria; requiere verificación."]
        elif localidades:
            soup = BeautifulSoup(raw["linked_page"]["html"], "html.parser")
            paragraphs = [plain(str(p)) for p in soup.select("p")]
            clauses = [p for p in paragraphs if re.match(r"\([123]\)\s*PROMOCI", p)]
            if len(clauses) != 3:
                raise ValueError("Changed localidades legal sections")
            # Section 3 is the existing Comercios de Cercanía campaign, not a third reward here.
            sections = [("lunes-martes", clauses[0]), ("miercoles-jueves", clauses[1])]
            legal = "\n\n".join(clauses)
            extra_conditions = ["Acumulable con Comercios de Cercanía; topes independientes. Consultar locales adheridos por localidad."]
            # This redirect's modal API retains obsolete display conditions.
            # Preserve it in raw; only its current linked-page clauses govern variants.
            conditions = []
        else:
            numbered = re.split(r"\b[12]-\s*(?=\d+% DE REINTEGRO)", legal)
            if len(numbered) > 1:
                sections = []
                for part in numbered[1:]:
                    first_clause = re.split(r"EN LOCALES|APLICARÁ|EL TOPE", part, maxsplit=1)[0]
                    name = "nfc" if "NFC" in first_clause else "saldo"
                    sections.append((name, part))
            if not legal:
                raise ValueError("Blank essential legal terms")
        rows = []
        for suffix, clause in sections:
            installments = b["tipo"] == 2
            if installments:
                if "cuotas sin interes" not in fold(clause):
                    raise ValueError("Unsupported installment campaign")
                quantity = re.search(r"\((\d+)\) cuotas", fold(clause))
                if not quantity:
                    raise ValueError("Missing installments")
                benefits = [Benefit(type="installments", installment_options=[int(quantity.group(1))], interest_free=True,
                                    description="Hasta " + quantity.group(1) + " cuotas sin interés")]
            else:
                rate = re.search(r"(?:bonificacion del?\s+|consiste en un\s+)?(\d+(?:[.,]\d+)?)\s*%", fold(clause))
                if not rate:
                    raise ValueError("No evidenced campaign percentage")
                immediate = bool(re.search(r"(?:descuento|beneficio).{0,65}(?:momento de la compra|directamente en linea de caja)|descuento en caja", fold(clause)))
                benefits = [Benefit(type="discount" if immediate else "cashback", percentage=Decimal(rate.group(1).replace(",", ".")),
                                    description="Descuento en línea de caja" if immediate else "Reintegro en cuenta o resumen según medio de pago")]
            period_legal = legal
            start, end = validity(clause if b["url"] == "especiallocalidades" else legal)
            if external:
                start, end = date.fromisoformat(offer["validityFromDate"]), date.fromisoformat(offer["validityToDate"])
            days, everyday = weekdays(clause if b["url"] == "especiallocalidades" else period_legal, b.get("titulo_fecha", ""))
            if external:
                days, everyday = weekdays("", offer["offerShortDescription"]["text"])
            limits = limits_for(clause, group + ":" + suffix)
            effective_clause = clause
            if external:
                effective_clause = "Visa débito NFC " + clause
            elif suffix in {"saldo", "nfc"}:
                effective_clause = re.split(r"EN LOCALES|APLICARÁ|EL TOPE", clause, maxsplit=1)[0]
            else:
                effective_clause += " " + " ".join(c for c in conditions if "promocion valida para compras" in fold(c))
            # Full exclusion clauses remain in terms; concise useful restrictions here.
            restrictions = []
            restrictions_legal = clause if localidades else legal
            for sentence in re.split(r"(?<=[.!])\s+", restrictions_legal):
                if any(token in fold(sentence) for token in ["se excluy", "no acumulable", "acumulable con", "no aplica", "ambito de", "valida unicamente", "valido solo", "territorio", "neuquen"]):
                    if "ejemplo" not in fold(sentence):
                        restrictions.append(sentence)
            display_conditions = [] if localidades else [b.get("subtitulo", ""), b.get("bajada", ""), *conditions]
            specific = [*display_conditions, *restrictions, *extra_conditions]
            if localidades:
                specific.append("Condiciones de la página vigente; el detalle API conserva información desactualizada, preservada en el registro original.")
                if "sin tope" in fold(clause):
                    specific.append("Sin tope de reintegro.")
                for limit in limits:
                    if limit.type == "monetary_cap":
                        period_label = {"weekly": "semanal", "monthly": "mensual"}.get(limit.period, "según términos")
                        specific.append(f"Tope de reintegro {period_label} por CUIT de comercio y por persona: ${limit.amount}.")
            if conflicting_cap_scope(clause):
                specific.append("Alcance del tope contradictorio: el encabezado y la cláusula por CUIT indican por comercio, pero el legal también lo unifica sobre compras en todos los comercios adheridos. Verificar el alcance antes de comprar.")
            if suffix != "base":
                specific.append("Modalidad exclusiva: " + suffix + "; los porcentajes de otras modalidades no se suman.")
            if "por sabado" in fold(legal) and "total de compras realizadas en el mes" in fold(legal):
                specific.append("Período del tope no resuelto: el legal indica por sábado y también total mensual; consultar antes de comprar.")
            if "no acumulable" in fold(legal) and any("beneficio acumulable" in fold(c) for c in [*conditions, b.get("bajada", "")]):
                specific.append("La fuente contradice la acumulación entre condiciones y legal; verificar antes de comprar.")
            specific.append("Consultar los comercios o sucursales adheridos en el enlace oficial de la promoción.")
            if not legal and not external:
                raise ValueError("No legal terms")
            merchant = {"dia": "DIA", "nini": "Nini", "laanonima": "La Anónima", "carrefour": "Carrefour",
                        "sodimac": "Sodimac", "josimar": "Josimar", "changomas": "Chango Más", "supermercadocoto": "COTO",
                        "mostaza": "Mostaza", "supercoop": "Supercoop", "comerciosdebarrio": "Comercios de cercanía",
                        "especiallocalidades": "Comercios adheridos por localidad", "beneficio_librerias": "Librerías de texto",
                        "farmaciasyperfumerias": "Farmacias y perfumerías", "petshopyvet": "Veterinarias y pet shops",
                        "especialypf": "YPF Full", "especialgastronomia": "Gastronomía", "beneficiouniversidades": "Comercios de universidades",
                        "feriasymercados": "Ferias y mercados bonaerenses", "marcasdestacadas": "Marcas destacadas"}.get(b["url"], "Comercios adheridos")
            scope = "merchant" if b["url"] in {"dia", "nini", "laanonima", "carrefour", "sodimac", "josimar", "changomas", "supermercadocoto", "mostaza", "supercoop", "especialypf"} else "category"
            url = raw.get("linked_page", {}).get("url") or raw["promotion_url"]
            # The official Mostaza legal says "DE MANERA PRSENCIAL ... EN LOCALES".
            # Accept that contextual source typo; NFC alone does not establish a channel.
            physical_clause = fold(clause)
            physical_typo = bool(re.search(r"compras realizadas de manera prsencial\b.*?\ben locales\b", physical_clause))
            physical = True if "presencial" in physical_clause or "linea de caja" in physical_clause or physical_typo or external else None
            row = NormalizedPromotion(source="cuenta_dni", source_id=group + ":" + suffix, scraped_at=raw["scraped_at"],
                                      title=b["titulo"], scope=scope, valid_from=start, valid_to=end,
                                      promotion_group_id=group, merchant=merchant,
                                      category=", ".join(r["nombre"] for r in e.get("Rubros", [])), promotion_url=url,
                                      requires_merchant_verification=True, benefits=benefits, limits=limits,
                                      payment_methods=payment_options(effective_clause, installments), days_of_week=days,
                                      applies_every_day=everyday, online=False if external else None, physical=physical,
                                      specific_conditions=" ".join(dict.fromkeys(s.strip() for s in specific if s and s.strip())), terms=legal)
            rows.append(row)
            # An additional segment benefit is a compatible component, with its own cap.
            for condition in conditions:
                if "jubilado" in fold(condition) and "adicional" in fold(condition):
                    match = re.search(r"(\d+)\s*%.*?tope de\s*\$\s*([\d.,]+)", condition)
                    if not match:
                        raise ValueError("Unparsed retiree additional reward")
                    extra = row.model_copy(deep=True)
                    extra.source_id += ":jubilados"
                    extra.benefits.append(Benefit(type="cashback", percentage=Decimal(match.group(1)), description=condition))
                    extra.limits.append(PromotionLimit(type="monetary_cap", amount=decimal(match.group(2).rstrip(".")), currency="ARS",
                                                       scope="person", description="Tope exclusivo del reintegro adicional a jubilados; período no publicado"))
                    extra.specific_conditions += " Exclusivo jubilados que cobran en Banco Provincia. El porcentaje adicional tiene un tope independiente."
                    rows.append(extra)
        return rows
