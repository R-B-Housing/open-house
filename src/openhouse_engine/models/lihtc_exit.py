"""LIHTC investor interest sale with reviewed outside tax basis and debt relief.

This declares disposition valuation and investor tax consequences. Debt payoff
is informational; it does not turn an investor buyout into project liquidation
or create a funding source. Ordinary market-sale/promote terms are separate.
"""
from dataclasses import dataclass
from .. import ModelDefinitionError, const, if_, ref, round_to


@dataclass(frozen=True)
class ExitTerms:
    exit_month: int

    def __post_init__(self):
        if type(self.exit_month) is not int or not 1 <= self.exit_month <= 600:
            raise ModelDefinitionError('Investor buyout requires an explicit month from 1 to 600.')


def declare_exit_valuation(m, given, *, debt_owed, prefix='exit'):
    """Debt-plus-cash project valuation, independent of investor tax basis."""
    given(prefix + '.net_sale_cash', 'USD')
    given(prefix + '.investor_distribution', 'USD')
    m.check(prefix + '.distribution_available',
            condition=ref(prefix + '.investor_distribution') <= ref(prefix + '.net_sale_cash'),
            code='EXIT_DISTRIBUTION_EXCEEDS_PROCEEDS',
            message='Investor distribution exceeds reviewed project net sale cash.')
    m.calc(prefix + '.debt_payoff', unit='USD', expr=debt_owed)
    m.calc(prefix + '.sale_price', unit='USD', expr=debt_owed + ref(prefix + '.net_sale_cash'))
    m.calc(prefix + '.net_sale_proceeds', unit='USD', expr=ref(prefix + '.net_sale_cash'))


def declare_exit(m, terms, given, *, debt_owed, prefix='exit'):
    """Investor interest sale using reviewed pre-sale outside basis and liabilities.

    The tax rate is a reviewed effective rate for the sale's gain character.
    Loss benefits require explicit utilization. Book capital is not tax basis.
    Retained-cash repayment is a separate pre-sale partner distribution; callers
    supply outside basis after that distribution and all other closing changes.
    """
    if not isinstance(terms, ExitTerms):
        raise ModelDefinitionError('Investor buyout requires ExitTerms.')
    declare_exit_valuation(m, given, debt_owed=debt_owed, prefix=prefix)
    given(prefix + '.investor_outside_basis', 'USD')
    given(prefix + '.investor_liability_relief', 'USD')
    given(prefix + '.investor_tax_rate', 'ratio', high=1)
    given(prefix + '.investor_loss_utilization', 'ratio', high=1)
    m.check(prefix + '.liability_relief_limit',
            condition=ref(prefix + '.investor_liability_relief') <= ref(prefix + '.debt_payoff'),
            code='EXIT_LIABILITY_RELIEF_EXCEEDS_DEBT',
            message='Investor liability relief exceeds modeled partnership debt.')
    m.calc(prefix + '.investor_amount_realized', unit='USD',
           expr=ref(prefix + '.investor_distribution') + ref(prefix + '.investor_liability_relief'))
    m.calc(prefix + '.investor_gain', unit='USD',
           expr=ref(prefix + '.investor_amount_realized') - ref(prefix + '.investor_outside_basis'))
    m.calc(prefix + '.investor_tax', unit='USD',
           expr=round_to(ref(prefix + '.investor_gain') * ref(prefix + '.investor_tax_rate')
                * if_(ref(prefix + '.investor_gain') < 0,
                      ref(prefix + '.investor_loss_utilization'), const(1)), 0))
    m.calc(prefix + '.investor_after_tax_cash', unit='USD',
           expr=ref(prefix + '.investor_distribution') - ref(prefix + '.investor_tax'))
