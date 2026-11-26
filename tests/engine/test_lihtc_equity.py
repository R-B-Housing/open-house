"""Explicit contractual equity adjustment, using synthetic deal inputs."""
from decimal import Decimal
import unittest

from openhouse_engine import DecimalPolicy, Model, ModelDefinitionError, EngineError, evaluate, ref
from openhouse_engine.models.lihtc_equity import EquityAdjustment, declare_equity_adjustment


def adjustment(values, terms= None):
    model = Model('synthetic-equity', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
    for name in ('annual_credit', 'first_credit', 'second_credit'):
        model.input(name, unit='USD', minimum=0)
    model.input('price', unit='USD/USD-credit', minimum=0, maximum=2)
    def given(name, unit, dims=(), low=0, high=None):
        model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
    declare_equity_adjustment(model, given, annual_credit=ref('annual_credit'),
                              first_year_credit=ref('first_credit'), second_year_credit=ref('second_credit'),
                              price=ref('price'), terms=terms or EquityAdjustment(2026, 2027, 11))
    return evaluate(model, values)


class EquityAdjustmentTest(unittest.TestCase):
    def test_annual_and_lease_up_changes_include_discounted_tail_credits(self):
        values = {'annual_credit':'120.4', 'first_credit':'30.4', 'second_credit':'80.6',
                  'equity.adjustment.closing_annual_credit':'100',
                  'equity.adjustment.closing_first_year_credit':'20',
                  'equity.adjustment.closing_second_year_credit':'70',
                  'price':'0.8', 'equity.adjustment.first_year_discount_rate':'0.1', 'equity.adjustment.second_year_discount_rate':'0.1'}
        run = adjustment(values)
        self.assertEqual(run.value('equity.adjustment.projected_annual_credit'), Decimal('120'))
        self.assertEqual(run.value('equity.adjustment.annual'), Decimal('160'))
        self.assertEqual(run.value('equity.adjustment.first_year_normalized_closing_credit'), Decimal('24'))
        self.assertEqual(run.value('equity.adjustment.first_year_difference'), Decimal('6'))
        self.assertEqual(run.value('equity.adjustment.first_year_tail_present_value'), Decimal('-2'))
        self.assertEqual(run.value('equity.adjustment.first_year'), Decimal('3'))
        self.assertEqual(run.value('equity.adjustment.second_year_difference'), Decimal('-3'))
        self.assertEqual(run.value('equity.adjustment.second_year_tail_present_value'), Decimal('1'))
        self.assertEqual(run.value('equity.adjustment.second_year'), Decimal('-2'))
        self.assertEqual(run.value('equity.adjustment.total'), Decimal('161'))

    def test_zero_closing_credit_and_zero_discount_are_explicit_contract_cases(self):
        values = {'annual_credit':'100', 'first_credit':'20', 'second_credit':'30',
                  'equity.adjustment.closing_annual_credit':'0',
                  'equity.adjustment.closing_first_year_credit':'10',
                  'equity.adjustment.closing_second_year_credit':'20',
                  'price':'0.75', 'equity.adjustment.first_year_discount_rate':'0', 'equity.adjustment.second_year_discount_rate':'0'}
        run = adjustment(values)
        self.assertEqual(run.value('equity.adjustment.annual'), Decimal('750'))
        self.assertEqual(run.value('equity.adjustment.first_year_normalized_closing_credit'), Decimal('0'))
        self.assertEqual(run.value('equity.adjustment.first_year_tail_present_value'), Decimal('-20'))
        self.assertEqual(run.value('equity.adjustment.first_year'), Decimal('0'))
        self.assertEqual(run.value('equity.adjustment.second_year'), Decimal('0'))
        for key, value in (('equity.adjustment.first_year_discount_rate', '-0.01'),
                           ('equity.adjustment.closing_annual_credit', '-1')):
            with self.assertRaises(EngineError):
                adjustment({**values, key:value})

    def test_adjuster_terms_require_explicit_consecutive_years_and_tail(self):
        for terms in ((2026, 2028, 11), (True, 2027, 11), (2026, 2027, True),
                      (2026, 2027, 0), (2026, 2027, 101)):
            with self.assertRaises(ModelDefinitionError):
                EquityAdjustment(*terms)
