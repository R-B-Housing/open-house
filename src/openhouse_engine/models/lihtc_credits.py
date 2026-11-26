"""LIHTC credit basis, award caps, delivery and priced equity commitment."""
from .. import const, if_, matches, ref, round_to, sum_over, total
from ..financial import minimum


def declare_credits(m, given):
    for kind in ("acquisition", "rehab"):
        given(f"basis.{kind}_fraction", "ratio", ("cost",), high=1)
        m.check(f"basis.{kind}_excluded", dims=("cost",), where={"basis": "excluded"},
                condition=ref(f"basis.{kind}_fraction") == 0, code="INELIGIBLE_BASIS_ALLOCATION",
                message="Land and reserves cannot enter eligible basis.")
    m.check("basis.allocation", dims=("cost",),
            condition=ref("basis.acquisition_fraction") + ref("basis.rehab_fraction") <= 1,
            code="BASIS_ALLOCATION_EXCEEDS_COST", message="Eligible basis allocations exceed a cost's full amount.")
    given("basis.applicable_fraction", "ratio", high=1)
    given("basis.rehab_boost", "multiple", low=1, high="1.3")
    for name in ("credits.acquisition_rate", "credits.rehab_rate", "credits.investor_share"):
        given(name, "ratio", high=1)
    given("credits.price", "USD/USD-credit", high=2)
    given("equity.rounding_increment", "USD", low="0.01")
    for kind in ("acquisition", "rehab"):
        m.calc(f"basis.{kind}_eligible", unit="USD",
               expr=sum_over("cost", ref("cost.total") * ref(f"basis.{kind}_fraction")))
        m.calc(f"basis.{kind}_qualified", unit="USD",
               expr=ref(f"basis.{kind}_eligible") * ref("basis.applicable_fraction")
                    * (ref("basis.rehab_boost") if kind == "rehab" else 1))
        given(f"credits.{kind}_annual_cap", "USD/year")
        m.calc(f"credits.{kind}_annual", unit="USD/year",
               expr=minimum(ref(f"basis.{kind}_qualified") * ref(f"credits.{kind}_rate"), ref(f"credits.{kind}_annual_cap")))
        given(f"credits.{kind}_qualified_fraction", "ratio", ("credit_month",), high=1)
        m.calc(f"credits.{kind}_first_fraction", unit="ratio",
               expr=sum_over("credit_month", ref(f"credits.{kind}_qualified_fraction")) / 12)
        m.calc(f"credits.{kind}_delivered", unit="USD", dims=("tax_year",),
               expr=ref(f"credits.{kind}_annual") * if_(matches("tax_year", **{kind + "_first": True}),
                   ref(f"credits.{kind}_first_fraction"), if_(matches("tax_year", **{kind + "_regular": True}),
                   const(1), if_(matches("tax_year", **{kind + "_tail": True}),
                   1 - ref(f"credits.{kind}_first_fraction"), const(0)))))
    m.calc("credits.annual", unit="USD/year", expr=total("credits.acquisition_annual", "credits.rehab_annual"))
    m.calc("credits.ten_year_total", unit="USD", expr=ref("credits.annual") * 10)
    m.calc("credits.delivered", unit="USD", dims=("tax_year",),
           expr=total("credits.acquisition_delivered", "credits.rehab_delivered"))
    m.calc("credits.undelivered", unit="USD",
           expr=ref("credits.ten_year_total") - sum_over("tax_year", ref("credits.delivered")))
    m.calc("equity.commitment", unit="USD",
           expr=round_to(ref("credits.ten_year_total") * ref("credits.investor_share")
                         * ref("credits.price") / ref("equity.rounding_increment"), 0) * ref("equity.rounding_increment"))
