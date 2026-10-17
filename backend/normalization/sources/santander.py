"""Santander V2: publication IDs represent source eligibility variants."""
import re
import unicodedata
from datetime import date
from decimal import Decimal
from bs4 import BeautifulSoup
from normalization.models import Benefit, NormalizedPromotion, PaymentMethod, PromotionLimit

DAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
MONTHS = {name: number for number, name in enumerate([
    'enero','febrero','marzo','abril','mayo','junio','julio','agosto',
    'septiembre','octubre','noviembre','diciembre'], start=1)}


def plain(value):
    return BeautifulSoup(value or '', 'html.parser').get_text(' ', strip=True)


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if unicodedata.category(c) != 'Mn')


def _date(value):
    return date.fromisoformat(value[:10]) if value else None


def _amount(value):
    return Decimal(str(value))


def parse_date(value):
    day, month, year = map(int, value.split('/'))
    return date(year + 2000 if year < 100 else year, month, day)


CARD_TYPES = {'C':'credit','D':'debit','P':'prepaid','R':'prepaid'}


def named_card_types(text):
    return {typ for typ,pattern in [
        ('credit',r'\bcredito\b'),('debit',r'\bdebito\b'),
        ('prepaid',r'\brecargable\b|\bprepaga\b')]
        if re.search(pattern,text)}


def legal_card_constraints(legal):
    """Positive alternatives scoped by network/type; None means ambiguous attachment."""
    alternatives=[]
    evidence=legal.split('ejemplo',1)[0]
    for sentence in re.split(r'(?<=[.;])\s+',evidence):
        if re.search(r'\bpreventa\b|\bno (?:aplica|valid|incluye)|\bse exclu|\bexcluid',sentence):
            continue
        clause=re.search(r'\b(?:con|para)\s+(?:las?\s+)?tarjetas?\s+santander\b([^.;]+)',sentence)
        if not clause:
            continue
        text=re.split(r'\bincluidos\b',clause[1],maxsplit=1)[0]
        names=list(re.finditer(r'\bvisa\b|\bmaster(?:card)?\b|\bamex\b|\bamerican express\b',text))
        if not names:
            types=named_card_types(text)
            if types:
                alternatives.append((None,types))
            continue
        prefix_types=named_card_types(text[:names[0].start()])
        for i,name in enumerate(names):
            tail=text[name.end():names[i+1].start() if i+1<len(names) else len(text)]
            # E.g. "Visa y debito Mastercard" cannot safely attach the type to a network.
            if i+1<len(names) and re.search(r'(?:,|\by\b)\s+(?:de\s+)?(?:credito|debito|recargable)\s*$',tail):
                return None
            network='VISA' if name[0]=='visa' else 'MASTER' if name[0].startswith('master') else 'AMEX'
            types=named_card_types(tail) or prefix_types
            alternatives.append((network,types or None))
    return alternatives


def card_combination_allowed(network,card_type,constraints):
    if constraints is None:
        return False
    if not constraints:
        return True  # No positive legal restriction parsed; retain actual source cards[].
    return any((name is None or name==network) and (types is None or card_type in types)
               for name,types in constraints)


def legal_card_networks(legal):
    constraints=legal_card_constraints(legal)
    if not constraints or any(name is None for name,_ in constraints):
        return set()
    return {name for name,_ in constraints}


