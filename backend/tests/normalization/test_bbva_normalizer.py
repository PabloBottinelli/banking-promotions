from datetime import date

import pytest

from normalization.sources.bbva import BBVANormalizer


def build_raw_promotion(**overrides):
    raw = {
        "source": "bbva",
        "source_id": "85275",
        "scraped_at": "2026-10-05T20:00:00+00:00",
        "catalog": {
            "id": "85275",
            "cabecera": "Equus 20% y 6 cuotas",
            "subcabecera": "20% de reintegro y hasta 6 cuotas sin interés",
            "fechaDesde": "2026-05-28",
            "fechaHasta": "2026-05-28",
            "diasPromo": "0,0,0,1,0,0,0",
            "montoTope": "40000",
            "grupoTarjeta": "Tarjetas de crédito BBVA",
        },
        "detail": {
            "id": "85275",
            "cabecera": "Equus 20% y 6 cuotas",
            "beneficios": [
                {
                    "cuota": 6,
                    "tope": "40000",
                    "tipoTope": "Cliente",
                    "frecuenciaTope": "Mensual",
                    "requisitos": [
                        "Con tus tarjetas de crédito BBVA a través de app BBVA, leyendo un QR Modo."
                    ],
                }
            ],
            "canalesVenta": {
                "sucursales": [
                    {
                        "direccion": "Av. Santa Fe 1234",
                        "localidad": "Capital Federal",
                    }
                ],
                "web": [
                    {
                        "name": "Equus",
                        "url": "https://www.equus.com.ar",
                    }
                ],
            },
            "basesCondiciones": "Promoción válida para clientes BBVA.",
            "diasPromo": "0,0,0,1,0,0,0",
            "grupoTarjeta": "Tarjetas de crédito BBVA",
        },
    }

    raw.update(overrides)

    return raw


def test_normalizes_bbva_promotion():
    raw = build_raw_promotion()

    promotion = BBVANormalizer().normalize(raw)

    assert promotion.source == "bbva"
    assert promotion.source_id == "85275"

    assert promotion.title == "Equus 20% y 6 cuotas"
    assert promotion.scope == "merchant"
    assert promotion.merchant == "Equus 20% y 6 cuotas"
    assert promotion.category is None

    assert promotion.promotion_url == "https://www.bbva.com.ar/beneficios/"

    assert promotion.discount_percentage == 20
    assert promotion.installments == 6

    assert promotion.valid_from == date(2026, 5, 28)
    assert promotion.valid_to == date(2026, 5, 28)

    assert promotion.days_of_week == ["thursday"]

    assert promotion.cap_amount == 40000
    assert promotion.cap_scope == "customer"
    assert promotion.cap_period == "monthly"

    assert promotion.minimum_purchase is None

    assert len(promotion.payment_methods) == 1
    assert promotion.payment_methods[0].raw_name == "Tarjetas de crédito BBVA"
    assert promotion.payment_methods[0].network is None
    assert promotion.payment_methods[0].card_type == "credit"

    assert promotion.online is True
    assert promotion.physical is True

    assert promotion.qr is True
    assert promotion.nfc is False
    assert promotion.contactless is False

    assert promotion.customer_segments == []

    assert promotion.eligibility_requirements == [
        "Con tus tarjetas de crédito BBVA a través de app BBVA, leyendo un QR Modo."
    ]

    assert promotion.terms == "Promoción válida para clientes BBVA."


def test_normalizes_installments():
    normalizer = BBVANormalizer()

    assert normalizer._normalize_installments(3) == 3
    assert normalizer._normalize_installments("6") == 6

    assert normalizer._normalize_installments(None) is None
    assert normalizer._normalize_installments("") is None
    assert normalizer._normalize_installments(0) is None
    assert normalizer._normalize_installments("0") is None
    assert normalizer._normalize_installments(1) is None
    assert normalizer._normalize_installments("invalid") is None


