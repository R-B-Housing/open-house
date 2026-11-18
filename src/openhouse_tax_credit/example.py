"""Invented 80-unit, bond-financed (4%) new construction. Not a reviewed deal or quote."""
from .deal import TaxCreditDeal, CostLine

LINES = (('hard', 'Construction (hard costs)'), ('soft', 'Architecture, engineering and other soft costs'),
         ('construction_finance', 'Construction interest and fees'), ('permanent_finance', 'Permanent loan and bond issuance costs'),
         ('developer_fee', 'Developer fee'), ('reserves', 'Operating and replacement reserves'))


def example_deal():
    return TaxCreditDeal('lihtc', 'Synthetic LIHTC project', 'Testville, WA', tuple(CostLine(k, label) for k, label in LINES))


def example_inputs():
    return dict(
        land_cost='2400000',
        cost={'hard': '24000000', 'soft': '3200000', 'construction_finance': '1400000',
              'permanent_finance': '500000', 'developer_fee': '3200000', 'reserves': '600000'},
        basis_fraction={'hard': 1, 'soft': '0.95', 'construction_finance': '0.70',
                        'permanent_finance': 0, 'developer_fee': 1, 'reserves': 0},
        basis_reductions=0, high_cost_boost='0.30',
        total_units=80, lihtc_units=80, total_sqft='64000', lihtc_sqft='64000',
        credit_rate='0.04', annual_credit_cap=0, investor_share='0.9999', credit_price='0.88',
        permanent_loan='12000000', soft_sources='7850000', deferred_developer_fee='1200000',
        bond_financed=1, tax_exempt_bonds='18000000', bond_test_threshold='0.25')
