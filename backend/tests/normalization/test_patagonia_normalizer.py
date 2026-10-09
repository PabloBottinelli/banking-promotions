from datetime import date

from normalization.sources.patagonia import PatagoniaNormalizer



# Compatibility accessors in tests keep assertions focused on the V2 schema:
# percentages live in benefits; monetary caps and minima live in limits.
def _percentage(p):
    return next((b.percentage for b in p.benefits if b.type in ("discount", "cashback")), None)


def _installments(p):
    return next((b.installment_options[-1] for b in p.benefits if b.type == "installments" and b.installment_options), None)


def _cap(p):
    return next((l for l in p.limits if l.type == "monetary_cap"), None)


def _cap_amount(p):
    c = _cap(p)
    return c.amount if c else None


def _cap_scope(p):
    c = _cap(p)
    return c.scope if c else None


def _cap_period(p):
    c = _cap(p)
    return c.period if c else None


def _minimum_purchase(p):
    return next((l.amount for l in p.limits if l.type == "minimum_purchase"), None)


def _segments(p):
    """Check what the normalizer actually exposes for segment-based offers."""
    for line in (p.specific_conditions or "").splitlines():
        if line.startswith(("Segmentos: ", "Segmentos/requisitos: ")):
            return [t.strip() for t in line.split(": ", 1)[1].split(", ")]
        if line.startswith("Segmento: "):
            return [line.split(": ", 1)[1].lower()]
    return []


def _requirements(p):
    for line in (p.specific_conditions or "").splitlines():
        if line.startswith("Requisitos: "):
            return [s.strip() for s in line.removeprefix("Requisitos: ").split("; ")]
    return []


def _rail(p, name):
    return any(name.lower() in line.lower().split(": ", 1)[-1].split(", ")
               for line in (p.specific_conditions or "").splitlines()
               if line.startswith(("Modalidades",)))

def build_regular_raw():
    return {
        "source": "patagonia",
        "source_id": "20250516_1355_CarrefourPlanSueldoCARGAESPECIAL",
        "scraped_at": "2026-10-06T15:00:00+00:00",
        "catalog": {
            "source_id": "carrefour4",
            "value": "Carrefour",
            "u": "https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/carrefour4.html",
            "c": [
                "Supermercados",
            ],
            "segment": None,
        },
        "detail": {
            "sku": "20250516_1355_CarrefourPlanSueldoCARGAESPECIAL",
            "title": "Carrefour",
            "url": "https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/carrefour4.html",
            "summary_text": """
Carrefour
TODOS LOS MIÉRCOLES
Del 01/04/2026 al 31/03/2027
Exclusivo por acreditar tu sueldo

CLASICA
20%
Tope: $15.000

PLUS
25%
Tope: $20.000

SINGULAR
35%
Tope: $25.000

Más Información
""",
            "description_text": """
Legales Patagonia Clásica Plan Sueldo
PROMOCIÓN VÁLIDA DESDE EL 01/04/2026 AL 31/03/2027.
RECIBIRÁN UN 20% DE DESCUENTO.
TOPE DE DEVOLUCIÓN $15.000 POR MES Y POR CUENTA.
PROMOCIÓN VÁLIDA EN WWW.CARREFOUR.COM.AR Y EN LOCALES.

Legales Patagonia Plus Plan Sueldo
PROMOCIÓN VÁLIDA DESDE EL 01/04/2026 AL 31/03/2027.
RECIBIRÁN UN 25% DE DESCUENTO.
TOPE DE DEVOLUCIÓN $20.000 POR MES Y POR CUENTA.

Legales Patagonia Singular Plan Sueldo
PROMOCIÓN VÁLIDA DESDE EL 01/04/2026 AL 31/03/2027.
RECIBIRÁN UN 35% DE DESCUENTO.
TOPE DE DEVOLUCIÓN $25.000 POR MES Y POR CUENTA.
""",
            "main_text": None,
            "image_alts": [
                "Visa Débito",
                "Visa",
                "Amex",
                "Google Pay",
                "Apple Pay",
                "Modo",
            ],
        },
    }


