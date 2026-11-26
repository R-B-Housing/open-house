"""LIHTC acquisition/rehab: explicit assumptions, no workbook execution or I/O."""

from dataclasses import dataclass
from typing import Mapping, Any
import re

from .. import DecimalPolicy, Dimension, Item, Model, ModelDefinitionError, Run, evaluate
from .. import allocate_round, attr, const, if_, matches, previous, ref, round_to, sum_over, sum_within, total
from ..commercial import CommercialSpace, build_commercial_income, declare_inputs as declare_commercial_inputs, space_dimension
from .lihtc_partnership import declare_tax, declare_partners
from .lihtc_reserves import declare_reserves
from .lihtc_operating_projection import OperatingProjectionTerms, declare_operating_projection
from .lihtc_equity import EquityAdjustment, declare_equity_adjustment
from .lihtc_exit import ExitTerms, declare_exit
from .lihtc_costs import CostItem, declare_costs
from .lihtc_credits import declare_credits
from .lihtc_returns import ReturnTerms, declare_returns
from .lihtc_payins import EquityInstallment, declare_payins
from ..financial import minimum, maximum, operating_noi
from ..financing import LoanTerms, declare_loan_stack
from ..construction_financing import declare_construction_financing
from ..operations import AnnualProjectionTerms, declare_annual_projection

MODEL_ID = "lihtc-acquisition-rehab"
MODEL_VERSION = "12.0.0"
POLICY = DecimalPolicy(34, "ROUND_HALF_UP")
# Expense projection items a NNN commercial tenant reimburses: property taxes and insurance.
RECOVERABLE_EXPENSE = re.compile(r"(^|_)(property|real_estate|re)_tax(es)?($|_)|^tax(es)?$|(^|_)insurance($|_)")



@dataclass(frozen=True)
class StraightLineRecovery:
    service_month: int
    months: int
    convention: str

    def __post_init__(self):
        if (type(self.service_month) is not int or not 1 <= self.service_month <= 12
                or type(self.months) is not int or not 1 <= self.months <= 600
                or self.convention not in ("monthly", "mid_month")):
            raise ModelDefinitionError("Straight-line recovery requires service month, life and convention.")


@dataclass(frozen=True)
class TaxAsset:
    name: str
    kind: str
    service_year: int
    recovery: StraightLineRecovery | None
    rounding_places: int | None

    def __post_init__(self):
        if (not isinstance(self.name, str) or not self.name or len(self.name) > 100
                or self.kind not in ("depreciation", "amortization")
                or type(self.service_year) is not int or not 1900 <= self.service_year <= 2300
                or (self.recovery is not None and not isinstance(self.recovery, StraightLineRecovery))
                or (self.rounding_places is not None and
                    (type(self.rounding_places) is not int or self.rounding_places not in (0, 2)))):
            raise ModelDefinitionError("Tax assets require a name, recovery kind and service year.")


@dataclass(frozen=True)
class NonrecourseLoan:
    """Reviewed nonrecourse liens, ordered senior to junior in Structure."""
    name: str
    related_party: bool
    modeled_loan: str | None

    def __post_init__(self):
        if (not isinstance(self.name, str) or not self.name or len(self.name) > 100
                or type(self.related_party) is not bool
                or (self.modeled_loan is not None and not isinstance(self.modeled_loan, str))):
            raise ModelDefinitionError("Nonrecourse loans require a name and related-party classification.")


@dataclass(frozen=True)
class ConstructionTiming:
    """Reviewed monthly construction dates, independently of permanent funding.

    Capitalization stops before capitalization_end_month; lagged cash interest
    is settled only on its elected dates. Interest never increases principal.
    """
    draw_end_month: int
    settlement_month: int
    capitalization_end_month: int
    interest_payment_lag: int
    interest_settlement_month: int | None = None
    repayment: str = "all_drawn"

    def __post_init__(self):
        if (self.repayment not in ("all_drawn", "reviewed_amount")
                or any(type(value) is not int for value in
                (self.draw_end_month, self.settlement_month, self.capitalization_end_month,
                 self.interest_payment_lag))
                or not 1 <= self.draw_end_month <= self.settlement_month <= 600
                or not 0 <= self.capitalization_end_month <= 601
                or not 0 <= self.interest_payment_lag <= 12
                or (self.interest_settlement_month is not None and
                    (type(self.interest_settlement_month) is not int
                     or not self.settlement_month <= self.interest_settlement_month <= 600))):
            raise ModelDefinitionError('Construction timing requires explicit integer months, an ordered payoff and a payment lag.')


