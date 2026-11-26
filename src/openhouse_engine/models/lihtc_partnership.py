"""Annual tax and partner declarations for the acquisition/rehab model.

These extend the same graph; there is no second evaluation or copied project run.
"""

from ..financial import maximum, minimum
from .. import Dimension, Item, ModelDefinitionError, allocate_round, const, if_, matches, previous, ref, round_to, sum_over, sum_within
from .lihtc_tax_basis import declare_tax_basis_adjustment


def declare_tax(m, structure, given, *, construction_interest):
    m.dimension(Dimension("tax_asset", [Item(a.name, kind=a.kind, asset_name=a.name, automatic=a.recovery is not None) for a in structure.tax_assets]))
    given("tax.asset_cost_fraction", "ratio", ("cost", "tax_asset"), high=1)
    m.check("tax.asset_cost_limit", dims=("cost",),
            condition=sum_over("tax_asset", ref("tax.asset_cost_fraction")) <= 1,
            code="TAX_BASIS_ALLOCATION_EXCEEDS_COST", message="Tax asset allocations exceed the cost.")
    for excluded in ("land", "reserves"):
        # cost keys carry explicit exclusion attributes in the project model.
        m.check("tax." + excluded + "_excluded", dims=("cost", "tax_asset"),
                condition=if_(matches("cost", **{excluded: True}), ref("tax.asset_cost_fraction"), const(0)) == 0,
                code="NONRECOVERABLE_TAX_BASIS", message="Land and reserves cannot be depreciated or amortized.")
    given("tax.replacement_asset_fraction", "ratio", ("reserve", "tax_asset", "tax_year"), high=1)
    m.check("tax.replacement_allocation", dims=("reserve", "tax_year"),
            condition=sum_over("tax_asset", ref("tax.replacement_asset_fraction")) <= 1,
            code="REPLACEMENT_ALLOCATION_EXCEEDS_COST", message="Replacement tax allocations exceed expenditures.")
    for asset in structure.tax_assets:
        m.check("tax.replacement_service_" + asset.name, dims=("reserve", "tax_asset", "tax_year"),
                condition=if_(matches("tax_asset", asset_name=asset.name),
                    if_(matches("tax_year", year=asset.service_year), const(0),
                        ref("reserve.annual_expenditure") * ref("tax.replacement_asset_fraction")), const(0)) == 0,
                code="REPLACEMENT_SERVICE_YEAR_MISMATCH", message="Replacement assets must match expenditure service years.")
    m.calc("tax.replacement_basis", unit="USD", dims=("tax_asset", "tax_year"),
           expr=sum_over("reserve", ref("reserve.annual_expenditure") * ref("tax.replacement_asset_fraction")))
    given('tax.asset_excluded_basis', 'USD', ('tax_asset',))
    given('tax.asset_credit_reduction', 'USD', ('tax_asset',))
    declare_tax_basis_adjustment(m, given, prefix='tax.asset', dims=('tax_asset',),
        gross_basis=sum_over('cost', ref('cost.total') * ref('tax.asset_cost_fraction'))
                    + sum_over('tax_year', ref('tax.replacement_basis')),
        excluded_basis=ref('tax.asset_excluded_basis'), credit_reduction=ref('tax.asset_credit_reduction'))
    m.calc('tax.asset_basis', unit='USD', dims=('tax_asset',), expr=round_to(ref('tax.asset.net_basis'), 2))
    given("tax.reviewed_recovery_fraction", "ratio", ("tax_asset", "tax_year"), high=1)
    m.check("tax.recovery_method", dims=("tax_asset", "tax_year"),
            condition=if_(matches("tax_asset", automatic=True), ref("tax.reviewed_recovery_fraction"), const(0)) == 0,
            code="RECOVERY_METHOD_CONFLICT", message="Generated assets cannot also carry reviewed recovery rates.")
    recovery_fraction = ref("tax.reviewed_recovery_fraction")
    recovery_amount = allocate_round(ref("tax.asset_basis") * ref("tax.recovery_fraction"), "tax_year", 2)
    for asset in structure.tax_assets:
        if asset.rounding_places is None:
            recovery_amount = if_(matches("tax_asset", asset_name=asset.name),
                                  ref("tax.asset_basis") * ref("tax.recovery_fraction"), recovery_amount)
        if asset.rounding_places == 0:
            recovery_amount = if_(matches("tax_asset", asset_name=asset.name),
                                  round_to(ref("tax.asset_basis") * ref("tax.recovery_fraction"), 0), recovery_amount)
        if asset.recovery is None:
            continue
        terms = asset.recovery
        # Calendar overlap is structure, in half-month units; financial division
        # and basis recovery remain expressions evaluated by the shared engine.
        service = asset.service_year * 24 + (terms.service_month - 1) * 2 + (1 if terms.convention == "mid_month" else 0)
        end = service + terms.months * 2
        forecast_start = structure.start_year * 24 + (structure.start_month - 1) * 2
        forecast_end = forecast_start + (structure.months + 1) * 2
        fraction = const(0)
        for year in range(structure.start_year, structure.last_year + 1):
            overlap = max(0, min((year + 1) * 24, end, forecast_end)
                          - max(year * 24, service, forecast_start))
            fraction = if_(matches("tax_year", year=year), const(overlap) / (terms.months * 2), fraction)
        recovery_fraction = if_(matches("tax_asset", asset_name=asset.name), fraction, recovery_fraction)
        amount = ref("tax.asset_basis") * ref("tax.recovery_fraction")
        recovery_amount = if_(matches("tax_asset", asset_name=asset.name),
                              amount if asset.rounding_places is None else round_to(amount, asset.rounding_places), recovery_amount)
    m.calc("tax.recovery_fraction", unit="ratio", dims=("tax_asset", "tax_year"), expr=recovery_fraction)
    m.check("tax.recovery_limit", dims=("tax_asset",),
            condition=sum_over("tax_year", ref("tax.reviewed_recovery_fraction")) <= 1,
            code="TAX_RECOVERY_EXCEEDS_BASIS", message="Recovery fractions exceed the asset's basis.")
    # Checks are declared separately per asset to avoid a second source of recovery inputs.
    for asset in structure.tax_assets:
        m.check("tax.service_" + asset.name, dims=("tax_asset", "tax_year"),
                condition=if_(matches("tax_asset", asset_name=asset.name),
                    if_(matches("tax_year", **{"before_" + asset.name: True}), ref("tax.recovery_fraction"), const(0)), const(0)) == 0,
                code="RECOVERY_BEFORE_SERVICE", message="Recovery cannot precede the asset's service year.")
    m.calc("tax.scheduled_recovery", unit="USD", dims=("tax_asset", "tax_year"), expr=recovery_amount)
    m.calc("tax.cumulative_recovery", unit="USD", dims=("tax_asset", "tax_year"),
           expr=previous("tax.cumulative_recovery", "tax_year",
                         initial=minimum(ref("tax.asset_basis"), ref("tax.scheduled_recovery")),
                         step=lambda p: minimum(ref("tax.asset_basis"), p + ref("tax.scheduled_recovery"))))
    m.calc("tax.opening_recovery", unit="USD", dims=("tax_asset", "tax_year"),
           expr=previous("tax.cumulative_recovery", "tax_year", initial=const(0)))
    m.calc("tax.asset_recovery", unit="USD", dims=("tax_asset", "tax_year"),
           expr=ref("tax.cumulative_recovery") - ref("tax.opening_recovery"))
    m.calc("tax.asset_remaining_basis", unit="USD", dims=("tax_asset",),
           expr=ref("tax.asset_basis") - sum_over("tax_year", ref("tax.asset_recovery")))
    for kind in ("depreciation", "amortization"):
        m.calc("tax." + kind, unit="USD", dims=("tax_year",),
               expr=sum_over("tax_asset", ref("tax.asset_recovery"), kind=kind))
    given("tax.deductible_interest_fraction", "ratio", ("permanent_loan", "month"), high=1)
    deductible_interest = const(0)
    for loan in structure.permanent_loans:
        deductible_interest = deductible_interest + ref("debt." + loan.name + ".interest") * sum_over(
            "permanent_loan", ref("tax.deductible_interest_fraction"), loan_name=loan.name)
    deductible_insurance = const(0)
    if any(loan.mortgage_insurance_basis != "none" for loan in structure.permanent_loans):
        given("tax.deductible_mortgage_insurance_fraction", "ratio", ("permanent_loan", "month"), high=1)
        for loan in structure.permanent_loans:
            deductible_insurance = deductible_insurance + ref("debt." + loan.name + ".mortgage_insurance") * sum_over(
                "permanent_loan", ref("tax.deductible_mortgage_insurance_fraction"), loan_name=loan.name)
    m.calc("tax.mortgage_insurance", unit="USD", dims=("tax_year",),
           expr=sum_within("month", deductible_insurance))
    given("tax.other_income", "USD", ("tax_year",))
    given("tax.other_deductions", "USD", ("tax_year",))
    m.calc("tax.noi", unit="USD", dims=("tax_year",), expr=sum_within("month", ref("operations.noi")))
    m.calc("tax.interest", unit="USD", dims=("tax_year",),
           expr=sum_within("month", deductible_interest + construction_interest))
    m.calc("tax.reserve_interest", unit="USD", dims=("tax_year",),
           expr=sum_over("reserve", ref("reserve.annual_interest")))
    m.calc("tax.income", unit="USD", dims=("tax_year",),
           expr=round_to(ref("tax.noi") + ref("tax.other_income") + ref("tax.reserve_interest") - ref("tax.interest")
                         - ref("tax.mortgage_insurance") - ref("tax.depreciation") - ref("tax.amortization") - ref("tax.other_deductions"), 2))


