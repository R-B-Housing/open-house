"""Funding status distinguishes execution, dated liquidity and residual debt."""
from decimal import Decimal
import unittest

from openhouse_engine.models.lihtc_acquisition_rehab import calculate
from test_lihtc_acquisition_rehab import example


class FundingStatusTest(unittest.TestCase):
    def test_positive_terminal_cash_does_not_hide_an_earlier_funding_gap(self):
        structure, inputs = example()
        inputs['funding.sponsor_equity'][0] = '0'
        run = calculate(structure, inputs)
        self.assertGreater(run.value('funding.final_cash'), 0)
        self.assertEqual(run.value('funding.cash_shortfall', month=0), Decimal('425.30'))
        self.assertEqual(run.value('funding.cash_shortfall', month=4), 0)
        self.assertEqual(run.value('funding.cash_funded'), 0)
        self.assertEqual(run.value('funding.shortfall_months'), 1)
        self.assertEqual(run.value('funding.final_debt_owed'), Decimal('216.66'))

        # A reviewed contribution fixes liquidity; the engine never inserts it.
        inputs['funding.sponsor_equity'][0] = '425.30'
        funded = calculate(structure, inputs)
        self.assertEqual(funded.value('funding.cash_funded'), 1)
        self.assertEqual(funded.value('funding.shortfall_months'), 0)
        self.assertEqual(funded.value('funding.maximum_gap'), 0)
        self.assertEqual(funded.value('funding.ending_cash', month=0), 0)
        self.assertEqual(funded.value('funding.final_debt_owed'), Decimal('216.66'))
