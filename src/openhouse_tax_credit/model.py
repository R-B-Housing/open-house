"""Federal low-income housing tax credit (LIHTC) sizing and sources and uses.

One building or project, sized on its placed-in-service basis:

- Eligible basis is each cost line times the share of it that is depreciable
  and eligible (land, reserves and permanent-loan costs are usually not), less
  federal grants and other basis reductions.
- Qualified basis is eligible basis, raised by the high-cost (DDA or QCT) boost
  of up to 30%, times the applicable fraction: the lower of the low-income share
  of units and of floor area.
- Annual credits are qualified basis times the credit rate: 4% for a
  bond-financed deal, whose credits come with the bonds, or 9% for a
  competitive award, capped by the credits the agency allocated. The credit
  period is ten years.
- Tax credit equity is the ten years of credits times the investor's share
  times the price paid per dollar of credit.
- The funding gap is total development cost less tax credit equity, the
  permanent loan, soft sources and deferred developer fee.

A bond-financed (4%) deal must finance a minimum share of the aggregate basis
of land and building with tax-exempt bonds; this model approximates aggregate
basis as land plus eligible basis before reductions.

It does not model the credit delivery schedule, equity pay-ins, construction
financing, operations or the partnership's returns.
"""
from openhouse_engine import Model, DecimalPolicy, Dimension, Item, ref, if_, min_, max_, round_to, sum_over
from .deal import TaxCreditDeal

MODEL_ID = 'lihtc-sources-uses'
MODEL_VERSION = '0.1.0'
CREDIT_PERIOD_YEARS = 10
TOLERANCE = '0.000001'


def build_model(deal: TaxCreditDeal):
    m = Model(MODEL_ID, MODEL_VERSION, DecimalPolicy(34, 'ROUND_HALF_UP'))
    m.dimension(Dimension('cost_line', [Item(line.key, label=line.label) for line in deal.cost_lines]))
    line = ('cost_line',)

    def inp(name, unit='usd', dims=(), lo=0, hi=None):
        m.input(name, unit=unit, dims=dims, minimum=lo, maximum=hi)

    def calc(name, expr, unit='usd', dims=()):
        m.calc(name, unit=unit, dims=dims, expr=expr)
        return ref(name)

    def whole(name):
        m.check(name + '.whole', condition=ref(name) == round_to(ref(name), 0), code='NOT_WHOLE', message=name + ' must be whole.')

    # Uses and basis
    inp('land_cost')
    inp('cost', dims=line)
    inp('basis_fraction', 'rate', line, 0, 1)
    inp('basis_reductions')
    inp('high_cost_boost', 'rate', (), 0, '0.30')
    # Applicable fraction
    for name in ('total_units', 'lihtc_units'):
        inp(name, 'units')
        whole(name)
    for name in ('total_sqft', 'lihtc_sqft'):
        inp(name, 'sqft')
    m.check('total_units.positive', condition=ref('total_units') >= 1, code='NO_UNITS', message='total_units must be at least 1.')
    m.check('total_sqft.positive', condition=ref('total_sqft') > 0, code='NO_AREA', message='total_sqft must be positive.')
    m.check('lihtc_units.within_total', condition=ref('lihtc_units') <= ref('total_units'), code='UNIT_INVENTORY', message='lihtc_units exceed total_units.')
    m.check('lihtc_sqft.within_total', condition=ref('lihtc_sqft') <= ref('total_sqft'), code='AREA_INVENTORY', message='lihtc_sqft exceeds total_sqft.')
    # Credits and pricing
    inp('credit_rate', 'rate', (), 0, '0.10')
    inp('annual_credit_cap', 'usd/year')
    inp('investor_share', 'rate', (), 0, 1)
    inp('credit_price', 'usd/credit', (), 0, '1.5')
    # Other sources
    for name in ('permanent_loan', 'soft_sources', 'deferred_developer_fee', 'tax_exempt_bonds'):
        inp(name)
    inp('bond_financed', 'flag', (), 0, 1)
    whole('bond_financed')
    inp('bond_test_threshold', 'rate', (), 0, 1)

    # Uses
    lines = calc('basis.line_eligible', ref('cost') * ref('basis_fraction'), dims=line)
    tdc = calc('total_development_cost', ref('land_cost') + sum_over('cost_line', ref('cost')))
    calc('cost_per_unit', tdc / ref('total_units'), 'usd/unit')
    # Basis
    before = calc('basis.eligible_before_reductions', sum_over('cost_line', lines))
    eligible = calc('basis.eligible', max_(before - ref('basis_reductions'), 0))
    unit_fraction = calc('basis.unit_fraction', ref('lihtc_units') / ref('total_units'), 'rate')
    area_fraction = calc('basis.floor_area_fraction', ref('lihtc_sqft') / ref('total_sqft'), 'rate')
    applicable = calc('basis.applicable_fraction', min_(unit_fraction, area_fraction), 'rate')
    qualified = calc('basis.qualified', eligible * (1 + ref('high_cost_boost')) * applicable)
    # Credits and equity
    by_basis = calc('credits.supported_by_basis', qualified * ref('credit_rate'), 'usd/year')
    annual = calc('credits.annual', if_(ref('bond_financed') == 1, by_basis, min_(by_basis, ref('annual_credit_cap'))), 'usd/year')
    total = calc('credits.ten_year_total', annual * CREDIT_PERIOD_YEARS)
    equity = calc('tax_credit_equity', total * ref('investor_share') * ref('credit_price'))
    calc('equity_per_lihtc_unit', equity / max_(ref('lihtc_units'), 1), 'usd/unit')
    # Sources and uses
    sources = calc('total_sources', equity + ref('permanent_loan') + ref('soft_sources') + ref('deferred_developer_fee'))
    gap = calc('funding_gap', max_(tdc - sources, 0))
    calc('funding_surplus', max_(sources - tdc, 0))
    calc('equity_share_of_cost', equity / tdc, 'rate')
    # Bond test (4% deals)
    aggregate = calc('bond_test.aggregate_basis', ref('land_cost') + before)
    calc('bond_test.financed_share', ref('tax_exempt_bonds') / max_(aggregate, 1), 'rate')
    calc('bond_test.bonds_required', ref('bond_financed') * ref('bond_test_threshold') * aggregate)

    m.test('funded', condition=gap <= TOLERANCE, code='FUNDING_GAP',
           message='Sources fall short of total development cost; the gap needs another source or lower costs.')
    m.test('basis_supports_allocation', condition=(1 - ref('bond_financed')) * ref('annual_credit_cap') <= by_basis + TOLERANCE, code='CREDITS_LIMITED_BY_BASIS',
           message='Qualified basis supports fewer credits than the competitive award; part of the allocation would be returned.')
    m.test('bond_test', condition=ref('tax_exempt_bonds') >= ref('bond_test.bonds_required') - TOLERANCE, code='BOND_TEST',
           message='Tax-exempt bonds finance less than the required share of aggregate basis, so the 4% credit is at risk.')
    return m