def declare_partners(m, structure, given):
    """A reviewed two-partner operating split, with separate cash and tax shares."""
    m.dimension(Dimension("partner", [Item("investor", investor=True), Item("sponsor", investor=False)]))
    given("partner.investor_cash_share", "ratio", ("month",), high=1)
    given("partner.investor_income_share", "ratio", ("tax_year",), high=1)
    given("partner.tax_rate", "ratio", ("partner", "tax_year"), high=1)
    given("partner.credit_utilization", "ratio", ("partner", "tax_year"), high=1)
    given("partner.loss_utilization", "ratio", ("partner", "tax_year"), high=1)

    investor_pool = round_to(ref("funding.selected_distribution") * ref("partner.investor_cash_share"), 2)
    m.calc("partner.distribution", unit="USD", dims=("partner", "month"),
           expr=if_(matches("partner", investor=True),
                    investor_pool - ref("funding.retained_investor_cash") + ref("reserve.investor_retained_repayment"),
                    ref("funding.selected_distribution") - investor_pool))
    declare_capital(m, structure, given)
    m.calc("partner.taxable_income", unit="USD", dims=("partner", "tax_year"),
           expr=if_(matches("partner", investor=True), ref("partner.investor_allocated_income"),
                    ref("tax.income") - ref("partner.investor_allocated_income")))
    declare_credit_allocation(m, structure, given)
    m.calc("partner.contribution", unit="USD", dims=("partner", "month"),
           expr=if_(matches("partner", investor=True), ref("equity.contribution"), ref("funding.sponsor_equity")))
    for name in ("distribution", "contribution"):
        m.calc("partner.annual_" + name, unit="USD", dims=("partner", "tax_year"),
               expr=sum_within("month", ref("partner." + name)))
    declare_partner_benefits(m, cash_tax_rounding_places=structure.cash_tax_rounding_places)


