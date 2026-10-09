"""Integration-level assertions for the V2 promotion representation (offline)."""

from decimal import Decimal
from datetime import date, datetime, timezone

from normalization.models import Benefit, NormalizedPromotion
from normalization.sources.bbva import BBVANormalizer
from normalization.sources.galicia import GaliciaNormalizer
from normalization.sources.patagonia import PatagoniaNormalizer
from tests.normalization.test_bbva_normalizer import build_raw_promotion
from tests.normalization.test_patagonia_normalizer import build_regular_raw


def test_bbva_separates_cashback_installments_limits_and_qr():
    promo = BBVANormalizer().normalize(build_raw_promotion())
    assert [(b.type, b.percentage, b.installment_options) for b in promo.benefits] == [
        ("cashback", Decimal("20"), []),
        ("installments", None, [6]),
    ]
    assert promo.benefits[1].interest_free is True
    assert [(x.type, x.amount, x.currency, x.period) for x in promo.limits] == [
        ("monetary_cap", Decimal("40000"), "ARS", "monthly")
    ]
    assert promo.payment_methods[0].issuer == "BBVA"
    assert promo.payment_methods[0].payment_rail == "qr"
    assert "QR" in (promo.specific_conditions or "")


def test_galicia_preserves_financing_range_and_restrictions():
    raw = {
        "source": "galicia", "source_id": 99, "scraped_at": "2026-10-01T00:00:00Z",
        "catalog": {"titulo": "Comercio", "tipoPromocion": "Marca", "subtitulo": "Indumentaria"},
        "detail": {
            "fechaDesde": "01/10/2026", "fechaHasta": "31/10/2026",
            "marca": {"nombre": "Comercio", "categoria": {"descripcion": "Indumentaria"}},
            "porcentajeAhorro": 20, "cuotaSinInteresDesde": 2, "cuotaSinInteresHasta": 6,
            "tipoTope": "Cliente", "topeReintegro": 10000, "periodicidad": "Mensual",
            "minimoCompra": 5000, "diasAplicacion": "Lu;Ma;Mi;Ju;Vi;Sa;Do",
            "mediosDePago": [{"tarjeta": "Visa", "tipoTarjeta": "Credito"}],
            "tiendaOnline": True, "tiendaFisica": False,
            "modeloAtencion": {"nombre": "Eminent"}, "haberes": True,
            "pagoQR": True, "legales": "Solo para comercios adheridos.",
        },
    }
    promo = GaliciaNormalizer().normalize(raw)
    assert promo.applies_every_day is True
    assert promo.promotion_group_id is None
    assert promo.benefits[0].percentage == Decimal("20")
    assert promo.benefits[1].type == "installments"
    assert promo.benefits[1].interest_free is True
    assert "De 2 a 6 cuotas" in (promo.specific_conditions or "")
    assert "eminent" in (promo.specific_conditions or "")
    assert len(promo.limits) == 2
    assert promo.limits[0].type == "monetary_cap"
    assert promo.limits[1].type == "minimum_purchase"
    assert promo.limits[1].amount == Decimal("5000")
    assert promo.payment_methods[0].issuer == "Banco Galicia"
    assert promo.requires_merchant_verification is True


def test_patagonia_has_stable_group_ids_and_per_variant_limits():
    promos = PatagoniaNormalizer().normalize_many(build_regular_raw())
    assert len(promos) == 3
    assert len({p.source_id for p in promos}) == 3
    assert {p.promotion_group_id for p in promos} == {"20250516_1355_CarrefourPlanSueldoCARGAESPECIAL"}
    assert [p.benefits[0].percentage for p in promos] == [Decimal(20), Decimal(25), Decimal(35)]
    assert [p.limits[0].amount for p in promos] == [Decimal(15000), Decimal(20000), Decimal(25000)]
    assert all("salary" in (p.specific_conditions or "") for p in promos)


def test_v2_allows_unknown_validity_without_inventing_dates():
    promo = NormalizedPromotion(
        source="example", source_id="unknown-dates", scraped_at=datetime.now(timezone.utc),
        title="Servicio sin vencimiento publicado", scope="other",
        valid_from=None, valid_to=None,
        benefits=[Benefit(type="free_service", description="Servicio sin cargo")],
    )
    assert promo.valid_from is None
    assert promo.valid_to is None
    assert promo.applies_every_day is None
    assert promo.days_of_week == []


def test_bbva_fixed_value_coupon_preserves_amount_and_minimum_purchase():
    raw = build_raw_promotion()
    raw["catalog"]["cabecera"] = "Cupón del partido"
    raw["catalog"]["subcabecera"] = "Cupón especial"
    raw["catalog"]["montoTope"] = None
    raw["detail"]["cabecera"] = "Cupón del partido"
    raw["detail"]["beneficios"] = [{
        "cuota": 0, "tope": None,
        "requisitos": ["Usá el cupón del partido por $7.500 de descuento. Compra mínima: $15.000."],
    }]
    promo = BBVANormalizer().normalize(raw)
    assert len(promo.benefits) == 1
    assert promo.benefits[0].type == "discount"
    assert promo.benefits[0].percentage is None
    assert promo.benefits[0].amount == Decimal("7500")
    assert promo.benefits[0].currency == "ARS"
    assert len(promo.limits) == 1
    assert promo.limits[0].type == "minimum_purchase"
    assert promo.limits[0].amount == Decimal("15000")
