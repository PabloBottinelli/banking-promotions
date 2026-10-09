from normalization.sources.galicia import GaliciaNormalizer



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

def test_normalizes_merchant_promotion():
    raw = {
        "source": "galicia",
        "source_id": 170826,
        "scraped_at": "2026-10-03T00:09:28.551487+00:00",
        "catalog": {
            "titulo": "Viamo",
            "subtitulo": "Indumentaria",
            "tipoPromocion": "Marca",
        },
        "detail": {
            "cuotaSinInteresDesde": 2,
            "cuotaSinInteresHasta": 3,
            "diasAplicacion": "Vi",
            "fechaDesde": "03/07/2026",
            "fechaHasta": "31/12/2026",
            "marca": {
                "nombre": "Viamo",
                "categoria": {
                    "descripcion": "Indumentaria",
                },
                "urlTiendaOnline": None,
            },
            "porcentajeAhorro": 20,
            "tipoTope": "Sin tope",
            "periodicidad": None,
            "topeReintegro": 0,
            "mediosDePago": [
                {
                    "tarjeta": "Tarjeta Visa",
                    "tipoTarjeta": "Credito",
                }
            ],
            "modeloAtencion": {
                "nombre": "Masivo",
                "exclusivo": False,
            },
            "tiendaOnline": True,
            "tiendaFisica": True,
            "haberes": False,
            "minimoCompra": None,
            "legales": "Condiciones...",
        },
    }

    promotion = GaliciaNormalizer().normalize(raw)

    assert promotion.source == "galicia"
    assert promotion.source_id == "170826"

    assert promotion.title == "Viamo"
    assert promotion.scope == "merchant"
    assert promotion.merchant == "Viamo"
    assert promotion.category == "Indumentaria"
    assert promotion.promotion_url == (
        "https://www.galicia.ar/personas/buscador-de-promociones"
        "?path=%2Fpromocion%2F170826%7CViamo%7CMarca"
    )

    assert _percentage(promotion) == 20
    assert _installments(promotion) == 3

    assert promotion.days_of_week == ["friday"]

    assert _cap_amount(promotion) is None
    assert _cap_scope(promotion) is None
    assert _cap_period(promotion) is None

    assert promotion.payment_methods[0].raw_name == "Tarjeta Visa"
    assert promotion.payment_methods[0].network == "visa"
    assert promotion.payment_methods[0].card_type == "credit"

    assert _segments(promotion) == []
    assert _requirements(promotion) == []


def test_normalizes_cap():
    raw = {
        "source": "galicia",
        "source_id": 1,
        "scraped_at": "2026-10-03T00:00:00+00:00",
        "catalog": {
            "titulo": "Comercio",
            "subtitulo": "Gastronomía",
            "tipoPromocion": "Marca",
        },
        "detail": {
            "cuotaSinInteresHasta": None,
            "diasAplicacion": "Ju",
            "fechaDesde": "01/10/2026",
            "fechaHasta": "31/10/2026",
            "marca": {
                "nombre": "Comercio",
                "categoria": {
                    "descripcion": "Gastronomía",
                },
                "urlTiendaOnline": None,
            },
            "porcentajeAhorro": 20,
            "tipoTope": "Cliente",
            "periodicidad": "Mensual",
            "topeReintegro": 15000,
            "mediosDePago": [],
            "modeloAtencion": {
                "nombre": "Masivo",
                "exclusivo": False,
            },
            "tiendaOnline": False,
            "tiendaFisica": True,
            "haberes": False,
            "minimoCompra": None,
            "legales": None,
        },
    }

    promotion = GaliciaNormalizer().normalize(raw)

    assert _percentage(promotion) == 20
    assert _installments(promotion) is None

    assert _cap_amount(promotion) == 15000
    assert _cap_scope(promotion) == "customer"
    assert _cap_period(promotion) == "monthly"