def declare_partner_benefits(m, *, cash_tax_rounding_places=2):
    """Round annual cash plus raw income-tax effect before adding usable credits.

    The adjusted tax benefit includes the rounding residue so callers can keep
    distributions at their dated monthly timing and post tax benefits explicitly.
    Contributions and credits are outside the combined cash/tax rounding.
    All required variables are declared by the caller in (partner, tax_year).
    """
    if type(cash_tax_rounding_places) is not int or cash_tax_rounding_places not in (0, 2):
        raise ModelDefinitionError("Cash and income-tax rounding requires 0 or 2 decimal places.")
    m.calc("partner.raw_income_tax_effect", unit="USD", dims=("partner", "tax_year"),
           expr=-ref("partner.taxable_income") * ref("partner.tax_rate")
                * if_(ref("partner.taxable_income") < 0, ref("partner.loss_utilization"), const(1)))
    m.calc("partner.income_tax_effect", unit="USD", dims=("partner", "tax_year"),
           expr=round_to(ref("partner.raw_income_tax_effect"), 2))
    m.calc("partner.unutilized_loss", unit="USD", dims=("partner", "tax_year"),
           expr=round_to(maximum(-ref("partner.taxable_income"), const(0)) * (1 - ref("partner.loss_utilization")), 2))
    m.calc("partner.usable_credit", unit="USD", dims=("partner", "tax_year"),
           expr=round_to(ref("partner.credits") * ref("partner.credit_utilization"), 2))
    m.calc("partner.unutilized_credit", unit="USD", dims=("partner", "tax_year"),
           expr=ref("partner.credits") - ref("partner.usable_credit"))
    m.calc("partner.cash_tax_benefit", unit="USD", dims=("partner", "tax_year"),
           expr=round_to(ref("partner.annual_distribution") + ref("partner.raw_income_tax_effect"),
                         cash_tax_rounding_places))
    m.calc("partner.tax_benefit", unit="USD", dims=("partner", "tax_year"),
           expr=ref("partner.cash_tax_benefit") - ref("partner.annual_distribution") + ref("partner.usable_credit"))
    m.calc("partner.before_tax_cash_flow", unit="USD", dims=("partner", "tax_year"),
           expr=ref("partner.annual_distribution") - ref("partner.annual_contribution"))
    m.calc("partner.after_tax_cash_flow", unit="USD", dims=("partner", "tax_year"),
           expr=ref("partner.before_tax_cash_flow") + ref("partner.tax_benefit"))


