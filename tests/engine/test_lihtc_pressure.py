"""Adversarial synthetic deals exercise the canonical public calculator."""
from dataclasses import replace
from decimal import Decimal
import unittest

from openhouse_engine import EngineError
from openhouse_engine.models.lihtc_acquisition_rehab import calculate
from openhouse_engine.models.lihtc_acquisition_rehab import StraightLineRecovery, TaxAsset
from examples.lihtc_pressure import CASES, EXPECTED_ERRORS, build_pressure_fixture
from test_lihtc_acquisition_rehab import example


class CreditAllocationPressureTest(unittest.TestCase):
    def test_acquisition_credits_cannot_start_before_rehabilitation_credits(self):
        structure, inputs = example(month_count=23, rehab_credit_year=2028)
        with self.assertRaises(EngineError) as error:
            calculate(structure, inputs)
        self.assertEqual(error.exception.code, 'ACQUISITION_CREDIT_BEFORE_REHAB')

    def test_related_minimum_gain_cannot_create_negative_investor_credits(self):
        structure, inputs = example()
        structure = replace(structure, reallocate_losses=True,
                            reduce_credits_for_reallocated_losses=True)
        inputs['minimum_gain.original_asset_basis'] = '100'
        inputs['minimum_gain.reviewed_loan_balance'][('junior', 2027)] = '3000'
        with self.assertRaises(EngineError) as error:
            calculate(structure, inputs)
        self.assertEqual(error.exception.code, 'NEGATIVE_PARTNER_CREDITS')

    def test_related_loss_shift_cannot_allocate_more_credits_than_delivered(self):
        structure, inputs = example()
        structure = replace(structure, reallocate_losses=True,
                            reduce_credits_for_reallocated_losses=True)
        inputs['minimum_gain.original_asset_basis'] = '100'
        inputs['minimum_gain.reviewed_loan_balance'][('senior', 2027)] = '90'
        inputs['minimum_gain.reviewed_loan_balance'][('junior', 2027)] = '50'
        inputs['tax.other_deductions'][2027] = '2500'
        with self.assertRaises(EngineError) as error:
            calculate(structure, inputs)
        self.assertEqual(error.exception.code, 'PARTNER_CREDITS_EXCEED_DELIVERY')


class RecoveryTimingPressureTest(unittest.TestCase):
    def test_generated_recovery_stops_at_the_last_forecast_month(self):
        for service_month, convention, recovered, remaining in (
                (1, 'monthly', '41.67', '158.33'),
                (1, 'mid_month', '37.50', '162.50'),
                (5, 'mid_month', '4.17', '195.83')):
            with self.subTest(service_month=service_month, convention=convention):
                structure, inputs = example()
                structure = replace(structure, tax_assets=(
                    TaxAsset('building', 'depreciation', 2027,
                             StraightLineRecovery(service_month, 24, convention), 2),
                    structure.tax_assets[1]))
                inputs['tax.reviewed_recovery_fraction'][('building', 2027)] = '0'
                run = calculate(structure, inputs)
                # January closing through May, including only the service half-month.
                self.assertEqual(run.value('tax.asset_recovery', tax_asset='building', tax_year=2027),
                                 Decimal(recovered))
                self.assertEqual(run.value('tax.asset_remaining_basis', tax_asset='building'),
                                 Decimal(remaining))

    def test_generated_recovery_respects_forecast_start_and_future_service_months(self):
        for service_month, expected in ((1, '41.67'), (9, '25.00'), (12, '0')):
            with self.subTest(service_month=service_month):
                structure, inputs = example(start_month=7)
                structure = replace(structure, tax_assets=(
                    TaxAsset('building', 'depreciation', 2027,
                             StraightLineRecovery(service_month, 24, 'monthly'), 2),
                    structure.tax_assets[1]))
                inputs['tax.reviewed_recovery_fraction'][('building', 2027)] = '0'
                run = calculate(structure, inputs)
                # July closing through November; no recovery outside those months.
                self.assertEqual(run.value('tax.asset_recovery', tax_asset='building', tax_year=2027),
                                 Decimal(expected))

    def test_pre_payment_interest_remains_visible_even_after_scheduled_principal_matures(self):
        structure, inputs = example(month_count=15)
        structure = replace(structure, permanent_loans=(
            replace(structure.permanent_loans[0], first_payment_month=4),
            structure.permanent_loans[1]))
        inputs['debt.senior.annual_rate'] = '.12'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('debt.senior.interest_accrued', month=3), Decimal('2'))
        self.assertEqual(run.value('debt.senior.ending_balance', month=15), 0)
        self.assertEqual(run.value('debt.senior.accrued_interest_balance', month=15), Decimal('2'))
        self.assertEqual(run.value('debt.senior.total_owed', month=15), Decimal('2'))


class CompleteDealPressureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deals = {}
        for case in CASES:
            if case not in EXPECTED_ERRORS:
                structure, inputs = build_pressure_fixture(case)
                cls.deals[case] = (structure, inputs, calculate(structure, inputs))

    def test_cash_is_conserved_monthly_across_restricted_and_unrestricted_accounts(self):
        reserves = ('lease_up', 'operating', 'replacement', 'other_1', 'other_2')
        facilities = ('bond', 'taxable', 'equity_bridge')
        for case, (structure, inputs, run) in self.deals.items():
            with self.subTest(fixture=case):
                expected = sum(Decimal(v) for v in inputs['reserve.opening_balance'].values())
                for month in range(structure.months + 1):
                    # External receipts less external payments: reserve
                    # deposits/releases and retained LP cash are internal.
                    expected += (run.value('equity.contribution', month=month)
                        + run.value('debt.proceeds', month=month)
                        + Decimal(inputs['funding.sponsor_equity'][month])
                        + Decimal(inputs['funding.other_sources'][month])
                        + run.value('operations.noi', month=month)
                        + run.value('fee.accrual', month=month)
                        - sum(Decimal(inputs['cost.amount'][(c.name, month)])
                              for c in structure.cost_items if c.category != 'reserves')
                        - run.value('debt.debt_service', month=month)
                        - sum(run.value('partner.distribution', partner=p, month=month)
                              for p in ('investor', 'sponsor')))
                    for facility in facilities:
                        expected += (run.value('construction.draw', facility=facility, month=month)
                            - run.value('construction.repayment', facility=facility, month=month)
                            - run.value('construction.cash_interest', facility=facility, month=month))
                    for reserve in reserves:
                        expected += (run.value('reserve.interest', reserve=reserve, month=month)
                            - Decimal(inputs['reserve.expenditure'][(reserve, month)]))
                    actual = run.value('funding.ending_cash', month=month) + sum(
                        run.value('reserve.ending_balance', reserve=r, month=month) for r in reserves)
                    self.assertEqual(actual, expected, f'{case}, month {month}')

    def test_permanent_debt_preserves_every_advance_and_unpaid_interest(self):
        for case, (structure, _, run) in self.deals.items():
            for loan in structure.permanent_loans:
                with self.subTest(fixture=case, loan=loan.name):
                    owed = Decimal(0)
                    for month in range(structure.months + 1):
                        prefix = 'debt.' + loan.name
                        owed += (run.value(prefix + '.advance', month=month)
                            + run.value(prefix + '.interest', month=month)
                            - run.value(prefix + '.interest_paid', month=month)
                            - run.value(prefix + '.principal', month=month))
                        self.assertEqual(run.value(prefix + '.total_owed', month=month), owed)
                        self.assertGreaterEqual(owed, 0)

    def test_stresses_report_gaps_without_inventing_funding(self):
        for case in ('missing_sponsor', 'delayed_equity', 'operating_downturn'):
            with self.subTest(fixture=case):
                _, _, run = self.deals[case]
                self.assertEqual(run.value('funding.cash_funded'), 0)
                self.assertGreater(run.value('funding.maximum_gap'), 0)
                self.assertGreater(run.value('funding.shortfall_months'), 0)
        delayed = self.deals['delayed_equity'][2]
        self.assertGreater(delayed.value('funding.final_cash'), 0)
        self.assertEqual(delayed.value('equity.contribution', month=0), 0)
        self.assertEqual(delayed.value('equity.contribution', month=12), Decimal('633501'))

    def test_retention_moves_cash_into_reserves_without_changing_total_project_cash(self):
        baseline = self.deals['baseline'][2]
        retained = self.deals['retained_cash'][2]
        self.assertEqual(retained.value('funding.final_cash'), baseline.value('funding.final_cash'))
        self.assertEqual(retained.value('reserve.investor_retained_balance', month=179), Decimal('225450'))
        self.assertEqual(retained.value('reserve.investor_retained_repayment', month=180), Decimal('226800'))
        self.assertEqual(retained.value('reserve.ending_balance', reserve='operating', month=180),
                         baseline.value('reserve.ending_balance', reserve='operating', month=180))
        self.assertEqual(sum(baseline.value('partner.distribution', partner='investor', month=m)
            - retained.value('partner.distribution', partner='investor', month=m)
            for m in range(181)), Decimal('0'))

    def test_partial_construction_payoff_keeps_principal_and_lagged_interest_in_exit(self):
        run = self.deals['partial_construction_payoff'][2]
        self.assertEqual(run.value('construction.ending_balance', facility='bond', month=180), Decimal('200000'))
        self.assertEqual(run.value('construction.interest_owed', facility='bond'), Decimal('1000'))
        self.assertEqual(run.value('funding.final_debt_owed'),
            run.value('debt.total_owed', month=180) + Decimal('201000'))
        self.assertEqual(run.value('exit.debt_payoff'), run.value('funding.final_debt_owed'))

    def test_invalid_deals_fail_with_specific_diagnostics(self):
        for case, code in EXPECTED_ERRORS.items():
            with self.subTest(fixture=case):
                structure, inputs = build_pressure_fixture(case)
                with self.assertRaises(EngineError) as error:
                    calculate(structure, inputs)
                self.assertEqual(error.exception.code, code)