@dataclass(frozen=True)
class Structure:
    unit_types: tuple[str, ...]
    cost_items: tuple[CostItem, ...]
    construction_interest_cost: str
    equity_installments: tuple[EquityInstallment, ...]
    months: int
    conversion_month: int
    permanent_loans: tuple[LoanTerms, ...]
    start_year: int
    start_month: int
    acquisition_credit_year: int
    rehab_credit_year: int
    tax_assets: tuple[TaxAsset, ...]
    nonrecourse_loans: tuple[NonrecourseLoan, ...]
    allocation_places: int
    reallocate_losses: bool
    reduce_credits_for_reallocated_losses: bool
    minimum_gain_include_operating_reserve: bool
    minimum_gain_include_other_reserves: bool
    deferred_fee_loan: str | None = None
    equity_adjustment: EquityAdjustment | None = None
    exit_terms: ExitTerms | None = None
    return_terms: ReturnTerms | None = None
    expense_projection: AnnualProjectionTerms | None = None
    loan_rounding_places: int | None = 2
    cash_tax_rounding_places: int = 2
    construction_rounding_places: int | None = 2
    construction_timing: ConstructionTiming | None = None
    closing_month_operations: bool = False
    development_cost_end_month: int | None = None
    operating_projection: OperatingProjectionTerms | None = None
    commercial_spaces: tuple[CommercialSpace, ...] = ()

    def __post_init__(self):
        if (not isinstance(self.commercial_spaces, tuple) or len(self.commercial_spaces) > 20
                or any(not isinstance(s, CommercialSpace) or not isinstance(s.key, str)
                       or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", s.key) is None
                       or not isinstance(s.label, str) or not 1 <= len(s.label) <= 255
                       for s in self.commercial_spaces)
                or len({s.key for s in self.commercial_spaces}) != len(self.commercial_spaces)):
            raise ModelDefinitionError("Commercial spaces require at most twenty distinct keyed, labeled spaces.")
        if self.development_cost_end_month is not None and (
                type(self.development_cost_end_month) is not int or type(self.months) is not int
                or not 1 <= self.development_cost_end_month <= self.months + 1):
            raise ModelDefinitionError('Development costs require an explicit exclusive cutoff within the forecast.')
        if self.operating_projection is not None and (
                not isinstance(self.operating_projection, OperatingProjectionTerms)
                or any(type(value) is not int for value in (self.start_year, self.start_month, self.months))
                or self.expense_projection is None
                or self.operating_projection.first_year != self.start_year
                or self.last_year - self.start_year < 2):
            raise ModelDefinitionError('Annual operations require aligned three-year projections and annual expenses.')
        if type(self.closing_month_operations) is not bool:
            raise ModelDefinitionError("Closing-month operations require an explicit boolean election.")
        if self.construction_timing is not None and (
                not isinstance(self.construction_timing, ConstructionTiming)
                or type(self.months) is not int
                or self.construction_timing.settlement_month > self.months
                or self.construction_timing.capitalization_end_month > self.months + 1
                or (self.construction_timing.interest_settlement_month is not None
                    and self.construction_timing.interest_settlement_month > self.months)):
            raise ModelDefinitionError('Construction timing must fall within the complete project forecast.')
        if self.construction_rounding_places is not None and (type(self.construction_rounding_places) is not int
                                                            or self.construction_rounding_places != 2):
            raise ModelDefinitionError('Construction interest precision must be cents or explicitly full precision.')
        if type(self.cash_tax_rounding_places) is not int or self.cash_tax_rounding_places not in (0, 2):
            raise ModelDefinitionError('Combined annual cash and tax effects require explicit whole-dollar or cent precision.')
        if self.loan_rounding_places is not None and (type(self.loan_rounding_places) is not int
                                                    or self.loan_rounding_places != 2):
            raise ModelDefinitionError('Loan precision must be two decimal places or explicitly full precision.')
        if self.expense_projection is not None and not isinstance(self.expense_projection, AnnualProjectionTerms):
            raise ModelDefinitionError('Expense projections require explicit annual projection terms.')
        if self.return_terms is not None and (not isinstance(self.return_terms, ReturnTerms)
                or type(self.months) is not int
                or (self.return_terms.frequency == 'quarterly' and (self.months < 3 or self.months % 3))):
            raise ModelDefinitionError('Investor returns require explicit terms; quarterly returns require complete quarters.')
        if self.exit_terms is not None and (not isinstance(self.exit_terms, ExitTerms)
                or self.exit_terms.exit_month != self.months):
            raise ModelDefinitionError('The investor buyout must terminate the modeled period.')
        if self.equity_adjustment is not None and (not isinstance(self.equity_adjustment, EquityAdjustment)
                or not self.start_year <= self.equity_adjustment.first_year
                < self.equity_adjustment.second_year <= self.last_year):
            raise ModelDefinitionError('Equity adjustment years must fall within the projection.')
        if type(self.months) is not int or type(self.conversion_month) is not int:
            raise ModelDefinitionError("The model period requires integer months.")
        if (not isinstance(self.permanent_loans, tuple) or not 1 <= len(self.permanent_loans) <= 20
                or any(not isinstance(loan, LoanTerms) for loan in self.permanent_loans)
                or len({loan.name for loan in self.permanent_loans}) != len(self.permanent_loans)
                or any(not (0 if loan.name == self.deferred_fee_loan else self.conversion_month) <= loan.advance_month <= self.months
                       for loan in self.permanent_loans)):
            raise ModelDefinitionError("Permanent loans require distinct names and advances at or after conversion.")
        fee_loans = [loan for loan in self.permanent_loans if loan.name == self.deferred_fee_loan]
        if (self.deferred_fee_loan is not None and (len(fee_loans) != 1
                or fee_loans[0].origination != 'noncash'
                or fee_loans[0].repayment not in ('accrual', 'cash_flow_interest', 'cash_flow_principal')
                or fee_loans[0].first_payment_month < self.conversion_month)):
            raise ModelDefinitionError('Deferred fees require a named noncash contingent loan payable after conversion.')
        if any(loan.origination == 'noncash' and loan.name != self.deferred_fee_loan
               for loan in self.permanent_loans):
            raise ModelDefinitionError('Each noncash loan requires an explicit deferred-cost owner.')
        if (not isinstance(self.nonrecourse_loans, tuple) or len(self.nonrecourse_loans) > 8
                or any(not isinstance(a, NonrecourseLoan) for a in self.nonrecourse_loans)
                or len({a.name for a in self.nonrecourse_loans}) != len(self.nonrecourse_loans)):
            raise ModelDefinitionError("Nonrecourse liens must be distinct and ordered, with at most eight loans.")
        mapped = [a.modeled_loan for a in self.nonrecourse_loans if a.modeled_loan is not None]
        if len(set(mapped)) != len(mapped) or any(name not in {a.name for a in self.permanent_loans} for name in mapped):
            raise ModelDefinitionError("Nonrecourse liens must name distinct declared permanent loans.")
        if (type(self.allocation_places) is not int or self.allocation_places not in (0, 2)
                or type(self.reallocate_losses) is not bool
                or type(self.reduce_credits_for_reallocated_losses) is not bool
                or type(self.minimum_gain_include_operating_reserve) is not bool
                or type(self.minimum_gain_include_other_reserves) is not bool):
            raise ModelDefinitionError("Partnership allocation precision and elections must be explicit.")
        if (not isinstance(self.tax_assets, tuple) or not 1 <= len(self.tax_assets) <= 100
                or any(not isinstance(a, TaxAsset) for a in self.tax_assets)
                or len({a.name for a in self.tax_assets}) != len(self.tax_assets)):
            raise ModelDefinitionError("Tax assets must be distinct named assets.")
        if (not isinstance(self.unit_types, tuple) or not 1 <= len(self.unit_types) <= 100
                or any(not isinstance(k, str) or not k or len(k) > 100 for k in self.unit_types)
                or len(set(self.unit_types)) != len(self.unit_types)):
            raise ModelDefinitionError("Unit types must be distinct named types.")
        for value, low, high in ((self.start_year, 1900, 2200), (self.start_month, 1, 12),
                                 (self.months, 1, 600)):
            if type(value) is not int or not low <= value <= high:
                raise ModelDefinitionError("The model period is outside its supported bounds.")
        for value, low, high in ((self.conversion_month, 1, self.months),
                                 (self.acquisition_credit_year, self.start_year, self.last_year),
                                 (self.rehab_credit_year, self.start_year, self.last_year)):
            if type(value) is not int or not low <= value <= high:
                raise ModelDefinitionError("The model period is outside its supported bounds.")

    @property
    def last_year(self):
        return self.start_year + (self.start_month - 1 + self.months) // 12


