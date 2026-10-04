from normalization.sources.galicia import GaliciaNormalizer


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

    assert promotion.discount_percentage == 20
    assert promotion.installments == 3

    assert promotion.days_of_week == ["friday"]

    assert promotion.cap_amount is None
    assert promotion.cap_scope is None
    assert promotion.cap_period is None

    assert promotion.payment_methods[0].raw_name == "Tarjeta Visa"
    assert promotion.payment_methods[0].network == "visa"
    assert promotion.payment_methods[0].card_type == "credit"

    assert promotion.customer_segments == []
    assert promotion.eligibility_requirements == []


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

    assert promotion.discount_percentage == 20
    assert promotion.installments is None

    assert promotion.cap_amount == 15000
    assert promotion.cap_scope == "customer"
    assert promotion.cap_period == "monthly"


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

    assert promotion.discount_percentage == 10
    assert promotion.installments is None

    assert promotion.days_of_week == ["saturday"]

    assert promotion.cap_amount == 10000
    assert promotion.cap_scope == "customer"
    assert promotion.cap_period == "one_time"

    assert promotion.qr is True
    assert promotion.nfc is True
    assert promotion.contactless is False

    assert promotion.customer_segments == []


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

    assert promotion.customer_segments == ["salary"]


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