def build_on_raw():
    return {
        "source": "patagonia",
        "source_id": "2026_05_05_Vans_ON",
        "scraped_at": "2026-10-06T15:00:00+00:00",
        "catalog": {
            "source_id": "vans2",
            "value": "Vans",
            "u": "https://ahorrosybeneficios.bancopatagonia.com.ar/on/vans2.html",
            "c": [
                "Indumentaria y Deportes",
            ],
            "segment": "on",
        },
        "detail": {
            "sku": "2026_05_05_Vans_ON",
            "title": "Vans",
            "url": "https://ahorrosybeneficios.bancopatagonia.com.ar/on/vans2.html",
            "summary_text": """
Vans
TODOS LOS JUEVES
Del 07/05/2026 al 31/12/2026
PATAGONIA ON
15%
3 cuotas sin interés
Tope: $10.000
""",
            "description_text": """
Legales Patagonia ON.
PROMOCIÓN VÁLIDA DESDE EL 07/05/2026 AL 31/12/2026.
15% DE DESCUENTO.
TOPE DE DEVOLUCIÓN $10.000 POR MES Y POR CLIENTE.
VÁLIDA ABONANDO CON TARJETAS VISA DE CRÉDITO BANCO PATAGONIA.
PROMOCIÓN VÁLIDA EN LOCALES Y TIENDA ONLINE.
""",
            "main_text": None,
            "image_alts": [
                "Visa",
                "Modo",
            ],
        },
    }


def test_normalizes_regular_tier_variants():
    promotions = PatagoniaNormalizer().normalize_many(
        build_regular_raw()
    )

    assert len(promotions) == 3

    clasica = promotions[0]
    plus = promotions[1]
    singular = promotions[2]

    assert clasica.source == "patagonia"

    assert clasica.source_id == (
        "20250516_1355_CarrefourPlanSueldoCARGAESPECIAL:clasica"
    )

    assert plus.source_id == (
        "20250516_1355_CarrefourPlanSueldoCARGAESPECIAL:plus"
    )

    assert singular.source_id == (
        "20250516_1355_CarrefourPlanSueldoCARGAESPECIAL:singular"
    )

    assert clasica.title == "Carrefour"
    assert clasica.scope == "merchant"
    assert clasica.merchant == "Carrefour"
    assert clasica.category == "Supermercados"

    assert _percentage(clasica) == 20
    assert _percentage(plus) == 25
    assert _percentage(singular) == 35

    assert _cap_amount(clasica) == 15000
    assert _cap_amount(plus) == 20000
    assert _cap_amount(singular) == 25000

    assert _cap_scope(clasica) == "account"
    assert _cap_period(clasica) == "monthly"

    assert clasica.valid_from == date(
        2026,
        4,
        1,
    )

    assert clasica.valid_to == date(
        2027,
        3,
        31,
    )

    assert clasica.days_of_week == [
        "wednesday",
    ]

    assert _segments(clasica) == [
        "clasica",
        "salary",
    ]

    assert _segments(plus) == [
        "plus",
        "salary",
    ]

    assert _segments(singular) == [
        "singular",
        "salary",
    ]

    assert _requirements(clasica) == [
        "Exclusivo por acreditar tu sueldo",
    ]


def test_regular_promotion_detects_channels():
    promotion = PatagoniaNormalizer().normalize_many(
        build_regular_raw()
    )[0]

    assert promotion.online is True
    assert promotion.physical is True


def test_regular_promotion_detects_payment_methods():
    promotion = PatagoniaNormalizer().normalize_many(
        build_regular_raw()
    )[0]

    methods = {
        (
            method.raw_name,
            method.network,
            method.card_type,
        )
        for method in promotion.payment_methods
    }

    assert (
        "Visa Débito",
        "visa",
        "debit",
    ) in methods

    assert (
        "Visa Crédito",
        "visa",
        "credit",
    ) in methods

    assert (
        "American Express",
        "american_express",
        "credit",
    ) in methods

    assert (
        "MODO",
        None,
        None,
    ) in methods

    assert (
        "Google Pay",
        None,
        None,
    ) in methods

    assert (
        "Apple Pay",
        None,
        None,
    ) in methods


