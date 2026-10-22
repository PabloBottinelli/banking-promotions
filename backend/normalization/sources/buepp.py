import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from bs4 import BeautifulSoup

from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit


def plain(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def fold(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn")


def money(value):
    return Decimal(value.replace(".", "").replace(",", "."))


class BueppNormalizer:
    def normalize_many(self, raw):
        b = raw["detail"]["beneficio"]
        terms = b.get("legales", "")
        text = plain(terms)
        legal = fold(text)
        if not legal:
            raise ValueError("Missing legal evidence")
        benefit_list = []
        percent = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:\([^)]*\)\s*)?(?:de\s+)?(?:descuento|reintegro)", legal)
        if not percent:
            percent = re.search(r"(?:reintegro sera del|descuento del)\s+(\d+(?:[.,]\d+)?)\s*%", legal)
        if percent:
            kind = "cashback" if re.search(r"reintegro|devolucion|se acreditara|via reintegro", legal) else "discount"
            benefit_list.append(Benefit(type=kind, percentage=Decimal(percent[1].replace(",", "."))))
        installment = re.search(r"((?:\d+\s*(?:\([^)]*\)\s*)?(?:,\s*|y\s*)?)+)cuotas?\s+sin\s+interes", legal)
        if installment:
            options = [int(n) for n in re.findall(r"\d+", installment[1])]
            benefit_list.append(Benefit(type="installments", installment_options=options,
                                       interest_free=True, description="Hasta " + str(options[-1]) + " cuotas sin interés" if "hasta" in legal[max(0, installment.start()-15):installment.start()] else None))
        if not benefit_list:
            raise ValueError("No verified benefit could be parsed from legal terms")
        identifier = str(raw["source_id"])
        limits = self._limits(legal, identifier)
        start, end = self._dates(b, legal)
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        prefix = legal[:400]
        names = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        days = [day for day, name in zip(weekdays, names) if re.search(r"\b"+name+r"s?\b", prefix)]
        every_day = True if not days and re.search(r"\btodos los dias\b", prefix) else None
        if not days and not every_day:
            mask = b.get("dias", "")
            if mask == "LMMJVSD":
                every_day = True
            elif len(mask) == 7 and all(c in "LMMJVSD-" for c in mask):
                days = [day for day,c in zip(weekdays,mask) if c != "-"]
        physical = True if re.search(r"compras presenciales|locales fisicos|comercios fis(?:i)?cos|tiendas fisicas", legal) else None
        online_evidence = re.sub(r"no (?:incluye|aplica|valido|valida)[^.]*?(?:on ?line|por internet)","",legal)
        positive_online = bool(re.search(r"\btiendas? onlines?\b|a traves de la pagina web|compra online|compras (?:realizadas )?en (?:https?://|www\.)|y www\.", online_evidence))
        excluded_online = bool(re.search(r"no (?:incluye|aplica|valido|valida) (?:para )?(?:la )?(?:venta|compras?|tienda)?\s*(?:on ?line|por internet)", legal))
        online = None if positive_online and excluded_online else True if positive_online else False if excluded_online else None
        if re.search(r"(?:aplica )?exclusivamente a compras presenciales",legal):
            online = False
        requires = bool(re.search(r"adherid[oa]s", legal))
        merchant = raw["detail"].get("comercio", {}).get("nombre") or raw["catalog"].get("comercio_nombre")
        category = b.get("nombreRubro")
        scope = "other" if re.search(r"pagos no tributarios|impuesto inmobiliario", legal) else "shopping" if b.get("shopping") else "merchant" if merchant else "category"
        conditions = self._conditions(text, b, raw, requires)
        if online is None and positive_online and excluded_online:
            conditions += " La fuente contiene indicaciones contradictorias sobre compras online; consultar condiciones oficiales."
        labels = [f"{x.percentage}% {'reintegro' if x.type == 'cashback' else 'descuento'}" if x.percentage is not None else " / ".join(map(str,x.installment_options)) + " cuotas sin interés" for x in benefit_list]
        common = dict(source="buepp", scraped_at=raw["scraped_at"], title=f"{merchant or category}: " + " + ".join(labels),
                      scope=scope, merchant=merchant, category=category, promotion_url=raw["promotion_url"],
                      requires_merchant_verification=requires, valid_from=start, valid_to=end,
                      limits=limits, days_of_week=days, applies_every_day=every_day,
                      online=online, physical=physical, specific_conditions=conditions,
                      terms=terms + ("\n" + b["legales_genericas"] if b.get("legales_genericas") else ""))
        credit, debit, balance = self._payments(legal, b)
        has_financing = any(x.type == "installments" for x in benefit_list)
        other_benefits = [x for x in benefit_list if x.type != "installments"]
        if has_financing and other_benefits and (debit or balance):
            for limit in limits:
                if limit.type == "monetary_cap" and not limit.shared_group_id:
                    limit.shared_group_id = "buepp:" + identifier
            noncredit_common = {**common, "title":f"{merchant or category}: " + " + ".join(labels[:-1]),
                                "specific_conditions":conditions + " Financiación solo con tarjeta de crédito; esta variante corresponde a reintegro con otros medios admitidos."}
            return [NormalizedPromotion(**common, source_id=identifier+":credit", promotion_group_id=identifier,
                                        benefits=benefit_list, payment_methods=credit),
                    NormalizedPromotion(**noncredit_common, source_id=identifier+":non-credit", promotion_group_id=identifier,
                                        benefits=other_benefits, payment_methods=debit+balance)]
        payments = credit if has_financing else credit+debit+balance
        if re.search(r"funcionalidad nfc.*?unicamente para dispositivos android",legal):
            qr_payments = [p for p in payments if p.payment_rail == "qr"]
            nfc_payments = [p.model_copy(update={"wallet":wallet,"payment_rail":"nfc",
                                               "raw_name":f"{p.card_type} {p.network or ''} NFC vía {wallet}"})
                            for p in qr_payments if p.wallet == "Buepp" for wallet in ("Buepp","MODO")]
            for limit in limits:
                if limit.type == "monetary_cap" and not limit.shared_group_id:
                    limit.shared_group_id = "buepp:" + identifier
            return [NormalizedPromotion(**{**common,"specific_conditions":conditions + " Esta variante utiliza QR desde Buepp o App Ciudad; la restricción Android corresponde únicamente a NFC."},source_id=identifier+":qr",promotion_group_id=identifier,
                                        benefits=benefit_list,payment_methods=qr_payments),
                    NormalizedPromotion(**{**common,"specific_conditions":conditions + " NFC exclusivamente desde Buepp o MODO y únicamente en dispositivos Android."},source_id=identifier+":nfc-android",promotion_group_id=identifier,
                                        benefits=benefit_list,payment_methods=nfc_payments)]
        if re.search(r"y en la tienda online.{0,100}pagando con tarjetas",legal):
            direct = [p.model_copy(update={"wallet":None,"payment_rail":"card","raw_name":"Tarjeta de crédito "+(p.network or "")}) for p in credit if p.wallet == credit[0].wallet]
            for limit in limits:
                if limit.type == "monetary_cap" and not limit.shared_group_id:
                    limit.shared_group_id = "buepp:" + identifier
            return [NormalizedPromotion(**{**common,"online":False,"physical":True},source_id=identifier+":physical-qr",promotion_group_id=identifier,
                                        benefits=benefit_list,payment_methods=payments),
                    NormalizedPromotion(**{**common,"online":online,"physical":False,"specific_conditions":conditions + " Esta alternativa corresponde al pago con tarjeta en la tienda online mencionada; consultar la contradicción de canales en el legal."},source_id=identifier+":online-card",promotion_group_id=identifier,
                                        benefits=benefit_list,payment_methods=direct)]
        if re.search(r"en comercios fisicos(?: adheridos)? pagando con tarjetas",legal) and any(x.payment_rail=="card" for x in payments):
            return [NormalizedPromotion(**{**common,"online":True,"physical":None},source_id=identifier+":online-qr",promotion_group_id=identifier,
                                        benefits=benefit_list,payment_methods=[x for x in payments if x.payment_rail=="qr"]),
                    NormalizedPromotion(**{**common,"online":False,"physical":True},source_id=identifier+":physical-card",promotion_group_id=identifier,
                                        benefits=benefit_list,payment_methods=[x for x in payments if x.payment_rail=="card"])]
        return [NormalizedPromotion(**common, source_id=identifier, promotion_group_id=identifier,
                                    benefits=benefit_list, payment_methods=payments)]

    @staticmethod
    def _dates(b, legal):
        matches = re.search(r"(?:desde\s+(?:del?\s+)?|entre el dia\s+)(\d{1,2}/\d{1,2}/\d{2,4}).{0,25}?(\d{1,2}/\d{1,2}/\d{2,4})", legal)
        if matches:
            def parse(s):
                return datetime.strptime(s, "%d/%m/%Y" if len(s.split('/')[-1]) == 4 else "%d/%m/%y").date()
            return parse(matches[1]), parse(matches[2])
        return tuple(datetime.fromisoformat(b[key]).date() if b.get(key) else None for key in ("fechaDesde", "fechaHasta"))

    @staticmethod
    def _limits(legal, identifier):
        result = []
        cap_text = re.sub(r"\bsin tope(?: de reintegro)?\b","",legal)
        cap = re.search(r"(?:tope|importe maximo de descuento)[^$.;]{0,100}\$\s*([\d.]+(?:,\d+)?)", cap_text)
        if cap:
            clause = cap_text[max(0,cap.start()-30):cap.end()+90]
            period = "monthly" if re.search(r"mensual|por mes",clause) else "weekly" if re.search(r"semana",clause) else "promotion" if "unica vez" in clause else None
            scope = "card" if "por tarjeta" in clause else "person" if "por cliente" in clause else None
            shared = None
            if "totales para todos los comercios" in legal:
                group = re.search(r'bajo el rubro\s+[“"\']([^”"\']+)',legal)
                if group:
                    shared = "buepp:" + re.sub(r"\W+","-",group[1]).strip("-")
            elif "tope compartido para el pago de ambos impuestos" in legal:
                shared = "buepp:agip"
            result.append(PromotionLimit(type="monetary_cap",amount=money(cap[1]),currency="ARS",period=period,scope=scope,
                                         shared_group_id=shared,description="Tope compartido: consultar condiciones" if shared else None))
        minimum = re.search(r"(?:minimo (?:de )?compra|compras? minimas?)[^$]{0,25}\$\s*([\d.]+(?:,\d+)?)",legal)
        if minimum:
            result.append(PromotionLimit(type="minimum_purchase",amount=money(minimum[1]),currency="ARS",period="transaction"))
        budget = re.search(r"hasta alcanzar la suma de\s*\$\s*([\d.]+(?:,\d+)?)",legal)
        if budget:
            result.append(PromotionLimit(type="stock",amount=money(budget[1]),currency="ARS",scope="campaign",period="promotion",
                                         shared_group_id="buepp:"+identifier+":budget",description="Presupuesto total de reintegros; finaliza al agotarse"))
        if "por unica vez por cliente" in legal:
            result.append(PromotionLimit(type="usage_count",quantity=1,period="promotion",scope="person"))
        return result

    @staticmethod
    def _payments(legal, b):
        legal = re.sub(r"\([^)]*\)","",legal)
        legal = re.split(r"quedan excluidas|no valido para|no aplica para|el reintegro|el descuento podra|la presente promocion es valida solo", legal)[0]
        credit_clause = re.search(r"tarjetas?\s+de\s+credito\s+(.{0,100}?)(?:de banco|del banco|de locales|a traves|exclusivamente|\. |\s*,\s*que\b)", legal)
        debit_clause = re.search(r"tarjetas?\s+de\s+debito\s+(.{0,70}?)(?:,| y de credito|escaneando|exclusivamente|\. )", legal)
        wallet_names = []
        if re.search(r"(?:desde|a traves de).{0,50}\bbuepp\b",legal):
            wallet_names.append("Buepp")
        if re.search(r"(?:desde|a traves de).{0,50}\bapp ciudad\b",legal):
            wallet_names.append("App Ciudad")
        if "a traves de modo, app ciudad o buepp" in legal:
            wallet_names.append("MODO")
        qr = bool(re.search(r"\bqr\b",legal))
        wallets = wallet_names or [None]
        issuer = "Banco Ciudad" if re.search(r"tarjetas.{0,160}(?:banco ciudad|del ciudad)",legal) else None
        def card_options(kind,clause):
            if not re.search(r"tarjetas?\s+de\s+"+kind,legal) and not (kind == "credito" and re.search(r"tarjeta de debito, credito",legal)):
                return []
            networks = [network for token,network in [("visa","Visa"),("mastercard","Mastercard"),("maestro","Maestro"),("cabal","Cabal")] if clause and re.search(r"\b"+token+r"\b",clause[1])]
            if not networks:
                networks = [None]
            return [PaymentMethod(raw_name=f"{kind} {network or ''} {wallet or ''}".strip(),issuer=issuer,network=network,
                                  card_type="credit" if kind=="credito" else "debit",wallet=wallet,
                                  payment_rail="qr" if qr else None if wallet else "card") for network in networks for wallet in wallets]
        credit, debit = card_options("credito",credit_clause), card_options("debito",debit_clause)
        if "tarjetas de credito y debito del banco ciudad" in legal:
            credit = [PaymentMethod(raw_name="Crédito Banco Ciudad vía " + (wallet or "tarjeta"),issuer="Banco Ciudad",card_type="credit",wallet=wallet,payment_rail="qr" if qr else None) for wallet in wallets]
            debit = [PaymentMethod(raw_name="Débito Banco Ciudad vía " + (wallet or "tarjeta"),issuer="Banco Ciudad",card_type="debit",wallet=wallet,payment_rail="qr" if qr else None) for wallet in wallets]
        if "tarjetas de debito visa y maestro y de credito visa o mastercard" in legal:
            credit = [PaymentMethod(raw_name="Crédito " + network + " vía " + (wallet or "tarjeta"),issuer="Banco Ciudad",network=network,card_type="credit",wallet=wallet,payment_rail="qr" if qr else "card") for network in ("Visa","Mastercard") for wallet in wallets]
        if "tarjetas de credito o debito visa y/o mastercard" in legal:
            credit = [PaymentMethod(raw_name="Crédito " + network + " vía " + wallet,issuer="Banco Ciudad",network=network,card_type="credit",wallet=wallet,payment_rail="qr") for network in ("Visa","Mastercard") for wallet in wallet_names]
            debit = [PaymentMethod(raw_name="Débito " + network + " vía " + wallet,issuer="Banco Ciudad",network=network,card_type="debit",wallet=wallet,payment_rail="qr") for network in ("Visa","Mastercard") for wallet in wallet_names]
            if "prepagas cabal" in legal:
                debit += [PaymentMethod(raw_name="Prepaga Cabal vía " + wallet,issuer="Banco Ciudad",network="Cabal",card_type="prepaid",wallet=wallet,payment_rail="qr") for wallet in wallet_names]
        balance = [PaymentMethod(raw_name="Dinero en cuenta vía "+wallet,wallet=wallet,payment_rail="qr" if qr else "account_balance") for wallet in (wallet_names or ["Buepp"])] if "dinero en cuenta" in legal else []
        if "y/o con qr modo" in legal or re.search(r"en comercios fisicos(?: adheridos)? pagando con tarjetas",legal):
            credit += [p.model_copy(update={"wallet":None,"payment_rail":"card","raw_name":"Tarjeta de crédito "+(p.network or "")}) for p in credit if p.wallet == wallets[0]]
        return credit,debit,balance

    @staticmethod
    def _conditions(text, b, raw, requires):
        parts = []
        if requires:
            parts.append("Solo comercios/sucursales adheridos: consultar listado y condiciones en la página oficial del beneficio.")
        if b.get("con_archivo_pdf"):
            parts.append("Listado oficial de adheridos: https://www.buepp.com.ar/buepp_api/"+str(raw["source_id"])+"/beneficio_detalle.pdf.")
        if "no aplica para tarjetas corporativas" in fold(b.get("legales_genericas", "")):
            parts.append("No aplica para tarjetas corporativas.")
        for sentence in re.split(r"(?<=[.!?])\s+",text):
            s = fold(sentence)
            if re.search(r"exclusiv|solo |no aplica|no valido|no acumul|excluid|requisito|adicional|segment|acreditacion|90 dias|productos seleccionados|galaxy|7:00|mascotas|suscripcion|tope compartido|impuesto inmobiliario|pagos no tributarios|disponibilidad|cupo|terceros|co-producciones|prisma|fiserv|posnet|android",s):
                if len(sentence) <= 700:
                    parts.append(sentence)
                elif re.search(r"exclus|no incluye",s):
                    parts.append("Existen productos y/o medios de pago excluidos: consultar detalle oficial antes de comprar.")
        return " ".join(dict.fromkeys(parts)) or "Consultar condiciones oficiales del beneficio."
