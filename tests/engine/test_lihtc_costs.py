"""Line-item acquisition/rehab costs retain one owner for capitalized interest."""
from decimal import Decimal
import unittest

from openhouse_engine import DecimalPolicy, Dimension, Item, Model, ModelDefinitionError, evaluate
from openhouse_engine.models.lihtc_costs import CostItem, declare_costs


class CostTest(unittest.TestCase):
    def test_explicit_cost_lines_allocate_construction_interest_once(self):
        m = Model('synthetic-cost-items', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('month', [Item(i) for i in range(2)]))
        m.dimension(Dimension('facility', [Item('bond'), Item('bridge')]))
        m.input('construction.capitalized_interest', unit='USD', dims=('facility', 'month'))
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        items = (CostItem('purchase', 'acquisition_building'), CostItem('origination', 'financing'),
                 CostItem('construction_carry', 'financing'), CostItem('deferrable_fee', 'developer_fee'))
        declare_costs(m, given, items, construction_interest_cost='construction_carry')
        vals = {'construction.capitalized_interest': {('bond', 0): '3', ('bond', 1): '4',
                                         ('bridge', 0): '1', ('bridge', 1): '2'},
                'cost.amount': {(k.name, i): '0' for k in items for i in range(2)}}
        vals['cost.amount'].update({('purchase', 0): '100', ('origination', 0): '5',
                                   ('construction_carry', 0): '2', ('deferrable_fee', 1): '20'})
        r = evaluate(m, vals)
        self.assertEqual(r.value('cost.scheduled_total', cost='construction_carry'), Decimal('2'))
        self.assertEqual(r.value('cost.total', cost='construction_carry'), Decimal('12'))
        self.assertEqual(r.value('cost.total', cost='origination'), Decimal('5'))
        self.assertEqual(r.value('cost.category_total', cost_category='financing'), Decimal('17'))
        self.assertEqual(r.value('cost.category_total', cost_category='developer_fee'), Decimal('20'))
        self.assertEqual(r.value('cost.category_total', cost_category='acquisition_building'), Decimal('100'))
        self.assertEqual(r.value('cost.category_total', cost_category='land'), Decimal('0'))

    def test_cost_identity_and_capitalized_interest_owner_are_explicit(self):
        for name, category in (('bad name', 'land'), ('ok', 'unreviewed'), ('ok', []), (False, 'land')):
            with self.subTest(name=name), self.assertRaises(ModelDefinitionError):
                CostItem(name, category)
        for items, owner in (((CostItem('land', 'land'),), 'land'),
                              ((CostItem('fee', 'financing'),), 'missing'),
                              ((CostItem('fee', 'financing'), CostItem('fee', 'financing')), 'fee'),
                              ((), 'fee')):
            m = Model('synthetic-cost-invalid', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
            with self.subTest(owner=owner), self.assertRaises(ModelDefinitionError):
                declare_costs(m, m.input, items, construction_interest_cost=owner)
