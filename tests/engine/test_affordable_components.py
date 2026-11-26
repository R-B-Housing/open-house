"""Shared affordable-housing components, each checked against an independent calculation."""
from decimal import Decimal
import unittest

from openhouse_engine import Dimension, Item, Model, DecimalPolicy, annual_calendar, const, evaluate, ref
from openhouse_engine.capital_stack import build_gap_source
from openhouse_engine.residual_receipts import (build_accruing_payment, build_cash_flow_note, build_residual_receipts,
                                                  build_simple_interest_balances)

POLICY = DecimalPolicy(precision=34, rounding="ROUND_HALF_UP")
D = Decimal


def model(*dims):
    m = Model("components", "0.0.1", POLICY)
    for dim in dims:
        m.dimension(dim)
    return m


class GapSourceTest(unittest.TestCase):
    def test_closed_form_matches_the_fixed_point_and_caps_report_a_shortfall(self):
        def run(maximum):
            m = model()
            build_gap_source(m, prefix="gap", need=const(30000000), payment_rate=const("0.0042"), maximum=const(maximum),
                             senior_capacity=const(500000), senior_constant=const("0.075"),
                             senior_amount=(const(500000) - const("0.0042") * ref("gap.assumed")) / const("0.075"))
            return evaluate(m, {})
        result = run(99999999)
        senior = 30000000 - result.value("gap.amount")
        # Fixed point: the senior loan's capacity after the gap's own payment.
        self.assertAlmostEqual(senior, (500000 - D("0.0042") * result.value("gap.amount")) / D("0.075"), places=6)
        self.assertAlmostEqual(result.value("gap.surplus"), 0, places=6)
        capped = run(20000000)
        self.assertEqual(capped.value("gap.amount"), 20000000)
        self.assertLess(capped.value("gap.surplus"), 0)


class ResidualReceiptsTest(unittest.TestCase):
    def build(self):
        years = annual_calendar(2025, 3)
        lenders = Dimension("lender", [Item("city", residual=True), Item("state", residual=True), Item("grant", residual=False)])
        m = model(years, lenders)
        m.input("cash", unit="usd", dims=("year",))
        m.input("principal", unit="usd", dims=("lender",))
        fee = build_accruing_payment(m, prefix="fee", period_dim="year", scheduled=const(100), available=ref("cash"))
        note = build_cash_flow_note(m, prefix="note", period_dim="year", principal=const(500), rate=const("0.02"),
                                    available=fee.remaining)
        m.calc("after_note", unit="usd", dims=("year",), expr=note.remaining)
        rr = build_residual_receipts(m, prefix="rr", period_dim="year", lender_dim="lender", principal=ref("principal"),
                                     available=ref("after_note"), lender_share=const("0.5"), residual=True)
        build_simple_interest_balances(m, prefix="soft", lender_dim="lender", period_dim="year",
                                       principal=ref("principal"), rate=const("0.03"), payments=rr.payment)
        return m

    def test_fees_accrue_the_note_compounds_on_unpaid_balance_and_receipts_share_by_principal(self):
        run = evaluate(self.build(), {"cash": {1: "60", 2: "540", 3: "900"},
                                      "principal": {"city": "1000", "state": "3000", "grant": "500"}})
        self.assertEqual(run.value("fee.paid", year=1), 60)
        self.assertEqual(run.value("fee.due", year=2), 140)  # 40 carried forward.
        # Year 1 pays only the fee; the note compounds on its unpaid balance.
        self.assertEqual(run.value("note.closing", year=1), 510)
        self.assertEqual(run.value("note.paid", year=2), 400)
        self.assertEqual(run.value("note.closing", year=2), (510 - 400) * D("1.02"))
        self.assertEqual(run.value("note.paid", year=3), D("112.2"))
        residual = 900 - 100 - D("112.2")
        self.assertEqual(run.value("rr.payment", lender="city", year=3), residual * D("0.5") * D("0.25"))
        self.assertEqual(run.value("rr.payment", lender="grant", year=3), 0)
        self.assertEqual(run.value("rr.partnership", year=3), residual * D("0.5"))
        self.assertEqual(run.value("soft.balance", lender="state", year=3),
                         3000 + 3 * 90 - run.value("rr.payment", lender="state", year=3))


if __name__ == "__main__":
    unittest.main()