def test_normalizes_days():
    normalizer = BBVANormalizer()

    days = normalizer._normalize_days("1,0,1,0,0,1,0")

    assert days == [
        "monday",
        "wednesday",
        "saturday",
    ]


def test_normalizes_all_days():
    normalizer = BBVANormalizer()

    days = normalizer._normalize_days("1,1,1,1,1,1,1")

    assert days == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]


def test_returns_empty_days_for_invalid_value():
    normalizer = BBVANormalizer()

    assert normalizer._normalize_days(None) == []
    assert normalizer._normalize_days("") == []
    assert normalizer._normalize_days("1,0,1") == []


def test_extracts_discount_from_title():
    normalizer = BBVANormalizer()

    discount = normalizer._extract_discount(
        "Equus 20% y 6 cuotas",
        "",
        [],
        None,
    )

    assert discount == 20


def test_extracts_discount_from_subtitle():
    normalizer = BBVANormalizer()

    discount = normalizer._extract_discount(
        "Equus",
        "20% de reintegro",
        [],
        None,
    )

    assert discount == 20


def test_extracts_discount_from_requirements():
    normalizer = BBVANormalizer()

    discount = normalizer._extract_discount(
        "Beneficio especial",
        "",
        ["Obtené un 30% de reintegro"],
        None,
    )

    assert discount == 30


def test_extracts_decimal_discount():
    normalizer = BBVANormalizer()

    discount = normalizer._extract_discount(
        "12,5% de descuento",
        "",
        [],
        None,
    )

    assert discount == 12.5


def test_returns_none_when_discount_is_missing():
    normalizer = BBVANormalizer()

    discount = normalizer._extract_discount(
        "Beneficio especial",
        "",
        [],
        None,
    )

    assert discount is None


def test_normalizes_amount():
    normalizer = BBVANormalizer()

    assert normalizer._normalize_amount(40000) == 40000
    assert normalizer._normalize_amount("40000") == 40000
    assert normalizer._normalize_amount("$40.000,50") == 40000.50

    assert normalizer._normalize_amount(None) is None
    assert normalizer._normalize_amount("") is None
    assert normalizer._normalize_amount(0) is None
    assert normalizer._normalize_amount("invalid") is None


def test_normalizes_cap_scope():
    normalizer = BBVANormalizer()

    assert normalizer._normalize_cap_scope("Cliente") == "customer"
    assert normalizer._normalize_cap_scope("Persona") == "customer"
    assert normalizer._normalize_cap_scope("Por compra") == "purchase"
    assert normalizer._normalize_cap_scope("Sin tope") is None
    assert normalizer._normalize_cap_scope(None) is None


def test_normalizes_unknown_cap_scope():
    normalizer = BBVANormalizer()

    assert normalizer._normalize_cap_scope("Usuario") == "usuario"


def test_normalizes_cap_period():
    normalizer = BBVANormalizer()

    assert normalizer._normalize_cap_period("Mensual") == "monthly"
    assert normalizer._normalize_cap_period("Mes") == "monthly"
    assert normalizer._normalize_cap_period("Semanal") == "weekly"
    assert normalizer._normalize_cap_period("Semana") == "weekly"
    assert normalizer._normalize_cap_period("Diario") == "daily"
    assert normalizer._normalize_cap_period("Día") == "daily"
    assert normalizer._normalize_cap_period("Único") == "one_time"
    assert normalizer._normalize_cap_period(None) is None


def test_normalizes_requirements():
    normalizer = BBVANormalizer()

    requirements = normalizer._normalize_requirements(
        [
            "Pago con tarjeta",
            "  Solo clientes BBVA  ",
            "",
            None,
            "Pago\ncon QR",
        ]
    )

    assert requirements == [
        "Pago con tarjeta",
        "Solo clientes BBVA",
        "Pago con QR",
    ]


