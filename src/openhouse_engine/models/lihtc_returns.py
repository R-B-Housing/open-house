"""Explicit annual or quarterly LIHTC investor return conventions."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .. import Dimension, Item, ModelDefinitionError, const, if_, matches, ref, sum_over, sum_within
from ..returns import declare_periodic_irr


@dataclass(frozen=True)
class ReturnTerms:
    lower: str
    upper: str
    iterations: int
    frequency: str = "quarterly"

    def __post_init__(self):
        if self.frequency not in ("annual", "quarterly"):
            raise ModelDefinitionError("Return frequency must be annual or quarterly.")
        if not isinstance(self.lower, str) or not isinstance(self.upper, str):
            raise ModelDefinitionError('Return bounds require exact decimal strings.')
        try:
            lo, hi = Decimal(self.lower), Decimal(self.upper)
        except InvalidOperation as exc:
            raise ModelDefinitionError('Return bounds require finite decimal rates.') from exc
        if (not lo.is_finite() or not hi.is_finite() or not -1 < lo < hi <= 100
                or type(self.iterations) is not int or not 32 <= self.iterations <= 120):
            raise ModelDefinitionError('Return terms require -1 < lower < upper <= 100 and 32–120 iterations.')


def declare_returns(m, structure, given):
    """Declare the elected investor cash-flow aggregation and bounded return.

    Quarterly returns preserve monthly distribution/contribution timing and
    require a reviewed monthly vector allocating every year's tax benefit.
    The benefit includes combined cash/tax rounding residue, so the quarterly
    series reconciles to canonical annual after-tax benefits.

    Annual returns separate closing cash from canonical calendar-year benefits
    and aggregate the remainder at successive annual endpoints. They require
    no monthly tax-posting election; partial years still use annual intervals.
    """
    terms = structure.return_terms
    if not isinstance(terms, ReturnTerms) or type(structure.months) is not int or structure.months < 1:
        raise ModelDefinitionError("Investor returns require explicit terms and a monthly horizon.")
    if terms.frequency == "quarterly" and (structure.months < 3 or structure.months % 3):
        raise ModelDefinitionError("Quarterly returns require a complete-quarter horizon.")
    if 'month' not in m.dimensions:
        raise ModelDefinitionError('Returns require modeled monthly cash flows.')
    items = m.dimensions['month'].items
    if (any(type(i.key) is not int for i in items)
            or [i.key for i in items] != list(range(structure.months + 1))):
        raise ModelDefinitionError('Return months must be contiguous integers from zero through the horizon.')
    if terms.frequency == "annual":
        declare_annual_returns(m, structure)
        return
    if any(i.attrs.get('return_period') != (i.key + 2) // 3 for i in items):
        raise ModelDefinitionError('Months require closing-relative return_period attributes.')
    m.dimension(Dimension('quarter', [Item(q, period=q) for q in range(structure.months // 3 + 1)]))
    given('returns.tax_benefit_fraction', 'ratio', ('month',), high=1)
    m.check('returns.tax_posting_complete', dims=('tax_year',),
            condition=sum_within('month', ref('returns.tax_benefit_fraction')) == 1,
            code='RETURN_TAX_POSTING_NOT_ONE',
            message='Each tax year requires a complete reviewed tax-benefit posting schedule.')
    terminal = (if_(matches('month', last=True), ref('exit.investor_after_tax_cash'), const(0))
                if structure.exit_terms is not None else const(0))
    m.calc('returns.investor_monthly_cash', unit='USD', dims=('month',),
           expr=sum_over('partner', ref('partner.distribution') - ref('partner.contribution'), investor=True)
                + sum_over('partner', ref('partner.tax_benefit'), investor=True)
                * ref('returns.tax_benefit_fraction') + terminal)
    quarterly = const(0)
    for q in reversed(range(structure.months // 3 + 1)):
        quarterly = if_(matches('quarter', period=q),
                        sum_over('month', ref('returns.investor_monthly_cash'), return_period=q), quarterly)
    m.calc('returns.investor_cash_flow', unit='USD', dims=('quarter',), expr=quarterly)
    declare_periodic_irr(m, cash_flow='returns.investor_cash_flow', period_dim='quarter',
                         periods_per_year=4, lower=terms.lower, upper=terms.upper, iterations=terms.iterations)


def declare_annual_returns(m, structure):
    """Aggregate canonical annual benefits under an explicit year-end convention.

    Period zero contains closing investor cash only. Period one contains the
    first calendar year's remaining after-tax cash; subsequent calendar years
    follow at annual intervals. Partial calendar years receive one full annual
    discount interval. This is an elected periodic convention, not a date-exact
    return or a deduction about when tax benefits become cash.
    """
    terms = structure.return_terms
    if "tax_year" not in m.dimensions:
        raise ModelDefinitionError("Annual returns require modeled calendar tax years.")
    years = [item.key for item in m.dimensions["tax_year"].items]
    if (not years or any(type(year) is not int for year in years)
            or years != list(range(years[0], years[-1] + 1))):
        raise ModelDefinitionError("Annual return years must be contiguous calendar years.")
    m.dimension(Dimension("return_year", [Item(0, period=0)] +
                          [Item(period, period=period, year=year)
                           for period, year in enumerate(years, 1)]))
    m.calc("returns.investor_closing_cash", unit="USD",
           expr=sum_over("month", sum_over("partner",
                ref("partner.distribution") - ref("partner.contribution"), investor=True), period=0))
    annual = const(0)
    for period, year in reversed(list(enumerate(years, 1))):
        cash = sum_over("tax_year", sum_over("partner", ref("partner.after_tax_cash_flow"),
                         investor=True), year=year)
        if period == 1:
            cash = cash - ref("returns.investor_closing_cash")
        if year == years[-1] and structure.exit_terms is not None:
            cash = cash + ref("exit.investor_after_tax_cash")
        annual = if_(matches("return_year", period=period), cash, annual)
    m.calc("returns.investor_cash_flow", unit="USD", dims=("return_year",),
           expr=if_(matches("return_year", period=0), ref("returns.investor_closing_cash"), annual))
    declare_periodic_irr(m, cash_flow="returns.investor_cash_flow", period_dim="return_year",
                         periods_per_year=1, lower=terms.lower, upper=terms.upper, iterations=terms.iterations)