def legal_monthly_caps(legal, segment=None):
    """Select an explicit segment ceiling; extra caps remain separate, never summed."""
    evidence = ' '.join(sentence for sentence in re.split(r'(?<=[.;])\s+',legal.split('ejemplo',1)[0])
        if not re.search(r'\bno (?:aplica|incluye|valid)|\bse exclu|\bexcluid',sentence))
    number = r'(?:\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)'
    amount = r'(?P<amount>'+number+r')'
    prefix = r'\btope(?: de (?:reintegro|ahorro|descuento))?'
    patterns = [
        prefix+r'\s+mensual\s*(?:sera\s*)?(?:de\s*|:\s*)?\$\s*'+amount,
        prefix+r'\s*(?:sera\s*)?(?:de\s*|:\s*)?\$\s*'+amount+r'\s*(?:\([^)]*\)\s*)?(?:por mes|mensual)\b',
    ]
    def money(match):
        return Decimal(match['amount'].replace('.','').replace(',','.'))
    unqualified={money(match) for pattern in patterns for match in re.finditer(pattern,evidence)}
    if not segment or fold(segment)=='masiva':
        return unqualified
    scoped=re.finditer(prefix+r'\s+mensual\s+(?P<qualifier>para\s+[^$;.]{1,180})\$\s*'
                       +amount+r'(?P<extra>\s+extra)?',evidence)
    selected=[]
    for match in scoped:
        if re.search(r'\b'+re.escape(fold(segment))+r'\b',match['qualifier']):
            selected.append((money(match),bool(match['extra']) or bool(re.search(r'\bextra\b',match['qualifier']))))
    if selected and not any(extra for _,extra in selected):
        return {value for value,_ in selected}
    return unqualified | {value for value,_ in selected}


def effective_presale_clause(legal):
    """Skip standalone headings/stock labels; retain a positive stage and its duration."""
    return re.search(
        r'(?<!stock )\bpreventa\s+(?:(?:exclusiva\s+)?(?:con\s+tarjetas?|santander|para\s+clientes)|del?\s+(?=\d))'
        r'[^.]*(?:\.\s*(?:por|durante)\s+\d+[^.]*)?', legal, re.I)


def presale_card_types(clause):
    """Types named in the positive stage clause; an unnamed stage retains ambiguity."""
    clause=fold(clause)
    if not re.match(r'preventa\b',clause) or not re.search(r'\btarjetas?\b|\bsantander\b',clause):
        return set()
    return {typ for typ,pattern in [
        ('credit',r'\bcredito\b'),('debit',r'\bdebito\b'),
        ('prepaid',r'\brecargable\b|\bprepaga\b')]
        if re.search(pattern,clause)}


def unlimited_claim_fields(raw):
    """Published claim provenance, independent of whether API has a numeric cap."""
    claims=[]
    for name,node in [('detail',raw.get('detail',{})),('program',raw.get('program',{}))]:
        values={name+'.texts.'+key:value for key,value in (node.get('texts') or {}).items()
                if isinstance(value,str)}
        values.update({name+'.'+key:node.get(key) for key in ['additionalText','specialCondition']})
        if name=='detail':
            values[name+'.legal']=re.split(r'\bejemplo\b',plain(node.get('legal')),maxsplit=1,flags=re.I)[0]
        for path,value in values.items():
            if re.search(r'\bsin tope\b',fold(plain(value))):
                claims.append(path)
    if re.search(r'\bsin tope\b',fold(plain(raw.get('catalog',{}).get('benefitDescription')))):
        claims.append('catalog.benefitDescription')
    return claims


