"""Partner benefit rounding combines cash with raw income tax before credits."""
from decimal import Decimal
from types import SimpleNamespace
import unittest

from openhouse_engine import DecimalPolicy, Dimension, Item, Model, ModelDefinitionError, evaluate
from openhouse_engine.models.lihtc_partnership import declare_partner_benefits
from openhouse_engine.models.lihtc_returns import ReturnTerms, declare_returns


class PartnerBenefitsTest(unittest.TestCase):
    def test_whole_dollar_cash_tax_rounding_precedes_credits_and_contributions(self):
        model = Model('synthetic-partner-benefit', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('partner', [Item('investor', investor=True)]))
        model.dimension(Dimension('tax_year', [Item(2027)]))
        values = {
            'taxable_income': '-1.495', 'tax_rate': '.2', 'loss_utilization': '1',
            'credits': '10.25', 'credit_utilization': '.8',
            'annual_distribution': '.2', 'annual_contribution': '2.13',
        }
        for suffix in values:
            unit = 'ratio' if suffix in ('tax_rate', 'loss_utilization', 'credit_utilization') else 'USD'
            model.input('partner.' + suffix, unit=unit, dims=('partner', 'tax_year'))
        declare_partner_benefits(model, cash_tax_rounding_places=0)
        result = evaluate(model, {'partner.' + suffix: {('investor', 2027): value}
                                  for suffix, value in values.items()})
        coord = dict(partner='investor', tax_year=2027)
        # Raw tax .299 plus cash .2 = .499 rounds down, rather than .30+.2 up.
        self.assertEqual(result.value('partner.raw_income_tax_effect', **coord), Decimal('.299'))
        self.assertEqual(result.value('partner.income_tax_effect', **coord), Decimal('.30'))
        self.assertEqual(result.value('partner.cash_tax_benefit', **coord), Decimal('0'))
        self.assertEqual(result.value('partner.usable_credit', **coord), Decimal('8.20'))
        self.assertEqual(result.value('partner.tax_benefit', **coord), Decimal('8'))
        self.assertEqual(result.value('partner.after_tax_cash_flow', **coord), Decimal('6.07'))

    def test_positive_income_is_taxed_without_loss_utilization_and_combined_cent_rounding(self):
        model = Model('synthetic-positive-income', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('partner', [Item('investor', investor=True)]))
        model.dimension(Dimension('tax_year', [Item(2027)]))
        values = {
            'taxable_income': '10.02', 'tax_rate': '.25', 'loss_utilization': '0',
            'credits': '2.12', 'credit_utilization': '.5',
            'annual_distribution': '3.20', 'annual_contribution': '1',
        }
        for suffix in values:
            unit = 'ratio' if suffix in ('tax_rate', 'loss_utilization', 'credit_utilization') else 'USD'
            model.input('partner.' + suffix, unit=unit, dims=('partner', 'tax_year'))
        declare_partner_benefits(model)
        result = evaluate(model, {'partner.' + suffix: {('investor', 2027): value}
                                  for suffix, value in values.items()})
        coord = dict(partner='investor', tax_year=2027)
        self.assertEqual(result.value('partner.income_tax_effect', **coord), Decimal('-2.51'))
        self.assertEqual(result.value('partner.cash_tax_benefit', **coord), Decimal('.70'))
        self.assertEqual(result.value('partner.after_tax_cash_flow', **coord), Decimal('.76'))
        for value in (True, False, 2.0, '2', None, 1):
            with self.assertRaises(ModelDefinitionError):
                declare_partner_benefits(model, cash_tax_rounding_places=value)

    def test_quarterly_posting_reconciles_rounded_annual_benefit_and_terminal_cash(self):
        model = Model('synthetic-rounded-quarter-return', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('partner', [Item('investor', investor=True)]))
        model.dimension(Dimension('tax_year', [Item(2027)]))
        model.dimension(Dimension('month', [Item(i, tax_year=2027, return_period=(i + 2) // 3,
                                                last=i == 9) for i in range(10)], parent='tax_year'))
        annual = {'taxable_income': '-501.495', 'tax_rate': '.2', 'loss_utilization': '1',
                  'credits': '10.25', 'credit_utilization': '.8',
                  'annual_distribution': '.6', 'annual_contribution': '10'}
        for suffix in annual:
            unit = 'ratio' if suffix in ('tax_rate', 'loss_utilization', 'credit_utilization') else 'USD'
            model.input('partner.' + suffix, unit=unit, dims=('partner', 'tax_year'))
        for suffix in ('distribution', 'contribution'):
            model.input('partner.' + suffix, unit='USD', dims=('partner', 'month'))
        model.input('exit.investor_after_tax_cash', unit='USD')
        declare_partner_benefits(model, cash_tax_rounding_places=0)
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        structure = SimpleNamespace(months=9, exit_terms=object(),
                                    return_terms=ReturnTerms('-.99', '10', 80))
        declare_returns(model, structure, given)
        inputs = {'partner.' + suffix: {('investor', 2027): value} for suffix, value in annual.items()}
        inputs.update({
            'partner.distribution': {('investor', i): '.2' if i in (3, 6, 9) else '0' for i in range(10)},
            'partner.contribution': {('investor', i): '10' if i == 0 else '0' for i in range(10)},
            'exit.investor_after_tax_cash': '2',
            'returns.tax_benefit_fraction': {i: '1' if i == 9 else '0' for i in range(10)},
        })
        result = evaluate(model, inputs)
        quarterly = [result.value('returns.investor_cash_flow', quarter=i) for i in range(4)]
        self.assertEqual(quarterly, [Decimal('-10'), Decimal('.2'), Decimal('.2'), Decimal('110.8')])
        self.assertEqual(sum(quarterly), result.value('partner.after_tax_cash_flow',
                                                    partner='investor', tax_year=2027) + Decimal('2'))
