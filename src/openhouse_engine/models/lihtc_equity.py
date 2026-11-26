"""Reviewed LIHTC annual and lease-up credit adjusters, separate from pay-ins."""
from dataclasses import dataclass

from .. import ModelDefinitionError, const, if_, ref, round_to


@dataclass(frozen=True)
class EquityAdjustment:
    first_year: int
    second_year: int
    tail_years: int

    def __post_init__(self):
        if (type(self.first_year) is not int or type(self.second_year) is not int
                or not 1900 <= self.first_year <= 9998 or self.second_year != self.first_year + 1
                or type(self.tail_years) is not int or not 1 <= self.tail_years <= 100):
            raise ModelDefinitionError('Credit adjustment requires consecutive calendar years and an explicit tail term of 1..100 years.')


def declare_equity_adjustment(m, given, *, annual_credit, first_year_credit,
                              second_year_credit, price, terms, prefix='equity.adjustment'):
    if not isinstance(terms, EquityAdjustment):
        raise ModelDefinitionError('Credit adjustment requires explicit EquityAdjustment terms.')
    for name in ('closing_annual_credit', 'closing_first_year_credit', 'closing_second_year_credit'):
        given(prefix + '.' + name, 'USD')
    m.calc(prefix + '.projected_annual_credit', unit='USD', expr=round_to(annual_credit, 0))
    m.calc(prefix + '.annual_difference', unit='USD',
           expr=ref(prefix + '.projected_annual_credit') - ref(prefix + '.closing_annual_credit'))
    m.calc(prefix + '.annual_price_difference', unit='USD', expr=ref(prefix + '.annual_difference') * price)
    m.calc(prefix + '.annual', unit='USD', expr=round_to(ref(prefix + '.annual_price_difference') * 10, 0))
    for name, projected in (('first_year', first_year_credit), ('second_year', second_year_credit)):
        base = prefix + '.' + name
        given(base + '_discount_rate', 'ratio', high=1)
        discount_factor = const(1)
        for _ in range(terms.tail_years):
            discount_factor = discount_factor * (1 + ref(base + '_discount_rate'))
        m.calc(base + '_tail_discount_factor', unit='multiple', expr=discount_factor)
        m.calc(base + '_projected_credit', unit='USD', expr=round_to(projected, 0))
        m.calc(base + '_normalized_closing_credit', unit='USD',
               expr=if_(ref(prefix + '.closing_annual_credit') == 0, const(0),
                        round_to(ref(prefix + '.closing_' + name + '_credit')
                                 * ref(prefix + '.projected_annual_credit')
                                 / ref(prefix + '.closing_annual_credit'), 0)))
        m.calc(base + '_difference', unit='USD',
               expr=ref(base + '_projected_credit') - ref(base + '_normalized_closing_credit'))
        m.calc(base + '_tail_present_value', unit='USD',
               expr=round_to(-ref(base + '_difference') / ref(base + '_tail_discount_factor'), 0))
        m.calc(base + '_net_difference', unit='USD',
               expr=ref(base + '_difference') + ref(base + '_tail_present_value'))
        m.calc(base, unit='USD', expr=round_to(ref(base + '_net_difference') * price, 0))
    m.calc(prefix + '.total', unit='USD',
           expr=ref(prefix + '.annual') + ref(prefix + '.first_year') + ref(prefix + '.second_year'))
