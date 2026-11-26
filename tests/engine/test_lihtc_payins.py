"""Canonical equity installments preserve contractual rounding and timing."""
from decimal import Decimal
import unittest

from openhouse_engine import DecimalPolicy, Dimension, EngineError, Item, Model, ModelDefinitionError, evaluate, ref
from openhouse_engine.models.lihtc_payins import EquityInstallment, declare_payins


class PayinsTest(unittest.TestCase):
    def test_percentage_and_fixed_tranches_round_before_monthly_aggregation(self):
        m = Model('synthetic-payins', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(i, period=i) for i in range(4)]))
        m.input('commitment', unit='USD')
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_payins(m, given, (EquityInstallment('admission', 0, 'percentage'),
                                  EquityInstallment('completion', 3, 'fixed')),
                       commitment=ref('commitment'))
        r = evaluate(m, {'commitment': '101', 'equity.admission.fraction': '.333333333333333333',
                         'equity.completion.amount': '67.33'})
        self.assertEqual(r.value('equity.installment_amount', equity_installment='admission'), Decimal('33.67'))
        self.assertEqual(r.value('equity.contribution', month=0), Decimal('33.67'))
        self.assertEqual(r.value('equity.contribution', month=3), Decimal('67.33'))
        self.assertEqual(r.value('equity.contribution', month=1), Decimal('0'))

    def test_same_month_tranches_keep_their_individual_rounding(self):
        m = Model('synthetic-payins', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(i, period=i) for i in range(2)]))
        m.input('commitment', unit='USD')
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_payins(m, given, (EquityInstallment('first', 1, 'fixed'),
                                  EquityInstallment('second', 1, 'fixed')),
                       commitment=ref('commitment'))
        values = {'commitment': '1.02', 'equity.first.amount': '.505', 'equity.second.amount': '.505'}
        r = evaluate(m, values)
        self.assertEqual(r.value('equity.contribution', month=1), Decimal('1.02'))
        values['commitment'] = '1.01'
        with self.assertRaises(EngineError) as err:
            evaluate(m, values)
        self.assertEqual(err.exception.code, 'EQUITY_PAYINS_NOT_COMMITMENT')

    def test_unknown_month_and_duplicate_tranches_are_rejected(self):
        for tranches in ((EquityInstallment('first', 3, 'fixed'),),
                         (EquityInstallment('first', 1, 'fixed'), EquityInstallment('first', 1, 'fixed'))):
            m = Model('synthetic-payins', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            m.dimension(Dimension('month', [Item(i, period=i) for i in range(2)]))
            with self.assertRaises(ModelDefinitionError):
                declare_payins(m, None, tranches, commitment=ref('commitment'))
        for values in (('bad.name', 0, 'fixed'), ('first', True, 'fixed'), ('first', 0, 'other')):
            with self.assertRaises(ModelDefinitionError):
                EquityInstallment(*values)