def test_normalizes_category_promotion_without_merchant():
    raw = {
        "source": "galicia",
        "source_id": 181389,
        "scraped_at": "2026-10-03T00:10:09.165026+00:00",
        "catalog": {
            "titulo": "Combustible",
            "subtitulo": "Combustible",
            "tipoPromocion": "Categoria",
            "pagoQR": True,
            "pagoNFC": True,
            "contactLess": False,
        },
        "detail": {
            "cuotaSinInteresHasta": None,
            "diasAplicacion": "Sa",
            "fechaDesde": "10/10/2026",
            "fechaHasta": "10/10/2026",
            "marca": None,
            "categoria": {
                "descripcion": "Combustible",
            },
            "porcentajeAhorro": 10,
            "tipoTope": "Cliente",
            "periodicidad": "Unico",
            "topeReintegro": 10000,
            "mediosDePago": [
                {
                    "tarjeta": "Tarjeta Mastercard",
                    "tipoTarjeta": "Credito",
                }
            ],
            "modeloAtencion": {
                "nombre": "Masivo",
                "exclusivo": False,
            },
            "tiendaOnline": False,
            "tiendaFisica": False,
            "haberes": False,
            "minimoCompra": None,
            "legales": "Condiciones...",
        },
    }

    promotion = GaliciaNormalizer().normalize(raw)

    assert promotion.scope == "category"
    assert promotion.merchant is None
    assert promotion.category == "Combustible"
    assert promotion.promotion_url == (
        "https://www.galicia.ar/personas/buscador-de-promociones"
        "?path=%2Fpromocion%2F181389%7CCombustible%7CCategoria"
    )

    assert _percentage(promotion) == 10
    assert _installments(promotion) is None

    assert promotion.days_of_week == ["saturday"]

    assert _cap_amount(promotion) == 10000
    assert _cap_scope(promotion) == "customer"
    assert _cap_period(promotion) == "one_time"

    assert _rail(promotion, "qr") is True
    assert _rail(promotion, "nfc") is True
    assert _rail(promotion, "contactless") is False

    assert _segments(promotion) == []


def test_normalizes_salary_customer():
    raw = {
        "source": "galicia",
        "source_id": 2,
        "scraped_at": "2026-10-03T00:00:00+00:00",
        "catalog": {
            "titulo": "Combustible",
            "subtitulo": "Combustible",
            "tipoPromocion": "Categoria",
        },
        "detail": {
            "cuotaSinInteresHasta": None,
            "diasAplicacion": "Sa",
            "fechaDesde": "10/10/2026",
            "fechaHasta": "10/10/2026",
            "marca": None,
            "categoria": {
                "descripcion": "Combustible",
            },
            "porcentajeAhorro": 20,
            "tipoTope": "Cliente",
            "periodicidad": "Unico",
            "topeReintegro": 15000,
            "mediosDePago": [],
            "modeloAtencion": {
                "nombre": "Masivo",
                "exclusivo": False,
            },
            "tiendaOnline": False,
            "tiendaFisica": False,
            "haberes": True,
            "minimoCompra": None,
            "legales": None,
        },
    }

    promotion = GaliciaNormalizer().normalize(raw)

    assert _segments(promotion) == ["salary"]


def test_normalizes_eminent_customer():
    detail = {
        "modeloAtencion": {
            "nombre": "Eminent",
            "exclusivo": True,
        },
        "haberes": False,
    }

    segments = GaliciaNormalizer()._normalize_customer_segments(detail)

    assert segments == ["eminent"]


def test_normalizes_eminent_black_customer():
    detail = {
        "modeloAtencion": {
            "nombre": "Eminent Black",
            "exclusivo": False,
        },
        "haberes": False,
    }

    segments = GaliciaNormalizer()._normalize_customer_segments(detail)

    assert segments == ["eminent_black"]


def test_ignores_cross_customer_segment():
    detail = {
        "modeloAtencion": {
            "nombre": "Cross",
            "exclusivo": False,
        },
        "haberes": False,
    }

    segments = GaliciaNormalizer()._normalize_customer_segments(detail)

    assert segments == []


def test_salary_customer_can_have_another_segment():
    detail = {
        "modeloAtencion": {
            "nombre": "Eminent",
            "exclusivo": True,
        },
        "haberes": True,
    }

    segments = GaliciaNormalizer()._normalize_customer_segments(detail)

    assert segments == ["salary", "eminent"]


def test_normalizes_purchase_cap():
    detail = {
        "tipoTope": "Compra",
        "periodicidad": "Unico",
        "topeReintegro": 5000,
    }

    amount, scope, period = GaliciaNormalizer()._normalize_cap(detail)

    assert amount == 5000
    assert scope == "purchase"
    assert period == "one_time"


def test_normalizes_weekly_cap():
    detail = {
        "tipoTope": "Cliente",
        "periodicidad": "Semanal",
        "topeReintegro": 10000,
    }

    amount, scope, period = GaliciaNormalizer()._normalize_cap(detail)

    assert amount == 10000
    assert scope == "customer"
    assert period == "weekly"


def test_normalizes_shopping_scope():
    normalizer = GaliciaNormalizer()

    assert normalizer._normalize_scope("Shopping") == "shopping"


def test_builds_encoded_promotion_url():
    normalizer = GaliciaNormalizer()

    url = normalizer._build_promotion_url(123456, "Masse Cariló", "Marca")

    assert url == (
        "https://www.galicia.ar/personas/buscador-de-promociones"
        "?path=%2Fpromocion%2F123456%7CMasse+Caril%C3%B3%7CMarca"
    )


def test_returns_none_when_promotion_url_cannot_be_built():
    normalizer = GaliciaNormalizer()

    assert normalizer._build_promotion_url(123456, None, "Marca") is None
    assert normalizer._build_promotion_url(123456, "Viamo", None) is None