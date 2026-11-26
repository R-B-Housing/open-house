"""Reviewed asset exclusions, credit reductions and retained tax allocation."""
from decimal import Decimal
import unittest
from openhouse_engine import DecimalPolicy, Dimension, EngineError, Item, Model, evaluate, ref
from openhouse_engine.models.lihtc_tax_basis import declare_tax_basis_adjustment


def adjusted_basis(values):
    model = Model('synthetic-tax-basis', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
    model.dimension(Dimension('asset', [Item('building'), Item('fees')]))
    for name in ('gross', 'excluded', 'credit'):
        model.input(name, unit='USD', dims=('asset',))
    def given(name, unit, dims=(), low=0, high=None):
        model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
    declare_tax_basis_adjustment(model, given, gross_basis=ref('gross'),
        excluded_basis=ref('excluded'), credit_reduction=ref('credit'), prefix='basis', dims=('asset',))
    return evaluate(model, values)


class TaxBasisAdjustmentTest(unittest.TestCase):
    def test_exclusions_and_credit_reductions_precede_retained_asset_allocation(self):
        run = adjusted_basis({'gross':{'building':1000, 'fees':100},
                              'excluded':{'building':100, 'fees':0},
                              'credit':{'building':50, 'fees':0},
                              'basis.retained_fraction':{'building':'0.8', 'fees':1}})
        self.assertEqual(run.value('basis.net_basis', asset='building'), Decimal('680'))
        self.assertEqual(run.value('basis.net_basis', asset='fees'), Decimal('100'))
        self.assertEqual(run.value('basis.gross_basis', asset='building'), Decimal('1000'))
        self.assertEqual(run.value('basis.excluded_basis', asset='building'), Decimal('100'))
        self.assertEqual(run.value('basis.credit_reduction', asset='building'), Decimal('50'))

    def test_reductions_cannot_create_negative_basis_or_hide_negative_inputs(self):
        values = {'gross':{'building':100, 'fees':0},
                  'excluded':{'building':10, 'fees':0},
                  'credit':{'building':20, 'fees':0},
                  'basis.retained_fraction':{'building':1, 'fees':0}}
        self.assertEqual(adjusted_basis(values).value('basis.net_basis', asset='fees'), Decimal('0'))
        for name, replacement in (('excluded', {'building':90, 'fees':0}),
                                  ('gross', {'building':-1, 'fees':0}),
                                  ('credit', {'building':-1, 'fees':0}),
                                  ('basis.retained_fraction', {'building':'1.01', 'fees':0})):
            with self.assertRaises(EngineError):
                adjusted_basis({**values, name:replacement})
