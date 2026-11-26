"""The public project consumes canonical annual operations with reviewed dates."""
from dataclasses import replace
from decimal import Decimal
import unittest

from openhouse_engine import EngineError, ModelDefinitionError
from openhouse_engine.operations import AnnualProjectionTerms
from openhouse_engine.models.lihtc_acquisition_rehab import calculate
from test_lihtc_acquisition_rehab import example as project_example
from test_lihtc_operating_projection import example as operating_example


def annual_project(month_count=35, start_month=1, closing_operations=True):
    structure, inputs = project_example(month_count, start_month=start_month)
    _, operating = operating_example()
    from openhouse_engine.models.lihtc_operating_projection import OperatingProjectionTerms
    structure = replace(structure, closing_month_operations=closing_operations,
        expense_projection=AnnualProjectionTerms(('base',), 0),
        operating_projection=OperatingProjectionTerms(2027, 'percentage', True, True, 2027, 7))
    for name in tuple(inputs):
        if name == 'units' or name.startswith('rent.') or name in ('operations.other_income', 'operations.expenses', 'reserve.deposit'):
            inputs.pop(name)
    operating.pop('reviewed_expenses')
    inputs.update(operating)
    inputs.update({'expenses.annual_base': {'base': '100'},
        'expenses.annual_growth': {('base', y): '0' for y in (2027, 2028, 2029)},
        'expenses.period_fraction': {y: '1' for y in (2027, 2028, 2029)}})
    months = range(month_count + 1)
    year_ends = {max(i for i in months if structure.start_year + (start_month - 1 + i) // 12 == y)
                 for y in range(structure.start_year, structure.last_year + 1)}
    for name in ('revenue', 'expense'):
        inputs['operations.' + name + '_monthly_fraction'] = {
            m: '1' if m in year_ends and (m > 0 or closing_operations) else '0' for m in months}
    inputs['reserve.operating_monthly_fraction'] = {
        (r, m): '1' if r != 'lease_up' and m in year_ends and (m > 0 or closing_operations) else '0'
        for r in ('lease_up', 'operating', 'replacement', 'other_1', 'other_2') for m in months}
    return structure, inputs


class AnnualProjectTest(unittest.TestCase):
    def test_annual_income_expenses_and_reserves_feed_the_same_project_cash_and_tax(self):
        structure, inputs = annual_project()
        result = calculate(structure, inputs)
        for year, month, noi, deposit in ((2027, 11, '397.70', '6'), (2028, 23, '580.94', '12'), (2029, 35, '600.11', '12')):
            self.assertEqual(result.value('operations.noi', month=month), Decimal(noi))
            self.assertEqual(result.value('tax.noi', tax_year=year), Decimal(noi))
            self.assertEqual(result.value('reserve.deposit', reserve='replacement', month=month), Decimal(deposit))
        self.assertEqual(result.value('operations.noi', month=1), Decimal('0'))
        self.assertEqual(result.value('reserve.annual_ending_balance', reserve='replacement', tax_year=2029), Decimal('30'))
        self.assertEqual(result.value('tax.income', tax_year=2027), Decimal('367.70'))
        self.assertEqual(result.value('funding.uses', month=35), Decimal('12'))

    def test_reviewed_posting_is_complete_and_cannot_assign_operations_to_closing(self):
        structure, inputs = annual_project()
        inputs['operations.revenue_monthly_fraction'][11] = '.5'
        with self.assertRaises(EngineError) as error:
            calculate(structure, inputs)
        self.assertEqual(error.exception.code, 'OPERATING_POSTING_NOT_ONE')
        structure, inputs = annual_project()
        inputs['reserve.operating_monthly_fraction'][('replacement', 11)] = '.5'
        with self.assertRaises(EngineError) as error:
            calculate(structure, inputs)
        self.assertEqual(error.exception.code, 'RESERVE_OPERATING_POSTING_NOT_ONE')
        structure, inputs = annual_project()
        inputs['operations.revenue_monthly_fraction'][11] = '0'
        inputs['operations.revenue_monthly_fraction'][0] = '1'
        with self.assertRaises(EngineError) as error:
            calculate(replace(structure, closing_month_operations=False), inputs)
        self.assertEqual(error.exception.code, 'OPERATING_POSTING_BEFORE_OPERATIONS')

    def test_annual_owner_rejects_unaligned_years_and_keeps_capitalized_reserve_separate(self):
        structure, inputs = annual_project()
        with self.assertRaises(ModelDefinitionError):
            replace(structure, expense_projection=None)
        with self.assertRaises(ModelDefinitionError):
            replace(structure, operating_projection=replace(structure.operating_projection, first_year=2028))
        with self.assertRaises(ModelDefinitionError):
            replace(structure, months=11)
        inputs['cost.amount'][('reserves', 0)] = '10'
        result = calculate(structure, inputs)
        self.assertEqual(result.value('reserve.capitalized_contribution', reserve='operating', month=0), Decimal('10'))
        self.assertEqual(result.value('reserve.deposit', reserve='operating', month=0), Decimal('0'))
        self.assertEqual(result.value('reserve.annual_ending_balance', reserve='operating', tax_year=2029), Decimal('10'))
        self.assertEqual(result.value('reserve.annual_ending_balance', reserve='replacement', tax_year=2029), Decimal('30'))

    def test_reserve_cash_cannot_post_before_the_reviewed_reserve_start_month(self):
        structure, inputs = annual_project()
        inputs['reserve.operating_monthly_fraction'][('replacement', 11)] = '0'
        inputs['reserve.operating_monthly_fraction'][('replacement', 0)] = '1'
        with self.assertRaises(EngineError) as error:
            calculate(structure, inputs)
        self.assertEqual(error.exception.code, 'RESERVE_DEPOSIT_BEFORE_START')

    def test_closing_only_year_posts_no_operating_cash_or_reserves(self):
        structure, inputs = annual_project(24, 12, False)
        structure = replace(structure, operating_projection=replace(structure.operating_projection,
                            reserve_start_year=2028, reserve_start_month=1))
        inputs['expenses.period_fraction'][2027] = '0'
        inputs['annual_operations.first_operating_fraction'] = '0'
        inputs['annual_operations.first_commercial_fraction'] = '0'
        for group in ('restricted', 'market'):
            for i in range(12):
                inputs['annual_operations.occupied_units'][(group, i)] = '0'
        result = calculate(structure, inputs)
        self.assertEqual(result.value('operations.noi', month=0), Decimal('0'))
        self.assertEqual(result.value('reserve.deposit', reserve='replacement', month=0), Decimal('0'))
        self.assertEqual(result.value('reserve.annual_ending_balance', reserve='replacement', tax_year=2027), Decimal('0'))
        self.assertEqual(result.value('reserve.annual_ending_balance', reserve='replacement', tax_year=2029), Decimal('24'))
        # A positive scheduled reserve amount cannot disappear from an unmodeled operating year.
        bad = replace(structure, operating_projection=replace(structure.operating_projection,
                      reserve_start_year=2027, reserve_start_month=12))
        with self.assertRaises(EngineError) as error:
            calculate(bad, inputs)
        self.assertEqual(error.exception.code, 'RESERVE_AMOUNT_BEFORE_OPERATIONS')