class SantanderNormalizer:
    def normalize_many(self, raw):
        d, p, b = raw['detail'], raw['program'], raw['catalog']
        legal = plain(d.get('legal'))
        title = plain(d.get('texts', {}).get('title'))
        if not legal or not title or not plain(b.get('name')):
            raise ValueError('Missing essential publication evidence')
        terms, folded, warnings = d['legal'], fold(legal), []
        start, end = _date(d.get('initialDate')), _date(d.get('endDate'))
        pair = re.search(r'(?:desde el|del|desde)\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+(?:hasta el|al|hasta)\s+(\d{1,2}/\d{1,2}/\d{2,4})', folded)
        legal_dates = None
        if pair:
            legal_dates = parse_date(pair[1]), parse_date(pair[2])
        else:
            long_pair = re.search(
                r'desde el\s+(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})\s+'
                r'hasta el\s+(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})', folded)
            if long_pair and long_pair[2] in MONTHS and long_pair[5] in MONTHS:
                legal_dates = (date(int(long_pair[3]),MONTHS[long_pair[2]],int(long_pair[1])),
                               date(int(long_pair[6]),MONTHS[long_pair[5]],int(long_pair[4])))
        if legal_dates:
            a, z = legal_dates
            if (start and a != start) or (end and z != end):
                warnings.append('La vigencia legal difiere de la ventana del catálogo; se muestra la vigencia legal.')
            start, end = a, z
        benefits = []
        special = plain(d.get('specialCondition'))
        if special:
            benefits.append(Benefit(type='other', description=special))
        presale = effective_presale_clause(legal)
        if presale:
            benefits.append(Benefit(type='other', description=presale[0]))
        percent = d.get('customerDiscount')
        if percent and _amount(percent) > 0:
            if _amount(percent) > 100:
                raise ValueError('Invalid source discount percentage')
            kind = 'cashback' if re.search(r'via reintegro|se hara efectivo.*reintegro|se acreditara|reintegro se', folded) else 'discount'
            benefits.append(Benefit(type=kind, percentage=_amount(percent),
                description=title if d.get('texts', {}).get('untilDiscount') else None))
        display = title + ' ' + plain(d.get('texts', {}).get('description'))
        quoted = re.search(r'(hasta\s+)?(\d+)\s+cuotas?\s+(sin interes|fijas)?', fold(display))
        fees = d.get('texts', {}).get('fees') or (int(quoted[2]) if quoted else None)
        if fees and quoted:
            interest = True if d.get('interestFreeFees') is True and 'sin interes' in fold(display) else None
            explicit_options=re.search(r'\b(\d+(?:\s*(?:,|y)\s*\d+)+)\s+cuotas?\s+sin interes',folded)
            options=sorted({int(n) for n in re.findall(r'\d+',explicit_options[1])}) if explicit_options else [int(fees)]
            benefits.append(Benefit(type='installments', installment_options=options, interest_free=interest,
                description=('Hasta ' if d['texts'].get('untilFees') or quoted[1] else '') + str(fees) + ' cuotas' + (' sin interés' if interest else '')))
        if not benefits:
            raise ValueError('No evidenced benefit in source publication')
        limits = []
        cap, freq = d.get('topAmount'), (d.get('frecuency') or {}).get('code')
        periods = {'M':'monthly','S':'weekly','D':'daily','V':'promotion','A':'transaction'}
        desc = plain(d.get('texts', {}).get('description'))
        monthly_values=legal_monthly_caps(folded,d.get('productSegmentation'))
        if cap and _amount(cap) > 0:
            currency = 'USD' if re.search(r'US\$|USD|U\$S', desc, re.I) else 'ARS' if '$' in desc + ' ' + legal or 'pesos' in folded else None
            scope = 'account' if re.search(r'titular.*adicional|adicional.*titular', folded) else None
            limits.append(PromotionLimit(type='monetary_cap', amount=_amount(cap), currency=currency,
                period=periods.get(freq), scope=scope,
                shared_group_id='santander:'+str(p.get('idPromotion') or d['id']) if scope else None,
                description=desc or None))
            # The merchant-family relationship is explicit source evidence and may cross campaign IDs.
            # Derive its stable identity from that evidence; never infer sharing from similar names.
            shared = re.search(r'\btope compartido con las demas promociones en ([^.;]+)',
                               fold(plain(d.get('additionalText'))+' '+legal))
            if shared:
                label = re.sub(r'[^a-z0-9]+','-',shared[1].strip()).strip('-')
                if not label:
                    raise ValueError('Blank shared cap identity in source')
                limits[-1].shared_group_id='santander:shared-cap:'+label
                limits[-1].description=(desc+'. ' if desc else '')+shared[0]
            # A conflicting legal transaction cap must not become an asserted economic value.
            transaction_cap=re.search(r'tope(?: sera)?(?: de)?\s*(?:\$\s*([\d.]+)|([\d.]+)\s*\$)\s*por transaccion',folded)
            if transaction_cap and freq=='A':
                legal_amount=Decimal((transaction_cap[1] or transaction_cap[2]).replace('.',''))
                if legal_amount!=_amount(cap):
                    warning=f'Conflicto de tope: catálogo {cap} ARS por transacción; legales {legal_amount} ARS por transacción. Consultar el banco antes de utilizar el beneficio.'
                    warnings.append(warning)
                    limits[-1].amount=None
                    limits[-1].description=warning
            if freq=='M' and currency=='ARS':
                if monthly_values and monthly_values!={_amount(cap)}:
                    warning=('Conflicto de tope mensual: catálogo '+str(cap)+' ARS; legales '
                             +', '.join(str(value) for value in sorted(monthly_values))
                             +' ARS. El importe queda sin confirmar; consultar Santander antes de utilizar el beneficio.')
                    warnings.append(warning)
                    limits[-1].amount=None
                    limits[-1].description=(limits[-1].description+'. ' if limits[-1].description else '')+warning
        monthly=re.search(r'tope mensual\s*:\s*\$\s*([\d.]+(?:,\d{1,2})?)',fold(plain(d.get('additionalText'))))
        if monthly and freq!='M':
            limits.append(PromotionLimit(type='monetary_cap',amount=Decimal(monthly[1].replace('.','').replace(',','.')),currency='ARS',period='monthly',description=monthly[0]))
        if freq!='M' and monthly_values:
            account_scope='account' if re.search(r'titular.*adicional|adicional.*titular',folded.split('ejemplo',1)[0]) else None
            for value in sorted(monthly_values):
                evidence_note='Tope mensual publicado en condiciones legales: '+str(value)+' ARS.'
                existing=next((limit for limit in limits if limit.type=='monetary_cap'
                    and limit.period=='monthly' and limit.currency=='ARS' and limit.amount==value),None)
                if existing:
                    existing.description=(existing.description+' ' if existing.description else '')+evidence_note
                    if account_scope:
                        existing.scope=account_scope
                        existing.shared_group_id='santander:'+str(p.get('idPromotion') or d['id'])
                else:
                    limits.append(PromotionLimit(type='monetary_cap',amount=value,currency='ARS',period='monthly',
                        scope=account_scope,shared_group_id='santander:'+str(p.get('idPromotion') or d['id']) if account_scope else None,
                        description=evidence_note))
            if any(limit.type=='monetary_cap' and limit.period!='monthly' for limit in limits):
                warnings.append('La fuente publica topes de distintos períodos; los importes no se suman. Consultar su aplicación conjunta en las condiciones oficiales.')
        transactions=re.search(r'hasta\s+(\d+)\s+transacciones por mes',folded)
        if transactions:
            limits.append(PromotionLimit(type='usage_count',quantity=int(transactions[1]),period='monthly',description=transactions[0]))
        budget=re.search(r'stock de\s+(\d{1,3}(?:,\d{3})+|\d+)\s+pesos argentinos',folded)
        if budget:
            limits.append(PromotionLimit(type='stock',amount=Decimal(budget[1].replace(',','')),currency='ARS',period='promotion',scope='campaign',description=budget[0]))
        if re.search(r'limitada a un descuento por dispositivo y por reserva',folded):
            for scope in ['device','reservation']:
                limits.append(PromotionLimit(type='usage_count',quantity=1,period='promotion',scope=scope,description='Un descuento por dispositivo y por reserva.'))
        if d.get('stock') and int(d['stock']) > 0:
            limits.append(PromotionLimit(type='stock',quantity=int(d['stock']),description='Stock publicado por Santander'))
        stock = re.search(r'stock (?:de )?preventa(?: santander)?\s*:\s*(?:[a-z ]+\()?((?:\d{1,3}(?:\.\d{3})+)|\d+)(?:\))?\s*(?:tickets|entradas|abonos)', folded)
        if stock:
            limits.append(PromotionLimit(type='stock',quantity=int(stock[1].replace('.','')),period='presale',description=stock[0]))
        usage = re.search(r'cupo maximo de\s+(\d+)\s+entradas por cliente',folded)
        if usage:
            limits.append(PromotionLimit(type='usage_count',quantity=int(usage[1]),period='promotion',scope='person',description=usage[0]))
        for m in re.finditer(r'(?:compra minima|monto minimo de compra|compras superiores a|compras (?:mayor(?:es)? o iguales|mayores o igual) a)\s*(?:de\s*)?\$\s*([\d.]+(?:,\d{1,2})?)',folded):
            limits.append(PromotionLimit(type='minimum_purchase',amount=Decimal(m[1].replace('.','').replace(',','.')),currency='ARS',description=m[0]))
        unlimited_claims=unlimited_claim_fields(raw)
        unlimited_conflict=bool(unlimited_claims and (monthly_values or any(
            limit.type=='monetary_cap' and limit.amount is not None and limit.amount>0 for limit in limits)))
        if unlimited_conflict:
            warnings.append('Conflicto de tope: hay afirmaciones publicadas de «sin tope» en '
                +', '.join(unlimited_claims)+', pero la fuente también publica límites monetarios. '
                +'La ausencia de tope no está confirmada; verificar las condiciones con Santander.')
        payments = self._payments(d, folded)
        legal_networks = legal_card_networks(folded)
        contradicted = sorted({card.get('description') for card in d.get('cards',[])
                               if legal_networks and card.get('description') not in legal_networks})
        if contradicted:
            warnings.append('Conflicto de medios de pago: el catálogo incluye '+', '.join(contradicted)
                +'; la cláusula legal admite '+', '.join(sorted(legal_networks))
                +'. Se muestran solo las redes de la cláusula legal. Verificar las condiciones con Santander.')
        card_constraints=legal_card_constraints(folded)
        if card_constraints is None:
            warnings.append('No se pudo separar inequívocamente la elegibilidad de tipos por red; consultar las condiciones oficiales. Los medios de pago quedan sin estructurar.')
        else:
            type_conflicts=sorted({str(card.get('description'))+' '+str(card.get('descriptionType'))
                for card in d.get('cards',[])
                if (not legal_networks or card.get('description') in legal_networks)
                and not card_combination_allowed(card.get('description'),CARD_TYPES.get(card.get('codeType')),card_constraints)})
            if type_conflicts:
                warnings.append('Conflicto de tipos de tarjeta: el catálogo incluye '+', '.join(type_conflicts)
                    +', que no cumplen la cláusula legal positiva de elegibilidad. Se conservan solo las combinaciones admitidas por los legales; verificar las condiciones con Santander.')
        requires = bool(d.get('brands')) or bool(re.search(r'\badherid[oa]s\b', folded))
        conditions = []
        additional = BeautifulSoup(d.get('additionalText') or '', 'html.parser')
        parts = [node.get_text(' ',strip=True) for node in additional.find_all(['p','li'])]
        restrictions = ' '.join(x for x in parts if re.search(r'pagando|abonando|exclusiv|preventa|cuota|codigo|cupon|solo|paquetes|nacionales|sorpresa|tope|vuelos|no aplica|no valid|no incluye|exclu|\b\d+\s*h\b',fold(x)))
        for value in [restrictions,special]:
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
        for sentence in re.split(r'(?<=[.;])\s+|\n+', legal):
            f = fold(sentence)
            if re.search(r'\bno valid|\bno incluye', f):
                conditions.append(sentence if len(sentence)<=450 else
                    'Hay exclusiones adicionales de productos y marcas; consultar el listado completo en los términos oficiales antes de comprar.')
                continue
            if ('ejemplo' not in f and re.search(r'exclu|no aplica|no acumul|no valid|no incluye|unicamente|solo |solamente|adherid|codigo|cupon|sorpresa|select|sueldo|jubil|provincia|localidad|primer[ao]|extra|adicional|tope|minim|mayor(?:es)? o igual|preventa|stock|cupo maximo|acumulable|dos reintegros|limitada|reserva|vuelo|\d+\s*(?:am|pm|hs?\b)',f)
                    and not re.search(r'cftna|costo financiero|ejemplo:',f) and len(sentence)<1500):
                conditions.append(sentence)
        if requires:
            conditions.append('Consultar locales y comercios adheridos en el detalle oficial de Santander.')
        if unlimited_conflict:
            conditions=['Afirmación publicada discordante: «'+condition+'». Confirmar el tope con Santander.'
                if re.search(r'\bsin tope\b',fold(condition)) else condition for condition in conditions]
            if re.search(r'\bsin tope\b',fold(title)):
                title+=' (tope sujeto a confirmación por contradicción de la fuente)'
            for benefit in benefits:
                if benefit.description and re.search(r'\bsin tope\b',fold(benefit.description)):
                    benefit.description='Afirmación publicada discordante: «'+benefit.description+'». Confirmar el tope con Santander.'
        conditions.extend(warnings)
        days = [day for day in DAYS if d.get(day) is True]
        every = True if d.get('fullWeek') is True else None
        positive_channels=' '.join(sentence for sentence in re.split(r'(?<=[.;])\s+|\n+',folded)
            if not re.search(r'\bno (?:aplica|valid|incluye)|\bexclu',sentence))
        online = True if re.search(r'(?:valido|valida|aplica|compras?).{0,45}(?:tienda online|sitio web|compra online|compras online)', positive_channels) else None
        physical = True if re.search(r'en (?:los )?(?:locales|comercios|sucursales) (?:fisicos |presenciales )?adheridos|sucursales fisicas|tiendas presenciales',positive_channels) else None
        categories = [c['description'] for c in d.get('categories',[]) if c.get('code') not in {'SOR','MOD','SEC','EXV','SMI'}]
        group = str(p.get('idPromotion') or d['id'])
        common = dict(source='santander',scraped_at=raw['scraped_at'],title=b['name']+': '+title,
            scope='shopping' if b.get('brandType',{}).get('code')=='SHP' else 'merchant',
            merchant=b['name'],category=', '.join(categories) or None,promotion_group_id='santander:'+group,
            valid_from=start,valid_to=end,promotion_url=raw['promotion_url'],requires_merchant_verification=requires,
            days_of_week=days,applies_every_day=every,online=online,physical=physical,
            specific_conditions=' '.join(dict.fromkeys(conditions)),terms=terms,limits=limits)
        credit = [m for m in payments if m.card_type=='credit']
        other = [m for m in payments if m.card_type!='credit']
        stages = []
        if presale:
            stage_benefits=[x for x in benefits if x.type=='other' and x.description==presale[0]]
            benefits=[x for x in benefits if x not in stage_benefits]
            stage_payments=payments
            networks=[network for network,pattern in [('VISA',r'\bvisa\b'),('AMEX',r'american express|\bamex\b'),('MASTER',r'mastercard|\bmaster\b')] if re.search(pattern,fold(presale[0]))]
            if networks:
                stage_payments=[m for m in payments if m.network in networks]
            stage_types=presale_card_types(presale[0])
            if stage_types:
                stage_payments=[m for m in stage_payments if m.card_type in stage_types]
            if payments and not stage_payments:
                raise ValueError('Presale eligibility contradicts all published payment combinations; review required')
            dates=re.findall(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',presale[0])
            stage_start=stage_end=None
            if dates:
                stage_start=parse_date(dates[0])
                if len(dates)>1:
                    stage_end=parse_date(dates[1])
                    if stage_end<stage_start:
                        stage_start=stage_end=None
            stages.append(NormalizedPromotion(**{**common,'title':b['name']+': Preventa exclusiva',
                'valid_from':stage_start,'valid_to':stage_end,
                'specific_conditions':common['specific_conditions']+' Etapa de preventa: '+presale[0]+'. Consultar horario, duración y stock oficiales; no confundir con la vigencia general de financiación.'},
                source_id=raw['source_id']+':presale',benefits=stage_benefits,payment_methods=stage_payments))
            common['limits']=[limit for limit in limits if not (limit.type=='stock' and limit.period=='presale')]
            limits=common['limits']
        installments=[x for x in benefits if x.type=='installments']
        rest=[x for x in benefits if x.type!='installments']
        # Keep the established semantic credit ID when legal reconciliation removes a
        # contradicted non-credit option from the source's original card alternatives.
        source_had_noncredit=any(CARD_TYPES.get(card.get('codeType'))!='credit' for card in d.get('cards',[]))
        if installments and rest and (other or source_had_noncredit):
            for cap in limits:
                if cap.type=='monetary_cap':
                    cap.shared_group_id=cap.shared_group_id or 'santander:'+raw['source_id']
            return stages+[
                NormalizedPromotion(**common,source_id=raw['source_id']+':credit',benefits=benefits,payment_methods=credit)] + ([
                NormalizedPromotion(**{**common,'title':b['name']+': '+' + '.join(str(x.percentage)+'% de ahorro' if x.percentage is not None else x.description or x.type for x in rest),
                    'specific_conditions':common['specific_conditions']+' Las cuotas corresponden exclusivamente a tarjetas de crédito.'},
                    source_id=raw['source_id']+':non-credit',benefits=rest,payment_methods=other)] if other else [])
        return stages+([NormalizedPromotion(**common,source_id=raw['source_id'],benefits=benefits,payment_methods=credit if installments else payments)] if benefits else [])

    @staticmethod
    def _payments(d, legal):
        result=[]
        code=(d.get('paymentType') or {}).get('code')
        allowed_networks=legal_card_networks(legal)
        constraints=legal_card_constraints(legal)
        if not d.get('cards') and 'transferencia (pct)' in legal and 'qr' in legal:
            for wallet in ['App Santander','MODO'] if 'app santander o app modo' in legal else ['MODO']:
                result.append(PaymentMethod(raw_name=wallet+' QR transporte por transferencia (PCT)',issuer='Santander',wallet=wallet,payment_rail='qr'))
            return result
        for card in d.get('cards',[]):
            typ=CARD_TYPES.get(card.get('codeType'))
            network=card.get('description')
            if allowed_networks and network not in allowed_networks:
                continue
            if not card_combination_allowed(network,typ,constraints):
                continue
            rail='qr' if code=='M' or re.search(r'abonando con qr|pagando con qr',legal) else 'nfc' if code=='C' else 'card'
            wallets=['App Santander','MODO'] if rail=='qr' and 'app santander o app modo' in legal else ['App Santander'] if rail=='qr' and 'app santander' in legal else ['MODO'] if rail=='qr' and 'modo' in legal else [None]
            if rail=='nfc':
                wallets=[name for name,pattern in [('Apple Pay',r'apple pay'),('Google Pay',r'google pay'),('MODO Contactless',r'modo contactless')] if re.search(pattern,legal)] or [None]
            if code=='A':
                evidence=legal+' '+fold(plain(d.get('additionalText')))
                wallets=['App YPF'] if re.search(r'app\s*ypf',evidence) else ['App Cabify'] if 'app cabify' in evidence else ['PedidosYa'] if re.search(r'pedidos\s*ya',evidence) else [None]
            accepted_wallets=re.search(r'incluidos\s+(?:tambien\s+)?los pagos\s+(?:los\s+)?realizados con\s+([^.;]+)',legal)
            if accepted_wallets and rail=='card':
                extra=[name for name,pattern in [('App Santander',r'\bapp santander\b'),('MODO',r'\bmodo\b'),('Google Pay',r'google pay'),('Apple Pay',r'apple pay')] if re.search(pattern,accepted_wallets[1])]
                # The source applies this explicit list to the complete cards[] combinations.
                # External merchant-app restrictions remain in raw_name/conditions, not a fictitious second rail.
                wallets=list(dict.fromkeys(wallets+extra))
            for wallet in wallets:
                app_context='App Cabify' if code=='A' and 'app cabify' in legal else None
                result.append(PaymentMethod(raw_name=' '.join(dict.fromkeys(filter(None,['Santander',network,card.get('descriptionType'),app_context,wallet,rail]))),issuer='Santander',network=network,card_type=typ,wallet=wallet,payment_rail=rail))
        return result
