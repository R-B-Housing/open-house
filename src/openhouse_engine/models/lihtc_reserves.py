"""Restricted reserve balances, retained LP cash, and annual opening-balance yield."""

from .. import Dimension, Item, allocate_round, const, if_, matches, previous, ref, sum_over, sum_within


def declare_reserves(m, given, *, deposit=None, exit_month=None):
    names = ("lease_up", "operating", "replacement", "other_1", "other_2")
    m.dimension(Dimension("reserve", [Item(r, reserve_name=r, operating=r == "operating",
                                          other=r in ("other_1", "other_2")) for r in names]))
    given("reserve.opening_balance", "USD", ("reserve",))
    given("reserve.capitalized_fraction", "ratio", ("reserve", "month"), high=1)
    m.check("reserve.capitalized_allocation", dims=("month",), condition=sum_over("reserve", ref("reserve.capitalized_fraction")) == 1,
            code="RESERVE_ALLOCATION_NOT_ONE", message="Capitalized reserve allocations must total one.")
    given("reserve.annual_rate", "ratio", ("reserve", "tax_year"), high=1)
    if deposit is None:
        given("reserve.deposit", "USD", ("reserve", "month"))
    else:
        m.calc("reserve.deposit", unit="USD", dims=("reserve", "month"), expr=deposit)
        m.check("reserve.deposit_nonnegative", dims=("reserve", "month"), condition=ref("reserve.deposit") >= 0,
                code="NEGATIVE_RESERVE_DEPOSIT", message="Scheduled reserve deposits must be nonnegative.")
    for name in ("release", "expenditure"):
        given("reserve." + name, "USD", ("reserve", "month"))
    given("reserve.investor_retained_opening_balance", "USD")
    given("reserve.investor_retained_release", "USD", ("month",))
    designated_release = ref("reserve.investor_retained_release")
    at_exit = (const(0) == 1) if exit_month is None else matches("month", period=exit_month)

    def retained_closing(opening):
        available = opening + ref("funding.retained_investor_cash")
        return if_(at_exit, const(0), available - designated_release)

    m.calc("reserve.investor_retained_balance", unit="USD", dims=("month",),
           expr=previous("reserve.investor_retained_balance", "month",
               initial=retained_closing(ref("reserve.investor_retained_opening_balance")),
               step=retained_closing))
    m.calc("reserve.investor_retained_final_balance", unit="USD",
           expr=sum_over("month", ref("reserve.investor_retained_balance"), last=True))
    m.calc("reserve.investor_retained_opening", unit="USD", dims=("month",),
           expr=previous("reserve.investor_retained_balance", "month",
                         initial=ref("reserve.investor_retained_opening_balance")))
    retained_available = ref("reserve.investor_retained_opening") + ref("funding.retained_investor_cash")
    m.calc("reserve.investor_retained_repayment", unit="USD", dims=("month",),
           expr=retained_available - ref("reserve.investor_retained_balance"))
    m.calc("reserve.investor_exit_release", unit="USD", dims=("month",),
           expr=if_(at_exit, retained_available - designated_release, const(0)))
    m.check("reserve.retained_release_limit", dims=("month",),
            condition=designated_release <= retained_available,
            code="RETAINED_CASH_RELEASE_EXCEEDS_CLAIM", message="Designated investor repayment exceeds retained cash owed.")
    m.check("reserve.retained_opening_coverage",
            condition=ref("reserve.investor_retained_opening_balance")
                <= sum_over("reserve", ref("reserve.opening_balance"), operating=True),
            code="RETAINED_CASH_UNFUNDED", message="Opening investor retained cash exceeds the operating reserve.")
    m.calc("reserve.capitalized_contribution", unit="USD", dims=("reserve", "month"),
           expr=allocate_round(sum_over("cost", ref("cost.amount"), reserves=True) * ref("reserve.capitalized_fraction"), "reserve", 2))
    m.calc("reserve.net_movement", unit="USD", dims=("reserve", "month"),
           expr=ref("reserve.capitalized_contribution") + ref("reserve.deposit") - ref("reserve.release")
                - ref("reserve.expenditure")
                + if_(matches("reserve", operating=True),
                      ref("funding.retained_investor_cash") - ref("reserve.investor_retained_repayment"), const(0)))
    m.calc("reserve.annual_expenditure", unit="USD", dims=("reserve", "tax_year"),
           expr=sum_within("month", ref("reserve.expenditure")))
    m.calc("reserve.annual_net_movement", unit="USD", dims=("reserve", "tax_year"),
           expr=sum_within("month", ref("reserve.net_movement")))

    def closing(opening):
        return opening + opening * ref("reserve.annual_rate") + ref("reserve.annual_net_movement")

    m.calc("reserve.annual_ending_balance", unit="USD", dims=("reserve", "tax_year"),
           expr=previous("reserve.annual_ending_balance", "tax_year",
                         initial=closing(ref("reserve.opening_balance")), step=closing))
    m.calc("reserve.annual_opening_balance", unit="USD", dims=("reserve", "tax_year"),
           expr=previous("reserve.annual_ending_balance", "tax_year", initial=ref("reserve.opening_balance")))
    m.calc("reserve.annual_interest", unit="USD", dims=("reserve", "tax_year"),
           expr=ref("reserve.annual_opening_balance") * ref("reserve.annual_rate"))
    m.calc("reserve.interest", unit="USD", dims=("reserve", "month"),
           expr=if_(matches("month", year_end=True), ref("reserve.annual_interest"), const(0)))
    m.calc("reserve.ending_balance", unit="USD", dims=("reserve", "month"),
           expr=previous("reserve.ending_balance", "month",
                         initial=ref("reserve.opening_balance") + ref("reserve.net_movement") + ref("reserve.interest"),
                         step=lambda p: p + ref("reserve.net_movement") + ref("reserve.interest")))
    m.check("reserve.balance_nonnegative", dims=("reserve", "month"),
            condition=ref("reserve.ending_balance") >= 0, code="RESERVE_OVERDRAWN",
            message="Reserve releases and expenditures exceed available funds.")
    m.check("reserve.retained_coverage", dims=("month",),
            condition=sum_over("reserve", ref("reserve.ending_balance"), operating=True)
                >= ref("reserve.investor_retained_balance"),
            code="RETAINED_CASH_UNFUNDED", message="Operating reserve expenditures cannot consume investor-owned retained cash.")
