"""Public project timing tests use synthetic assumptions only."""
from dataclasses import replace
from decimal import Decimal
import unittest

from openhouse_engine import EngineError, ModelDefinitionError
from openhouse_engine.models.lihtc_acquisition_rehab import ConstructionTiming, calculate
from test_lihtc_acquisition_rehab import example


class ConstructionTimingTest(unittest.TestCase):
    def test_distinct_completion_payoff_and_permanent_funding_reconcile_cost_cash_and_tax(self):
        structure, inputs = example(month_count=6)
        loans = tuple(replace(loan, advance_month=5, first_payment_month=5)
                      if loan.name == 'senior' else loan for loan in structure.permanent_loans)
        structure = replace(structure, permanent_loans=loans,
            construction_timing=ConstructionTiming(2, 4, 2, 1, 5))
        inputs['tax.construction_deductible_interest_fraction'] = {
            (f, m): '.5' for f in ('bond', 'taxable', 'equity_bridge') for m in range(7)}
        inputs['tax.asset_cost_fraction'][('financing', 'loan_cost')] = '1'
        inputs['operations.expenses'] = {m: '899' for m in range(7)}
        inputs['debt.developer_fee.cash_flow_fraction'] = {m: '1' for m in range(7)}
        run = calculate(structure, inputs)
        self.assertEqual(run.value('cost.total', cost='financing'), Decimal('4'))
        self.assertEqual(run.value('tax.asset.gross_basis', tax_asset='loan_cost'), Decimal('14'))
        self.assertEqual(run.value('construction.capitalized_interest', facility='bond', month=1), Decimal('2'))
        self.assertEqual(run.value('construction.operating_interest', facility='bond', month=2), Decimal('2'))
        self.assertEqual(run.value('construction.cash_interest', facility='bond', month=0), Decimal('0'))
        self.assertEqual(run.value('construction.cash_interest', facility='bond', month=4), Decimal('2'))
        self.assertEqual(run.value('construction.ending_interest_payable', facility='bond', month=3), Decimal('2'))
        self.assertEqual(run.value('construction.ending_interest_payable', facility='bond', month=6), Decimal('0'))
        self.assertEqual(run.value('construction.repayment', facility='bond', month=4), Decimal('200'))
        self.assertEqual(run.value('debt.proceeds', month=4), Decimal('0'))
        self.assertEqual(run.value('debt.proceeds', month=5), Decimal('200'))
        self.assertEqual(run.value('funding.uses', month=4), Decimal('202'))
        self.assertEqual(run.value('funding.ending_cash', month=4), Decimal('-.60'))
        self.assertEqual(run.value('funding.maximum_gap'), Decimal('.60'))
        self.assertEqual(run.value('fee.repayment', month=3), Decimal('0'))
        self.assertEqual(run.value('fee.repayment', month=4), Decimal('0'))
        self.assertEqual(run.value('tax.interest', tax_year=2027), Decimal('2'))
        self.assertEqual(run.value('tax.income', tax_year=2027), Decimal('-30'))

    def test_unpaid_interest_stays_a_liability_in_terminal_valuation(self):
        from openhouse_engine.models.lihtc_exit import ExitTerms
        structure, inputs = example()
        structure = replace(structure, construction_timing=ConstructionTiming(2, 3, 2, 12),
                            exit_terms=ExitTerms(4))
        inputs.update({'exit.net_sale_cash': '1', 'exit.investor_distribution': '1',
                       'exit.investor_outside_basis': '100', 'exit.investor_liability_relief': '0',
                       'exit.investor_loss_utilization': '0', 'exit.investor_tax_rate': '.25'})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('construction.interest_owed', facility='bond'), Decimal('6'))
        self.assertEqual(run.value('construction.cash_interest', facility='bond', month=4), Decimal('0'))
        terminal_debt = run.value('debt.total_owed', month=4) + Decimal('6')
        self.assertEqual(run.value('exit.debt_payoff'), terminal_debt)
        self.assertEqual(run.value('funding.debt_owed', month=4), terminal_debt)
        self.assertEqual(run.value('funding.final_debt_owed'), terminal_debt)
        self.assertEqual(run.value('exit.sale_price'), terminal_debt + 1)

    def test_reviewed_partial_payoff_preserves_residual_principal_and_interest(self):
        structure, inputs = example()
        structure = replace(structure, construction_timing=ConstructionTiming(2, 3, 2, 0,
                                                                             repayment='reviewed_amount'))
        inputs['construction.settlement_amount'] = {'bond': '150', 'taxable': '0', 'equity_bridge': '0'}
        run = calculate(structure, inputs)
        self.assertEqual(run.value('construction.repayment', facility='bond', month=3), Decimal('150'))
        self.assertEqual(run.value('construction.ending_balance', facility='bond', month=4), Decimal('50'))
        self.assertEqual(run.value('construction.operating_interest', facility='bond', month=4), Decimal('.50'))
        self.assertEqual(run.value('funding.debt_owed', month=4), run.value('debt.total_owed', month=4) + 50)
        self.assertEqual(run.value('funding.final_debt_owed'), run.value('debt.total_owed', month=4) + 50)
        self.assertEqual(run.value('funding.uses', month=3), Decimal('167.17'))

    def test_reviewed_closing_month_operations_enter_cash_and_tax_once(self):
        structure, inputs = example()
        ordinary = calculate(structure, inputs)
        operating = calculate(replace(structure, closing_month_operations=True), inputs)
        self.assertEqual(operating.value('operations.noi', month=0), Decimal('600'))
        self.assertEqual(operating.value('tax.noi', tax_year=2027) - ordinary.value('tax.noi', tax_year=2027), Decimal('600'))
        self.assertEqual(operating.value('funding.final_cash') - ordinary.value('funding.final_cash'), Decimal('600'))

    def test_reviewed_cost_cutoff_allows_conversion_month_cost_without_date_shift(self):
        structure, inputs = example()
        structure = replace(structure, development_cost_end_month=4)
        inputs['cost.amount'][('rehab_soft', 3)] = '10'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('cost.total', cost='rehab_soft'), Decimal('10'))
        self.assertEqual(run.value('funding.uses', month=3), Decimal('226.67'))
        inputs['cost.amount'][('rehab_soft', 4)] = '1'
        with self.assertRaises(EngineError) as error:
            calculate(structure, inputs)
        self.assertEqual(error.exception.code, 'COST_AFTER_DEVELOPMENT_CUTOFF')
