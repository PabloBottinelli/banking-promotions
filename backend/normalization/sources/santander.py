"""Deterministic Santander V2 mapping: source publication IDs are eligibility variants."""
import re
import unicodedata
from datetime import date
from decimal import Decimal
from bs4 import BeautifulSoup
from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit

DAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']


def plain(value):
    return BeautifulSoup(value or '', 'html.parser').get_text(' ', strip=True)


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if unicodedata.category(c) != 'Mn')


def _date(value):
    return date.fromisoformat(value[:10]) if value else None


def _amount(value):
    return Decimal(str(value))


class SantanderNormalizer:
    def normalize_many(self, raw):
        d, p, b = raw['detail'], raw['program'], raw['catalog']
        legal = plain(d.get('legal'))
        title = plain(d.get('texts', {}).get('title'))
        if not legal or not title or not plain(b.get('name')):
            raise ValueError('Missing essential publication evidence')
        terms = d['legal']
        folded = fold(legal)
        warnings = []
        start, end = _date(d.get('initialDate')), _date(d.get('endDate'))
        # Full legal validity clauses outrank the source presentation window. No inferred year.
        pair = re.search(r'(?:desde el|del|desde)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+(?:hasta el|al|hasta)\s+(\d{1,2}/\d{1,2}/\d{2,4})', folded)
        if pair:
            def parse(s):
                day, month, year = map(int, s.split('/'))
                return date(year + 2000 if year < 100 else year, month, day)
            a, z = parse(pair[1]), parse(pair[2])
            if (start and a != start) or (end and z != end):
                warnings.append('La vigencia legal difiere de la ventana del catálogo; se muestra la vigencia legal.')
            start, end = a, z
        benefits = []
        special = plain(d.get('specialCondition'))
        if special:
            # E.g. 2x1 is a documented entitlement, not a percentage fallback.
            benefits.append(Benefit(type='other', description=special))
        presale = re.search(r'\bpreventa\b[^.]*', legal, re.I)
        if presale:
            benefits.append(Benefit(type='other', description=presale[0]))
        percent = d.get('customerDiscount')
        if percent and _amount(percent) > 0:
            if _amount(percent) > 100:
                raise ValueError('Invalid source discount percentage')
            # Ahorro is credited back when legal terms specify reintegro/accreditation.
            kind = 'cashback' if re.search(r'via reintegro|se hara efectivo.*reintegro|se acreditara|reintegro se', folded) else 'discount'
            benefits.append(Benefit(type=kind, percentage=_amount(percent),
                                   description=title if d.get('texts', {}).get('untilDiscount') else None))
        display = title + ' ' + plain(d.get('texts', {}).get('description'))
        quoted = re.search(r'(hasta\s+)?(\d+)\s+cuotas?\s+(sin interes|fijas)?', fold(display))
        fees = d.get('texts', {}).get('fees') or (int(quoted[2]) if quoted else None)
        if fees and quoted:
            interest = True if d.get('interestFreeFees') is True and 'sin interes' in fold(display) else None
            benefits.append(Benefit(type='installments', installment_options=[int(fees)], interest_free=interest,
                                   description=('Hasta ' if d['texts'].get('untilFees') or quoted[1] else '') + str(fees) + ' cuotas' + (' sin interés' if interest else '')))
        if not benefits:
            raise ValueError('No evidenced benefit in source publication')
        limits = []
        cap = d.get('topAmount')
        freq = (d.get('frecuency') or {}).get('code')
        periods = {'M':'monthly', 'S':'weekly', 'D':'daily', 'V':'promotion','A':'transaction'}
        desc = plain(d.get('texts', {}).get('description'))
        if cap and _amount(cap) > 0:
            # currency comes from the source display, never infer USD as ARS.
            currency_evidence = desc + ' ' + legal
            currency = 'USD' if re.search(r'US\$|USD|U\$S', desc, re.I) else 'ARS' if '$' in currency_evidence or 'pesos' in folded else None
            scope = 'account' if re.search(r'titular.*adicional|adicional.*titular', folded) else None
            limits.append(PromotionLimit(type='monetary_cap', amount=_amount(cap), currency=currency,
                        period=periods.get(freq), scope=scope,
                        shared_group_id='santander:'+str(p.get('idPromotion') or d['id']) if scope else None,
                        description=desc or None))
            if 'sin tope' in fold(plain(d.get('texts',{}).get('subtitle'))):
                warnings.append('El subtítulo dice sin tope, pero el detalle publica un tope; consultar condiciones legales.')
        if d.get('stock') and int(d['stock']) > 0:
            limits.append(PromotionLimit(type='stock',quantity=int(d['stock']),description='Stock publicado por Santander'))
        stock = re.search(r'stock (?:de )?preventa(?: santander)?\s*:\s*(?:[a-z ]+\()?((?:\d{1,3}(?:\.\d{3})+)|\d+)(?:\))?\s*(?:tickets|entradas|abonos)', folded)
        if stock:
            limits.append(PromotionLimit(type='stock',quantity=int(stock[1].replace('.','')),period='presale',description=stock[0]))
        usage = re.search(r'cupo maximo de\s+(\d+)\s+entradas por cliente',folded)
        if usage:
            limits.append(PromotionLimit(type='usage_count',quantity=int(usage[1]),period='promotion',scope='person',description=usage[0]))
        # Explicit minimum-purchase phrases only, not examples or operating ceilings.
        for m in re.finditer(r'(?:compra minima|monto minimo de compra|compras superiores a)\s*(?:de\s*)?\$\s*([\d.]+(?:,\d{1,2})?)', folded):
            limits.append(PromotionLimit(type='minimum_purchase',amount=Decimal(m[1].replace('.','').replace(',','.')),currency='ARS',description=m[0]))
        payments = self._payments(d, folded)
        requires = bool(d.get('brands')) or bool(re.search(r'\badherid[oa]s\b', folded))
        conditions = []
        additional = BeautifulSoup(d.get('additionalText') or '', 'html.parser')
        # Event biographies are retained raw, not copied into user-facing restrictions.
        additional_parts = [p.get_text(' ',strip=True) for p in additional.find_all(['p','li'])]
        additional_restrictions = ' '.join(x for x in additional_parts if re.search(r'pagando|abonando|exclusiv|preventa|cuota|codigo|cupon|solo|paquetes|nacionales|sorpresa',fold(x)))
        for value in [additional_restrictions, plain(d.get('specialCondition'))]:
            if value:
                conditions.append(value)
        segment = d.get('productSegmentation')
        if segment and segment != 'Masiva':
            conditions.append('Segmento publicado: ' + segment + '.')
        tag = (d.get('tag') or {}).get('description')
        if tag and tag != segment:
            conditions.append('Condición publicada: ' + tag + '.')
        if desc:
            conditions.append(desc + '.')
        # Keep restrictions, exclusions, regions, codes and benefit stages separate from full legal text.
        for sentence in re.split(r'(?<=[.;])\s+|\n+', legal):
            f = fold(sentence)
            if ('ejemplo' not in f and re.search(r'exclu|no aplica|no acumul|unicamente|solo |solamente|adherid|codigo|cupon|sorpresa|select|sueldo|jubil|provincia|localidad|primer[ao]|extra|adicional|tope|minim|preventa|stock|cupo maximo|acumulable|dos reintegros', f)
                    and not re.search(r'cftna|costo financiero|ejemplo:', f)):
                if len(sentence) < 1500:
                    conditions.append(sentence)
        if requires:
            conditions.append('Consultar locales y comercios adheridos en el detalle oficial de Santander.')
        conditions.extend(warnings)
        days = [day for day in DAYS if d.get(day) is True]
        every = True if d.get('fullWeek') is True else None
        # App and QR do not establish purchase channels. Positive legal source clauses only.
        online = True if re.search(r'(?:valido|valida|aplica|compras?).{0,45}(?:tienda online|sitio web|compra online|compras online)', folded) and not re.search(r'(?:no aplica|excluye).{0,45}(?:online|sitio web)',folded) else None
        physical = True if re.search(r'en (?:los )?(?:locales|comercios|sucursales) (?:fisicos |presenciales )?adheridos|sucursales fisicas|tiendas presenciales',folded) else None
        categories = [c['description'] for c in d.get('categories',[]) if c.get('code') not in {'SOR','MOD','SEC','EXV','SMI'}]
        group = str(p.get('idPromotion') or d['id'])
        common = dict(source='santander', scraped_at=raw['scraped_at'], title=b['name'] + ': ' + title,
            scope='shopping' if b.get('brandType',{}).get('code') == 'SHP' else 'merchant', merchant=b['name'], category=', '.join(categories) or None,
            promotion_group_id='santander:' + group, valid_from=start, valid_to=end,
            promotion_url=raw['promotion_url'], requires_merchant_verification=requires,
            days_of_week=days, applies_every_day=every, online=online, physical=physical,
            specific_conditions=' '.join(dict.fromkeys(conditions)), terms=terms, limits=limits)
        credit = [m for m in payments if m.card_type == 'credit']
        other = [m for m in payments if m.card_type != 'credit']
        stages = []
        if presale:
            presale_benefits = [x for x in benefits if x.type=='other' and x.description==presale[0]]
            benefits = [x for x in benefits if x not in presale_benefits]
            presale_payments = payments
            presale_folded=fold(presale[0])
            networks=[network for network,pattern in [('VISA',r'\bvisa\b'),('AMEX',r'american express|\bamex\b'),('MASTER',r'mastercard|\bmaster\b')] if re.search(pattern,presale_folded)]
            if networks:
                presale_payments=[m for m in payments if m.network in networks]
            presale_dates=re.findall(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',presale[0])
            presale_start=presale_end=None
            if presale_dates:
                def presale_date(s):
                    day,month,year=map(int,s.split('/'))
                    return date(year+2000 if year<100 else year,month,day)
                presale_start=presale_date(presale_dates[0])
                if len(presale_dates)>1:
                    presale_end=presale_date(presale_dates[1])
                    if presale_end<presale_start:
                        presale_start=presale_end=None
            stages.append(NormalizedPromotion(**{**common,'title':b['name']+': Preventa exclusiva',
                'valid_from':presale_start,'valid_to':presale_end,
                'specific_conditions':common['specific_conditions']+' Etapa de preventa: '+presale[0]+'. Consultar horario, duración y stock oficiales; no confundir con la vigencia general de financiación.'},
                source_id=raw['source_id']+':presale',benefits=presale_benefits,payment_methods=presale_payments))
            common['limits']=[l for l in limits if not (l.type=='stock' and l.period=='presale')]
            limits=common['limits']
        installments = [x for x in benefits if x.type == 'installments']
        rest = [x for x in benefits if x.type != 'installments']
        if installments and rest and other:
            for cap in limits:
                if cap.type == 'monetary_cap':
                    cap.shared_group_id = cap.shared_group_id or 'santander:' + raw['source_id']
            return stages + [NormalizedPromotion(**common,source_id=raw['source_id']+':credit',benefits=benefits,payment_methods=credit),
                    NormalizedPromotion(**{**common,'title':b['name'] + ': ' + ' + '.join((str(x.percentage)+'% de ahorro') if x.percentage is not None else x.description or x.type for x in rest),
                        'specific_conditions':common['specific_conditions']+' Las cuotas corresponden exclusivamente a tarjetas de crédito.'},
                        source_id=raw['source_id']+':non-credit',benefits=rest,payment_methods=other)]
        return stages + ([NormalizedPromotion(**common,source_id=raw['source_id'],benefits=benefits,payment_methods=credit if installments else payments)] if benefits else [])

    @staticmethod
    def _payments(d, legal):
        result = []
        code = (d.get('paymentType') or {}).get('code')
        if not d.get('cards') and 'transferencia (pct)' in legal and 'qr' in legal:
            for wallet in ['App Santander', 'MODO'] if 'app santander o app modo' in legal else ['MODO']:
                result.append(PaymentMethod(raw_name=wallet+' QR transporte por transferencia (PCT)',
                    issuer='Santander',wallet=wallet,payment_rail='qr'))
            return result
        # Each cards[] entry is an actual supported network/type combination.
        for card in d.get('cards', []):
            typ = {'C':'credit','D':'debit','P':'prepaid'}.get(card.get('codeType'))
            network = card.get('description')
            rail = 'qr' if code == 'M' or re.search(r'abonando con qr|pagando con qr',legal) else 'nfc' if code == 'C' else 'card'
            wallets = ['App Santander','MODO'] if rail == 'qr' and 'app santander o app modo' in legal else ['App Santander'] if rail == 'qr' and 'app santander' in legal else ['MODO'] if rail == 'qr' and 'modo' in legal else [None]
            if rail=='nfc':
                wallets=[name for name,pattern in [('Apple Pay',r'apple pay'),('Google Pay',r'google pay'),('MODO Contactless',r'modo contactless')] if re.search(pattern,legal)] or [None]
            if code=='A':
                evidence=legal+' '+fold(plain(d.get('additionalText')))
                wallets=['App YPF'] if re.search(r'app\s*ypf',evidence) else ['App Cabify'] if 'app cabify' in evidence else ['PedidosYa'] if re.search(r'pedidos\s*ya',evidence) else [None]
            for wallet in wallets:
                result.append(PaymentMethod(raw_name=' '.join(filter(None,['Santander',network,card.get('descriptionType'),wallet,rail])),issuer='Santander', network=network,card_type=typ,wallet=wallet,payment_rail=rail))
        return result
