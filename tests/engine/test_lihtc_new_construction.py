"""LIHTC new construction sizing behavior on the synthetic example deal."""
from decimal import Decimal
import unittest

from openhouse_engine import EngineError
from dataclasses import replace

from openhouse_engine.commercial import CommercialSpace
from openhouse_engine.models.lihtc_new_construction import SoftLoan, calculate
from openhouse_engine.models.lihtc_new_construction_example import build_example


class LihtcNewConstructionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.structure, cls.inputs = build_example()
        cls.base = calculate(cls.structure, cls.inputs)

    def test_sources_close_and_every_reported_test_passes(self):
        self.assertEqual(self.base.value("soft.gap.surplus"), 0)
        self.assertEqual(self.base.value("construction.surplus"), 0)
        self.assertGreater(self.base.value("soft.gap.amount"), 0)
        self.assertGreater(self.base.value("construction.taxable_loan"), 0)
        self.assertTrue(all(test["passed"] for test in self.base.tests.values()), self.base.tests)

    def test_gap_loan_mandatory_payment_is_inside_permanent_loan_sizing(self):
        rate = Decimal(self.inputs["soft.mandatory_rate"]["gap"])
        self.assertEqual(self.base.value("soft.mandatory_payment", soft="gap"), self.base.value("soft.gap.amount") * rate)
        dscr = Decimal(self.inputs["perm.dscr"])
        self.assertGreaterEqual(self.base.value("perm.base_dscr"), dscr)
        # Rounding the loan down to the increment leaves coverage just above the target.
        self.assertLess(self.base.value("perm.base_dscr"), dscr + Decimal("0.005"))

    def test_lender_cap_raises_the_gap_and_a_maximum_award_leaves_a_reported_shortfall(self):
        cap = Decimal(4000000)
        shortfall = self.base.value("perm.amount") - cap
        capped = dict(self.inputs, **{"perm.maximum": str(cap)})
        run = calculate(self.structure, capped)
        self.assertEqual(run.value("perm.amount"), cap)
        self.assertEqual(run.value("soft.gap.amount"), self.base.value("soft.gap.amount") + shortfall)
        award = self.base.value("soft.gap.amount")
        limited = dict(capped, **{"soft.gap_maximum": str(award)})
        run = calculate(self.structure, limited)
        self.assertEqual(run.value("soft.gap.amount"), award)
        self.assertEqual(run.value("soft.gap.surplus"), -shortfall)
        self.assertFalse(run.tests["sources.permanent_funded"]["passed"])

    def test_bond_test_and_threshold_basis_limit_are_reported_not_failed(self):
        run = calculate(self.structure, dict(self.inputs, **{"construction.bond_fraction": "0.45"}))
        self.assertFalse(run.tests["bond.fifty_percent_test"]["passed"])
        self.assertGreater(run.value("construction.taxable_loan"), self.base.value("construction.taxable_loan"))
        run = calculate(self.structure, dict(self.inputs, **{"tbl.unit_limit": {k: "100000" for k in self.inputs["tbl.unit_limit"]}}))
        self.assertFalse(run.tests["tbl.within_limit"]["passed"])

    def test_unpaid_fees_accrue_and_are_paid_first_when_cash_returns(self):
        # Expenses outgrowing rents squeeze later cash flow below the partner fees.
        run = calculate(self.structure, dict(self.inputs, **{"growth.expenses": "0.06"}))
        short = [y for y in range(1, 18) if run.value("waterfall.gp_fee.accrued", year=y) > 0]
        self.assertTrue(short)
        self.assertEqual(run.value("ddf.paid", year=short[0]), 0)

    def test_commercial_space_uses_the_shared_lease_component(self):
        structure = replace(self.structure, commercial_spaces=(CommercialSpace("retail", "Ground-floor retail", 4000, "nnn"),),
                            expense_lines=tuple(replace(e, recoverable=e.key in ("insurance", "real_estate_taxes"))
                                                for e in self.structure.expense_lines))
        inputs = dict(self.inputs, **{
            "commercial.rent": {"retail": "80000"}, "commercial.bump": {"retail": "0.03"},
            "commercial.bump_month": {"retail": "1"}, "commercial.expiry_month": {"retail": "60"},
            "commercial.option_exercised": {"retail": "0"}, "commercial.option_months": {"retail": "0"},
            "commercial.renewal_probability": {"retail": "0.5"}, "commercial.market_rent": {"retail": "20"},
            "commercial.downtime_months": {"retail": "6"}, "commercial.ti": {"retail": "30"},
            "commercial.lc": {"retail": "8"}, "commercial.recovery_share": {"retail": "0.06"},
            "commercial.market_growth": "0.03", "commercial.new_lease_bump": "0.03", "commercial.credit_loss_rate": "0.05"})
        run = calculate(structure, inputs)
        # Year 1: in-place rent (bumped in January of operating year 1) plus NNN recoveries; credit loss is vacancy.
        expenses = self.inputs["expense.amount"]
        recoveries = Decimal("0.06") * (Decimal(expenses["insurance"]) + Decimal(expenses["real_estate_taxes"]))
        self.assertAlmostEqual(run.value("cf.commercial", year=1), 80000 * Decimal("1.03") + recoveries, places=6)
        self.assertGreater(run.value("cf.noi", year=1), self.base.value("cf.noi", year=1))
        # Rollover in month 61 (year 6): leasing costs are capital, out of NOI but out of cash flow.
        self.assertAlmostEqual(run.value("cf.commercial_leasing_costs", year=6), Decimal("0.5") * 4000 * 38, places=6)
        self.assertAlmostEqual(run.value("cf.cash_flow", year=6),
                               run.value("cf.net_remaining", year=6) - run.value("perm.debt_service", year=6)
                               - run.value("cf.commercial_leasing_costs", year=6), places=6)
        # More base-year income sizes a larger permanent loan and a smaller gap.
        self.assertGreater(run.value("perm.amount"), self.base.value("perm.amount"))
        self.assertLess(run.value("soft.gap.amount"), self.base.value("soft.gap.amount"))

    def test_invalid_structure_and_inputs_fail_explicitly(self):
        loans = tuple(SoftLoan(s.key, s.label, s.construction, s.residual_receipts, False) for s in self.structure.soft_loans)
        with self.assertRaisesRegex(ValueError, "gap loan"):
            calculate(type(self.structure)(**{**self.structure.__dict__, "soft_loans": loans}), self.inputs)
        bad = dict(self.inputs, **{"basis.eligible_fraction": dict(self.inputs["basis.eligible_fraction"], land="0.5")})
        with self.assertRaises(EngineError) as raised:
            calculate(self.structure, bad)
        self.assertEqual(raised.exception.code, "INELIGIBLE_BASIS_ALLOCATION")


if __name__ == "__main__":
    unittest.main()