def test_normalizes_patagonia_on():
    promotions = PatagoniaNormalizer().normalize_many(
        build_on_raw()
    )

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.source == "patagonia"
    assert promotion.source_id == "2026_05_05_Vans_ON:on"

    assert promotion.title == "Vans"
    assert promotion.merchant == "Vans"

    assert promotion.category == "Indumentaria y Deportes"

    assert _percentage(promotion) == 15
    assert _installments(promotion) == 3

    assert _cap_amount(promotion) == 10000
    assert _cap_scope(promotion) == "customer"
    assert _cap_period(promotion) == "monthly"

    assert promotion.valid_from == date(
        2026,
        5,
        7,
    )

    assert promotion.valid_to == date(
        2026,
        12,
        31,
    )

    assert promotion.days_of_week == [
        "thursday",
    ]

    assert _segments(promotion) == [
        "on",
    ]

    assert promotion.online is True
    assert promotion.physical is True

    assert promotion.promotion_url == (
        "https://ahorrosybeneficios.bancopatagonia.com.ar/on/vans2.html"
    )


def test_on_segment_comes_from_catalog():
    raw = build_on_raw()

    raw["detail"]["summary_text"] = """
Vans
TODOS LOS JUEVES
Del 07/05/2026 al 31/12/2026
15%
3 cuotas sin interés
Tope: $10.000
"""

    promotion = PatagoniaNormalizer().normalize_many(
        raw
    )[0]

    assert _segments(promotion) == [
        "on",
    ]

    assert promotion.source_id.endswith(
        ":on"
    )


def test_normalizes_shared_installment_offer():
    raw = build_regular_raw()

    raw["source_id"] = "ski-1"

    raw["catalog"] = {
        "source_id": "cerro-chapelco",
        "value": "Cerro Chapelco",
        "u": "https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/cerro-chapelco.html",
        "c": [
            "Turismo",
        ],
        "segment": None,
    }

    raw["detail"]["title"] = "Cerro Chapelco"

    raw["detail"]["summary_text"] = """
Cerro Chapelco
Todos los días
Del 01/06/2026 al 30/09/2026
CLASICA PLUS SINGULAR
9 cuotas
sin interés
Sin tope
Más Información
"""

    raw["detail"]["description_text"] = """
Legales Patagonia Clásica Plus Singular.
PROMOCIÓN VÁLIDA DESDE EL 01/06/2026 AL 30/09/2026.
9 CUOTAS SIN INTERÉS.
SIN TOPE.
"""

    promotions = PatagoniaNormalizer().normalize_many(
        raw
    )

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.source_id == (
        "ski-1:clasica-plus-singular"
    )

    assert _percentage(promotion) is None
    assert _installments(promotion) == 9

    assert _cap_amount(promotion) is None
    assert _cap_scope(promotion) is None
    assert _cap_period(promotion) is None

    assert promotion.category == "Turismo"

    assert promotion.days_of_week == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

    assert _segments(promotion) == [
        "clasica",
        "plus",
        "singular",
    ]


def test_extracts_amounts():
    normalizer = PatagoniaNormalizer()

    assert normalizer._parse_amount(
        "15.000"
    ) == 15000

    assert normalizer._parse_amount(
        "15.000,50"
    ) == 15000.50

    assert normalizer._parse_amount(
        "10000"
    ) == 10000


def test_extracts_days():
    normalizer = PatagoniaNormalizer()

    assert normalizer._extract_days(
        "TODOS LOS JUEVES"
    ) == [
        "thursday",
    ]

    assert normalizer._extract_days(
        "De martes a viernes"
    ) == [
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
    ]

    assert normalizer._extract_days(
        "Todos los días"
    ) == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

