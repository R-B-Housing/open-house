"""Classified project costs generate acquisition and rehab credits separately."""
from decimal import Decimal
import unittest
from openhouse_engine import DecimalPolicy, Dimension, Item, Model, evaluate
from openhouse_engine.models.lihtc_credits import declare_credits


class CreditDeclarationTest(unittest.TestCase):
    def test_classified_costs_feed_separate_basis_caps_delivery_and_equity(self):
        model = Model('synthetic-credit-costs', '1.0.0', DecimalPolicy(34, 'ROUND_HALF_UP'))
        model.dimension(Dimension('cost', [Item('building', basis='eligible'), Item('work', basis='eligible')]))
        model.dimension(Dimension('credit_month', [Item(i) for i in range(12)]))
        model.dimension(Dimension('tax_year', [Item(y, acquisition_first=y==2026, rehab_first=y==2026,
                                                    acquisition_regular=2026<y<2036, rehab_regular=2026<y<2036,
                                                    acquisition_tail=y==2036, rehab_tail=y==2036)
                                                    for y in range(2026,2037)]))
        model.input('cost.total', unit='USD', dims=('cost',), minimum=0)
        def given(name, unit, dims=(), low=0, high=None):
            model.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        declare_credits(model, given)
        values = {'cost.total':{'building':1000, 'work':2000},
                  'basis.acquisition_fraction':{'building':1, 'work':0},
                  'basis.rehab_fraction':{'building':0, 'work':0.8},
                  'basis.applicable_fraction':0.9, 'basis.rehab_boost':1.3,
                  'credits.acquisition_rate':0.04, 'credits.rehab_rate':0.04,
                  'credits.investor_share':1, 'credits.price':0.8, 'equity.rounding_increment':1,
                  'credits.acquisition_annual_cap':1000, 'credits.rehab_annual_cap':70,
                  'credits.acquisition_qualified_fraction':{i:0.5 for i in range(12)},
                  'credits.rehab_qualified_fraction':{i:0.75 for i in range(12)}}
        run = evaluate(model, values)
        self.assertEqual(run.value('basis.acquisition_eligible'), Decimal('1000'))
        self.assertEqual(run.value('basis.rehab_qualified'), Decimal('1872'))
        self.assertEqual(run.value('credits.annual'), Decimal('106'))
        self.assertEqual(run.value('credits.delivered', tax_year=2026), Decimal('70.50'))
        self.assertEqual(run.value('credits.delivered', tax_year=2036), Decimal('35.50'))
        self.assertEqual(run.value('credits.undelivered'), Decimal('0'))
        self.assertEqual(run.value('equity.commitment'), Decimal('848'))