def build(structure: Structure, documents: Mapping[str, Mapping[str, str]] | None = None) -> Model:
    """Declare a model; documents optionally identifies evidence-backed variables.

    Values for those variables must be passed separately as `sources`, never
    substituted by inputs. The document identity participates in the run digest.
    """
    documents = documents or {}
    if not isinstance(documents, Mapping):
        raise ModelDefinitionError("Source documents must be a mapping.")
    for document in documents.values():
        if (not isinstance(document, Mapping) or not isinstance(document.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", document["sha256"]) is None):
            raise ModelDefinitionError("Every source document must carry its SHA-256 digest.")
    m = Model(MODEL_ID, MODEL_VERSION, POLICY)
    m.dimension(Dimension("credit_month", [Item(i) for i in range(1, 13)]))
    m.dimension(Dimension("tax_year", [Item(y, year=y,
        acquisition_first=y == structure.acquisition_credit_year,
        acquisition_regular=structure.acquisition_credit_year < y < structure.acquisition_credit_year + 10,
        acquisition_tail=y == structure.acquisition_credit_year + 10,
        rehab_first=y == structure.rehab_credit_year,
        rehab_regular=structure.rehab_credit_year < y < structure.rehab_credit_year + 10,
        rehab_tail=y == structure.rehab_credit_year + 10,
        **{"before_" + a.name: y < a.service_year for a in structure.tax_assets})
        for y in range(structure.start_year, structure.last_year + 1)]))
    m.dimension(Dimension("month", [Item(i, period=i, operating=i > 0 or structure.closing_month_operations,
                                          return_period=(i + 2) // 3,
                                          tax_year=structure.start_year + (structure.start_month - 1 + i) // 12,
                                          construction=i < structure.conversion_month,
                                          development_cost=i < (structure.conversion_month if structure.development_cost_end_month is None
                                                                else structure.development_cost_end_month),
                                          conversion=i == structure.conversion_month,
                                          permanent=i >= structure.conversion_month,
                                          reserve_contribution_active=structure.operating_projection is None or (
                                              structure.start_year * 12 + structure.start_month - 1 + i >=
                                              structure.operating_projection.reserve_start_year * 12
                                              + structure.operating_projection.reserve_start_month - 1),
                                          month_of_year=(structure.start_month - 1 + i) % 12 + 1,
                                          last=i == structure.months,
                                          year_end=(structure.start_month - 1 + i) % 12 == 11 or i == structure.months)
                                    for i in range(structure.months + 1)], parent="tax_year"))
    m.dimension(Dimension("unit_type", [Item(k) for k in structure.unit_types]))
    m.dimension(Dimension("facility", [Item(k) for k in ("bond", "taxable", "equity_bridge")]))
    has_commercial = bool(structure.commercial_spaces)
    if has_commercial:
        m.dimension(space_dimension(structure.commercial_spaces))

    def given(name, unit, dims=(), low=0, high=None):
        if name in documents:
            m.source(name, unit=unit, dims=dims, document=documents[name])
            if low is not None:
                m.check(name + ".nonnegative", dims=dims, condition=ref(name) >= low,
                        code="INPUT_OUT_OF_RANGE", message="A source is outside its supported bounds.")
            if high is not None:
                m.check(name + ".maximum", dims=dims, condition=ref(name) <= high,
                        code="INPUT_OUT_OF_RANGE", message="A source is outside its supported bounds.")
        else:
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)

    declare_costs(m, given, structure.cost_items, construction_interest_cost=structure.construction_interest_cost)
    m.check("cost.period", dims=("cost", "month"),
            condition=if_(matches("month", development_cost=True), const(0), ref("cost.amount")) == 0,
            code="COST_AFTER_DEVELOPMENT_CUTOFF", message="Development costs must precede their elected cutoff.")
    m.calc("uses.total_development_cost", unit="USD", expr=sum_over("cost", ref("cost.total")))
    declare_credits(m, given)
    if structure.acquisition_credit_year < structure.rehab_credit_year:
        m.check('credits.acquisition_start', condition=ref('credits.acquisition_annual') == 0,
                code='ACQUISITION_CREDIT_BEFORE_REHAB',
                message='Acquisition credits cannot begin before the rehabilitation credit period.')
    if structure.equity_adjustment is not None:
        terms = structure.equity_adjustment
        declare_equity_adjustment(m, given, terms=terms, annual_credit=ref('credits.annual'),
            first_year_credit=sum_over('tax_year', ref('credits.delivered'), year=terms.first_year),
            second_year_credit=sum_over('tax_year', ref('credits.delivered'), year=terms.second_year),
            price=ref('credits.price'))
    if structure.operating_projection is None:
        given("units", "units", ("unit_type",), low=1, high=5000)
        for name in ("rent.market", "rent.maximum_gross", "rent.utility_allowance"):
            given(name, "USD/unit/month", ("unit_type", "month"))
        given("rent.occupied_units", "units", ("unit_type", "month"), high=5000)
        m.check("rent.occupancy", dims=("unit_type", "month"),
                condition=ref("rent.occupied_units") <= ref("units"), code="OCCUPANCY_EXCEEDS_UNITS",
                message="Occupied units exceed the unit count.")
        m.check("rent.allowance", dims=("unit_type", "month"),
                condition=ref("rent.utility_allowance") <= ref("rent.maximum_gross"),
                code="UTILITY_ALLOWANCE_EXCEEDS_RENT", message="Utility allowance exceeds maximum gross rent.")
        m.calc("rent.net_cap", unit="USD/unit/month", dims=("unit_type", "month"),
               expr=ref("rent.maximum_gross") - ref("rent.utility_allowance"))
        m.calc("rent.charged", unit="USD/unit/month", dims=("unit_type", "month"),
               expr=minimum(ref("rent.market"), ref("rent.net_cap")))
        m.calc("rent.collected", unit="USD", dims=("unit_type", "month"),
               expr=if_(matches("month", operating=True), ref("rent.charged") * ref("rent.occupied_units"), const(0)))
        given("operations.other_income", "USD", ("month",))
        if structure.expense_projection is None:
            given("operations.expenses", "USD", ("month",))
        else:
            terms = structure.expense_projection
            declare_annual_projection(m, given, terms.items, rounding_places=terms.rounding_places)
            given('expenses.monthly_fraction', 'ratio', ('expense', 'month'), high=1)
            has_operations = sum_within('month', const(1), operating=True) > 0
            m.check('expenses.allocation', dims=('expense', 'tax_year'),
                    condition=sum_within('month', ref('expenses.monthly_fraction')) == if_(has_operations, const(1), const(0)),
                    code='EXPENSE_ALLOCATION_NOT_ONE', message='Each annual expense needs complete reviewed monthly allocation.')
            m.check('expenses.nonoperating_year', dims=('expense', 'tax_year'),
                    condition=if_(has_operations, const(0), ref('expenses.amount')) == 0,
                    code='EXPENSE_BEFORE_OPERATIONS', message='A closing-only year cannot carry operating expenses.')
            m.check('expenses.operating_period', dims=('expense', 'month'),
                    condition=if_(matches('month', operating=True), const(0), ref('expenses.monthly_fraction')) == 0,
                    code='EXPENSE_BEFORE_OPERATIONS', message='Projected expenses cannot be assigned to closing month zero.')
            m.calc('operations.expenses', unit='USD', dims=('month',),
                   expr=sum_over('expense', ref('expenses.amount') * ref('expenses.monthly_fraction')))
        commercial = declare_commercial(m, given, structure, lambda body: body * ref('expenses.monthly_fraction'))
        revenue = (sum_over("unit_type", ref("rent.collected"))
                   + if_(matches("month", operating=True), ref("operations.other_income"), const(0)))
        expenses = if_(matches("month", operating=True), ref("operations.expenses"), const(0))
        if commercial is not None:
            given("commercial.management_fraction", "ratio", high=1)
            m.calc("operations.commercial_management_fee", unit="USD", dims=("month",),
                   expr=commercial.income * ref("commercial.management_fraction"))
            revenue = revenue + commercial.income
            expenses = expenses + ref("operations.commercial_management_fee")
        m.calc("operations.revenue", unit="USD", dims=("month",), expr=revenue)
        m.calc("operations.operating_expenses", unit="USD", dims=("month",), expr=expenses)
    else:
        expense_terms = structure.expense_projection
        declare_annual_projection(m, given, expense_terms.items, rounding_places=expense_terms.rounding_places)
        commercial = declare_commercial(m, given, structure,
                                        lambda body: body * ref('operations.expense_monthly_fraction'))
        declare_operating_projection(m, given, structure.operating_projection, expenses=ref('expenses.total'),
            commercial=None if commercial is None else {
                # Lease-based commercial rent and recoveries, and their credit loss, by tax year.
                'rent': sum_within('month', commercial.base_rent + commercial.recoveries),
                'vacancy': sum_within('month', commercial.credit_loss)})
        has_operations = sum_within('month', const(1), operating=True) > 0
        for posting, annual_name, output in (
                ('revenue', 'revenue', 'revenue'), ('expense', 'operating_expenses', 'operating_expenses')):
            name = 'operations.' + posting + '_monthly_fraction'
            given(name, 'ratio', ('month',), high=1)
            m.check(name + '.complete', dims=('tax_year',),
                    condition=sum_within('month', ref(name)) == if_(has_operations, const(1), const(0)),
                    code='OPERATING_POSTING_NOT_ONE', message='Annual operations require complete reviewed monthly posting.')
            m.check(name + '.operating_period', dims=('month',),
                    condition=if_(matches('month', operating=True), const(0), ref(name)) == 0,
                    code='OPERATING_POSTING_BEFORE_OPERATIONS', message='Operating amounts require elected operating months.')
            m.check(name + '.nonoperating_year', dims=('tax_year',),
                    condition=if_(has_operations, const(0), ref('annual_operations.' + annual_name)) == 0,
                    code='OPERATING_AMOUNT_BEFORE_OPERATIONS', message='Nonoperating years cannot carry projected operations.')
            m.calc('operations.' + output, unit='USD', dims=('month',),
                   expr=ref('annual_operations.' + annual_name) * ref(name))
    operating_noi(m, revenue="operations.revenue", expenses="operations.operating_expenses")

    declare_payins(m, given, structure.equity_installments, commitment=ref('equity.commitment'))

    given("bond.financed_cost", "USD", ("cost",))
    given("bond.basis_fraction", "ratio", ("cost",), high=1)
    given("bond.required_fraction", "ratio", low="0.00000001", high=1)
    m.calc("bond.basis", unit="USD", expr=sum_over("cost", ref("cost.total") * ref("bond.basis_fraction")))
    m.check("bond.positive_basis", condition=ref("bond.basis") > 0,
            code="BOND_BASIS_REQUIRED", message="A positive bond test basis is required.")
    m.check("bond.financed_cost_limit", dims=("cost",),
            condition=ref("bond.financed_cost") <= ref("cost.total") * ref("bond.basis_fraction"),
            code="BOND_FINANCED_COST_EXCEEDS_BASIS", message="Bond-financed costs exceed their test basis.")
    m.calc("bond.financed_fraction", unit="ratio", expr=sum_over("cost", ref("bond.financed_cost")) / ref("bond.basis"))
    m.calc("bond.test_passed", unit="boolean",
           expr=if_(ref("bond.financed_fraction") >= ref("bond.required_fraction"), const(1), const(0)))

    timing = structure.construction_timing
    reviewed_payoff = timing is not None and timing.repayment == 'reviewed_amount'
    if reviewed_payoff:
        given('construction.settlement_amount', 'USD', ('facility',))
    declare_construction_financing(m, given,
        draw_end_period=structure.conversion_month if timing is None else timing.draw_end_month,
        settlement_period=structure.conversion_month if timing is None else timing.settlement_month,
        capitalization_end_period=None if timing is None else timing.capitalization_end_month,
        interest_payment_lag=0 if timing is None else timing.interest_payment_lag,
        interest_settlement_period=None if timing is None else timing.interest_settlement_month,
        rounding_places=structure.construction_rounding_places,
        repayment_amount=ref('construction.settlement_amount') if reviewed_payoff else None)

    m.dimension(Dimension("permanent_loan", [Item(loan.name, loan_name=loan.name) for loan in structure.permanent_loans]))
    given("fee.deferred_fraction", "ratio", high=1)
    m.calc("fee.accrual", unit="USD", dims=("month",),
           expr=allocate_round(sum_over("cost", ref("cost.amount"), developer_fee=True) * ref("fee.deferred_fraction"), "month", 2))
    if structure.deferred_fee_loan is None:
        m.check('fee.debt_owner', condition=ref('fee.deferred_fraction') == 0,
                code='DEFERRED_FEE_LOAN_REQUIRED', message='Deferred fees require an explicitly declared debt owner.')
    advances = {} if structure.deferred_fee_loan is None else {structure.deferred_fee_loan: ref('fee.accrual')}
    # Commercial TI and leasing commissions are capital: paid from cash, never through NOI.
    leasing_costs = ref("commercial.leasing_costs_total") if has_commercial else None
    cash_available = (ref("operations.noi") - sum_over("reserve", ref("reserve.deposit"))
                      - sum_over("facility", ref("construction.cash_interest")))
    declare_loan_stack(m, structure.permanent_loans, given,
                      cash_available=cash_available if leasing_costs is None else cash_available - leasing_costs,
                      advances_by_loan=advances, rounding_places=structure.loan_rounding_places)
    for name, owner in (('repayment', 'debt_service'), ('ending_balance', 'total_owed'),
                        ('opening_balance', 'opening_balance')):
        m.calc('fee.' + name, unit='USD', dims=('month',),
               expr=const(0) if structure.deferred_fee_loan is None else
                    ref('debt.' + structure.deferred_fee_loan + '.' + owner))

    given("funding.sponsor_equity", "USD", ("month",))
    given("funding.other_sources", "USD", ("month",))
    given("funding.selected_distribution", "USD", ("month",))
    given("partner.investor_distribution_fraction", "ratio", ("month",), high=1)
    investor_pool = round_to(ref("funding.selected_distribution") * ref("partner.investor_cash_share"), 2)
    m.calc("funding.retained_investor_cash", unit="USD", dims=("month",),
           expr=investor_pool - round_to(investor_pool * ref("partner.investor_distribution_fraction"), 2))
    m.calc("funding.distribution", unit="USD", dims=("month",),
           expr=ref("funding.selected_distribution") - ref("funding.retained_investor_cash")
                + ref("reserve.investor_retained_repayment"))
    if structure.operating_projection is None:
        declare_reserves(m, given, exit_month=None if structure.exit_terms is None else structure.exit_terms.exit_month)
    else:
        annual_deposit = const(0)
        for name in ('replacement', 'operating', 'other_1', 'other_2'):
            annual_deposit = if_(matches('reserve', reserve_name=name),
                sum_over('operating_reserve', ref('annual_operations.reserve_contribution'), reserve_name=name), annual_deposit)
        declare_reserves(m, given, deposit=annual_deposit * ref('reserve.operating_monthly_fraction'),
                         exit_month=None if structure.exit_terms is None else structure.exit_terms.exit_month)
        given('reserve.operating_monthly_fraction', 'ratio', ('reserve', 'month'), high=1)
        m.check('reserve.scheduled_start', dims=('reserve', 'month'),
                condition=if_(matches('month', reserve_contribution_active=True), const(0), ref('reserve.deposit')) == 0,
                code='RESERVE_DEPOSIT_BEFORE_START', message='Scheduled reserve deposits cannot precede their reviewed start month.')
        m.check('reserve.operating_posting_complete', dims=('reserve', 'tax_year'),
                condition=sum_within('month', ref('reserve.operating_monthly_fraction'))
                    == if_(matches('reserve', reserve_name='lease_up'), const(0),
                           if_(has_operations, const(1), const(0))),
                code='RESERVE_OPERATING_POSTING_NOT_ONE', message='Scheduled reserve contributions require complete reviewed posting.')
        m.check('reserve.nonoperating_amount', dims=('reserve', 'tax_year'),
                condition=if_(has_operations, const(0), annual_deposit) == 0,
                code='RESERVE_AMOUNT_BEFORE_OPERATIONS', message='Nonoperating years cannot lose scheduled reserve contributions.')
        m.check('reserve.operating_posting_period', dims=('reserve', 'month'),
                condition=if_(matches('month', operating=True), const(0), ref('reserve.operating_monthly_fraction')) == 0,
                code='RESERVE_POSTING_BEFORE_OPERATIONS', message='Scheduled reserve contributions require operating months.')
    m.check("funding.distribution_period", dims=("month",),
            condition=if_(matches("month", permanent=True), const(0), ref("funding.selected_distribution")) == 0,
            code="DISTRIBUTION_BEFORE_CONVERSION", message="Distributions must follow permanent conversion.")
    m.calc("funding.sources", unit="USD", dims=("month",),
           expr=total("equity.contribution", "debt.proceeds",
                      "funding.sponsor_equity", "funding.other_sources") + sum_over("reserve", ref("reserve.release")) + ref("reserve.investor_retained_repayment")
                + sum_over("facility", ref("construction.draw")))
    uses = (sum_over("cost", ref("cost.amount")) - ref('fee.accrual') + sum_over("facility", ref("construction.cash_interest")
            + ref("construction.repayment")) + total("debt.debt_service", "funding.selected_distribution", "reserve.investor_retained_repayment") + sum_over("reserve", ref("reserve.deposit")))
    m.calc("funding.uses", unit="USD", dims=("month",), expr=uses if leasing_costs is None else uses + leasing_costs)
    m.calc("funding.net_cash", unit="USD", dims=("month",),
           expr=ref("funding.sources") + ref("operations.noi") - ref("funding.uses"))
    m.calc("funding.ending_cash", unit="USD", dims=("month",),
           expr=previous("funding.ending_cash", "month", initial=ref("funding.net_cash"), step=lambda p: p + ref("funding.net_cash")))
    m.calc('funding.cash_shortfall', unit='USD', dims=('month',),
           expr=maximum(-ref('funding.ending_cash'), const(0)))
    m.calc("funding.available_distribution", unit="USD", dims=("month",),
           expr=maximum(ref("funding.ending_cash") + ref("funding.selected_distribution"), const(0)))
    m.check("funding.distribution_limit", dims=("month",),
            condition=ref("funding.selected_distribution") <= ref("funding.available_distribution"),
            code="DISTRIBUTION_EXCEEDS_CASH", message="Distributions exceed available cash.")
    m.calc("funding.gap_to_date", unit="USD", dims=("month",),
           expr=previous("funding.gap_to_date", "month", initial=maximum(-ref("funding.ending_cash"), const(0)),
                         step=lambda p: maximum(p, -ref("funding.ending_cash"))))
    m.calc("funding.maximum_gap", unit="USD", expr=sum_over("month", ref("funding.gap_to_date"), last=True))
    m.calc('funding.cash_funded', unit='count',
           expr=if_(ref('funding.maximum_gap') == 0, const(1), const(0)))
    m.calc('funding.shortfall_months', unit='count',
           expr=sum_over('month', if_(ref('funding.cash_shortfall') > 0, const(1), const(0))))
    m.calc("funding.final_cash", unit="USD", expr=sum_over("month", ref("funding.ending_cash"), last=True))
    m.calc('funding.debt_owed', unit='USD', dims=('month',),
           expr=ref('debt.total_owed') + sum_over('facility',
               ref('construction.ending_balance') + ref('construction.ending_interest_payable')))
    m.calc('funding.final_debt_owed', unit='USD',
           expr=sum_over('month', ref('funding.debt_owed'), last=True))
    given('tax.construction_deductible_interest_fraction', 'ratio', ('facility', 'month'), high=1)
    declare_tax(m, structure, given, construction_interest=sum_over('facility',
        ref('construction.operating_interest') * ref('tax.construction_deductible_interest_fraction')))
    declare_partners(m, structure, given)
    if structure.exit_terms is not None:
        declare_exit(m, structure.exit_terms, given,
            debt_owed=sum_over('month', ref('funding.debt_owed'), last=True))
    terminal_year = structure.last_year
    m.calc('partner.terminal_after_tax_cash', unit='USD', dims=('partner', 'tax_year'),
           expr=const(0) if structure.exit_terms is None else
                if_(matches('partner', investor=True),
                    if_(matches('tax_year', year=terminal_year), ref('exit.investor_after_tax_cash'), const(0)), const(0)))
    m.calc('partner.total_after_tax_cash_flow', unit='USD', dims=('partner', 'tax_year'),
           expr=ref('partner.after_tax_cash_flow') + ref('partner.terminal_after_tax_cash'))
    if structure.return_terms is not None:
        m.check('returns.retained_cash_settled',
            condition=ref('reserve.investor_retained_final_balance') == 0,
            code='UNSETTLED_RETAINED_CASH_RETURN',
            message='Investor returns require settlement of the terminal retained-cash claim.')
        declare_returns(m, structure, given)
    unknown = set(documents) - {name for name, var in m.variables.items() if var.kind == "source"}
    if unknown:
        raise ModelDefinitionError("A document names an undeclared source variable.")
    return m


def declare_commercial(m, given, structure, monthly_posting):
    """Lease-by-lease commercial income over the model months; None without commercial space.

    NNN tenants reimburse their share of the expense projection's property tax
    and insurance lines (names matching RECOVERABLE_EXPENSE), posted to months
    as those expenses are. Without an expense projection, or when no line is
    identifiable, the reviewed monthly recoverable cost pool is an explicit
    input, `commercial.recoverable_costs`.
    """
    if not structure.commercial_spaces:
        return None
    declare_commercial_inputs(m, prefix="commercial", space_dim="space")
    recoverable = []
    if structure.expense_projection is not None:
        for item in m.dimensions["expense"].items:
            item.attrs["commercial_recoverable"] = RECOVERABLE_EXPENSE.search(item.key) is not None
            if item.attrs["commercial_recoverable"]:
                recoverable.append(item.key)
    if recoverable:
        m.calc("commercial.recoverable_costs", unit="USD", dims=("month",),
               expr=sum_over("expense", monthly_posting(ref("expenses.amount")), commercial_recoverable=True))
    else:
        given("commercial.recoverable_costs", "USD", ("month",))
    active = if_(matches("month", operating=True), const(1), const(0))
    return build_commercial_income(m, prefix="commercial", space_dim="space", period_dim="month",
                                   period_index=attr("month", "period"), month_of_year=attr("month", "month_of_year"),
                                   active=active, recoverable_costs=ref("commercial.recoverable_costs") * active,
                                   money="USD")


def calculate(structure: Structure, inputs: Mapping[str, Any],
              sources: Mapping[str, Any] | None = None, *,
              documents: Mapping[str, Mapping[str, str]] | None = None) -> Run:
    """Evaluate through the shared engine, retaining all values, lineage and digest."""
    return evaluate(build(structure, documents), inputs, sources)