def declare_capital(m, structure, given):
    """Workbook capital-limited allocation; reviewed terms, not a tax opinion."""
    given("partner.opening_capital", "USD", ("partner",), low=None)
    given("partner.capital_reduction", "USD", ("partner", "tax_year"))
    given("partner.gross_income_to_sponsor", "USD", ("tax_year",))
    m.calc("partner.initial_investor_income", unit="USD", dims=("tax_year",),
           expr=round_to((ref("tax.income") - ref("partner.gross_income_to_sponsor"))
                         * ref("partner.investor_income_share"), structure.allocation_places))
    m.calc("partner.capital_movement", unit="USD", dims=("partner", "tax_year"),
           expr=ref("partner.annual_contribution") - ref("partner.annual_distribution")
                - ref("partner.capital_reduction"))
    declare_minimum_gain(m, structure, given)
    investor_opening = sum_over("partner", ref("partner.opening_capital"), investor=True)
    investor_movement = sum_over("partner", ref("partner.capital_movement"), investor=True)

    def allocated(capacity):
        initial = ref("partner.initial_investor_income")
        if not structure.reallocate_losses:
            return initial
        potential = initial - ref("minimum_gain.related_change")
        capacity = capacity + ref("minimum_gain.unrelated_opening") * ref("partner.investor_income_share") + ref("minimum_gain.unrelated_change")
        return if_(potential >= 0, potential, maximum(potential, -maximum(capacity, const(0))))

    m.calc("partner.investor_ending_capital", unit="USD", dims=("tax_year",),
           expr=previous("partner.investor_ending_capital", "tax_year",
               initial=investor_opening + investor_movement + allocated(investor_opening + investor_movement),
               step=lambda p: p + investor_movement + allocated(p + investor_movement)))
    m.calc("partner.investor_opening_capital", unit="USD", dims=("tax_year",),
           expr=previous("partner.investor_ending_capital", "tax_year", initial=investor_opening))
    m.calc("partner.investor_allocated_income", unit="USD", dims=("tax_year",),
           expr=ref("partner.investor_ending_capital") - ref("partner.investor_opening_capital") - investor_movement)
    m.calc("partner.loss_reallocated", unit="USD", dims=("tax_year",),
           expr=ref("partner.initial_investor_income") - ref("partner.investor_allocated_income"))
    m.calc("partner.sponsor_ending_capital", unit="USD", dims=("tax_year",),
           expr=previous("partner.sponsor_ending_capital", "tax_year",
               initial=sum_over("partner", ref("partner.opening_capital"), investor=False)
                       + sum_over("partner", ref("partner.capital_movement"), investor=False)
                       + ref("tax.income") - ref("partner.investor_allocated_income"),
               step=lambda p: p + sum_over("partner", ref("partner.capital_movement"), investor=False)
                       + ref("tax.income") - ref("partner.investor_allocated_income")))
    m.calc("partner.ending_capital", unit="USD", dims=("partner", "tax_year"),
           expr=if_(matches("partner", investor=True), ref("partner.investor_ending_capital"),
                    ref("partner.sponsor_ending_capital")))


