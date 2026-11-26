"""Canonical dated equity installments with per-tranche contractual rounding."""

from dataclasses import dataclass
import re

from .. import Dimension, Item, ModelDefinitionError, const, if_, matches, ref, round_to, sum_over


@dataclass(frozen=True)
class EquityInstallment:
    name: str
    month: int
    kind: str

    def __post_init__(self):
        if (not isinstance(self.name, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,63}', self.name) is None
                or type(self.month) is not int or not 0 <= self.month <= 600
                or self.kind not in ('percentage', 'fixed')):
            raise ModelDefinitionError('Equity installments require a safe name, month and percentage/fixed kind.')


def declare_payins(m, given, installments, *, commitment):
    """Round each contractual tranche, then aggregate to its reviewed month.

    Percentage tranches use the canonical commitment. Fixed tranches require
    their own amount. A discrepancy against commitment fails visibly; there is
    no final-tranche plug or redistribution of a rounding remainder.
    """
    if (not isinstance(installments, tuple) or not 1 <= len(installments) <= 100
            or any(not isinstance(t, EquityInstallment) for t in installments)
            or len({t.name for t in installments}) != len(installments)
            or 'month' not in m.dimensions):
        raise ModelDefinitionError('Pay-ins require distinct reviewed equity installments and modeled months.')
    periods = [i.attrs.get('period') for i in m.dimensions['month'].items]
    if (any(type(p) is not int for p in periods) or len(set(periods)) != len(periods)
            or any(t.month not in periods for t in installments)):
        raise ModelDefinitionError('Every equity installment must name one modeled integer month.')
    m.dimension(Dimension('equity_installment', [Item(t.name, installment=t.name, month=t.month)
                                                for t in installments]))
    amount_expr = const(0)
    for tranche in reversed(installments):
        name = 'equity.' + tranche.name
        if tranche.kind == 'percentage':
            given(name + '.fraction', 'ratio', high=1)
            amount = commitment * ref(name + '.fraction')
        else:
            given(name + '.amount', 'USD')
            amount = ref(name + '.amount')
        amount_expr = if_(matches('equity_installment', installment=tranche.name),
                          round_to(amount, 2), amount_expr)
    m.calc('equity.installment_amount', unit='USD', dims=('equity_installment',), expr=amount_expr)
    m.calc('equity.payin_total', unit='USD', expr=sum_over('equity_installment', ref('equity.installment_amount')))
    m.check('equity.payins_match_commitment', condition=ref('equity.payin_total') == commitment,
            code='EQUITY_PAYINS_NOT_COMMITMENT', message='Rounded contractual equity installments do not equal commitment.')
    monthly = const(0)
    for period in reversed(sorted({t.month for t in installments})):
        monthly = if_(matches('month', period=period),
                      sum_over('equity_installment', ref('equity.installment_amount'), month=period), monthly)
    m.calc('equity.contribution', unit='USD', dims=('month',), expr=monthly)
