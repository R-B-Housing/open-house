"""Reviewed operating projections derive income before debt from monthly leases."""
from decimal import Decimal
import unittest

from openhouse_engine import DecimalPolicy, Dimension, Item, Model, EngineError, ModelDefinitionError, evaluate, ref
from openhouse_engine.models.lihtc_operating_projection import OperatingProjectionTerms, declare_operating_projection


def example(terms=None):
    m = Model('synthetic-operating-projection', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
    m.dimension(Dimension('tax_year', [Item(y) for y in (2027, 2028, 2029)]))
    m.input('reviewed_expenses', unit='USD', dims=('tax_year',))
    def given(name, unit, dims=(), low=0, high=None):
        m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
    terms = terms or OperatingProjectionTerms(2027, 'percentage', True, True, 2027, 7)
    declare_operating_projection(m, given, terms, expenses=ref('reviewed_expenses'))
    p = 'annual_operations'
    values = {'reviewed_expenses': {y: '100' for y in (2027, 2028, 2029)},
              p + '.units': {'restricted': '2', 'market': '1'},
              p + '.monthly_rent': {(g, i): '10' if g == 'restricted' else '20'
                                   for g in ('restricted', 'market') for i in range(36)},
              p + '.occupied_units': {(g, i): '2' if g == 'restricted' else '1'
                                     for g in ('restricted', 'market') for i in range(36)},
              p + '.residential_growth': '.1', p + '.first_to_second_growth': '.2',
              p + '.other_annual_base': '120', p + '.commercial_annual_base': '100',
              p + '.commercial_growth': '.05', p + '.first_operating_fraction': '.5',
              p + '.first_commercial_fraction': '.5',
              p + '.residential_vacancy_fraction': {y: '.1' for y in (2027, 2028, 2029)},
              p + '.commercial_vacancy_fraction': {y: '.2' for y in (2027, 2028, 2029)},
              p + '.special_income': {y: '0' for y in (2027, 2028, 2029)},
              p + '.supplemental_expenses': {y: '0' for y in (2027, 2028, 2029)},
              p + '.residential_management_fraction': '.05', p + '.commercial_management_fraction': '.1',
              p + '.reserve_annual_base': {r: '12' if r == 'replacement' else '0'
                                        for r in ('replacement', 'operating', 'other_1', 'other_2')},
              p + '.reserve_growth': {r: '0' for r in ('replacement', 'operating', 'other_1', 'other_2')}}
    if terms.management_fee_method == 'fixed':
        values.pop(p + '.residential_management_fraction')
        values[p + '.fixed_management_annual_base'] = '100'
        values[p + '.fixed_management_growth'] = '.1'
    return m, values


class OperatingProjectionTest(unittest.TestCase):
    def test_monthly_rent_times_occupancy_drives_revenue_management_and_noi(self):
        m, values = example()
        p = "annual_operations"
        r = evaluate(m, values)
        self.assertEqual(r.value(p + '.residential_rent', tax_year=2027), Decimal('480'))
        self.assertEqual(r.value(p + '.residential_rent', tax_year=2028), Decimal('576'))
        self.assertEqual(r.value(p + '.residential_rent', tax_year=2029), Decimal('580.8'))
        self.assertEqual(r.value(p + '.revenue', tax_year=2027), Decimal('526'))
        self.assertEqual(r.value(p + '.management_fee', tax_year=2027), Decimal('28.30'))
        self.assertEqual(r.value(p + '.noi', tax_year=2027), Decimal('397.70'))
        self.assertEqual(r.value(p + '.cash_before_debt', tax_year=2027), Decimal('391.70'))

    def test_fixed_management_fee_and_special_income_elections_are_explicit(self):
        terms = OperatingProjectionTerms(2027, 'fixed', False, False, 2027, 7)
        m, values = example(terms)
        values['annual_operations.special_income'][2027] = '100'
        r = evaluate(m, values)
        self.assertEqual(r.value('annual_operations.revenue', tax_year=2027), Decimal('626'))
        self.assertEqual(r.value('annual_operations.management_fee', tax_year=2027), Decimal('54'))
        self.assertEqual(r.value('annual_operations.management_fee', tax_year=2028), Decimal('118.4'))
        terms = OperatingProjectionTerms(2027, 'percentage', False, False, 2027, 7)
        m, values = example(terms)
        values['annual_operations.special_income'][2027] = '100'
        r = evaluate(m, values)
        self.assertEqual(r.value('annual_operations.management_fee', tax_year=2027), Decimal('28.3'))
        self.assertEqual(r.value('annual_operations.residential_vacancy', tax_year=2027), Decimal('54'))

    def test_occupancy_vacancy_and_structural_calendar_bounds_fail_visibly(self):
        m, values = example()
        values['annual_operations.occupied_units'][('restricted', 0)] = '3'
        with self.assertRaises(EngineError) as err:
            evaluate(m, values)
        self.assertEqual(err.exception.code, 'PROJECTED_OCCUPANCY_EXCEEDS_UNITS')
        m, values = example()
        values['annual_operations.residential_vacancy_fraction'][2027] = '1.1'
        with self.assertRaises(EngineError):
            evaluate(m, values)
        for terms in ((True, 'percentage', True, True, 2027, 7),
                      (2027, 'other', True, True, 2027, 7),
                      (2027, 'percentage', 1, True, 2027, 7),
                      (2027, 'percentage', True, True, 2027, 13)):
            with self.assertRaises(ModelDefinitionError):
                OperatingProjectionTerms(*terms)