def declare_minimum_gain(m, structure, given):
    # Loan classification and asset schedules are declared in the same graph.
    m.dimension(Dimension("nonrecourse_loan", [Item(a.name, related_party=a.related_party, loan_name=a.name, modeled=a.modeled_loan is not None)
                                             for a in structure.nonrecourse_loans]))
    given("minimum_gain.original_asset_basis", "USD")
    for name in ("other_asset_additions", "basis_reduction"):
        given("minimum_gain." + name, "USD", ("tax_year",))
    given("minimum_gain.reviewed_loan_balance", "USD", ("nonrecourse_loan", "tax_year"))
    m.check("minimum_gain.loan_balance_owner", dims=("nonrecourse_loan", "tax_year"),
            condition=if_(matches("nonrecourse_loan", modeled=True), ref("minimum_gain.reviewed_loan_balance"), const(0)) == 0,
            code="NONRECOURSE_BALANCE_DUPLICATE", message="Modeled nonrecourse debt cannot also have reviewed balances.")
    balance = ref("minimum_gain.reviewed_loan_balance")
    for loan in structure.nonrecourse_loans:
        if loan.modeled_loan is not None:
            balance = if_(matches("nonrecourse_loan", loan_name=loan.name),
                          sum_within("month", ref("debt." + loan.modeled_loan + ".total_owed"), year_end=True), balance)
    m.calc("minimum_gain.loan_balance", unit="USD", dims=("nonrecourse_loan", "tax_year"), expr=balance)

    m.calc("minimum_gain.asset_additions", unit="USD", dims=("tax_year",),
           expr=ref("minimum_gain.other_asset_additions")
                + sum_over("reserve", ref("reserve.annual_expenditure"), reserve_name="replacement"))
    m.calc("minimum_gain.cumulative_recovery", unit="USD", dims=("tax_year",),
           expr=previous("minimum_gain.cumulative_recovery", "tax_year", initial=ref("tax.depreciation"),
                         step=lambda p: p + ref("tax.depreciation")))
    for name in ("asset_additions", "basis_reduction"):
        m.calc("minimum_gain.cumulative_" + name, unit="USD", dims=("tax_year",),
               expr=previous("minimum_gain.cumulative_" + name, "tax_year", initial=ref("minimum_gain." + name),
                             step=lambda p, name=name: p + ref("minimum_gain." + name)))
    m.calc("minimum_gain.reserve_assets", unit="USD", dims=("tax_year",),
           expr=sum_over("reserve", ref("reserve.annual_ending_balance"), reserve_name="replacement")
                + (sum_over("reserve", ref("reserve.annual_ending_balance"), reserve_name="operating")
                   if structure.minimum_gain_include_operating_reserve else const(0))
                + (sum_over("reserve", ref("reserve.annual_ending_balance"), other=True)
                   if structure.minimum_gain_include_other_reserves else const(0)))
    m.calc("minimum_gain.net_assets", unit="USD", dims=("tax_year",),
           expr=ref("minimum_gain.original_asset_basis") + ref("minimum_gain.cumulative_asset_additions")
                + ref("minimum_gain.reserve_assets") - ref("minimum_gain.cumulative_recovery")
                - ref("minimum_gain.cumulative_basis_reduction"))
    remaining = ref("minimum_gain.net_assets")
    gains = {True: const(0), False: const(0)}
    for index, loan in enumerate(structure.nonrecourse_loans):
        balance = sum_over("nonrecourse_loan", ref("minimum_gain.loan_balance"), loan_name=loan.name)
        name = "minimum_gain.lien_" + str(index + 1)
        m.calc(name, unit="USD", dims=("tax_year",), expr=maximum(balance - remaining, const(0)))
        gains[loan.related_party] = gains[loan.related_party] + ref(name)
        asset_name = "minimum_gain.assets_after_lien_" + str(index + 1)
        m.calc(asset_name, unit="USD", dims=("tax_year",), expr=remaining - minimum(balance, remaining))
        remaining = ref(asset_name)
    for related, name in ((True, "related"), (False, "unrelated")):
        m.calc("minimum_gain." + name, unit="USD", dims=("tax_year",), expr=gains[related])
        m.calc("minimum_gain." + name + "_opening", unit="USD", dims=("tax_year",),
               expr=previous("minimum_gain." + name, "tax_year", initial=const(0)))
        m.calc("minimum_gain." + name + "_change", unit="USD", dims=("tax_year",),
               expr=ref("minimum_gain." + name) - ref("minimum_gain." + name + "_opening"))


