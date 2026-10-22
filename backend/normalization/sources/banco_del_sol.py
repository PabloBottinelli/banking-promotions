"""Normalize the published Banco del Sol benefit detail and its legal text."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if unicodedata.category(c) != "Mn")


def _money(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


class BancoDelSolNormalizer:
    def normalize_many(self, raw: dict) -> list[NormalizedPromotion]:
        detail = raw["detail"]
        terms = detail.get("terms", "").strip()
        if not terms:
            raise ValueError("Faltan términos legales oficiales")
        legal = _fold(terms)
        title = detail["title"].strip()
        identifier = str(raw["source_id"])

        benefits: list[Benefit] = []
        clause = re.split(r"\bejemplo:\s*(?:para|si)\b", legal, maxsplit=1)[0]
        if "-eliteplus" in identifier:
            segment = "Elite Plus"
        elif "-elite" in identifier:
            segment = "Elite"
        else:
            segment = None
        selected_clause = clause
        if segment:
            match = re.search(r"segmento " + _fold(segment) + r":\s*reintegro del\s+(\d+(?:[.,]\d+)?)\s*%(.{0,150})", clause)
            if not match:
                raise ValueError(f"Falta porcentaje legal para segmento {segment}")
            selected_clause = match.group(0)

        refund = re.search(r"reintegro\s+del\s+(\d+(?:[.,]\d+)?)\s*%", selected_clause)
        if not refund:
            refund = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:\([^)]*\)\s*)?de\s+reintegro", selected_clause)
        if not refund:
            refund = re.search(r"devolucion[^.]{0,80}?(\d+(?:[.,]\d+)?)\s*%", selected_clause)
        if refund:
            benefits.append(Benefit(type="cashback", percentage=Decimal(refund.group(1).replace(",", "."))))
        discount = re.search(r"descuento\s+del\s+(\d+(?:[.,]\d+)?)\s*%", clause)
        if discount:
            benefits.append(Benefit(type="discount", percentage=Decimal(discount.group(1).replace(",", "."))))
        installments = re.search(r"(?:en\s+)?(\d+)\s*(?:\([^)]*\)\s*)?(?:y\s+)?hasta\s+(\d+)\s*(?:\([^)]*\)\s*)?cuotas?\s+sin\s+interes", clause)
        if installments:
            benefits.append(Benefit(type="installments", interest_free=True,
                                    description=f"De {installments.group(1)} hasta {installments.group(2)} cuotas sin interés"))
        elif re.search(r"cuotas?\s+sin\s+interes", clause):
            exact = re.search(r"(?:en\s+)(\d+)\s*(?:\([^)]*\)\s*)?cuotas?\s+sin\s+interes", clause)
            options = re.search(r"en\s+(\d+)\s*\([^)]*\),\s*(\d+)\s*\([^)]*\)\s+y\s+(\d+)\s*\([^)]*\)\s+cuotas?\s+sin\s+interes", clause)
            if options:
                benefits.append(Benefit(type="installments", installment_options=[int(x) for x in options.groups()], interest_free=True))
            elif exact:
                benefits.append(Benefit(type="installments", installment_options=[int(exact.group(1))], interest_free=True))
            elif re.search(r"en\s+\d+\s*\([^)]*\)\s+y\s+hasta", clause):
                pass
            else:
                summary = _fold(detail.get("summary") or "")
                if re.search(r"\d+\s+a\s+\d+\s+cuotas?\s+sin\s+interes", summary):
                    benefits.append(Benefit(type="installments", interest_free=True,
                                            description=detail["summary"]))
                elif re.search(r"hasta\s+\d+\s+cuotas?\s+sin\s+interes", summary):
                    benefits.append(Benefit(type="installments", interest_free=True,
                                            description=detail["summary"]))
                else:
                    benefits.append(Benefit(type="installments", interest_free=True,
                                            description="Financiación sin interés según condiciones oficiales"))
        if identifier == "caja-de-ahorro-en-usd-remunerada":
            benefits = [Benefit(type="other", reward_currency="USD",
                                description="Intereses variables sobre saldo de caja de ahorro en USD cuando la TNA publicada supere 0%")]
        elif identifier == "prevencion-retiro":
            amount_match = re.search(r"pago de\s+(\d+)\s*\([^)]*\)\s+cuotas mensuales y consecutivas de\s*\$\s*([\d.]+)", legal)
            if not amount_match:
                raise ValueError("No se pudo leer cantidad y máximo de cuotas de Prevención Retiro")
            benefits = [Benefit(type="cashback", description=f"Reintegro de hasta ${amount_match.group(2)} por cada una de {amount_match.group(1)} cuotas efectivamente debitadas")]
        elif identifier == "tarjeta-de-credito":
            waiver = re.search(r"bonificacion del\s+(\d+)\s*%.*?cargo de mantenimiento mensual", legal)
            if not waiver:
                raise ValueError("No se pudo leer bonificación de mantenimiento")
            benefits = [Benefit(type="fee_waiver", percentage=Decimal(waiver.group(1)), description="Bonificación del cargo de mantenimiento mensual de tarjeta de crédito")]
        if not benefits:
            raise ValueError("No se pudo identificar un beneficio en la cláusula legal")

        limits: list[PromotionLimit] = []
        cap = re.search(r"tope(?:\s+de\s+reintegro)?(?:\s+de)?\s*\$\s*([\d.]+(?:,\d+)?)\s*(?:\([^)]*\))?\s*por cliente por\s+(promocion|mes calendario|semana|compra)", selected_clause)
        if not cap:
            cap = re.search(r"unico tope de reintegro\s*\$\s*([\d.]+(?:,\d+)?)\s*(?:\([^)]*\))?\s*por cliente por\s+(promocion|mes calendario|semana|compra)", selected_clause)
        if cap:
            period = {"promocion": "promotion", "mes calendario": "monthly", "semana": "weekly", "compra": "transaction"}[cap.group(2)]
            limits.append(PromotionLimit(type="monetary_cap", amount=_money(cap.group(1)), currency="ARS",
                                         period=period, scope="person",
                                         shared_group_id=("banco_del_sol:" + identifier + ":cap") if "unico tope" in clause or "tope es unico" in clause else None))
        if identifier == "prevencion-retiro":
            limits.extend([PromotionLimit(type="monetary_cap", amount=_money(amount_match.group(2)), currency="ARS", period="monthly", scope="person"),
                           PromotionLimit(type="usage_count", quantity=int(amount_match.group(1)), period="promotion", scope="person")])
        elif identifier == "prevencion-salud":
            per_payment = re.search(r"tope de reintegro de\s*\$\s*([\d.]+).*?por cada cuota mensual", legal)
            if per_payment:
                limits.append(PromotionLimit(type="monetary_cap", amount=_money(per_payment.group(1)), currency="ARS", period="transaction", scope="person"))
            count = re.search(r"pago de\s+(\d+)\s*\([^)]*\)\s+cuotas mensuales consecutivas", legal)
            if count:
                limits.append(PromotionLimit(type="usage_count", quantity=int(count.group(1)), period="promotion", scope="person"))
        elif identifier == "sancor-seguros":
            per_month = re.search(r"tope de reintegro de\s*\$\s*([\d.]+).*?por mes", legal)
            if per_month:
                limits.append(PromotionLimit(type="monetary_cap", amount=_money(per_month.group(1)), currency="ARS", period="monthly", scope="person"))
            count = re.search(r"primeras\s+(\d+)\s*\([^)]*\)\s+cuotas mensuales consecutivas", legal)
            if count:
                limits.append(PromotionLimit(type="usage_count", quantity=int(count.group(1)), period="promotion", scope="person"))
        elif identifier == "primera-compra":
            first = re.search(r"tope de\s*\$\s*([\d.]+)\s*por cuenta", legal)
            if first:
                limits.append(PromotionLimit(type="monetary_cap", amount=_money(first.group(1)), currency="ARS", period="promotion", scope="account"))
            limits.append(PromotionLimit(type="usage_count", quantity=1, period="promotion", scope="account"))
        minimum = re.search(r"(?:compra minima|monto minimo de compra)\s*(?:de)?\s*\$\s*([\d.]+(?:,\d+)?)", legal)
        if minimum:
            limits.append(PromotionLimit(type="minimum_purchase", amount=_money(minimum.group(1)), currency="ARS", period="transaction"))

        date_match = re.search(r"desde las?\s+[\d:]+\s*hs\s+del\s+(\d{1,2}/\d{1,2}/\d{4}).{0,55}?hasta las?\s+[\d:]+\s*hs\s+del\s+(\d{1,2}/\d{1,2}/\d{4})", legal, re.S)
        if date_match:
            valid_from, valid_to = (datetime.strptime(value, "%d/%m/%Y").date() for value in date_match.groups())
        else:
            def label_date(key):
                label = detail.get(key)
                if not label:
                    return None
                try:
                    return datetime.strptime(label, "%d/%m/%Y").date()
                except ValueError:
                    return None
            valid_from = label_date("valid_from_label")
            valid_to = label_date("valid_to_label")
        if identifier in {"prevencion-retiro", "prevencion-salud", "sancor-seguros"}:
            validity = re.search(r"(?:plazo de vigencia|vigencia).{0,220}?desde.{0,120}?(\d{1,2}/\d{1,2}/\d{4}).{0,120}?hasta.{0,120}?(\d{1,2}/\d{1,2}/\d{4})", legal, re.S)
            if validity:
                valid_from, valid_to = (datetime.strptime(value, "%d/%m/%Y").date() for value in validity.groups())
        if identifier == "caja-de-ahorro-en-usd-remunerada":
            start = re.search(r"vigente en argentina a partir del\s+(\d{1,2}/\d{1,2}/\d{4})", legal)
            valid_from = datetime.strptime(start.group(1), "%d/%m/%Y").date() if start else None
            valid_to = None

        days = []
        eligibility = legal[: legal.find("el beneficio consiste") if "el beneficio consiste" in legal else len(legal)]
        day_clause_match = re.search(r"\bvalida?\s+(?:(?:todos?|los?|de|dias?)\s+)*(?:lunes|martes|miercoles|jueves|viernes|sabado|sabados|domingo|domingos)[^.]{0,100}?(?:desde|\.)", eligibility)
        day_clause = day_clause_match.group(0) if day_clause_match else ""
        day_names = {"lunes": "monday", "martes": "tuesday", "miercoles": "wednesday", "jueves": "thursday", "viernes": "friday", "sabados": "saturday", "sabado": "saturday", "domingos": "sunday", "domingo": "sunday"}
        for word, value in day_names.items():
            if re.search(r"\b" + word + r"\b", day_clause) and value not in days:
                days.append(value)
        ordering = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if len(days) == 2 and re.search(r"\b(?:de\s+)?\w+\s+a\s+\w+\b", day_clause):
            start, end = (ordering.index(day) for day in days)
            if start <= end:
                days = ordering[start:end + 1]
        published_every_day = any(_fold(str(label)).strip() == "todos los dias" for label in (detail.get("days") or []))
        every_day = True if not days and (published_every_day or re.search(r"\bvalida?\s+todos\s+los\s+dias\b", eligibility)) else None

        payment_methods = []
        if re.search(r"tarjeta de credito mastercard emitida por (?:el banco|bds)", eligibility):
            payment_methods.append(PaymentMethod(raw_name="Tarjeta de crédito Mastercard Banco del Sol", issuer="Banco del Sol", network="Mastercard", card_type="credit", payment_rail="card"))
        if re.search(r"tarjeta de debito visa emitidas? por el banco", eligibility):
            payment_methods.append(PaymentMethod(raw_name="Tarjeta de débito Visa Banco del Sol", issuer="Banco del Sol", network="Visa", card_type="debit", payment_rail="card"))
        if re.search(r"codigo qr desde la aplicacion de bds", eligibility):
            payment_methods.append(PaymentMethod(raw_name="QR desde la app Banco del Sol con fondos en cuenta", wallet="Banco del Sol", payment_rail="qr"))
        if identifier in {"prevencion-retiro", "prevencion-salud"}:
            payment_methods = [PaymentMethod(raw_name="Débito automático en caja de ahorro en pesos Banco del Sol", issuer="Banco del Sol", payment_rail="account_balance")]
        elif identifier == "sancor-seguros":
            payment_methods = [PaymentMethod(raw_name="Débito automático en caja de ahorro en pesos Banco del Sol", issuer="Banco del Sol", payment_rail="account_balance"),
                               PaymentMethod(raw_name="Tarjeta de crédito Banco del Sol", issuer="Banco del Sol", card_type="credit", payment_rail="card")]
        elif identifier == "los-sunchales-sunbar" and "exclusivamente para pagos efectuados mediante la aplicacion del banco" in legal:
            payment_methods = [PaymentMethod(raw_name="Débito Visa Banco del Sol mediante QR de la app Banco del Sol",
                                             issuer="Banco del Sol", network="Visa", card_type="debit",
                                             wallet="Banco del Sol", payment_rail="qr")]

        online = True if re.search(r"(?:tienda online|tiendas online|aplicable en el sitio web)", eligibility) else None
        physical = True if re.search(r"(?:todas las sucursales|locales fisicos|consumos presenciales|operaciones presenciales)", eligibility) else None
        if online and re.search(r"aplicable exclusivamente en la tienda online", eligibility):
            physical = False
        if physical and re.search(r"(?:consumos|operaciones) presenciales", eligibility) and not online:
            online = False
        if identifier == "los-sunchales-sunbar" and "ubicado en ruta nacional" in legal:
            physical = True
            online = False
        if identifier == "jbl":
            online = physical = None

        notes = ["Para clientes registrados en la app de Banco del Sol."]
        published_day_names = {
            "lunes": "monday", "martes": "tuesday", "miercoles": "wednesday",
            "jueves": "thursday", "viernes": "friday", "sabado": "saturday",
            "domingo": "sunday",
        }
        published_labels = [str(label).strip() for label in (detail.get("days") or []) if str(label).strip()]
        published_days = {published_day_names[_fold(label)] for label in published_labels
                          if _fold(label) in published_day_names}
        if days and (published_every_day or (published_days and published_days != set(days))):
            shown = ", ".join(published_labels)
            legal_days = ", ".join({"monday": "lunes", "tuesday": "martes", "wednesday": "miércoles",
                                    "thursday": "jueves", "friday": "viernes", "saturday": "sábados",
                                    "sunday": "domingos"}[day] for day in days)
            notes.append(f"La ficha indica {shown}, pero los términos legales indican {legal_days}; confirmar el día con el banco antes de comprar.")
        displayed_from = detail.get("valid_from_label")
        if displayed_from and valid_from:
            try:
                if datetime.strptime(displayed_from, "%d/%m/%Y").date() != valid_from:
                    notes.append("La fecha de inicio de la ficha difiere de los términos; se utilizó la fecha legal.")
            except ValueError:
                pass
        if segment:
            notes.append(f"Exclusivo segmento {segment}; tope compartido entre débito Visa y QR de Banco del Sol.")
        elif re.search(r"pertenecientes\s+al\s+segmento\s+elite\s+plus", eligibility):
            notes.append("Exclusivo para clientes del segmento Elite Plus; el segmento se verifica al momento de cada operación.")
        if "productos seleccionados" in legal:
            notes.append("Solo productos seleccionados por el comercio y sujetos a stock; consultar productos adheridos.")
        if "no es acumulable" in legal:
            notes.append("No acumulable con otras promociones.")
        if "programas gubernamentales" in legal:
            notes.append("Excluye productos de programas gubernamentales.")
        if "mora y/o bloqueadas" in legal:
            notes.append("Excluye cuentas en mora o bloqueadas.")
        if "prisma medios de pago" in legal and "fiserv argentina" in legal:
            notes.append("Solo pagos procesados por Prisma o Fiserv.")
        if "excluyendo operaciones realizadas mediante billeteras virtuales" in legal:
            notes.append("Excluye billeteras virtuales, plataformas de pago y PEI.")
        if "diez) dias corridos" in legal or "10 (diez) dias corridos" in legal:
            notes.append("Reintegro acreditado dentro de los 10 días corridos posteriores a la compra.")
        regions = [region for region in detail.get("regions", []) if _fold(region) != "todo el pais"]
        if regions:
            notes.append("Ámbito geográfico publicado: " + ", ".join(regions) + ".")
        if re.search(r"consumos presenciales en", eligibility):
            notes.append("Solo consumo presencial en el local indicado en los términos oficiales; verificar domicilio antes de comprar.")
        if "farmacity" in legal and "unico tope" in legal:
            notes.append("El legal describe un tope conjunto con crédito Mastercard y débito Visa; confirmar alcance de crédito, pues la elegibilidad inicial indica débito Visa.")
        if identifier == "caja-de-ahorro-en-usd-remunerada":
            remunerable = re.search(r"tope maximo para el calculo de intereses es de usd\s*([\d.]+)", legal)
            ceiling = f"USD {remunerable.group(1)}" if remunerable else "el máximo indicado en los términos"
            notes.append(f"La TNA es variable y puede ser 0%; consultar tasa vigente. Solo se remunera saldo disponible hasta {ceiling}. No se acreditan intereses diarios inferiores a USD 0,01.")
        if identifier == "oncity":
            notes.append("El legal contiene un texto incompleto sobre tramos de cuotas; verificar las opciones en el comercio antes de comprar.")
        if identifier == "jbl":
            notes.append("La ficha anuncia JBL, pero sus términos legales nombran Samsung, Samshop, Quint y 9z; confirmar elegibilidad antes de comprar.")
        merchant_check = bool(re.search(r"nomina de locales adheridos podra consultarse", legal))
        if merchant_check:
            notes.append("Solo locales adheridos: consultar la nómina indicada en los términos y confirmar la sucursal en la página oficial del beneficio antes de comprar.")
        advertised = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s+de\s+reintegro", _fold(detail.get("summary") or ""))
        parsed_refund = next((benefit.percentage for benefit in benefits if benefit.type == "cashback"), None)
        if advertised and parsed_refund is not None and Decimal(advertised.group(1).replace(",", ".")) != parsed_refund:
            notes.append(f"La ficha anuncia {advertised.group(1)}% de reintegro, pero los términos legales indican {parsed_refund}% de reintegro; confirmar con el banco antes de comprar.")
        advertised_cap = re.search(r"\btope\s*\$\s*([\d.]+(?:,\d+)?)", _fold(detail.get("description") or ""))
        legal_caps = [limit.amount for limit in limits if limit.type == "monetary_cap" and limit.currency == "ARS"]
        if advertised_cap and len(legal_caps) == 1 and _money(advertised_cap.group(1)) != legal_caps[0]:
            legal_amount = f"{legal_caps[0]:,.0f}".replace(",", ".")
            notes.append(f"La ficha anuncia un tope de ${advertised_cap.group(1)}, pero los términos legales indican un tope de ${legal_amount}; confirmar con el banco antes de comprar.")
        if 'tope de ""' in legal:
            notes.append("El legal publica un tope sin monto; consultar al banco antes de comprar.")
        if identifier == "prevencion-retiro":
            notes.append("Adhesión a débito automático de Prevención Retiro; reintegro equivalente al débito efectivo hasta el máximo por cuota, durante los primeros meses indicados.")
        if identifier in {"prevencion-salud", "sancor-seguros"}:
            notes.append("Solo primeras cuotas mensuales consecutivas efectivamente debitadas, con exclusiones y plazo de acreditación detallados en términos.")
        if identifier == "sancor-seguros":
            if "se hayan favorecido, con anterioridad, de esta promocion" in legal:
                notes.append("Excluye clientes que ya recibieron esta promoción, cualquiera haya sido el medio de pago.")
            if all(name in legal for name in ("prevencion salud", "prevencion art", "prevencion retiro")):
                notes.append("No incluye pólizas de Prevención Salud, Prevención ART ni Prevención Retiro.")
        if identifier == "primera-compra":
            notes.append("Solo primera compra en pesos con nueva tarjeta de crédito Mastercard; se requiere alta y evaluación crediticia.")
        if identifier == "el-pulqui-la-tostadense":
            notes.append("El reintegro con débito y la financiación con crédito son alternativas y no se aplican en una misma compra.")

        item = NormalizedPromotion(
            source="banco_del_sol", source_id=identifier,
            promotion_group_id=re.sub(r"-eliteplus$|-elite$", "", identifier),
            scraped_at=datetime.fromisoformat(raw["scraped_at"]), title=title,
            scope="other" if identifier in {"caja-de-ahorro-en-usd-remunerada", "tarjeta-de-credito", "primera-compra"} else "merchant",
            merchant=None if identifier in {"caja-de-ahorro-en-usd-remunerada", "tarjeta-de-credito", "primera-compra"}
                     else "Samsung, Samshop, Quint y 9z (según términos legales)" if identifier == "jbl" else title,
            category=detail.get("category"),
            promotion_url=raw["promotion_url"], requires_merchant_verification=merchant_check,
            valid_from=valid_from, valid_to=valid_to,
            benefits=benefits, limits=limits, payment_methods=payment_methods,
            days_of_week=days, applies_every_day=every_day, online=online, physical=physical,
            specific_conditions=" ".join(notes), terms=terms,
        )
        if identifier == "tarjeta-de-credito":
            initial_months = re.search(r"durante los primeros tres\s*\((\d+)\)\s+meses", legal)
            high = re.search(r"en un\s+(\d+)\s*%.{0,180}?superiores a\s*\$\s*([\d.]+)", legal, re.S)
            lower = re.search(r"en un\s+(\d+)\s*%.{0,180}?superiores a\s*\$\s*([\d.]+).{0,120}?iguales a\s*\$\s*([\d.]+)", legal, re.S)
            annual = re.search(r"bonificacion del\s+(\d+)\s*\([^)]*\)\s+del cargo anual de renovacion.{0,360}?superiores a\s*\$\s*([\d.]+)", legal, re.S)
            if not all((initial_months, high, lower, annual)):
                raise ValueError("Tramos legales incompletos de bonificación de tarjeta")
            card_restrictions = []
            if "tarjetas adicionales, empresariales" in legal:
                card_restrictions.append("Excluye tarjetas adicionales, empresariales y otras distintas de las Mastercard Banco del Sol indicadas.")
            if "no se encontrara gozando de un beneficio promocional vigente de igual naturaleza" in legal:
                card_restrictions.append("Para tarjetas existentes, el mantenimiento se bonifica solo si al inicio de la promoción no tenían una bonificación similar vigente o esta ya había vencido; se computa desde el inicio de la promoción y aplican las condiciones previstas desde el cuarto mes para tarjetas nuevas.")
            shared_conditions = " ".join(card_restrictions)
            first = item.model_copy(update={"source_id": identifier + ":initial-maintenance",
                                            "title": title + ": mantenimiento inicial",
                                            "specific_conditions": f"Tarjetas nuevas: cargo de mantenimiento mensual bonificado durante los primeros {initial_months.group(1)} meses desde el alta. {shared_conditions}".strip()})
            full = item.model_copy(update={"source_id": identifier + ":ongoing-full-maintenance",
                                           "title": title + f": mantenimiento mensual {high.group(1)}%",
                                           "benefits": [Benefit(type="fee_waiver", percentage=Decimal(high.group(1)), description="Bonificación del mantenimiento mensual")],
                                           "specific_conditions": f"Desde el cuarto mes: débito automático de Sancor Seguros o consumos mensuales con la tarjeta superiores a ${high.group(2)}. Solo cuentan consumos confirmados, netos de anulaciones y devoluciones. {shared_conditions}".strip()})
            half = item.model_copy(update={"source_id": identifier + ":ongoing-half-maintenance",
                                           "title": title + f": mantenimiento mensual {lower.group(1)}%",
                                           "benefits": [Benefit(type="fee_waiver", percentage=Decimal(lower.group(1)), description="Bonificación del mantenimiento mensual")],
                                           "specific_conditions": f"Desde el cuarto mes: consumos mensuales superiores a ${lower.group(2)} e inferiores o iguales a ${lower.group(3)}. Solo cuentan consumos confirmados, netos de anulaciones y devoluciones. {shared_conditions}".strip()})
            renewal = item.model_copy(update={"source_id": identifier + ":annual-renewal",
                                              "title": title + ": renovación anual",
                                              "benefits": [Benefit(type="fee_waiver", percentage=Decimal(annual.group(1)), description="Bonificación del cargo anual de renovación")],
                                              "specific_conditions": f"Durante los primeros 12 meses desde el alta, requiere condiciones de bonificación del mantenimiento y consumos anuales acumulados superiores a ${annual.group(2)}. Solo cuentan consumos confirmados, netos de anulaciones y devoluciones. {shared_conditions}".strip()})
            return [first, full, half, renewal]
        if identifier == "el-pulqui-la-tostadense":
            credit_clause = re.search(r"quienes abonen con tarjeta de credito mastercard.{0,260}?financiar sus compras en\s+(\d+)\s*\([^)]*\)\s+y\s+hasta\s+(\d+)\s*\([^)]*\)\s+cuotas sin interes", legal)
            if not credit_clause:
                raise ValueError("No se pudo estructurar alternativa de financiación con crédito")
            shared = {key: value for key, value in item.model_dump().items()
                      if key not in {"source_id", "benefits", "limits", "payment_methods", "specific_conditions"}}
            debit = item.model_copy(update={"source_id": identifier + ":debit-cashback",
                                            "payment_methods": [p for p in payment_methods if p.card_type == "debit"]})
            credit = NormalizedPromotion(**shared, source_id=identifier + ":credit-installments",
                                         benefits=[Benefit(type="installments", interest_free=True,
                                                           description=f"De {credit_clause.group(1)} hasta {credit_clause.group(2)} cuotas sin interés")],
                                         limits=[], payment_methods=[p for p in payment_methods if p.card_type == "credit"],
                                         specific_conditions=" ".join(notes))
            return [debit, credit]
        return [item]
