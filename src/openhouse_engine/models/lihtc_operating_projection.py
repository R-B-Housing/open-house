"""Reviewed annual LIHTC operating projection from explicit monthly rent leases."""
from dataclasses import dataclass

from .. import Dimension, Item, ModelDefinitionError, const, if_, matches, previous, ref, round_to, sum_over


@dataclass(frozen=True)
class OperatingProjectionTerms:
    first_year: int
    management_fee_method: str
    include_special_income_in_vacancy: bool
    include_special_income_in_management: bool
    reserve_start_year: int
    reserve_start_month: int

    def __post_init__(self):
        if (type(self.first_year) is not int or not 1900 <= self.first_year <= 2300
                or self.management_fee_method not in ('percentage', 'fixed')
                or type(self.include_special_income_in_vacancy) is not bool
                or type(self.include_special_income_in_management) is not bool
                or type(self.reserve_start_year) is not int or not 1900 <= self.reserve_start_year <= 2300
                or type(self.reserve_start_month) is not int or not 1 <= self.reserve_start_month <= 12):
            raise ModelDefinitionError('Operating projections require reviewed years, fee method, vacancy elections and reserve start date.')


def declare_operating_projection(m, given, terms, *, expenses, prefix='annual_operations', commercial=None):
    """Produce annual operating NOI and cash before debt in one expression graph.

    Three reviewed lease-up blocks supply monthly prices and occupied counts.
    Year two has its own escalation; year three onward uses stabilized block
    three with regular rent escalation measured from the first projection year.
    Existing expense projections remain their canonical owner. The lease-up
    blocks are inputs; the model does not derive a calendar leasing plan.

    `commercial`, when given, holds lease-based annual commercial 'rent' (base
    rent plus recoveries) and 'vacancy' (credit loss) expressions by tax year;
    they replace the crude base/growth/vacancy-fraction commercial inputs.
    """
    if not isinstance(terms, OperatingProjectionTerms) or 'tax_year' not in m.dimensions:
        raise ModelDefinitionError('Operating projections require explicit terms and tax years.')
    years = m.dimensions['tax_year'].keys()
    if len(years) < 3 or years != list(range(terms.first_year, terms.first_year + len(years))):
        raise ModelDefinitionError('Operating projections require three or more contiguous years starting at the reviewed first year.')
    m.dimension(Dimension('tenant_group', [Item('restricted'), Item('market')]))
    m.dimension(Dimension('leaseup_month', [Item(i, block=i // 12) for i in range(36)]))
    reserves = ('replacement', 'operating', 'other_1', 'other_2')
    m.dimension(Dimension('operating_reserve', [Item(r, reserve_name=r) for r in reserves]))
    for i, item in enumerate(m.dimensions['tax_year'].items):
        item.attrs[prefix + '.elapsed'] = i
    p = prefix
    given(p + '.units', 'units', ('tenant_group',))
    given(p + '.monthly_rent', 'USD/unit/month', ('tenant_group', 'leaseup_month'))
    given(p + '.occupied_units', 'units', ('tenant_group', 'leaseup_month'))
    m.check(p + '.occupancy_limit', dims=('tenant_group', 'leaseup_month'),
            condition=ref(p + '.occupied_units') <= ref(p + '.units'),
            code='PROJECTED_OCCUPANCY_EXCEEDS_UNITS', message='Reviewed occupancy exceeds the available units.')
    m.calc(p + '.leaseup_rent', unit='USD', dims=('tenant_group', 'leaseup_month'),
           expr=ref(p + '.monthly_rent') * ref(p + '.occupied_units'))
    leased = commercial is not None
    crude = () if leased else ('commercial',)
    for name in ('residential_growth', 'first_to_second_growth') + tuple(c + '_growth' for c in crude):
        given(p + '.' + name, 'ratio', low=-1)
    for name in ('other_annual_base',) + tuple(c + '_annual_base' for c in crude):
        given(p + '.' + name, 'USD')
    for name in ('first_operating_fraction',) + tuple('first_' + c + '_fraction' for c in crude):
        given(p + '.' + name, 'ratio', high=1)
    for name in ('residential_vacancy_fraction',) + tuple(c + '_vacancy_fraction' for c in crude):
        given(p + '.' + name, 'ratio', ('tax_year',), high=1)
    for name in ('special_income', 'supplemental_expenses'):
        given(p + '.' + name, 'USD', ('tax_year',))
    given(p + '.commercial_management_fraction', 'ratio', high=1)
    if terms.management_fee_method == 'percentage':
        given(p + '.residential_management_fraction', 'ratio', high=1)
    else:
        given(p + '.fixed_management_annual_base', 'USD')
        given(p + '.fixed_management_growth', 'ratio', low=-1)
    given(p + '.reserve_annual_base', 'USD', ('operating_reserve',))
    given(p + '.reserve_growth', 'ratio', ('operating_reserve',), low=-1)
    growths = ((('residential', ref(p + '.residential_growth')),)
               + (() if leased else (('commercial', ref(p + '.commercial_growth')),))
               + (('reserve', ref(p + '.reserve_growth')),))
    for name, growth in growths:
        dims = ('operating_reserve', 'tax_year') if name == 'reserve' else ('tax_year',)
        m.calc(p + '.' + name + '_growth_factor', unit='multiple', dims=dims,
               expr=previous(p + '.' + name + '_growth_factor', 'tax_year', initial=const(1),
                             step=lambda prior, growth=growth: prior * (1 + growth)))
    rental = sum_over('leaseup_month', ref(p + '.leaseup_rent'), block=2) * ref(p + '.residential_growth_factor')
    rental = if_(matches('tax_year', **{p + '.elapsed': 1}),
                 sum_over('leaseup_month', ref(p + '.leaseup_rent'), block=1) * (1 + ref(p + '.first_to_second_growth')), rental)
    rental = if_(matches('tax_year', **{p + '.elapsed': 0}),
                 sum_over('leaseup_month', ref(p + '.leaseup_rent'), block=0), rental)
    m.calc(p + '.residential_by_group', unit='USD', dims=('tenant_group', 'tax_year'), expr=rental)
    m.calc(p + '.residential_rent', unit='USD', dims=('tax_year',),
           expr=sum_over('tenant_group', ref(p + '.residential_by_group')))
    first = matches('tax_year', **{p + '.elapsed': 0})
    m.calc(p + '.other_income', unit='USD', dims=('tax_year',),
           expr=if_(first, round_to(ref(p + '.other_annual_base') * ref(p + '.first_operating_fraction'), 0),
                    ref(p + '.other_annual_base') * ref(p + '.residential_growth_factor')))
    m.calc(p + '.commercial_rent', unit='USD', dims=('tax_year',),
           expr=commercial['rent'] if leased else
                ref(p + '.commercial_annual_base') * ref(p + '.commercial_growth_factor')
                * if_(first, ref(p + '.first_commercial_fraction'), const(1)))
    m.calc(p + '.residential_vacancy', unit='USD', dims=('tax_year',),
           expr=(ref(p + '.residential_rent') + ref(p + '.other_income')
                 + (ref(p + '.special_income') if terms.include_special_income_in_vacancy else const(0)))
                * ref(p + '.residential_vacancy_fraction'))
    m.calc(p + '.commercial_vacancy', unit='USD', dims=('tax_year',),
           expr=commercial['vacancy'] if leased else ref(p + '.commercial_rent') * ref(p + '.commercial_vacancy_fraction'))
    m.calc(p + '.residential_effective_income', unit='USD', dims=('tax_year',),
           expr=ref(p + '.residential_rent') + ref(p + '.special_income') + ref(p + '.other_income')
                - ref(p + '.residential_vacancy'))
    m.calc(p + '.commercial_effective_income', unit='USD', dims=('tax_year',),
           expr=ref(p + '.commercial_rent') - ref(p + '.commercial_vacancy'))
    m.calc(p + '.revenue', unit='USD', dims=('tax_year',),
           expr=ref(p + '.residential_effective_income') + ref(p + '.commercial_effective_income'))
    commercial_fee = ref(p + '.commercial_effective_income') * ref(p + '.commercial_management_fraction')
    if terms.management_fee_method == 'percentage':
        residential_fee = (ref(p + '.residential_effective_income')
                           - (const(0) if terms.include_special_income_in_management else ref(p + '.special_income'))) * ref(p + '.residential_management_fraction')
    else:
        m.calc(p + '.fixed_management_growth_factor', unit='multiple', dims=('tax_year',),
               expr=previous(p + '.fixed_management_growth_factor', 'tax_year', initial=const(1),
                             step=lambda prior: prior * (1 + ref(p + '.fixed_management_growth'))))
        residential_fee = ref(p + '.fixed_management_annual_base') * ref(p + '.fixed_management_growth_factor') * if_(first, ref(p + '.first_operating_fraction'), const(1))
    m.calc(p + '.management_fee', unit='USD', dims=('tax_year',), expr=residential_fee + commercial_fee)
    m.calc(p + '.operating_expenses', unit='USD', dims=('tax_year',),
           expr=expenses + ref(p + '.management_fee') + ref(p + '.supplemental_expenses'))
    m.calc(p + '.noi', unit='USD', dims=('tax_year',), expr=ref(p + '.revenue') - ref(p + '.operating_expenses'))
    reserve_fraction = const(1)
    for year in reversed(years):
        fraction = const(0) if year < terms.reserve_start_year else (const(13 - terms.reserve_start_month) / 12 if year == terms.reserve_start_year else const(1))
        reserve_fraction = if_(matches('tax_year', **{p + '.elapsed': year - terms.first_year}), fraction, reserve_fraction)
    m.calc(p + '.reserve_contribution', unit='USD', dims=('operating_reserve', 'tax_year'),
           expr=ref(p + '.reserve_annual_base') * ref(p + '.reserve_growth_factor') * reserve_fraction)
    m.calc(p + '.cash_before_debt', unit='USD', dims=('tax_year',),
           expr=ref(p + '.noi') - sum_over('operating_reserve', ref(p + '.reserve_contribution')))
