"""Reviewed LIHTC investor buyout convention, separate from project liquidation."""
from decimal import Decimal
import unittest
from openhouse_engine import DecimalPolicy, EngineError, Model, evaluate, ref
from openhouse_engine.models.lihtc_exit import ExitTerms, declare_exit


class ExitTest(unittest.TestCase):
    def test_buyout_gain_uses_cash_liability_relief_and_outside_basis(self):
        m = Model('synthetic-buyout', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.input('debt', unit='USD', minimum=0)
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_exit(m, ExitTerms(120), given, debt_owed=ref('debt'))
        r = evaluate(m, {'debt': '1000', 'exit.net_sale_cash': '500',
            'exit.investor_distribution': '400', 'exit.investor_tax_rate': '.25',
            'exit.investor_outside_basis': '300', 'exit.investor_liability_relief': '200',
            'exit.investor_loss_utilization': '0'})
        self.assertEqual(r.value('exit.investor_amount_realized'), Decimal('600'))
        self.assertEqual(r.value('exit.investor_gain'), Decimal('300'))
        self.assertEqual(r.value('exit.investor_tax'), Decimal('75'))
        self.assertEqual(r.value('exit.investor_after_tax_cash'), Decimal('325'))

    def test_loss_benefit_requires_reviewed_utilization_and_proceeds_affect_gain(self):
        m = Model('synthetic-exit', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.input('debt', unit='USD', minimum=0)
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_exit(m, ExitTerms(1), given, debt_owed=ref('debt'))
        values = {'debt': '0', 'exit.net_sale_cash': '100',
                  'exit.investor_distribution': '1', 'exit.investor_tax_rate': '.25',
                  'exit.investor_outside_basis': '101', 'exit.investor_liability_relief': '0',
                  'exit.investor_loss_utilization': '0'}
        r = evaluate(m, values)
        self.assertEqual(r.value('exit.investor_gain'), Decimal('-100'))
        self.assertEqual(r.value('exit.investor_tax'), Decimal('0'))
        values['exit.investor_loss_utilization'] = '.4'
        r = evaluate(m, values)
        self.assertEqual(r.value('exit.investor_tax'), Decimal('-10'))
        self.assertEqual(r.value('exit.investor_after_tax_cash'), Decimal('11'))
        values['exit.investor_distribution'] = '100'
        self.assertEqual(evaluate(m, values).value('exit.investor_gain'), Decimal('-1'))
        values['exit.investor_distribution'] = '101'
        with self.assertRaises(EngineError) as err:
            evaluate(m, values)
        self.assertEqual(err.exception.code, 'EXIT_DISTRIBUTION_EXCEEDS_PROCEEDS')

    def test_missing_outside_basis_cannot_fall_back_to_book_capital(self):
        m = Model('missing-exit-basis', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.input('debt', unit='USD', minimum=0)
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_exit(m, ExitTerms(1), given, debt_owed=ref('debt'))
        with self.assertRaises(EngineError):
            evaluate(m, {'debt': '0', 'exit.net_sale_cash': '1',
                'exit.investor_distribution': '1', 'exit.investor_tax_rate': '.25',
                'exit.investor_liability_relief': '0', 'exit.investor_loss_utilization': '0'})

    def test_liability_relief_cannot_exceed_modeled_partnership_debt(self):
        m = Model('excess-relief', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.input('debt', unit='USD', minimum=0)
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_exit(m, ExitTerms(1), given, debt_owed=ref('debt'))
        with self.assertRaises(EngineError) as err:
            evaluate(m, {'debt':'1000', 'exit.net_sale_cash':'400',
                'exit.investor_distribution':'400', 'exit.investor_tax_rate':'.25',
                'exit.investor_outside_basis':'300', 'exit.investor_liability_relief':'5000',
                'exit.investor_loss_utilization':'0'})
        self.assertEqual(err.exception.code, 'EXIT_LIABILITY_RELIEF_EXCEEDS_DEBT')