def test_normalizes_credit_visa():
    normalizer = BBVANormalizer()

    methods = normalizer._normalize_payment_methods(
        "Tarjetas de crédito Visa BBVA"
    )

    assert len(methods) == 1
    assert methods[0].raw_name == "Tarjetas de crédito Visa BBVA"
    assert methods[0].network == "visa"
    assert methods[0].card_type == "credit"


def test_normalizes_debit_mastercard():
    normalizer = BBVANormalizer()

    methods = normalizer._normalize_payment_methods(
        "Tarjetas de débito Mastercard"
    )

    assert len(methods) == 1
    assert methods[0].network == "mastercard"
    assert methods[0].card_type == "debit"


def test_normalizes_american_express():
    normalizer = BBVANormalizer()

    methods = normalizer._normalize_payment_methods(
        "American Express crédito"
    )

    assert len(methods) == 1
    assert methods[0].network == "american_express"
    assert methods[0].card_type == "credit"


def test_returns_no_payment_methods_when_card_group_is_missing():
    normalizer = BBVANormalizer()

    assert normalizer._normalize_payment_methods(None) == []
    assert normalizer._normalize_payment_methods("") == []


def test_detects_online_and_physical_channels():
    normalizer = BBVANormalizer()

    channels = {
        "web": [
            {
                "name": "Comercio",
                "url": "https://example.com",
            }
        ],
        "sucursales": [
            {
                "direccion": "Av. Test 123",
            }
        ],
    }

    assert normalizer._has_online_channels(channels) is True
    assert normalizer._has_physical_channels(channels) is True


def test_detects_missing_channels():
    normalizer = BBVANormalizer()

    channels = {
        "web": [],
        "sucursales": [],
    }

    assert normalizer._has_online_channels(channels) is False
    assert normalizer._has_physical_channels(channels) is False


def test_detects_qr_requirement():
    normalizer = BBVANormalizer()

    requirements = [
        "Pagando desde app BBVA leyendo un QR Modo."
    ]

    assert normalizer._contains_requirement(requirements, "qr") is True
    assert normalizer._contains_requirement(requirements, "nfc") is False


def test_detects_nfc_requirement():
    normalizer = BBVANormalizer()

    requirements = [
        "Pagá acercando tu celular mediante NFC."
    ]

    assert normalizer._contains_requirement(requirements, "nfc") is True
    assert normalizer._contains_requirement(requirements, "qr") is False


def test_detects_contactless_requirement():
    normalizer = BBVANormalizer()

    requirements = [
        "Promoción válida para pagos contactless."
    ]

    assert normalizer._contains_requirement(requirements, "contactless") is True


def test_normalizes_black_customer_segment():
    raw = build_raw_promotion()

    raw["detail"]["basesCondiciones"] = (
        "Promoción exclusiva para clientes BBVA Black."
    )

    promotion = BBVANormalizer().normalize(raw)

    assert promotion.customer_segments == ["black"]


def test_does_not_add_black_segment_for_regular_customer():
    raw = build_raw_promotion()

    raw["detail"]["basesCondiciones"] = (
        "Promoción válida para clientes BBVA."
    )

    promotion = BBVANormalizer().normalize(raw)

    assert promotion.customer_segments == []


def test_cleans_html_and_whitespace():
    normalizer = BBVANormalizer()

    text = normalizer._clean_text(
        "Pagá&nbsp;con BBVA\n  y obtené 20% &amp; cuotas"
    )

    assert text == "Pagá con BBVA y obtené 20% & cuotas"


def test_parses_supported_date_formats():
    normalizer = BBVANormalizer()

    assert normalizer._parse_date("2026-10-05") == date(2026, 10, 5)
    assert normalizer._parse_date("05/10/2026") == date(2026, 10, 5)
    assert normalizer._parse_date("2026-10-05T12:30:00") == date(2026, 10, 5)


def test_raises_for_unknown_date_format():
    normalizer = BBVANormalizer()

    with pytest.raises(ValueError, match="Formato de fecha BBVA desconocido"):
        normalizer._parse_date("October 5, 2026")