"""LIHTC new construction (ground-up) sizing model, California 4% bond / state credit convention.

An annual sources-and-uses sizing model laid out like a California 4% bond /
state credit application workbook. It is an assembly of shared components:

| Step | Component |
|---|---|
| Years 1..N from placed in service | `calendar.annual_calendar` |
| Unit mix, applicable fraction, TCAC limit, credits, equity | `models.lihtc_tcac` |
| Net rent: market bounded by the TCAC limit less utility allowance | `rents.rent_target` |
| Commercial space under its own leases (monthly, summed into years) | `commercial` |
| NOI and cash before debt | `operating.build_noi`, `build_operating_projection`, `build_operating_cash_flow` |
| DSCR-sized permanent loan with fees, prior payments, rounding, cap | `debt.build_payment_terms`, `build_loan_sizing` |
| Gap loan whose own mandatory payment constrains the permanent loan | `capital_stack.build_gap_source` |
| Monthly amortization reported by year, partial first year | `debt.build_period_amortization` |
| Partner fees, deferred fee, residual receipts, soft-loan balances | `residual_receipts` |

What remains here is the policy that joins them: cost-line basis and 50%
test allocations, the developer fee split, construction sources (bonds sized
to the 50% test, a taxable tail closing the gap) and the reported TCAC tests.

Not modeled (0.1.0): the TCAC developer-fee formula (the reviewed limit is an
input), construction interest (a reviewed cost line), CDLAC tiebreaker and
scoring, partnership tax allocations, exit and investor returns. The
acquisition/rehab model owns monthly construction, partnership and exit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .. import (Model, DecimalPolicy, Dimension, Item, annual_calendar, attr, const, evaluate, if_, matches, max_,
                min_, monthly_calendar, power, ref, round_to, sum_over, sum_within)
from .. import commercial as leases
from ..capital_stack import build_gap_source
from ..commercial import CommercialSpace
from ..debt import build_loan_sizing, build_payment_terms, build_period_amortization
from ..operating import build_noi, build_operating_cash_flow, build_operating_projection
from ..rents import rent_target
from ..residual_receipts import (build_accruing_payment, build_cash_flow_note, build_residual_receipts,
                                 build_simple_interest_balances)
from .lihtc_tcac import (UnitType, declare_credits_and_equity, declare_qualified_basis,
                         declare_threshold_basis_limit, declare_unit_mix, unit_dimension)

MODEL_ID = "lihtc-new-construction"
MODEL_VERSION = "0.1.0"
POLICY = DecimalPolicy(precision=34, rounding="ROUND_HALF_UP")
COST_CATEGORIES = ("land", "acquisition", "hard", "soft", "financing", "reserve", "developer_fee")
EXPENSE_KINDS = ("operating", "property_tax")
TOLERANCE = const("0.005")
__all__ = ("CommercialSpace", "CostItem", "ExpenseLine", "SoftLoan", "Structure", "UnitType", "build", "calculate")


@dataclass(frozen=True)
class CostItem:
    key: str
    label: str
    category: str


@dataclass(frozen=True)
class ExpenseLine:
    key: str
    label: str
    kind: str  # operating (standard inflator) | property_tax
    recoverable: bool = False  # Reimbursed by NNN commercial tenants (taxes, insurance).


@dataclass(frozen=True)
class SoftLoan:
    """A public soft loan or grant. Exactly one is the gap loan."""
    key: str
    label: str
    construction: bool  # Funds at construction closing; otherwise at conversion.
    residual_receipts: bool  # Shares residual receipts pro rata by principal.
    gap: bool = False


@dataclass(frozen=True)
class Structure:
    unit_types: tuple[UnitType, ...]
    cost_items: tuple[CostItem, ...]
    expense_lines: tuple[ExpenseLine, ...]
    soft_loans: tuple[SoftLoan, ...]
    years: int  # Operating years from the placed-in-service year.
    first_year: int  # Calendar year of operating year 1.
    commercial_spaces: tuple[CommercialSpace, ...] = field(default=())


def _validate(s: Structure) -> None:
    def unique(rows, what):
        if not rows or len({r.key for r in rows}) != len(rows):
            raise ValueError(f"{what} keys must be present and unique.")
    unique(s.cost_items, "Cost item")
    unique(s.expense_lines, "Expense line")
    unique(s.soft_loans, "Soft loan")
    if any(c.category not in COST_CATEGORIES for c in s.cost_items):
        raise ValueError("Unknown cost category.")
    if sum(c.category == "developer_fee" for c in s.cost_items) != 1:
        raise ValueError("Exactly one cost item is the developer fee.")
    if any(e.kind not in EXPENSE_KINDS for e in s.expense_lines):
        raise ValueError("Unknown expense kind.")
    if sum(loan.gap for loan in s.soft_loans) != 1:
        raise ValueError("Exactly one soft loan is the gap loan.")
    if not 1 <= s.years <= 40 or not 1900 <= s.first_year <= 2300:
        raise ValueError("Cash flow years must be 1-40 from a valid calendar year.")


def build(s: Structure) -> Model:
    _validate(s)
    m = Model(MODEL_ID, MODEL_VERSION, POLICY)
    m.dimension(unit_dimension(s.unit_types))
    m.dimension(Dimension("cost", [Item(c.key, label=c.label, category=c.category) for c in s.cost_items]))
    m.dimension(Dimension("expense", [Item(e.key, label=e.label, kind=e.kind, recoverable=e.recoverable)
                                      for e in s.expense_lines]))
    m.dimension(Dimension("soft", [Item(loan.key, label=loan.label, construction=loan.construction,
                                        residual_receipts=loan.residual_receipts, gap=loan.gap)
                                   for loan in s.soft_loans]))
    m.dimension(annual_calendar(s.first_year, s.years))
    if s.commercial_spaces:
        m.dimension(leases.space_dimension(s.commercial_spaces))
        # Month 0 is 31 December before operating year 1; month i falls in operating year ceil(i / 12).
        # Months nest under their year (closing under year 1, where it earns nothing) so a year sums its own months.
        months = monthly_calendar(date(s.first_year - 1, 12, 31), s.years * 12)
        m.dimension(Dimension("month", [Item(i.key, **i.attrs, year=max(i.attrs["hold_year"], 1)) for i in months.items],
                              parent="year"))
    _rents(m)
    _costs(m)
    declare_qualified_basis(m, _given(m), eligible_basis=ref("basis.eligible"))
    declare_threshold_basis_limit(m, _given(m), eligible_basis=ref("basis.eligible"),
                                  cost_containment_basis=ref("basis.eligible") + ref("fee.deferred")
                                  + ref("equity.gp_fee_contribution"))
    declare_credits_and_equity(m, _given(m))
    _equity(m)
    _operations(m, bool(s.commercial_spaces))
    terms = _sources(m)
    _cash_flow(m, s.years, terms)
    return m


def calculate(s: Structure, inputs):
    return evaluate(build(s), inputs)


def _given(m):
    def given(name, unit, dims=(), low=0, high=None, where=None):
        m.input(name, unit=unit, dims=dims, minimum=low, maximum=high, where=where)
    return given


def _rents(m):
    ut, given = ("unit_type",), _given(m)
    declare_unit_mix(m, given)
    for name in ("rent.market", "rent.gross_limit", "rent.utility_allowance", "subsidy.contract_rent"):
        given(name, "usd/unit-month", ut)
    given("subsidy.units", "units", ut)
    m.check("rent.allowance", dims=ut, condition=ref("rent.utility_allowance") <= ref("rent.gross_limit"),
            code="ALLOWANCE_EXCEEDS_RENT", message="A utility allowance exceeds its gross rent limit.")
    m.check("subsidy.units_available", dims=ut, condition=ref("subsidy.units") <= ref("units"),
            code="SUBSIDY_UNITS_EXCEED_UNITS", message="Subsidized units exceed the unit type's units.")
    m.calc("rent.net", unit="usd/unit-month", dims=ut,
           expr=rent_target(ref("rent.market"), net_ceiling=ref("rent.gross_limit") - ref("rent.utility_allowance")))
    m.calc("rent.annual", unit="usd/year", dims=ut, expr=ref("units") * ref("rent.net") * 12)
    m.calc("subsidy.increment", unit="usd/unit-month", dims=ut,
           expr=max_(ref("subsidy.contract_rent") - ref("rent.net"), 0))
    m.calc("subsidy.annual", unit="usd/year", dims=ut, expr=ref("subsidy.units") * ref("subsidy.increment") * 12)


def _costs(m):
    c, given = ("cost",), _given(m)
    given("cost.amount", "usd", c)
    given("basis.eligible_fraction", "ratio", c, high=1)
    given("basis.bond_test_fraction", "ratio", c, high=1)
    given("cost.deferred_to_conversion", "usd", c)
    for category in ("land", "reserve"):
        m.check(f"basis.{category}_ineligible", dims=c, where={"category": category},
                condition=ref("basis.eligible_fraction") == 0, code="INELIGIBLE_BASIS_ALLOCATION",
                message="Land and reserves cannot enter eligible basis.")
    m.check("cost.deferral", dims=c, condition=ref("cost.deferred_to_conversion") <= ref("cost.amount"),
            code="DEFERRAL_EXCEEDS_COST", message="A cost deferred to conversion exceeds the cost.")
    m.calc("uses.total_development_cost", unit="usd", expr=sum_over("cost", ref("cost.amount")))
    m.calc("uses.per_unit", unit="usd/unit", expr=ref("uses.total_development_cost") / ref("units.total"))
    for category in COST_CATEGORIES:
        m.calc(f"uses.{category}", unit="usd", expr=sum_over("cost", ref("cost.amount"), category=category))
    m.calc("basis.eligible_cost", unit="usd", dims=c, expr=ref("cost.amount") * ref("basis.eligible_fraction"))
    m.calc("basis.eligible", unit="usd", expr=sum_over("cost", ref("basis.eligible_cost")))
    m.calc("bond.test_basis", unit="usd", expr=sum_over("cost", ref("cost.amount") * ref("basis.bond_test_fraction")))
    m.calc("cost.deferred_total", unit="usd", expr=sum_over("cost", ref("cost.deferred_to_conversion")))

    # Developer fee: cash fee is the reviewed limit; the rest is deferred or contributed by the GP.
    for name in ("fee.limit", "fee.cash", "equity.gp_fee_contribution", "equity.gp_other_contribution"):
        given(name, "usd")
    m.calc("fee.total", unit="usd", expr=ref("uses.developer_fee"))
    m.calc("fee.deferred", unit="usd", expr=ref("fee.total") - ref("fee.cash") - ref("equity.gp_fee_contribution"))
    m.check("fee.deferred_nonnegative", condition=ref("fee.deferred") >= 0, code="FEE_OVERPAID",
            message="Cash fee and GP fee contribution exceed the developer fee.")
    m.test("fee.within_limit", condition=ref("fee.total") <= ref("fee.limit"), code="FEE_ABOVE_LIMIT",
           message="The developer fee exceeds the most restrictive limit.")


def _equity(m):
    given = _given(m)
    given("equity.syndication_costs", "usd")
    given("equity.construction_fraction", "ratio", high=1)
    m.calc("equity.net_of_syndication", unit="usd", expr=ref("equity.investor") - ref("equity.syndication_costs"))
    m.calc("equity.construction", unit="usd",
           expr=round_to(ref("equity.investor") * ref("equity.construction_fraction"), 0))


def _operations(m, has_spaces):
    given, y = _given(m), ("year",)
    given("income.other_annual", "usd/year")
    for name in ("vacancy.residential", "vacancy.subsidy"):
        given(name, "ratio", high=1)
    given("expense.amount", "usd/year", ("expense",))
    given("reserve.replacement_annual", "usd/year")
    for name in ("growth.rent", "growth.subsidy", "growth.expenses", "growth.property_tax", "growth.reserve"):
        given(name, "ratio/year", low="-0.2", high="0.5")

    # Each expense line grows at its kind's rate from the base year.
    def expense_growth(period):
        return if_(matches("expense", kind="property_tax"), power(1 + ref("growth.property_tax"), period - 1),
                   power(1 + ref("growth.expenses"), period - 1))

    if has_spaces:
        leases.declare_inputs(m)
        hold = attr("month", "hold_year")
        m.calc("commercial.recoverable_costs", unit="usd", dims=("month",),
               expr=if_(hold > 0, sum_over("expense", ref("expense.amount") * expense_growth(hold), recoverable=True) / 12, 0))
        income = leases.build_commercial_income(
            m, period_index=attr("month", "index"), month_of_year=attr("month", "month_of_year"),
            active=if_(hold > 0, 1, 0), recoverable_costs=ref("commercial.recoverable_costs"))
        in_year = lambda body: sum_within("month", body)
        commercial, credit_loss, leasing = (in_year(income.base_rent + income.recoveries), in_year(income.credit_loss),
                                            in_year(income.leasing_costs))
    else:
        commercial = credit_loss = leasing = const(0)

    idx = attr("year", "index")
    grow = lambda name: power(1 + ref(name), idx - 1)
    m.calc("cf.residential_rent", unit="usd", dims=y, expr=sum_over("unit_type", ref("rent.annual")) * grow("growth.rent"))
    m.calc("cf.subsidy", unit="usd", dims=y, expr=sum_over("unit_type", ref("subsidy.annual")) * grow("growth.subsidy"))
    m.calc("cf.other_income", unit="usd", dims=y, expr=ref("income.other_annual") * grow("growth.rent"))
    m.calc("cf.commercial", unit="usd", dims=y, expr=commercial)
    m.calc("cf.gross_income", unit="usd", dims=y,
           expr=ref("cf.residential_rent") + ref("cf.subsidy") + ref("cf.other_income") + ref("cf.commercial"))
    m.calc("cf.vacancy", unit="usd", dims=y,
           expr=ref("vacancy.residential") * (ref("cf.residential_rent") + ref("cf.other_income"))
           + ref("vacancy.subsidy") * ref("cf.subsidy") + credit_loss)
    m.calc("cf.effective_gross_income", unit="usd", dims=y, expr=ref("cf.gross_income") - ref("cf.vacancy"))
    m.calc("cf.operating_expenses", unit="usd", dims=y,
           expr=sum_over("expense", ref("expense.amount"), kind="operating") * grow("growth.expenses"))
    m.calc("cf.property_tax", unit="usd", dims=y,
           expr=sum_over("expense", ref("expense.amount"), kind="property_tax") * grow("growth.property_tax"))
    projection = build_operating_projection(
        m, period_dim="year", units=ref("units.total"),
        income_lines=(ref("cf.residential_rent"), ref("cf.subsidy"), ref("cf.other_income"), ref("cf.commercial"),
                      -ref("cf.vacancy")),
        expense_lines=(ref("cf.operating_expenses"), ref("cf.property_tax")),
        income=ref("cf.effective_gross_income"), expenses=ref("cf.operating_expenses") + ref("cf.property_tax"),
        noi_name="cf.noi")
    m.calc("cf.replacement_reserve", unit="usd", dims=y, expr=ref("reserve.replacement_annual") * grow("growth.reserve"))
    build_operating_cash_flow(m, projection=projection, reserves=ref("cf.replacement_reserve"), name="cf.cash_before_debt")
    # TI and leasing commissions are capital paid from cash flow, never NOI.
    m.calc("cf.commercial_leasing_costs", unit="usd", dims=y, expr=leasing)

    # The base year is operating year 1 untrended, which sizes the permanent loan.
    first = lambda name: sum_over("year", if_(idx == 1, ref(name), 0))
    m.calc("base.residential_rent", unit="usd/year", expr=first("cf.residential_rent"))
    m.calc("base.subsidy", unit="usd/year", expr=first("cf.subsidy"))
    m.calc("base.effective_gross_income", unit="usd/year", expr=first("cf.effective_gross_income"))
    m.calc("base.operating_expenses", unit="usd/year", expr=sum_over("expense", ref("expense.amount")))
    m.calc("base.total_expenses", unit="usd/year",
           expr=ref("base.operating_expenses") + ref("reserve.replacement_annual"))
    m.calc("base.expenses_per_unit", unit="usd/unit-year", expr=ref("base.total_expenses") / ref("units.total"))
    build_noi(m, income=ref("base.effective_gross_income"), expenses=ref("base.total_expenses"),
              name="base.net_available_income")


def _sources(m):
    given, s = _given(m), ("soft",)
    given("soft.amount", "usd", s, where={"gap": False})
    given("soft.gap_maximum", "usd")
    given("soft.rate", "ratio/year", s, high="0.2")
    given("soft.mandatory_rate", "ratio/year", s, high="0.2")
    given("soft.mandatory_first_year", "year", low=1)
    given("perm.annual_rate", "ratio/year", low="0.0001", high="0.3")
    given("perm.fee_rate", "ratio/year", high="0.05")
    given("perm.dscr", "ratio", low=1, high=5)
    given("perm.amortization_years", "years", low=1, high=50)
    given("perm.rounding", "usd", low=1)
    given("perm.maximum", "usd")
    given("perm.first_year_months", "months", low=0, high=12)
    given("perm.fee_first_year", "year", low=1)
    given("construction.bond_fraction", "ratio", high=1)
    given("construction.bond_test_minimum", "ratio", high=1)
    for name in ("soft.mandatory_first_year", "perm.amortization_years", "perm.first_year_months", "perm.fee_first_year"):
        m.check(f"{name}.whole", condition=ref(name) == round_to(ref(name), 0), code="EVENT_NOT_WHOLE",
                message=f"{name} must be a whole number.")

    m.calc("sources.before_perm_and_gap", unit="usd",
           expr=sum_over("soft", ref("soft.amount"), gap=False) + ref("fee.deferred")
           + ref("equity.gp_fee_contribution") + ref("equity.gp_other_contribution") + ref("equity.investor"))
    m.calc("sources.need", unit="usd", expr=ref("uses.total_development_cost") - ref("sources.before_perm_and_gap"))
    fixed = sum_over("soft", ref("soft.amount") * ref("soft.mandatory_rate"), gap=False)
    gap_rate = sum_over("soft", ref("soft.mandatory_rate"), gap=True)
    m.calc("perm.capacity_before_gap", unit="usd/year", expr=ref("base.net_available_income") / ref("perm.dscr") - fixed)
    gap = build_gap_source(m, prefix="soft.gap", need=ref("sources.need"), payment_rate=gap_rate,
                           maximum=ref("soft.gap_maximum"), senior_capacity=ref("perm.capacity_before_gap"),
                           senior_constant=ref("perm.annual_constant"), senior_amount=ref("perm.amount"))
    terms = build_payment_terms(m, prefix="perm", annual_rate=ref("perm.annual_rate"),
                                amort_years=ref("perm.amortization_years"))
    build_loan_sizing(m, prefix="perm", income=ref("base.net_available_income"), value=None, max_ltv=None,
                      min_dscr=ref("perm.dscr"), payment_constant=terms.payment_constant, fee_rate=ref("perm.fee_rate"),
                      prior_payments=fixed + gap_rate * gap.assumed, increment=ref("perm.rounding"),
                      maximum=ref("perm.maximum"))
    m.calc("soft.principal", unit="usd", dims=s, expr=if_(matches("soft", gap=True), gap.amount, ref("soft.amount")))
    m.calc("soft.total", unit="usd", expr=sum_over("soft", ref("soft.principal")))
    m.calc("soft.mandatory_payment", unit="usd/year", dims=s, expr=ref("soft.principal") * ref("soft.mandatory_rate"))
    m.calc("perm.annual_payment", unit="usd/year", expr=12 * terms.payment_constant * ref("perm.amount"))
    m.calc("perm.annual_fee", unit="usd/year", expr=ref("perm.amount") * ref("perm.fee_rate"))
    m.calc("perm.noi_for_debt", unit="usd/year",
           expr=ref("base.net_available_income") - ref("perm.dscr") * sum_over("soft", ref("soft.mandatory_payment")))
    m.calc("perm.base_dscr", unit="ratio",
           expr=if_(ref("perm.amount") > 0, ref("perm.noi_for_debt") / (ref("perm.annual_payment") + ref("perm.annual_fee")), 0))
    m.test("perm.dscr_met", condition=ref("perm.base_dscr") >= ref("perm.dscr") - const("0.0001"), code="DSCR_BELOW_TARGET",
           message="Base-year debt service coverage is below the sizing DSCR.")
    m.test("sources.permanent_funded", condition=gap.surplus >= -TOLERANCE, code="PERMANENT_SHORTFALL",
           message="Permanent sources fall short of total development cost; the gap loan is at its maximum.")
    m.test("sources.permanent_balanced", condition=gap.surplus <= TOLERANCE, code="PERMANENT_SURPLUS",
           message="Permanent sources exceed total development cost without the gap loan.")

    # Construction sources; the taxable tail closes the gap.
    m.calc("construction.bond_loan", unit="usd", expr=round_to(ref("bond.test_basis") * ref("construction.bond_fraction"), 0))
    m.calc("construction.soft", unit="usd", expr=sum_over("soft", ref("soft.principal"), construction=True))
    m.calc("construction.before_tail", unit="usd",
           expr=ref("construction.bond_loan") + ref("construction.soft") + ref("cost.deferred_total") + ref("fee.deferred")
           + ref("equity.gp_fee_contribution") + ref("equity.gp_other_contribution") + ref("equity.construction"))
    m.calc("construction.taxable_loan", unit="usd",
           expr=max_(ref("uses.total_development_cost") - ref("construction.before_tail"), 0))
    m.calc("construction.surplus", unit="usd",
           expr=ref("construction.before_tail") + ref("construction.taxable_loan") - ref("uses.total_development_cost"))
    m.test("construction.balanced", condition=ref("construction.surplus") <= TOLERANCE, code="CONSTRUCTION_SURPLUS",
           message="Construction sources exceed cost before any taxable loan.")
    m.calc("bond.test_ratio", unit="ratio", expr=ref("construction.bond_loan") / ref("bond.test_basis"))
    m.test("bond.fifty_percent_test", condition=ref("bond.test_ratio") >= ref("construction.bond_test_minimum"),
           code="BOND_TEST_FAILED", message="Tax-exempt bonds are below the required share of aggregate basis and land.")
    return terms


def _cash_flow(m, years, terms):
    given, y = _given(m), ("year",)
    for party in ("lp", "gp"):
        given(f"waterfall.{party}_fee", "usd/year")
        given(f"waterfall.{party}_fee_growth", "ratio/year", high="0.2")
        given(f"waterfall.{party}_fee_growth_years", "years", high=40)
        given(f"waterfall.{party}_fee_later_growth", "ratio/year", high="0.2")
        m.check(f"waterfall.{party}_fee_growth_years.whole",
                condition=ref(f"waterfall.{party}_fee_growth_years") == round_to(ref(f"waterfall.{party}_fee_growth_years"), 0),
                code="EVENT_NOT_WHOLE", message="Fee growth years must be whole.")
    given("waterfall.first_year_fraction", "ratio", high=1)
    given("waterfall.deferred_fee_rate", "ratio/year", high="0.2")
    given("waterfall.lender_share", "ratio", high=1)
    given("waterfall.gp_residual_share", "ratio", high=1)
    given("tcac.minimum_dscr", "ratio", low=1, high=5)
    given("tcac.cash_flow_limit", "ratio", high=1)
    given("tcac.gross_income_limit", "ratio", high=1)

    idx = attr("year", "index")
    m.calc("cf.mandatory_payments", unit="usd", dims=y,
           expr=if_(idx >= ref("soft.mandatory_first_year"), sum_over("soft", ref("soft.mandatory_payment")), 0))
    m.calc("cf.net_remaining", unit="usd", dims=y, expr=ref("cf.cash_before_debt") - ref("cf.mandatory_payments"))

    perm = build_period_amortization(
        m, prefix="perm", period_dim="year", amount=ref("perm.amount"),
        terms=terms, months=if_(idx == 1, ref("perm.first_year_months"), 12),
        fee=if_(idx >= ref("perm.fee_first_year"), ref("perm.annual_fee"), 0))
    m.calc("cf.cash_flow", unit="usd", dims=y,
           expr=ref("cf.net_remaining") - perm.debt_service - ref("cf.commercial_leasing_costs"))
    m.calc("cf.dscr", unit="ratio", dims=y,
           expr=if_(perm.debt_service > 0, ref("cf.net_remaining") / perm.debt_service, 0))
    m.calc("cf.cash_flow_to_gross", unit="ratio", dims=y,
           expr=if_(ref("cf.gross_income") > 0, ref("cf.cash_flow") / ref("cf.gross_income"), 0))
    m.calc("cf.cash_flow_to_debt_service", unit="ratio", dims=y,
           expr=if_(perm.debt_service > 0, ref("cf.cash_flow") / perm.debt_service, 0))

    # Partner fees (each steps up at its growth rate for its growth years, then its later rate),
    # then the deferred fee, then residual receipts.
    t, first = idx - 1, if_(idx == 1, ref("waterfall.first_year_fraction"), 1)
    available = max_(ref("cf.cash_flow"), 0)
    for party in ("lp", "gp"):
        early = min_(t, ref(f"waterfall.{party}_fee_growth_years"))
        scheduled = (ref(f"waterfall.{party}_fee") * power(1 + ref(f"waterfall.{party}_fee_growth"), early)
                     * power(1 + ref(f"waterfall.{party}_fee_later_growth"), t - early) * first)
        available = build_accruing_payment(m, prefix=f"waterfall.{party}_fee", period_dim="year",
                                           scheduled=scheduled, available=available).remaining
    m.calc("waterfall.after_fees", unit="usd", dims=y, expr=available)
    ddf = build_cash_flow_note(m, prefix="ddf", period_dim="year", principal=ref("fee.deferred"),
                               rate=ref("waterfall.deferred_fee_rate"), available=ref("waterfall.after_fees"))
    m.calc("waterfall.residual", unit="usd", dims=y, expr=ddf.remaining)
    receipts = build_residual_receipts(m, prefix="residual", period_dim="year", lender_dim="soft",
                                       principal=ref("soft.principal"), available=ref("waterfall.residual"),
                                       lender_share=ref("waterfall.lender_share"), residual_receipts=True)
    m.calc("waterfall.gp_distribution", unit="usd", dims=y, expr=receipts.remaining * ref("waterfall.gp_residual_share"))
    m.calc("waterfall.lp_distribution", unit="usd", dims=y, expr=receipts.remaining - ref("waterfall.gp_distribution"))
    m.calc("soft.mandatory_paid", unit="usd", dims=("soft", "year"),
           expr=if_(idx >= ref("soft.mandatory_first_year"), ref("soft.mandatory_payment"), 0))
    build_simple_interest_balances(m, prefix="soft", lender_dim="soft", period_dim="year", principal=ref("soft.principal"),
                                   rate=ref("soft.rate"), payments=ref("soft.mandatory_paid") + receipts.payment)

    full = if_(perm.months == 12, 1, 0)
    m.test("tcac.dscr", dims=y, condition=if_(full == 1, ref("cf.dscr"), ref("tcac.minimum_dscr")) >= ref("tcac.minimum_dscr"),
           code="TCAC_DSCR", message="Debt service coverage is below the TCAC minimum in a full payment year.")
    limit = max_(ref("tcac.cash_flow_limit") * perm.debt_service, ref("tcac.gross_income_limit") * ref("cf.gross_income"))
    m.test("tcac.cash_flow", dims=y, condition=if_(idx <= 3, if_(full == 1, ref("cf.cash_flow") - limit, 0), 0) <= TOLERANCE,
           code="TCAC_CASH_FLOW", message="Cash flow after debt service exceeds the TCAC limit in an early full payment year.")
    at_end = lambda name: sum_over("year", if_(idx == years, ref(name), 0))
    m.calc("soft.final_balance", unit="usd", dims=("soft",), expr=at_end("soft.balance"))
    m.calc("ddf.unpaid", unit="usd", expr=at_end("ddf.closing"))
    m.calc("ddf.paid_total", unit="usd", expr=sum_over("year", ref("ddf.paid")))
    m.calc("residual.total", unit="usd", expr=sum_over("year", ref("residual.lender_total")))
