"""Investor-owned retained cash follows its owner through release and buyout."""
from dataclasses import replace
from decimal import Decimal
import unittest
from openhouse_engine import EngineError
from openhouse_engine.models.lihtc_acquisition_rehab import calculate
from openhouse_engine.models.lihtc_exit import ExitTerms
from test_lihtc_acquisition_rehab import example


class RetainedCashTest(unittest.TestCase):
    def test_release_repays_investor_before_shared_cash_distribution(self):
        structure, inputs = example()
        inputs['partner.investor_cash_share'] = {m: '.5' for m in range(5)}
        inputs['funding.selected_distribution'] = {m: '100' if m == 3 else '0' for m in range(5)}
        inputs['partner.investor_distribution_fraction'][3] = '0'
        inputs['reserve.investor_retained_release'][4] = '40'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('reserve.investor_retained_balance', month=3), Decimal('50'))
        self.assertEqual(run.value('reserve.investor_retained_repayment', month=4), Decimal('40'))
        self.assertEqual(run.value('partner.distribution', partner='investor', month=4), Decimal('40'))
        self.assertEqual(run.value('partner.distribution', partner='sponsor', month=4), Decimal('0'))
        self.assertEqual(run.value('reserve.investor_retained_balance', month=4), Decimal('10'))

    def test_buyout_settles_retained_cash_once_and_keeps_it_out_of_sale_proceeds(self):
        structure, inputs = example()
        structure = replace(structure, exit_terms=ExitTerms(4))
        inputs.update({'exit.net_sale_cash': '100', 'exit.investor_distribution': '60',
            'exit.investor_outside_basis': '50', 'exit.investor_liability_relief': '20',
            'exit.investor_tax_rate': '.25', 'exit.investor_loss_utilization': '0'})
        inputs['partner.investor_cash_share'] = {m: '.5' for m in range(5)}
        inputs['funding.selected_distribution'] = {m: '100' if m in (3, 4) else '0' for m in range(5)}
        inputs['partner.investor_distribution_fraction'] = {m: '0' for m in range(5)}
        inputs['reserve.investor_retained_release'][4] = '30'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('reserve.investor_retained_repayment', month=4), Decimal('100'))
        self.assertEqual(run.value('reserve.investor_exit_release', month=4), Decimal('70'))
        self.assertEqual(run.value('reserve.investor_retained_balance', month=4), Decimal('0'))
        self.assertEqual(run.value('reserve.ending_balance', reserve='operating', month=4), Decimal('0'))
        self.assertEqual(run.value('partner.distribution', partner='investor', month=4), Decimal('100'))
        self.assertEqual(run.value('partner.distribution', partner='sponsor', month=4), Decimal('50'))
        self.assertEqual(run.value('exit.investor_gain'), Decimal('30'))
        self.assertEqual(run.value('partner.terminal_after_tax_cash', partner='investor', tax_year=2027), Decimal('52'))
        self.assertEqual(run.value('partner.annual_distribution', partner='investor', tax_year=2027), Decimal('100'))

    def test_release_above_claim_leaves_only_surplus_for_project_cash(self):
        structure, inputs = example()
        inputs['reserve.opening_balance']['operating'] = '100'
        inputs['reserve.investor_retained_opening_balance'] = '40'
        inputs['reserve.investor_retained_release'][3] = '40'
        inputs['reserve.release'][('operating', 3)] = '30'
        inputs['partner.investor_cash_share'][3] = '.5'
        inputs['funding.selected_distribution'][3] = '20'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('reserve.investor_retained_repayment', month=3), Decimal('40'))
        self.assertEqual(run.value('partner.distribution', partner='investor', month=3), Decimal('50'))
        self.assertEqual(run.value('partner.distribution', partner='sponsor', month=3), Decimal('10'))
        self.assertEqual(run.value('reserve.ending_balance', reserve='operating', month=3), Decimal('30'))
        self.assertEqual(run.value('reserve.investor_retained_balance', month=3), Decimal('0'))

    def test_operating_expenditures_cannot_spend_investor_owned_cash(self):
        structure, inputs = example()
        inputs['reserve.opening_balance']['operating'] = '100'
        inputs['reserve.investor_retained_opening_balance'] = '40'
        inputs['reserve.expenditure'][('operating', 2)] = '61'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'RETAINED_CASH_UNFUNDED')

    def test_opening_claim_must_be_backed_by_operating_reserve(self):
        structure, inputs = example()
        inputs['reserve.investor_retained_opening_balance'] = '1'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'RETAINED_CASH_UNFUNDED')

    def test_project_reserve_release_can_fund_operations_without_paying_investor(self):
        structure, inputs = example()
        inputs['reserve.opening_balance']['operating'] = '100'
        inputs['reserve.investor_retained_opening_balance'] = '40'
        inputs['reserve.release'][('operating', 3)] = '50'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('reserve.investor_retained_repayment', month=3), Decimal('0'))
        self.assertEqual(run.value('reserve.investor_retained_balance', month=3), Decimal('40'))
        self.assertEqual(run.value('reserve.ending_balance', reserve='operating', month=3), Decimal('50'))

    def test_designated_repayment_cannot_exceed_investor_claim(self):
        structure, inputs = example()
        inputs['reserve.opening_balance']['operating'] = '100'
        inputs['reserve.investor_retained_opening_balance'] = '40'
        inputs['reserve.investor_retained_release'][3] = '41'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'RETAINED_CASH_RELEASE_EXCEEDS_CLAIM')

    def test_returns_require_settlement_of_the_retained_claim(self):
        from examples.lihtc_acquisition_rehab import build_example
        structure, inputs = build_example()
        structure = replace(structure, exit_terms=None)
        inputs = {name:value for name,value in inputs.items() if not name.startswith('exit.')}
        inputs['partner.investor_distribution_fraction'] = {m: '.5' for m in range(181)}
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'UNSETTLED_RETAINED_CASH_RETURN')
