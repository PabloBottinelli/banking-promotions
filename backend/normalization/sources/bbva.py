"""Evidence-based BBVA V2 conversion; ambiguous alternatives fail closed."""
import hashlib
import html
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit
from normalization.structure import conditions, requires_merchant_check


class BBVANormalizer:
    PROMOTIONS_URL = 'https://www.bbva.com.ar/beneficios/'
    DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    MONEY = r'([\d]+(?:[.,]\d+)*)'

    def normalize(self, raw: dict) -> NormalizedPromotion:
        variants = self.normalize_many(raw)
        if len(variants) != 1:
            raise ValueError('BBVA has multiple variants; use normalize_many()')
        return variants[0]

    def normalize_many(self, raw: dict) -> list[NormalizedPromotion]:
        catalog, detail = raw['catalog'], raw['detail']
        nodes = detail.get('beneficios')
        if not isinstance(nodes, list) or not nodes or any(not isinstance(n, dict) or not n for n in nodes):
            raise ValueError('BBVA missing or malformed benefits')
        title = self._clean_text(detail.get('cabecera') or catalog.get('cabecera'))
        terms = self._clean_text(detail.get('basesCondiciones')) or None
        if not title:
            raise ValueError('BBVA blank title')
        if re.search(r'\(IV\).*?GRATIS HASTA', terms or '', re.I) and re.search(r'\(V\)\s+UN PRODUCTO', terms or '', re.I):
            return self._assistance_variants(raw, terms)
        if re.search(r'no\s+aplica\s+para\s+compras\s+realizadas\s+con\s+tarjeta\s+de\s+cr[eé]dito', terms or '', re.I) and re.search(r'tope de descuento para vuelos.+?millas BBVA', terms or '', re.I):
            return self._mileage_redemption(raw, terms)
        if re.search(r'cuotas\s+en\s+vuelos\s+nacionales', ' '.join(self._normalize_requirements(nodes[0].get('requisitos'))), re.I) and re.search(r'paquetes\s+y\s+alojamientos', terms or '', re.I):
            return self._travel_financing(raw, terms)
        self._reject_unresolved_benefit_dimensions(detail, terms or '')
        variants = []
        for node in nodes:
            req = self._normalize_requirements(node.get('requisitos'))
            text = ' '.join(req)
            group = node.get('grupoTarjeta') or detail.get('grupoTarjeta') or catalog.get('grupoTarjeta')
            methods = self._payment_options(group, text, terms or '')
            benefit_text = self._clean_text(node.get('descripcion') or node.get('beneficio'))
            subtitle = self._clean_text(catalog.get('subcabecera')) if len(nodes) == 1 else ''
            headline = benefit_text or (title + ' ' + subtitle if len(nodes) == 1 else text)
            percent = self._extract_discount(headline, '', [], None)
            if percent is None:
                percent = self._extract_discount('', '', req, None)
            if percent is None and len(nodes) == 1:
                percent = self._extract_discount('', '', [], terms)
            legal_percent = re.search(r'(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:\([^)]*\)\s*)?de\s+(reintegro|descuento)', terms or '', re.I)
            if legal_percent and percent is not None and Decimal(legal_percent.group(1).replace(',', '.')) != percent:
                raise ValueError(f'BBVA conflicting benefit percentage: headline/requirements {percent}% versus legal {legal_percent.group(1)}%; review required')
            installments = self._normalize_installments(node.get('cuota'))
            benefits = []
            if percent is not None:
                kind_text = ' '.join([benefit_text, subtitle, text, terms or ''])
                kind = ('cashback' if legal_percent.group(2).lower() == 'reintegro' else 'discount') if legal_percent else ('cashback' if re.search(r'\breintegro\b|\bcashback\b|\bdevoluci[oó]n\b', kind_text, re.I) else 'discount')
                benefits.append(Benefit(type=kind, percentage=percent))
            fixed = self._extract_fixed_coupon_discount(text)
            if fixed is not None:
                benefits.append(Benefit(type='discount', amount=fixed, currency=self._currency(text)))
            if installments:
                free = bool(re.search(rf'\b{installments}\s+cuotas\s+sin\s+inter[eé]s', ' '.join([headline, text, terms or '']), re.I))
                benefits.append(Benefit(type='installments', installment_options=[installments], interest_free=True if free else None))
            # 2x1 is not a fictitious 50% discount. Preserve the actual entitlement.
            if re.search(r'\b2\s*[xX]\s*1\b', headline + ' ' + text):
                entitlement = re.search(r'entradas\s+2\s*x\s*1|2\s*x\s*1\s+en\s+entradas', terms or subtitle, re.I)
                benefits.append(Benefit(type='other', description=benefit_text or ((entitlement.group(0) + '. ') if entitlement else '') + (text or title)))
            if not benefits:
                if not (benefit_text or re.search(r'canje|sorteo|regalo|gratis|bonificaci[oó]n|sin\s+comisi[oó]n', text, re.I)):
                    raise ValueError('BBVA benefit not identifiable from source')
                benefits = [Benefit(type='other', description=benefit_text or text)]
            full = ' '.join([text, terms or ''])
            cap_value = node.get('tope') if node.get('tope') not in (None, '') else catalog.get('montoTope')
            cap = self._checked_amount(cap_value, 'cap')
            if cap is None:
                m = re.search(r'\btope(?:\s+de\s+reintegro)?\s*:?\s*(?:de\s*)?(?:ARS\s*|\$\s*)' + self.MONEY, full, re.I)
                cap = self._checked_amount(m.group(1), 'text cap') if m else None
            scope = self._normalize_cap_scope(node.get('tipoTope'))
            period = self._normalize_cap_period(node.get('frecuenciaTope'))
            period, cap_warning = self._cap_period_evidence(period, cap, terms or '')
            if re.search(r'tope.{0,100}?por cuenta', terms or '', re.I):
                scope = 'account'
            shared_merchants = re.search(r'tope.{0,100}?compartido\s+entre\s+(?:los\s+)?comercios\s+adheridos', terms or '', re.I)
            shared_group = None
            if shared_merchants:
                scope = 'person'
                campaign_id = str(catalog.get('idCampania') or '').strip()
                if campaign_id:
                    shared_group = f'bbva:campaign:{campaign_id}:cap'
            elif scope == 'account' and re.search(r'tope.{0,100}?compartido', terms or '', re.I):
                shared_group = f"bbva:{raw['source_id']}:account-cap"
            limits = []
            if cap is not None:
                limits.append(PromotionLimit(type='monetary_cap', amount=cap, currency=self._currency(full), scope=scope,
                    period=period, shared_group_id=shared_group,
                    description='Tope por persona compartido entre los comercios adheridos a la promoción; no es un tope por comercio.' if shared_merchants else None))
            # A threshold attached to an alternative installment count is not a global minimum.
            conditional = re.search(r'\b(\d+)\s+cuotas\s+(?:sin\s+inter[eé]s\s+)?para\s+compras\s+(?:mayores|superiores)\s+a\s*\$\s*' + self.MONEY, terms or '', re.I)
            min_text = text if conditional else full
            if conditional:
                min_text = re.sub(r'\b\d+\s+cuotas\s+para\s+compras\s+(?:mayores|superiores)\s+a\s*\$\s*' + self.MONEY, '', min_text, flags=re.I)
            minimum = self._extract_minimum_purchase(min_text)
            if minimum is not None:
                limits.append(PromotionLimit(type='minimum_purchase', amount=minimum, currency=self._currency(min_text),
                    description='Compra estrictamente superior al importe indicado' if re.search(r'compras?\s+(?:mayores|superiores)', min_text, re.I) else None))
            usage = re.search(r'\b(?:en\s+)?(\d+)\s+(?:viaje|compra)\s+por\s+vigencia', full, re.I)
            if usage:
                limits.append(PromotionLimit(type='usage_count', quantity=int(usage.group(1)), period='promotion'))
            daily_usage = re.search(r'\bm[aá]ximo\s+(\d+)\s+beneficios\s+por\s+d[ií]a', full, re.I)
            if daily_usage:
                card_person = bool(re.search(r'por tarjeta por d[ií]a y por cliente', terms or '', re.I))
                limits.append(PromotionLimit(type='usage_count', quantity=int(daily_usage.group(1)), period='daily',
                    scope='person_and_card' if card_person else None,
                    shared_group_id=f"bbva:{raw['source_id']}:daily-uses" if card_person else None))
            stock = re.search(r'\bstock\s+de\s+([\d.]+)\s+cupones\s+por\s+partido', terms or '', re.I)
            if stock:
                limits.append(PromotionLimit(type='stock', quantity=int(stock.group(1).replace('.', '')), period='event', description='Cupones por partido'))
            limits.extend(self._quantity_limits(full))
            days = self._normalize_days(detail.get('diasPromo') or catalog.get('diasPromo'))
            daily = bool(re.search(r'\btodos\s+los\s+d[ií]as\b', (terms or '').split('NO APLICA')[0], re.I))
            if not days and not daily:
                days = self._explicit_weekdays(text + ' ' + (terms or ''))
            if daily:
                days = list(self.DAYS)
            channels = detail.get('canalesVenta') or {}
            merchant_check = requires_merchant_check(full) or self._has_physical_channels(channels)
            category = 'Gastronomía' if re.match(r'gastronom[ií]a\b', title, re.I) else None
            warnings = cap_warning
            restriction_sentences = self._restrictions(terms or '')
            segment = self._exclusive_segment(full)
            p = NormalizedPromotion(source=raw['source'], source_id=str(raw['source_id']), scraped_at=datetime.fromisoformat(raw['scraped_at']),
                title=title, scope='category' if category else 'merchant', merchant=None if category else title, category=category,
                promotion_url=self.PROMOTIONS_URL, valid_from=self._parse_date(catalog.get('fechaDesde')), valid_to=self._parse_date(catalog.get('fechaHasta')),
                benefits=benefits, limits=limits, payment_methods=methods, days_of_week=days, applies_every_day=True if len(days) == 7 else None,
                online=True if self._has_online_channels(channels) or re.search(r'se aplica online|en la web|p[aá]gina web de', full, re.I) else None, physical=True if self._has_physical_channels(channels) else None,
                specific_conditions=conditions(('Requisitos', '; '.join(req)) if req else None, ('Segmento', segment) if segment else None,
                    ('Condiciones', restriction_sentences) if restriction_sentences else None,
                    ('Comercios', 'Consultar locales/sucursales adheridos en la página oficial de BBVA.') if merchant_check else None,
                    ('Revisión', warnings) if warnings else None,
                    ('Modalidades indicadas', ', '.join(t for t in ['QR','NFC','contactless'] if self._contains_requirement(req,t))) if any(self._contains_requirement(req,t) for t in ['QR','NFC','contactless']) else None),
                requires_merchant_verification=merchant_check, terms=terms)
            variants.append((node, p))
            if re.search(r'\bsuscripci[oó]n\b', full, re.I) and re.search(r'recibir[aá]s\s+un\s+set', terms or '', re.I):
                self._subscription_gift(p, terms or '')
            if installments and re.search(r'\bregalo\b', headline + ' ' + text, re.I):
                gift = self._gift_variant(raw, p, group, req, terms or '')
                variants.append(({'id': 'gift'}, gift))
            if re.search(r'\bsorteo\b', title, re.I) and re.search(r'chances\s+extra', full, re.I):
                extra = self._lottery_variant(raw, p, req, terms or '')
                variants.append(({'id': 'mastercard-extra-chances'}, extra))
            if any(b.type == 'other' and re.search(r'2\s*x\s*1', b.description or '', re.I) for b in p.benefits) and percent is not None and re.search(r'combos', terms or '', re.I):
                # Tickets and food are different eligible products. The 20% must not apply to tickets.
                p.benefits = [b for b in p.benefits if b.type == 'other']
                p.promotion_group_id = str(raw['source_id'])
                combos = p.model_copy(deep=True)
                combos.source_id = str(raw['source_id']) + ':combos'
                combos.benefits = [Benefit(type='discount', percentage=percent, description='Combos seleccionados y menús gastronómicos de funciones premium, sujeto a stock')]
                combos.payment_methods = self._normalize_payment_methods(group)
                combos.online = None
                combos.specific_conditions = 'Combos seleccionados y menús gastronómicos para funciones premium, sujeto a stock. Consultar bases oficiales para condiciones y disponibilidad.'
                variants.append(({'id':'combos'}, combos))
            if conditional and int(conditional.group(1)) != installments:
                alt_min = self._checked_amount(conditional.group(2), 'conditional minimum')
                alt_count = int(conditional.group(1))
                free = bool(re.search(rf'\b{alt_count}\s+cuotas\s+sin\s+inter[eé]s', terms or '', re.I))
                alt = p.model_copy(deep=True)
                alt.source_id = str(raw['source_id']) + ':financing-minimum'
                merchant_label = re.sub(r'\s+\d+(?:[.,]\d+)?%.*$|\s+\d+\s+cuotas.*$', '', title, flags=re.I)
                alt.title = f'{merchant_label}: {alt_count} cuotas para compras superiores al mínimo'
                alt.promotion_group_id = str(raw['source_id'])
                alt.benefits = [Benefit(type='installments', installment_options=[alt_count], interest_free=True if free else None)]
                alt.limits = [PromotionLimit(type='minimum_purchase', amount=alt_min, currency=self._currency(full), description='Compra estrictamente superior al importe indicado')]
                alt.specific_conditions = (p.specific_conditions or '') + f'\nAlternativa: {conditional.group(0)}. No se afirma acumulación del reintegro con esta financiación.'
                p.promotion_group_id = str(raw['source_id'])
                variants.append(({'id': 'financing-minimum'}, alt))
        if len(nodes) > 1:
            variants = self._resolve_nodes(raw, variants)
        output = [p for _, p in variants]
        if len({p.source_id for p in output}) != len(output):
            raise ValueError('BBVA duplicate variant identities')
        issues = self.review_normalized(raw, output)
        if issues:
            raise ValueError('BBVA incomplete commercial representation: ' + '; '.join(issues))
        return output

    def _reject_unresolved_benefit_dimensions(self, detail, terms):
        # A list of product-dependent rates cannot safely collapse to its first
        # percentage. Preserve the raw offer and block it until represented.
        offer = re.split(r'\bejemplo\b', terms, flags=re.I)[0]
        financing = any(self._normalize_installments(node.get('cuota')) for node in detail.get('beneficios', []))
        one_payment = re.search(r'v[aá]lida\s+(?:[uú]nicamente\s+)?para\s+clientes\s+que\s+abonen\s+sus\s+compras\s+en\s+(?:un|1)\s+pago\s+con\s+tarjetas?\s+de\s+cr[eé]dito', offer, re.I)
        if financing and one_payment:
            raise ValueError('BBVA conflicting payment eligibility: API installments versus legal single-payment-only purchase; review required')
        rates = {Decimal(value.replace(',', '.')) for value in re.findall(
            r'(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:\([^)]*\)\s*)?de\s+(?:descuento|reintegro)', offer, re.I)}
        if len(rates) > 1:
            raise ValueError('BBVA unresolved product/payment-dependent benefit rates; complete variant mapping required (raw preserved)')
        positive = ' '.join(sentence for sentence in re.split(r'(?<=[.;])\s+', offer)
                            if not re.match(r'\s*(?:no\s+|excepto\b)', sentence, re.I))
        quotas = {int(value) for value in re.findall(r'\b(\d+)\s+cuotas\b', positive, re.I)}
        if len(quotas) > 1 and not re.search(r'\b\d+\s+cuotas\s+(?:sin\s+inter[eé]s\s+)?para\s+compras\s+(?:mayores|superiores)\s+a\s*\$', offer, re.I):
            raise ValueError('BBVA unresolved product/payment-dependent installment options; complete variant mapping required (raw preserved)')

    def _cap_period_evidence(self, api_period, cap, terms):
        """Reconcile the same monetary cap, never another cap in the legal text."""
        legal_periods = set()
        pattern = (r'\btope(?:\s+de\s+(?:reintegro|descuento))?\s*:?'
                   r'\s*(?:de\s*)?\$\s*' + self.MONEY +
                   r'\s+(?:por\s+(?:usuario|cliente|persona|cuenta)\s+)?'
                   r'(por\s+(?:mes|vigencia)|mensual)\b')
        for match in re.finditer(pattern, terms, re.I):
            if cap is not None and self._checked_amount(match.group(1), 'legal cap') == cap:
                legal_periods.add(self._normalize_cap_period(match.group(2)))
        # Different cap amounts, or explicit simultaneous limits for more than
        # one period, are not evidence of a contradictory frequency field.
        if len(legal_periods) == 1:
            legal_period = next(iter(legal_periods))
            if api_period and api_period != legal_period:
                warning = (f'Fuente inconsistente: el mismo tope figura con frecuencia {api_period} '
                           f'en el campo estructurado y {legal_period} en las bases. '
                           'Periodicidad sin resolver; requiere revisión.')
                return None, warning
            return legal_period, None
        return api_period, None

    def _subscription_gift(self, promotion, terms):
        gift = re.search(r'recibir[aá]s\s+(un\s+set\s+de\s+\d+\s+copas.+?\ben\s+la\s+[^.]+?entrega)\.', terms, re.I)
        stock = re.search(r'stock\s+de\s+([\d.]+)\s+(sets\s+de\s+copas)', terms, re.I)
        deliveries = re.search(r'descuento\s+durante\s+las\s+primeras\s+(\d+)\s+entregas', terms, re.I)
        if not gift or not stock or not deliveries:
            raise ValueError('BBVA subscription gift/stock/delivery conditions incomplete; review required')
        quantity = self._checked_amount(stock.group(1), 'gift stock')
        if quantity != quantity.to_integral_value():
            raise ValueError('BBVA fractional gift stock')
        promotion.benefits.append(Benefit(type='gift', description=gift.group(1)))
        promotion.limits.append(PromotionLimit(type='stock', quantity=int(quantity), scope='campaign',
            description=stock.group(2) + '; limita el regalo, no las suscripciones ni el descuento'))
        promotion.limits.append(PromotionLimit(type='usage_count', quantity=int(deliveries.group(1)), scope='subscription',
            description='Primeras entregas de la suscripción con descuento; el regalo se entrega según su condición específica'))
        choices = re.search(r'aplicable a las opciones\s+(.+?)\.', terms, re.I)
        payment = re.search(r'Para acceder,\s+(.+?)\.(?=\s|$)', terms, re.I)
        renewal = re.search(r'A partir de la entrega n[úu]mero\s+\d+,.+?\.', terms, re.I)
        variable_price = re.search(r'El precio de la suscripci[oó]n puede variar.+?\.', terms, re.I)
        exclusion = re.search(r'No valido para venta online en\s+\S+', terms, re.I)
        if not choices or not payment or not renewal or not variable_price or not exclusion:
            raise ValueError('BBVA subscription restrictions incomplete; review required')
        promotion.specific_conditions = conditions(('Suscripción', choices.group(1)),
            ('Descuento', 'Solo las primeras ' + deliveries.group(1) + ' entregas de la suscripción.'),
            ('Pago y adhesión', payment.group(1)), ('Regalo', gift.group(1) + '; ' + stock.group(0) + '.'),
            ('Renovación', renewal.group(0) + ' ' + variable_price.group(0)), ('Exclusión', exclusion.group(0)))

    def review_normalized(self, raw, variants):
        """Evidence-based omissions, shared by conversion and scraper review.

        This deliberately checks specific positive source clauses. It is not a
        universal semantic proof or a substitute for independent source QA.
        """
        terms = self._clean_text(raw['detail'].get('basesCondiciones'))
        req = ' '.join(' '.join(self._normalize_requirements(n.get('requisitos'))) for n in raw['detail'].get('beneficios', []))
        text = terms + ' ' + req
        issues = []
        benefit_types = {b.type for p in variants for b in p.benefits}
        if re.search(r'\b(?:de\s+regalo|recibir[aá]s\s+un\s+set|gratis\s+hasta\s+\d+\s+productos)\b', text, re.I) and not benefit_types.intersection({'gift', 'free_service'}):
            issues.append('positive gift/free-product entitlement omitted')
        for match in re.finditer(r'\bstock\s+de\s+([\d.]+)\s+(?:sets|cupos|cupones|tickets)\b', terms, re.I):
            value = self._checked_amount(match.group(1), 'stock')
            if not any(l.type == 'stock' and l.quantity == value for p in variants for l in p.limits):
                issues.append('published stock quantity omitted')
        paired = re.search(r'tarjetas?\s+de\s+cr[eé]dito\s+visa\s+y(?:/o)?\s+mastercard\s+emitidas?\s+por\s+BBVA', terms, re.I)
        if paired and {m.network for p in variants for m in p.payment_methods} != {'visa', 'mastercard'}:
            issues.append('explicit eligible Visa/Mastercard credit alternatives omitted or broadened')
        if paired and any(m.card_type != 'credit' or m.issuer != 'BBVA' for p in variants for m in p.payment_methods):
            issues.append('eligible credit issuer restriction omitted')
        if re.search(r'primeras\s+\d+\s+entregas', terms, re.I) and not all(re.search(r'primeras\s+\d+\s+entregas', p.specific_conditions or '', re.I) for p in variants):
            issues.append('subscription delivery eligibility omitted')
        offer = re.split(r'\bEJEMPLO\b', terms, flags=re.I)[0]
        legal_rates = {Decimal(value.replace(',', '.')) for value in re.findall(r'(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:\([^)]*\)\s*)?de\s+(?:descuento|reintegro)', offer, re.I)}
        represented_rates = {b.percentage for p in variants for b in p.benefits if b.type in ('discount', 'cashback')}
        if not legal_rates.issubset(represented_rates):
            issues.append('published discount/cashback percentage omitted')
        segment = self._exclusive_segment(text)
        if segment and not any(segment.lower() in (p.specific_conditions or '').lower() for p in variants):
            issues.append('explicit customer segment omitted')
        for node in raw['detail'].get('beneficios', []):
            cap_value = node.get('tope') if node.get('tope') not in (None, '') else raw['catalog'].get('montoTope')
            cap = self._checked_amount(cap_value, 'cap')
            _, warning = self._cap_period_evidence(self._normalize_cap_period(node.get('frecuenciaTope')), cap, terms)
            if warning and not all('Fuente inconsistente' in (p.specific_conditions or '') for p in variants if any(l.type == 'monetary_cap' and l.amount == cap for l in p.limits)):
                issues.append('contradictory cap periodicity warning omitted')
        for p in variants:
            for limit in p.limits:
                if limit.type == 'monetary_cap':
                    expected, warning = self._cap_period_evidence(limit.period, limit.amount, terms)
                    if warning and (limit.period is not None or 'Fuente inconsistente' not in (p.specific_conditions or '')):
                        issues.append('contradictory cap periodicity asserted or warning omitted')
            if re.search(r'NO APLICABLE A CUOTAS', terms, re.I):
                single_pay = [b for b in p.benefits if re.search(r'(?:adicional|un solo pago)', b.description or '', re.I)]
                if single_pay and any(b.type == 'installments' for b in p.benefits):
                    issues.append('single-payment-only benefit combined with installments')
                additional = re.search(r'BENEFICIO ADICIONAL DEL\s+(\d+(?:[.,]\d+)?)%', terms, re.I)
                if p.source_id.endswith(':single-payment') and additional and not any(b.type == 'discount' and b.percentage == Decimal(additional.group(1).replace(',', '.')) and 'adicional' in (b.description or '').lower() for b in p.benefits):
                    issues.append('single-payment additional discount omitted')
                annual = any(re.search(r'ANUAL M[ÚU]LTIPLES VIAJES', b.description or '', re.I) for b in p.benefits if b.type == 'discount')
                child = re.search(r'GRATIS HASTA\s+(\d+)\s+PRODUCTOS.+?HIJOS MENORES DE\s+(\d+)\s+A[ÑN]OS', terms, re.I)
                if annual and child:
                    if not any(b.type == 'free_service' for b in p.benefits) or not any(l.type == 'usage_count' and l.quantity == int(child.group(1)) and l.scope == 'purchased_product' for l in p.limits):
                        issues.append('annual free-child-products entitlement or quantity omitted')
                    if not re.search(r'HIJOS MENORES DE\s+' + child.group(2) + r'\s+A[ÑN]OS', p.specific_conditions or '', re.I):
                        issues.append('annual child-age eligibility omitted')
        return list(dict.fromkeys(issues))

    def _assistance_variants(self, raw, terms):
        """Roman product clauses define this offer's disjoint payment options.

        Rates, quantities, ages, dates and financing all come from the payload.
        Unsupported clause shapes fail closed rather than emitting a subset.
        """
        boundaries = list(re.finditer(r'\((I|II|III|IV|V)\)\s+UN PRODUCTO ASSIST CARD\s+', terms, re.I))
        if [m.group(1).upper() for m in boundaries] != ['I', 'II', 'III', 'IV', 'V']:
            raise ValueError('BBVA assistance product clauses incomplete or reordered; review required')
        prefix = terms[:boundaries[0].start()]
        sections = {m.group(1).upper(): terms[m.end():boundaries[i+1].start() if i+1 < len(boundaries) else len(terms)]
                    for i, m in enumerate(boundaries)}
        parsed = []
        for key in ['I', 'II', 'III', 'IV']:
            section = sections[key]
            offer = re.match(r'(.+?)\s+MODALIDAD\s+(DIARIA\s*\(HASTA\s+(\d+)\s+D[IÍ]AS\)|ANUAL M[ÚU]LTIPLES VIAJES)\s+OBTENGA UN BENEFICIO DEL\s+(\d+(?:[.,]\d+)?)%\s*\([^)]*\)\s+DE DESCUENTO SOBRE LA TARIFA PUBLICADA\.', section, re.I)
            if not offer:
                raise ValueError('BBVA assistance product/rate/modality clause not understood; review required')
            products = tuple(sorted(part.strip().lower() for part in offer.group(1).split(',')))
            modality = 'daily' if offer.group(3) else 'annual'
            rate = Decimal(offer.group(4).replace(',', '.'))
            parsed.append((products, modality, offer.group(2), rate, offer.group(0)))
        extra = re.match(r'(.+?)\s+BAJO CUALQUIER MODALIDAD,\s+OBTENGA UN BENEFICIO ADICIONAL DEL\s+(\d+(?:[.,]\d+)?)%\s*\([^)]*\)\s+DE DESCUENTO SOBRE EL PRECIO FINAL PUBLICADO ABONANDO EL PRODUCTO ASSIST CARD EN\s+(\d+)\s*\([^)]*\)\s+SOLO PAGO CON TARJETAS DE CR[EÉ]DITO\s+(.+?)\.', sections['V'], re.I)
        child = re.search(r'OBTENGA GRATIS HASTA\s+(\d+)\s+PRODUCTOS COMO M[ÁA]XIMO CON ID[ÉE]NTICA VIGENCIA, MODALIDAD Y CARACTER[ÍI]STICAS AL ABONADO PARA SUS HIJOS MENORES DE\s+(\d+)\s+A[ÑN]OS', sections['IV'], re.I)
        service_start = re.search(r'FECHA L[IÍ]MITE DE INICIO DE VIGENCIA\s+(\d{2}/\d{2}/\d{4})', prefix, re.I)
        if not extra or not child or not service_start or int(extra.group(3)) != 1 or not re.search(r'NO APLICABLE A CUOTAS', sections['V'], re.I):
            raise ValueError('BBVA assistance payment/free-products/service-start dimensions incomplete; review required')
        extra_products = tuple(sorted(part.strip().lower() for part in extra.group(1).split(',')))
        annual = next((p for p in parsed if p[1] == 'annual'), None)
        daily_products = [name for products, modality, *_ in parsed if modality == 'daily' for name in products]
        if not annual or len(daily_products) != len(set(daily_products)) or set(daily_products) != set(extra_products) or annual[0] != extra_products:
            raise ValueError('BBVA assistance product coverage not exhaustive; review required')
        allowed_networks = []
        remainder = extra.group(4)
        for token in re.split(r'\s*,\s*|\s+O\s+', remainder, flags=re.I):
            network = {'american express': 'american_express', 'visa': 'visa', 'mastercard': 'mastercard'}.get(token.lower())
            if not network:
                raise ValueError('BBVA assistance payment networks not understood; review required')
            allowed_networks.append(network)
        quota = self._normalize_installments(raw['detail']['beneficios'][0].get('cuota'))
        if not quota:
            raise ValueError('BBVA assistance financing option missing; review required')
        common_tail = re.split(r'LOS ACCIONISTAS', sections['V'][extra.end():], flags=re.I)[0]
        daily_exclusions = re.search(r'PROMOCI[ÓO]N\s+\(I\),\(II\)\s+Y\s+\(III\)\s+(.+?)\s*$', sections['III'], re.I)
        annual_exclusions = re.search(r'PROMOCI[ÓO]N NO V[ÁA]LIDA.+?(?=A SU VEZ)', sections['IV'], re.I)
        if not daily_exclusions or not annual_exclusions:
            raise ValueError('BBVA assistance modality exclusions incomplete; review required')
        title = re.sub(r'\s+\d+\s+cuotas.*$', '', self._clean_text(raw['detail']['cabecera']), flags=re.I)
        output = []

        def build(products, modality, modality_label, rate, source_clause, single_payment):
            identity = '|'.join(products) + '|' + modality
            suffix = hashlib.sha256(identity.encode()).hexdigest()[:16]
            benefits = []
            if rate is not None:
                benefits.append(Benefit(type='discount', percentage=rate, description=source_clause + ' Descuento ya incluido en el precio publicado.'))
            if single_payment:
                benefits.append(Benefit(type='discount', percentage=Decimal(extra.group(2).replace(',', '.')),
                    description='Descuento adicional sobre el precio final publicado, en un solo pago; no se suman los porcentajes y no aplica a cuotas.'))
            else:
                benefits.append(Benefit(type='installments', installment_options=[quota], interest_free=None))
            p = NormalizedPromotion(source=raw['source'], source_id=f"{raw['source_id']}:product-{suffix}:" + ('single-payment' if single_payment else 'financing'),
                promotion_group_id=str(raw['source_id']), scraped_at=datetime.fromisoformat(raw['scraped_at']),
                title=title + ': ' + ', '.join(products) + ' / ' + modality_label + (' / un pago' if single_payment else ' / cuotas'),
                scope='merchant', merchant=re.sub(r'\s+\d+\s+cuotas.*$', '', title, flags=re.I), promotion_url=raw.get('source_url') or self.PROMOTIONS_URL,
                valid_from=self._parse_date(raw['catalog'].get('fechaDesde')), valid_to=self._parse_date(raw['catalog'].get('fechaHasta')),
                benefits=benefits, online=True, days_of_week=self._normalize_days(raw['detail'].get('diasPromo') or raw['catalog'].get('diasPromo')), terms=terms)
            p.applies_every_day = True if len(p.days_of_week) == 7 else None
            if single_payment:
                p.payment_methods = [PaymentMethod(raw_name='Tarjeta de crédito BBVA ' + network, issuer='BBVA', network=network, card_type='credit', payment_rail='card') for network in allowed_networks]
            else:
                p.payment_methods = [PaymentMethod(raw_name='Tarjeta de crédito BBVA', issuer='BBVA', card_type='credit', payment_rail='card')]
            if modality == 'annual':
                p.benefits.append(Benefit(type='free_service', description=child.group(0)))
                p.limits.append(PromotionLimit(type='usage_count', quantity=int(child.group(1)), scope='purchased_product',
                    description='Máximo de productos gratuitos para hijos por producto abonado, con idéntica vigencia, modalidad y características; no limita los productos abonados.'))
            covered_modalities = '; '.join(dict.fromkeys(item[2] for item in parsed))
            exclusions = daily_exclusions.group(0) if modality == 'daily' else annual_exclusions.group(0) if modality == 'annual' else 'Resto de modalidades: excluye ' + covered_modalities + ', ya representadas por separado. No se trasladan las exclusiones de I–IV al beneficio V.'
            if modality == 'remaining-modalities' and not single_payment:
                exclusions += ' Solo financiación publicada por la API para los productos enumerados; no se extrapolan los descuentos ni productos gratuitos de I–V.'
            req = '; '.join(self._normalize_requirements(raw['detail']['beneficios'][0].get('requisitos')))
            p.specific_conditions = conditions(('Productos', ', '.join(products)), ('Modalidad', modality_label),
                ('Condiciones', exclusions), ('Pago', extra.group(0) if single_payment else f'{quota} cuotas según catálogo; sin promesa de interés cero. El descuento adicional de un pago no aplica.'),
                ('Hijos', child.group(0)) if modality == 'annual' else None,
                ('Inicio del servicio', 'Fecha límite ' + service_start.group(1) + '; no extiende la vigencia de compra.'),
                ('Canales directos', req), ('Restricciones generales', prefix + ' ' + common_tail))
            return p

        for products, modality, label, rate, clause in parsed:
            for single_payment in [False, True]:
                output.append(build(products, modality, label, rate, clause, single_payment))
        # The API financing node does not restrict modalities. I–IV restrict
        # their discounts, and V excludes financing only for its extra discount.
        output.append(build(extra_products, 'remaining-modalities', 'Otras modalidades fuera de I–IV', None, '', False))
        output.append(build(extra_products, 'remaining-modalities', 'Otras modalidades fuera de I–IV', None, '', True))
        issues = self.review_normalized(raw, output)
        if issues:
            raise ValueError('BBVA incomplete assistance representation: ' + '; '.join(issues))
        return output

    def _mileage_redemption(self, raw, terms):
        catalog, detail = raw['catalog'], raw['detail']
        caps = re.findall(r'tope\s+de\s+descuento\s+para\s+vuelos\s+a\s+([^:]+):\s*([\d.,]+)\s+Millas\s+BBVA', terms, re.I)
        rate = re.search(r'hasta\s+un\s+(\d+(?:[.,]\d+)?)\s*%\s+de\s+descuento', terms, re.I)
        stock = re.search(r'stock\s+de\s+([\d.]+)\s+cupos', terms, re.I)
        unique_use = re.search(r'una\s+[uú]nica\s+vez\s+por\s+cliente', terms, re.I)
        validity = re.match(r'Del\s+(\d{1,2}/\d{1,2}/\d{4})\s+al\s+(\d{1,2}/\d{1,2}/\d{4})', terms, re.I)
        if not caps or not rate or not stock or not unique_use or not validity:
            raise ValueError('BBVA mileage redemption dimensions incomplete; review required')
        legal_start, legal_end = (self._parse_date(value) for value in validity.groups())
        source_start, source_end = self._parse_date(catalog.get('fechaDesde')), self._parse_date(catalog.get('fechaHasta'))
        conflict = (source_start, source_end) != (legal_start, legal_end)
        output, seen = [], set()
        for destinations, amount in caps:
            quantity = self._checked_amount(amount, 'mileage discount limit')
            if quantity != quantity.to_integral_value():
                raise ValueError('BBVA fractional mileage limit not representable as a quantity')
            identity = '|'.join(sorted(self._clean_text(part).lower() for part in destinations.split(',')))
            if identity in seen:
                raise ValueError('BBVA duplicate mileage destination group')
            seen.add(identity)
            suffix = hashlib.sha256(identity.encode()).hexdigest()[:16]
            output.append(NormalizedPromotion(
                source=raw['source'], source_id=f"{raw['source_id']}:miles-{suffix}", promotion_group_id=str(raw['source_id']),
                scraped_at=datetime.fromisoformat(raw['scraped_at']), title=self._clean_text(detail['cabecera']) + ': ' + destinations,
                scope='category', category='Pasajes aéreos', promotion_url=self.PROMOTIONS_URL,
                valid_from=legal_start, valid_to=legal_end,
                benefits=[Benefit(type='discount', percentage=Decimal(rate.group(1).replace(',', '.')), description=rate.group(0) + ' utilizando Millas BBVA, sujeto al tope por destino')],
                limits=[PromotionLimit(type='other', quantity=int(quantity), description='Tope de descuento en Millas BBVA para vuelos a ' + destinations),
                        PromotionLimit(type='stock', quantity=int(stock.group(1).replace('.', '')), scope='campaign', period='promotion', shared_group_id=f"bbva:{raw['source_id']}:redemption-stock", description='Cupos compartidos entre destinos'),
                        PromotionLimit(type='usage_count', quantity=1, scope='person', period='promotion', shared_group_id=f"bbva:{raw['source_id']}:first-redemption", description='Único uso por cliente en su primer canje, compartido entre destinos')],
                payment_methods=[PaymentMethod(raw_name='Canje de Millas BBVA dentro del Portal de Millas BBVA', issuer='BBVA', payment_rail='other')],
                days_of_week=self._normalize_days(detail.get('diasPromo') or catalog.get('diasPromo')), online=True,
                specific_conditions=conditions(('Elegibilidad', self._clean_text(detail['cabecera'])),
                    ('Destino', destinations), ('Condiciones', 'Primer canje dentro del Portal de Millas BBVA; no aplica a compras con tarjeta de crédito. Cupos y único uso por cliente compartidos entre destinos.'),
                    ('Origen', 'Buenos Aires (Ezeiza o Aeroparque)') if re.search(r'origen\s+en\s+Buenos\s+Aires\s*\(Ezeiza\s+o\s+Aeroparque\)', terms, re.I) else None,
                    ('Revisión', f'Fuente inconsistente: catálogo {source_start} a {source_end}; bases {legal_start} a {legal_end}. Se conserva la vigencia legal y se requiere revisión.') if conflict else None),
                terms=terms))
        return output

    def _travel_financing(self, raw, terms):
        packages = re.search(r'hasta\s+(\d+)\s+cuotas\s+sin\s+inter[eé]s\s+pagando\s+con\s+tarjetas\s+de\s+cr[eé]dito\s+BBVA\s+(paquetes\s+y\s+alojamientos\s+en\s+Argentina)\s+en\s+el\s+Portal\s+de\s+Millas\s+BBVA', terms, re.I)
        flights = re.search(r'hasta\s+(\d+)\s+cuotas\s+sin\s+inter[eé]s\s+en\s+(vuelos\s+con\s+destino\s+y\s+origen\s+en\s+Argentina)', terms, re.I)
        if not packages or not flights:
            raise ValueError('BBVA travel financing product conditions incomplete; review required')
        common_terms = terms.replace(packages.group(0), '').replace(flights.group(0), '')
        output = []
        for key, clause in [('packages-accommodation', packages), ('domestic-flights', flights)]:
            count = self._normalize_installments(clause.group(1))
            if count is None:
                raise ValueError('BBVA invalid product-specific installment count')
            output.append(NormalizedPromotion(
                source=raw['source'], source_id=f"{raw['source_id']}:{key}", promotion_group_id=str(raw['source_id']),
                scraped_at=datetime.fromisoformat(raw['scraped_at']), title=f'{clause.group(2)}: {count} cuotas sin interés',
                scope='category', category=clause.group(2), promotion_url=self.PROMOTIONS_URL,
                valid_from=self._parse_date(raw['catalog'].get('fechaDesde')), valid_to=self._parse_date(raw['catalog'].get('fechaHasta')),
                benefits=[Benefit(type='installments', installment_options=[count], interest_free=True)],
                payment_methods=[PaymentMethod(raw_name='Tarjetas de crédito BBVA', issuer='BBVA', card_type='credit', payment_rail='card')],
                days_of_week=self._normalize_days(raw['detail'].get('diasPromo') or raw['catalog'].get('diasPromo')),
                applies_every_day=True if len(self._normalize_days(raw['detail'].get('diasPromo') or raw['catalog'].get('diasPromo'))) == 7 else None,
                online=True, specific_conditions=conditions(('Producto', clause.group(2)), ('Canal', 'Exclusivo en el Portal de Millas BBVA.'), ('Restricciones', self._restrictions(common_terms))), terms=terms))
        return output

    def _quantity_limits(self, text):
        limits = []
        entries = re.search(r'm[aá]ximo\s+(\d+)\s+entradas\s+por\s+transacci[oó]n', text, re.I)
        if entries:
            limits.append(PromotionLimit(type='usage_count', quantity=int(entries.group(1)),
                period='transaction', scope='transaction', description='Entradas por transacción'))
        trips = re.search(r'pr[oó]ximos\s+(\d+)(?:\s*\([^)]*\))?\s+viajes', text, re.I)
        if trips:
            limits.append(PromotionLimit(type='usage_count', quantity=int(trips.group(1)),
                period='promotion', scope='person', description='Viajes elegibles por usuario'))
        presale = re.search(r'preventa[^.]{0,100}?stock\s+de\s+(\d+)\s+tickets', text, re.I)
        if presale:
            limits.append(PromotionLimit(type='stock', quantity=int(presale.group(1)),
                period='presale', scope='campaign', description='Tickets de la etapa de preventa BBVA; no limita la venta general'))
        return limits

    def _gift_variant(self, raw, financing, group, requirements, terms):
        # The threshold/card/channel/day clauses attached to a gift must not
        # become unconditional requirements of the financing component.
        boundary = re.search(r'adem[aá]s\s+de\s+lunes|para\s+compras\s+en\s+tiendas\s+f[ií]sicas', terms, re.I)
        if not boundary:
            raise ValueError('BBVA gift eligibility cannot be separated faithfully; review required')
        financing_terms, gift_terms = terms[:boundary.start()], terms[boundary.start():]
        threshold = re.search(r'(igual\s+o\s+superior\s+a|compras\s+(?:mayores|superiores)\s+a)\s*\$\s*' + self.MONEY, gift_terms, re.I)
        if not threshold:
            raise ValueError('BBVA gift minimum not identifiable; review required')
        minimum = self._checked_amount(threshold.group(2), 'gift minimum')
        gift_description = re.search(r'(?:se entregar[aá]|te llevas de regalo)\s+(.+?)(?=\s+(?:SE TENDR|V[aá]lido exclusivamente|M[aá]ximo)|$)', gift_terms, re.I)
        if not gift_description:
            raise ValueError('BBVA gift not identifiable; review required')
        gift = financing.model_copy(deep=True)
        gift.source_id = str(raw['source_id']) + ':gift'
        gift.promotion_group_id = str(raw['source_id'])
        gift.title = self._clean_text(raw['detail'].get('cabecera') or raw['catalog'].get('cabecera')) + ': regalo'
        gift.benefits = [Benefit(type='gift', description=gift_description.group(1))]
        if not re.search(r'productos\s+seleccionados', financing_terms, re.I):
            gift.benefits = [*financing.benefits, *gift.benefits]
        gift.limits = [PromotionLimit(type='minimum_purchase', amount=minimum, currency=self._currency(gift_terms),
            description='Compra igual o superior al importe indicado' if re.search(r'igual', threshold.group(1), re.I) else 'Compra estrictamente superior al importe indicado')]
        count = re.search(r'm[aá]ximo\s+(\d+)\s+(?:regalo|beneficio)\s+por\s+cliente', gift_terms, re.I)
        if count:
            gift.limits.append(PromotionLimit(type='usage_count', quantity=int(count.group(1)), period='promotion', scope='person', description='Regalos por cliente'))
        gift.payment_methods = self._payment_options(group, ' '.join(requirements), gift_terms)
        # The gift clause specifies direct purchases; app acceptance in the
        # general financing clause is not transferred to the gift.
        for method in gift.payment_methods:
            method.payment_rail, method.wallet = 'card', None
        physical_only = bool(re.search(r'tiendas\s+f[ií]sicas', gift_terms, re.I))
        online_only = bool(re.search(r'exclusivamente\s+para\s+compras[^.]{0,100}?sitio\s+web', gift_terms, re.I))
        gift.physical = True if physical_only else False if online_only else None
        gift.online = True if online_only else False if physical_only else None
        gift.days_of_week = self._explicit_weekdays(' '.join(requirements) + ' ' + gift_terms) or self._normalize_days(raw['detail'].get('diasPromo') or raw['catalog'].get('diasPromo'))
        gift.applies_every_day = True if len(gift.days_of_week) == 7 else None
        gift.specific_conditions = conditions(('Regalo', ' '.join(requirements)), ('Condiciones', self._restrictions(gift_terms)),
            ('Comercios', 'Consultar locales/sucursales adheridos en la página oficial de BBVA.') if gift.requires_merchant_verification else None)

        financing.promotion_group_id = str(raw['source_id'])
        label = re.sub(r'\s+(?:\d+\s+cuotas.*|regalo.*)$', '', financing.title, flags=re.I)
        count = next(b.installment_options[-1] for b in financing.benefits if b.type == 'installments')
        financing.title = f'{label}: {count} cuotas'
        financing.payment_methods = self._payment_options(group, '', financing_terms)
        financing.limits = [limit for limit in financing.limits if limit.type not in ('minimum_purchase', 'usage_count')]
        financing.days_of_week = self._normalize_days(raw['detail'].get('diasPromo') or raw['catalog'].get('diasPromo'))
        financing.applies_every_day = True if len(financing.days_of_week) == 7 else None
        exclusions = ' '.join(s for s in re.split(r'(?<=[.;])\s+', terms) if re.search(r'no participan|no aplica a pagos', s, re.I))
        financing.specific_conditions = conditions(('Financiación', financing_terms), ('Restricciones', exclusions) if exclusions else None,
            ('Comercios', 'Consultar locales/sucursales adheridos en la página oficial de BBVA.') if financing.requires_merchant_verification else None)
        return gift

    def _lottery_variant(self, raw, general, requirements, terms):
        extra_count = re.search(r'(\d+)\s+chances\s+extra', terms, re.I)
        exchange = re.search(r'1\s*\([^)]*\)\s*chance\s*=\s*(\d+)\s*\([^)]*\)\s*millas', terms, re.I)
        one_exchange = re.search(r'v[aá]lido\s+[uú]nicamente\s+para\s+(\d+)\s+canjes?\s+por\s+cliente', terms, re.I)
        eligible_card = re.search(r'tarjeta\s+de\s+cr[eé]dito\s+(Mastercard|Visa)\s+emitidas?\s+por\s+BBVA', terms, re.I)
        if not extra_count or not exchange or not one_exchange or not eligible_card:
            raise ValueError('BBVA lottery stages cannot be separated faithfully; review required')
        exclusions = re.search(r'Excluye\s+personas\s+jur[ií]dicas.+?\.', terms, re.I)
        restrictions = f'Clientes adheridos al programa Millas BBVA. {exchange.group(1)} millas por chance.'
        age = re.search(r'V[aá]lido\s+para\s+mayores\s+de\s+\d+\s+a[nñ]os', terms, re.I)
        if age:
            restrictions += ' ' + age.group(0) + '.'
        if exclusions:
            restrictions += ' ' + exclusions.group(0)
        description = re.split(r'\bSi\s+ten[eé]s\s+tarjeta', ' '.join(requirements), flags=re.I)[0].strip()
        general.benefits = [Benefit(type='other', description=description)]
        general.payment_methods = []
        general.scope, general.merchant = 'other', None
        general.specific_conditions = restrictions
        general.promotion_group_id = str(raw['source_id'])
        extra = general.model_copy(deep=True)
        network = eligible_card.group(1).lower()
        extra.source_id = str(raw['source_id']) + f':{network}-extra-chances'
        extra.title = general.title + ': chances extra ' + eligible_card.group(1)
        extra.benefits = [Benefit(type='other', description=f'{extra_count.group(1)} chances extra al realizar el primer canje elegible')]
        extra.payment_methods = [PaymentMethod(raw_name=eligible_card.group(0), issuer='BBVA', network=network, card_type='credit')]
        extra.limits = [PromotionLimit(type='usage_count', quantity=int(one_exchange.group(1)), period='promotion', scope='person', description='Canjes con chances extra por cliente')]
        extra.specific_conditions = restrictions + f' Exclusivo titulares de {eligible_card.group(0)}. {one_exchange.group(1)} canje(s) por cliente.'
        return extra

    def _resolve_nodes(self, raw, variants):
        # Compatibility requires identical conditions/payment/limits and disjoint benefit kinds.
        first = variants[0][1]
        key = lambda p: (p.specific_conditions, [m.model_dump() for m in p.payment_methods], [l.model_dump() for l in p.limits])
        kinds = [b.type for _, p in variants for b in p.benefits]
        terms = self._clean_text(raw['detail'].get('basesCondiciones'))
        cumulative = bool(re.search(r'beneficios\s+(?:son\s+)?acumulables\s+entre\s+s[ií]|ambos\s+beneficios\s+(?:se\s+)?(?:acumulan|combinan)',terms,re.I))
        if cumulative and all(key(p) == key(first) for _, p in variants) and len(kinds) == len(set(kinds)):
            first.benefits = [b for _, p in variants for b in p.benefits]
            return [(variants[0][0], first)]
        seen = set()
        for node, p in variants:
            identity = node.get('id') or node.get('idBeneficio')
            if not identity:
                identity = json.dumps([[(m.network,m.card_type,m.wallet,m.payment_rail) for m in p.payment_methods], self._exclusive_segment(p.specific_conditions or '')],sort_keys=True)
                identity = hashlib.sha256(identity.encode()).hexdigest()[:16]
            if identity in seen:
                raise ValueError('BBVA ambiguous benefit compatibility/identity; review required')
            seen.add(identity)
            p.source_id = f"{raw['source_id']}:benefit-{identity}"
            p.promotion_group_id = str(raw['source_id'])
        return variants

    def _clean_text(self, value):
        if value is None: return ''
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html.unescape(str(value)))).strip()

    def _parse_date(self, value):
        if value in (None, ''): return None
        for fmt in ('%Y-%m-%d','%d/%m/%Y','%Y-%m-%dT%H:%M:%S'):
            try: return datetime.strptime(str(value)[:19],fmt).date()
            except ValueError: pass
        raise ValueError(f'Formato de fecha BBVA desconocido: {value}')

    def _normalize_days(self, value):
        parts = str(value).split(',') if value else []
        if len(parts) != 7 or any(p.strip() not in ('0','1') for p in parts): return []
        return [d for d,p in zip(self.DAYS,parts) if p.strip() == '1']

    def _explicit_weekdays(self, text):
        positive = ' '.join(s for s in re.split(r'(?<=[.;])\s+',text) if not re.search(r'no\s+aplica|excepto|exclu',s,re.I))
        clauses = re.findall(r'\b(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bados?|domingos?)\b',positive,re.I)
        names = ['lunes','martes','miercoles','jueves','viernes','sabado','domingo']
        def plain(s): return s.lower().replace('é','e').replace('á','a').removesuffix('s') if s.lower().startswith(('sáb','sab','dom')) else s.lower().replace('é','e')
        normalized = [plain(s) for s in clauses]
        if re.search(r'lunes\s+a\s+viernes',positive,re.I): normalized.extend(names[:5])
        return [d for n,d in zip(names,self.DAYS) if n in normalized]

    def _extract_discount(self, title, subtitle, requirements, terms):
        text = ' '.join([title,subtitle,*requirements,terms or ''])
        # Never interpret CFT/TNA/TEA or a worked example as the promotion's percentage.
        text = re.split(r'\b(?:EJEMPLO|CFT|TNA|TEA)\b',text,flags=re.I)[0]
        match = re.search(r'(\d{1,3}(?:[.,]\d+)?)\s*%',text)
        if not match: return None
        value = Decimal(match.group(1).replace(',','.'))
        return value if 0 <= value <= 100 else None

    def _normalize_installments(self,value):
        if isinstance(value,bool): return None
        try:
            n = int(value)
            return n if n > 1 and Decimal(str(value)) == n else None
        except (ValueError,TypeError,InvalidOperation): return None

    def _normalize_amount(self,value):
        if isinstance(value,bool) or value in (None,''): return None
        if isinstance(value,(int,float,Decimal)):
            try: number = Decimal(str(value))
            except InvalidOperation: return None
        else:
            text = re.sub(r'^(?:ARS|\$)\s*','',str(value).strip(),flags=re.I).replace(' ','').replace('\u00a0','')
            if re.fullmatch(r'\d+',text): pass
            elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?',text): text = text.replace('.','').replace(',','.')
            elif re.fullmatch(r'\d+,\d{1,2}',text): text = text.replace(',','.')
            elif re.fullmatch(r'\d+\.\d{1,2}',text): pass
            # US-style grouping is accepted only when both delimiters disambiguate it.
            elif re.fullmatch(r'\d{1,3}(?:,\d{3})+\.\d{1,2}',text): text = text.replace(',','')
            else: return None
            try: number = Decimal(text)
            except InvalidOperation: return None
        return number if number.is_finite() and number > 0 else None

    def _checked_amount(self,value,label):
        parsed = self._normalize_amount(value)
        if parsed is None and value not in (None,'',0,'0'):
            raise ValueError(f'BBVA ambiguous or invalid {label}: {value!r}')
        return parsed

    def _currency(self,text):
        return 'USD' if re.search(r'\bUSD\b|US\$',text,re.I) else 'ARS'

    def _extract_fixed_coupon_discount(self,text):
        m = re.search(r'cup[oó]n.{0,100}?por\s+(?:ARS\s*|\$\s*)'+self.MONEY+r'\s+de\s+descuento',text,re.I)
        return self._checked_amount(m.group(1),'coupon') if m else None

    def _extract_minimum_purchase(self,text):
        m = re.search(r'(?:compra\s+m[ií]nima\s*:?|compras?\s+(?:mayores|superiores)\s+(?:a|de))\s*(?:ARS\s*|\$\s*)'+self.MONEY,text,re.I)
        return self._checked_amount(m.group(1),'minimum') if m else None

    def _normalize_cap_scope(self,value):
        value = self._clean_text(value).lower()
        if not value or value in ('ninguno','sin tope'): return None
        if 'compra' in value: return 'purchase'
        if 'cliente' in value or 'persona' in value: return 'customer'
        return value

    def _normalize_cap_period(self,value):
        value = self._clean_text(value).lower()
        if not value: return None
        if 'mensual' in value or re.search(r'\bmes\b',value): return 'monthly'
        if 'seman' in value: return 'weekly'
        if 'diario' in value or re.search(r'\bd[ií]a\b',value): return 'daily'
        if 'único' in value or 'unico' in value: return 'one_time'
        if 'vigencia' in value: return 'promotion'
        return value

    def _normalize_requirements(self,value):
        if value is not None and not isinstance(value,list):
            raise ValueError('BBVA malformed requirements')
        return [self._clean_text(v) for v in value if self._clean_text(v)] if isinstance(value,list) else []

    def _normalize_payment_methods(self,card_group):
        if not card_group: return []
        name = self._clean_text(card_group)
        networks = [v for pat,v in [(r'\bvisa\b','visa'),(r'\bmaster(?:card)?\b','mastercard'),(r'american express|\bamex\b','american_express')] if re.search(pat,name,re.I)]
        types = [v for pat,v in [(r'cr[eé]dito','credit'),(r'd[eé]bito','debit')] if re.search(pat,name,re.I)]
        # One generic method preserves ambiguity; never infer a network/type product.
        return [PaymentMethod(raw_name=name,issuer='BBVA',network=networks[0] if len(networks)==1 else None,card_type=types[0] if len(types)==1 else None)]

    def _payment_options(self,group,requirements,terms):
        methods = self._normalize_payment_methods(group)
        if not methods: return []
        # Only positive eligibility/payment clauses, excluding unrelated exclusions.
        positive = ' '.join(s for s in re.split(r'(?<=[.;])\s+',terms) if re.search(r'(?:con\s+(?:tu\s+)?tarjeta|exclusiv|pagos realizados|a trav[eé]s|desde tu celular)',s,re.I) and not re.match(r'(?:no\b|si\b|la promoci[oó]n no)',s,re.I))
        text = requirements + ' ' + positive
        networks = [v for pat,v in [(r'\bvisa\b','visa'),(r'\bmastercard\b','mastercard')] if re.search(pat,text,re.I)]
        if len(set(networks)) == 1: methods[0].network = networks[0]
        # A single explicit eligibility clause can name both networks for the same
        # credit card type; this is evidence for two alternatives, not a product.
        paired_networks = re.search(r'tarjetas?\s+de\s+cr[eé]dito\s+visa\s+y(?:/o)?\s+mastercard\s+emitidas?\s+por\s+BBVA', text, re.I)
        if paired_networks:
            methods = [methods[0].model_copy(update={'network': network, 'card_type': 'credit'}) for network in ['visa', 'mastercard']]
        # The legally binding exclusive route has priority over a vague marketing list.
        nfc_clause = re.search(r'(?:exclusiv[^.]*?(?:NFC|SIN CONTACTO)|desde tu celular con NFC)[^.]*',positive,re.I)
        qr_clause = re.search(r'(?:a trav[eé]s de app BBVA[^.]*?(?:QR|escaneando)|desde app BBVA[^.]*?QR)',positive,re.I)
        if not nfc_clause and not qr_clause:
            nfc_clause = re.search(r'(?:pagando|exclusiv)[^.]*?\bNFC\b[^.]*',requirements,re.I)
        if nfc_clause:
            route = nfc_clause.group(0)
            wallets = [w for pat,w in [(r'apple\s*pay','Apple Pay'),(r'google\s*pay','Google Pay'),(r'modo\s+conta?ct?less','MODO')] if re.search(pat,route,re.I)]
            if wallets: return [methods[0].model_copy(update={'wallet':w,'payment_rail':'nfc'}) for w in wallets]
        if qr_clause or (re.search(r'\bQR\b',requirements,re.I) and not re.search(r'\bNFC\b|contactless',requirements,re.I)):
            qr_methods = [m.model_copy(update={'payment_rail': 'qr', 'wallet': 'BBVA' if re.search(r'app\s+BBVA',text,re.I) else None}) for m in methods]
            additive_qr = re.search(r'aplica\s+tambi[eé]n\s+a\s+pagos\s+realizados[^.]*?\bQR\b', positive, re.I)
            if additive_qr:
                return [m.model_copy(update={'payment_rail': 'card', 'wallet': None}) for m in methods] + qr_methods
            return qr_methods
        return methods

    def _exclusive_segment(self,text):
        if re.search(r'(?:exclusiv\w*[^.]{0,100}\bblack\b|mastercard\s+black|visa\s+signature\s+black)',text,re.I):
            if re.search(r'black\+?\s*(?:travel|all)',text,re.I): return 'Black+ Travel / Black+ All; Visa Signature'
            return 'Black'
        return None

    def _restrictions(self,terms):
        # Keep actionable clauses; corporate boilerplate and worked examples stay in terms.
        text = re.split(r'LOS ACCIONISTAS|EJEMPLO:',terms,flags=re.I)[0]
        sentences = re.split(r'(?<=[.;])\s+',text)
        selected = [s for s in sentences if re.search(r'no (?:aplica|participan|se acumula)|exclusiv|requisito|vinculad|acumula|c[oó]digo|cup[oó]n|partido|stock|adherid|superior|mayor|adicional|por cuenta|titular|48 horas|compartido|m[aá]ximo|preventa|excluye|millas',s,re.I)]
        return ' '.join(dict.fromkeys(selected))

    def _has_online_channels(self,channels):
        if not isinstance(channels,dict): return False
        return any(isinstance(w,dict) and re.match(r'https?://',str(w.get('url',''))) and not re.search(r'bbva\.com|modo\.com|mastercard\.com|visa\.com|app\.adjust|onelink|play\.google|apps\.apple',str(w.get('url','')),re.I) for w in channels.get('web',[]) if isinstance(channels.get('web'),list))

    def _has_physical_channels(self,channels):
        return isinstance(channels,dict) and isinstance(channels.get('sucursales'),list) and bool(channels['sucursales'])

    def _contains_requirement(self,requirements,term):
        return any(re.search(r'\b'+re.escape(term)+r'\b',r,re.I) for r in requirements)
