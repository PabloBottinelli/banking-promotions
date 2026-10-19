"""Additional official cases discovered while comparing post-QA3 output."""
import json
from pathlib import Path

import pytest

from normalization.sources.bbva import BBVANormalizer
from scraping.sources.bbva.scraper import BBVAScraper


@pytest.fixture
def additional():
    path = Path(__file__).parents[1] / 'fixtures/bbva/official_post_qa3_additional.json'
    return {str(r['source_id']): r for r in json.loads(path.read_text(encoding='utf8'))}


@pytest.mark.parametrize('source_id', ['88313', '88282', '88050'])
def test_additional_official_same_cap_conflicts_require_review(additional, source_id):
    raw = additional[source_id]
    p = BBVANormalizer().normalize(raw)
    cap = next(l for l in p.limits if l.type == 'monetary_cap')
    assert cap.period is None
    assert 'Fuente inconsistente' in p.specific_conditions
    assert BBVAScraper._commercial_review([raw])


def test_additional_official_missing_frequency_is_supplied_by_matching_legal_cap(additional):
    p = BBVANormalizer().normalize(additional['85530'])
    cap = next(l for l in p.limits if l.type == 'monetary_cap')
    assert cap.amount == 20000 and cap.period == 'monthly'
    assert not BBVAScraper._commercial_review([additional['85530']])


def test_additional_official_credit_network_alternatives_are_both_preserved(additional):
    p = BBVANormalizer().normalize(additional['84535'])
    assert {(m.network, m.card_type, m.issuer) for m in p.payment_methods} == {
        ('visa', 'credit', 'BBVA'), ('mastercard', 'credit', 'BBVA')}


def test_additional_official_installments_conflict_with_single_payment_blocks(additional):
    raw = additional['86275']
    assert raw['detail']['beneficios'][0]['cuota'] == 3
    assert 'EN un pago' in raw['detail']['basesCondiciones']
    with pytest.raises(ValueError, match='conflicting payment eligibility'):
        BBVANormalizer().normalize_many(raw)
    assert BBVAScraper._commercial_review([raw])