def declare_credit_allocation(m, structure, given):
    given("partner.investor_credit_share", "ratio", ("tax_year",), high=1)
    m.calc("partner.credit_allowable_fraction", unit="ratio", dims=("tax_year",),
           expr=if_(ref("partner.initial_investor_income") != 0,
                    ref("partner.investor_allocated_income") / ref("partner.initial_investor_income"), const(0))
                if structure.reduce_credits_for_reallocated_losses else const(1))
    investor_credit = ref("credits.delivered") * ref("partner.investor_credit_share")
    m.calc("partner.credits", unit="USD", dims=("partner", "tax_year"),
           expr=if_(matches("partner", investor=True),
                    round_to(investor_credit * ref("partner.credit_allowable_fraction"), 2),
                    round_to(ref("credits.delivered"), 2) - round_to(investor_credit, 2)))
    m.check('partner.credits_nonnegative', dims=('partner', 'tax_year'),
            condition=ref('partner.credits') >= 0,
            code='NEGATIVE_PARTNER_CREDITS',
            message='The reviewed allocation produces negative partner credits; reconcile the allocation assumptions.')
    m.calc("credits.unallocated", unit="USD", dims=("tax_year",),
           expr=round_to(ref("credits.delivered"), 2) - sum_over("partner", ref("partner.credits")))
    m.check('partner.credits_delivery_limit', dims=('tax_year',),
            condition=ref('credits.unallocated') >= 0,
            code='PARTNER_CREDITS_EXCEED_DELIVERY',
            message='Partner credit allocations exceed project delivery; reconcile the allocation assumptions.')