def test_extracts_validity_with_full_dates():
    normalizer = PatagoniaNormalizer()

    valid_from, valid_to = normalizer._extract_validity(
        "Vigencia: 01/08/2026 al 31/12/2026",
        "2026-10-06T15:00:00+00:00",
    )

    assert valid_from == date(2026, 8, 1)
    assert valid_to == date(2026, 12, 31)


def test_extracts_validity_without_year():
    normalizer = PatagoniaNormalizer()

    valid_from, valid_to = normalizer._extract_validity(
        "DESDE 07/05 AL 31/12",
        "2026-10-06T15:00:00+00:00",
    )

    assert valid_from == date(2026, 5, 7)
    assert valid_to == date(2026, 12, 31)


def test_extracts_validity_without_year_crossing_year_boundary():
    normalizer = PatagoniaNormalizer()

    valid_from, valid_to = normalizer._extract_validity(
        "DESDE 30/07 AL 31/01",
        "2026-10-06T15:00:00+00:00",
    )

    assert valid_from == date(2026, 7, 30)
    assert valid_to == date(2027, 1, 31)

def test_normalizes_coto_nfc_single_day_shared_segments():
    raw = {
        "source": "patagonia",
        "source_id": "2026_07_29_Coto_NFC",
        "scraped_at": "2026-10-07T00:01:17.864803+00:00",
        "catalog": {
            "source_id": "coto-nfc",
            "value": "Coto NFC",
            "u": "https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/coto-nfc.html",
            "c": ["Supermercados"],
            "segment": None,
        },
        "detail": {
            "sku": "2026_07_29_Coto_NFC",
            "title": "Coto NFC",
            "summary_text": """
Coto NFC
JUEVES
08/10/2026
Exclusivo NFC
CLASICA
PLUS
SINGULAR
30
%
Sin tope
Cantidad
Comprar
""",
            "description_text": None,
            "main_text": """
Más Información
VIGENCIA DESDE
7 oct. 2026
VIGENCIA HASTA
7 oct. 2026
Dias
Jueves
Términos y Condiciones
Legales Patagonia Clásica, Plus y Singular
CARTERA DE CONSUMO Y COMERCIAL. LA PROMOCIÓN ESTARÁ VIGENTE EXCLUSIVAMENTE EN TODAS LAS SUCURSALES FÍSICAS DE COTO EL JUEVES, 08/10/2026 DE 2026.
RECIBIRA UN 30% DE DESCUENTO EN EL ACTO CON TARJETAS DE DEBITO DEL BANCO PATAGONIA ABONANDO CON GOOGLE PAY, APPLE PAY Y MODO CONTACTLESS EN LOS PAGOS SIN CONTACTO.
SIN TOPE.
NO VÁLIDO PARA VENTA ONLINE Y/O COTO DIGITAL.
LA PROMOCIÓN NO APLICA PARA PAGOS REALIZADOS MEDIANTE CÓDIGOS DE RESPUESTA RÁPIDA ("QR").
""",
            "image_alts": ["Visa Débito"],
            "url": "https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/coto-nfc.html",
        },
    }

    promotions = PatagoniaNormalizer().normalize_many(raw)

    assert len(promotions) == 1

    promotion = promotions[0]

    assert promotion.source_id == "2026_07_29_Coto_NFC:clasica-plus-singular"

    assert promotion.valid_from == date(2026, 10, 8)
    assert promotion.valid_to == date(2026, 10, 8)

    assert promotion.days_of_week == ["thursday"]

    assert _percentage(promotion) == 30

    assert _cap_amount(promotion) is None
    assert _cap_scope(promotion) is None
    assert _cap_period(promotion) is None

    assert _segments(promotion) == [
        "clasica",
        "plus",
        "singular",
    ]

    assert promotion.category == "Supermercados"

    assert promotion.online is False
    assert promotion.physical is True

    assert _rail(promotion, "qr") is False
    assert _rail(promotion, "nfc") is True
    assert _rail(promotion, "contactless") is True

    assert len(promotion.payment_methods) == 4

    methods = {
        method.raw_name
        for method in promotion.payment_methods
    }

    assert methods == {
        "Visa Débito",
        "Google Pay",
        "Apple Pay",
        "MODO",
    }