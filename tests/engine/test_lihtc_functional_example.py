"""A complete synthetic deal exercises the public LIHTC calculator."""
from decimal import Decimal
import unittest

from examples.lihtc_acquisition_rehab import build_example
from openhouse_engine.models.lihtc_acquisition_rehab import calculate


class FunctionalExampleTest(unittest.TestCase):
    def test_annual_return_reconciles_all_partner_benefits_and_explicit_buyout(self):
        structure, inputs = build_example()
        self.assertIsNotNone(structure.return_terms)
        self.assertEqual(structure.return_terms.frequency, 'annual')
        run = calculate(structure, inputs)
        flows = run.series('returns.investor_cash_flow')
        years = range(structure.start_year, structure.last_year + 1)
        ordinary = sum((run.value('partner.after_tax_cash_flow', partner='investor', tax_year=y)
                        for y in years), Decimal(0))
        self.assertEqual(sum(flows), ordinary + run.value('exit.investor_after_tax_cash'))
        self.assertEqual(flows[0], -Decimal('633501'))
        signs = [amount > 0 for amount in flows if amount != 0]
        self.assertFalse(signs[0])
        self.assertTrue(signs[-1])
        self.assertEqual(sum(a != b for a, b in zip(signs, signs[1:])), 1)
        rate = run.value('returns.periodic_irr')
        self.assertGreater(rate, Decimal('0'))
        independent_npv = sum((cash / (1 + rate) ** period for period, cash in enumerate(flows)), Decimal(0))
        self.assertAlmostEqual(independent_npv, Decimal('0'), places=12)

    def test_complete_deal_is_funded_and_reconciles_canonical_owners(self):
        structure, inputs = build_example()
        run = calculate(structure, inputs)
        self.assertEqual(run.value('uses.total_development_cost'), Decimal('2172000'))
        self.assertEqual(run.value('basis.acquisition_eligible'), Decimal('1000000'))
        self.assertEqual(run.value('basis.rehab_eligible'), Decimal('750000'))
        self.assertEqual(run.value('equity.commitment'), Decimal('633501'))
        self.assertEqual(sum(run.series('equity.contribution')), Decimal('633501'))
        self.assertEqual(sum(run.series('credits.delivered')), Decimal('711000'))
        self.assertEqual(run.value('funding.maximum_gap'), Decimal('0'))
        self.assertEqual(run.value('funding.cash_funded'), Decimal('1'))
        self.assertEqual(run.value('funding.shortfall_months'), Decimal('0'))
        self.assertTrue(all(amount >= 0 for amount in run.series('funding.ending_cash')))
        self.assertEqual(sum(run.series('fee.accrual')), Decimal('100000'))
        self.assertEqual(sum(run.series('debt.developer_fee.proceeds')), Decimal('0'))
        self.assertEqual(sum(run.series('debt.developer_fee.principal')), Decimal('100000'))
        self.assertEqual(sum(run.series('debt.soft_loan.principal')), Decimal('200000'))
        self.assertEqual(run.value('construction.interest_owed', facility='bond'), Decimal('0'))
        self.assertEqual(run.value('reserve.ending_balance', reserve='operating', month=180), Decimal('100000'))
        self.assertEqual(run.value('reserve.ending_balance', reserve='replacement', month=180), Decimal('175000'))
        self.assertEqual(run.value('tax.asset_basis', tax_asset='acquisition_building'), Decimal('1000000'))
        self.assertEqual(run.value('tax.asset_basis', tax_asset='rehab_building'), Decimal('750000'))
        self.assertEqual(run.value('tax.asset_basis', tax_asset='loan_cost'), Decimal('122000'))
        self.assertGreater(run.value('tax.income', tax_year=2028), Decimal('0'))
        self.assertEqual(run.value('exit.debt_payoff'), run.value('funding.debt_owed', month=180))
        self.assertEqual(run.value('exit.sale_price'), run.value('exit.debt_payoff') + Decimal('500000'))
        # Cash conservation includes reserve deposits once, preserves restricted
        # cash, and excludes both deferred loan advances and buyout valuation.
        expected_cash = (Decimal('633501') + 800000 + 1200000 + 1400000
                         + Decimal('11600') * 180 - (Decimal('2172000') - 100000)
                         - 1200000 - sum(run.series('debt.debt_service'))
                         - 1000 * 180 - 3000 * 168)
        self.assertEqual(run.value('funding.final_cash'), expected_cash)


if __name__ == '__main__':
    unittest.main()
