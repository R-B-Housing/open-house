"""Synthetic acquisition/rehab examples."""

from decimal import Decimal
import unittest
from dataclasses import replace

from openhouse_engine import EngineError, ModelDefinitionError
from openhouse_engine.financing import LoanTerms
from openhouse_engine.models.lihtc_costs import CostItem
from openhouse_engine.models.lihtc_payins import EquityInstallment
from openhouse_engine.models.lihtc_acquisition_rehab import Structure, TaxAsset, NonrecourseLoan, StraightLineRecovery, calculate


def example(month_count=4, start_month=1, rehab_credit_year=2027):
    structure = Structure(unit_types=("restricted",),
                          cost_items=tuple(CostItem(c, c) for c in ("land", "acquisition_building", "acquisition_costs", "rehab_hard",
                               "rehab_soft", "financing", "reserves", "developer_fee")),
                          construction_interest_cost="financing",
                          equity_installments=(EquityInstallment("closing", 0, "percentage"),
                                               EquityInstallment("completion", 1, "percentage")), months=month_count, conversion_month=3,
                          permanent_loans=(LoanTerms("senior", 3, 3, 12, 14, "amortizing", False),
                                           LoanTerms("developer_fee", 0, 3, 12, None, "cash_flow_principal", False, origination="noncash")),
                          deferred_fee_loan="developer_fee", start_year=2027, start_month=start_month,
                          acquisition_credit_year=2027, rehab_credit_year=rehab_credit_year,
                          allocation_places=2, reallocate_losses=False, reduce_credits_for_reallocated_losses=False,
                          minimum_gain_include_operating_reserve=True, minimum_gain_include_other_reserves=True,
                          nonrecourse_loans=(NonrecourseLoan("senior", False, None), NonrecourseLoan("junior", True, None)),
                          tax_assets=(TaxAsset("building", "depreciation", 2027, None, 2),
                                      TaxAsset("loan_cost", "amortization", 2027, None, 2)))
    months = range(month_count + 1)
    years = range(2027, structure.last_year + 1)
    costs = ("land", "acquisition_building", "acquisition_costs", "rehab_hard",
             "rehab_soft", "financing", "reserves", "developer_fee")
    amounts = {c: {m: "0" for m in months} for c in costs}
    for c, amount in {"land": "100", "acquisition_building": "400",
                      "rehab_hard": "200", "developer_fee": "100"}.items():
        amounts[c][0] = amount
    inputs = {
        "reserve.investor_retained_release": {m: "0" for m in months},
        "reserve.investor_retained_opening_balance": "0",
        "reserve.opening_balance": {r: "0" for r in ("lease_up", "operating", "replacement", "other_1", "other_2")},
        "reserve.capitalized_fraction": {(r,m): "1" if r == "operating" else "0" for r in ("lease_up", "operating", "replacement", "other_1", "other_2") for m in months},
        "reserve.annual_rate": {(r, y): "0" for r in ("lease_up", "operating", "replacement", "other_1", "other_2") for y in years},
        "reserve.deposit": {(r, m): "0" for r in ("lease_up", "operating", "replacement", "other_1", "other_2") for m in months},
        "reserve.release": {(r, m): "0" for r in ("lease_up", "operating", "replacement", "other_1", "other_2") for m in months},
        "reserve.expenditure": {(r, m): "0" for r in ("lease_up", "operating", "replacement", "other_1", "other_2") for m in months},
        "partner.investor_distribution_fraction": {m: "1" for m in months},
        "minimum_gain.original_asset_basis": "1000",
        "minimum_gain.other_asset_additions": {y: "0" for y in years},
        "minimum_gain.basis_reduction": {y: "0" for y in years},
        "minimum_gain.reviewed_loan_balance": {(l, y): "0" for l in ("senior", "junior") for y in years},
        "partner.opening_capital": {p: "0" for p in ("investor", "sponsor")},
        "partner.capital_reduction": {(p, y): "0" for p in ("investor", "sponsor") for y in years},
        "partner.gross_income_to_sponsor": {y: "0" for y in years},
        "tax.replacement_asset_fraction": {(r,a,y): "0" for r in ("lease_up", "operating", "replacement", "other_1", "other_2")
                                           for a in ("building", "loan_cost") for y in years},
        "tax.asset_excluded_basis": {a: "0" for a in ("building", "loan_cost")},
        "tax.asset_credit_reduction": {a: "0" for a in ("building", "loan_cost")},
        "tax.asset.retained_fraction": {a: "1" for a in ("building", "loan_cost")},
        "tax.asset_cost_fraction": {(c, a): "0.5" if (c, a) == ("acquisition_building", "building") else
                                    "0.1" if (c, a) == ("developer_fee", "loan_cost") else "0"
                                    for c in costs for a in ("building", "loan_cost")},
        "tax.reviewed_recovery_fraction": {(a, y): ("0.1" if a == "building" else "1") if y == 2027 else "0"
                                  for a in ("building", "loan_cost") for y in years},
        "tax.construction_deductible_interest_fraction": {(f,m): "0" for f in ("bond", "taxable", "equity_bridge") for m in months},
        "tax.deductible_interest_fraction": {(l,m): "1" for l in ("senior", "developer_fee") for m in months},
        "tax.other_income": {y: "0" for y in years}, "tax.other_deductions": {y: "0" for y in years},
        "partner.investor_cash_share": {m: "0.9" for m in months},
        "partner.investor_credit_share": {y: "0.99" for y in years},
        "partner.investor_income_share": {y: "0.8" for y in years},
        "partner.tax_rate": {(p, y): "0.25" if p == "investor" else "0.2"
                             for p in ("investor", "sponsor") for y in years},
        "partner.credit_utilization": {(p, y): "1" for p in ("investor", "sponsor") for y in years},
        "partner.loss_utilization": {(p, y): "1" for p in ("investor", "sponsor") for y in years},
        "units": {"restricted": 10},
        "rent.market": {"restricted": {m: "120" for m in months}},
        "rent.maximum_gross": {"restricted": {m: "100" for m in months}},
        "rent.utility_allowance": {"restricted": {m: "10" for m in months}},
        "rent.occupied_units": {"restricted": {m: 10 for m in months}},
        "operations.other_income": {m: "0" for m in months},
        "operations.expenses": {m: "300" for m in months},
        "cost.amount": amounts,
        "basis.acquisition_fraction": {c: "1" if c == "acquisition_building" else "0" for c in costs},
        "basis.rehab_fraction": {c: "1" if c in ("rehab_hard", "developer_fee") else "0" for c in costs},
        "basis.applicable_fraction": "0.9", "basis.rehab_boost": "1.3",
        "credits.acquisition_rate": "0.04", "credits.rehab_rate": "0.04",
        "credits.investor_share": "0.99", "credits.price": "0.9",
        "credits.acquisition_annual_cap": "1000000", "credits.rehab_annual_cap": "1000000",
        "credits.acquisition_qualified_fraction": {m: "1" if m <= min(month_count + 1, 12) else "0" for m in range(1, 13)},
        "credits.rehab_qualified_fraction": {m: "1" if m <= min(month_count + 1, 12) else "0" for m in range(1, 13)},
        "equity.rounding_increment": "0.01",
        "equity.closing.fraction": "0.5", "equity.completion.fraction": "0.5",
        "bond.financed_cost": {c: "200" if c == "acquisition_building" else "0" for c in costs},
        "bond.basis_fraction": {c: "0" if c == "financing" else "1" for c in costs}, "bond.required_fraction": "0.25",
        "construction.commitment": {f: "500" for f in ("bond", "taxable", "equity_bridge")},
        "construction.annual_rate": {f: "0.12" for f in ("bond", "taxable", "equity_bridge")},
        "construction.draw": {f: {m: "200" if f == "bond" and m == 0 else "0" for m in months}
                              for f in ("bond", "taxable", "equity_bridge")},
        "debt.senior.amount": "200", "debt.senior.annual_rate": "0",
        "funding.sponsor_equity": {m: "500" if m == 0 else "0" for m in months},
        "funding.other_sources": {m: "0" for m in months},
        "fee.deferred_fraction": "0.5",
        "debt.developer_fee.annual_rate": "0", "debt.developer_fee.paid_annual_rate": "0",
        "debt.developer_fee.payment_cap": "0", "debt.developer_fee.cash_flow_fraction": {m: "0" for m in months},
        "funding.selected_distribution": {m: "0" for m in months},
    }
    for name, values in list(inputs.items()):
        if isinstance(values, dict) and values and isinstance(next(iter(values.values())), dict):
            inputs[name] = {(key, month): value for key, row in values.items() for month, value in row.items()}
    return structure, inputs


class LihtcAcquisitionRehabTest(unittest.TestCase):
    def test_whole_dollar_cash_tax_election_rounds_distribution_and_tax_before_credits(self):
        structure, inputs = example()
        structure = replace(structure, cash_tax_rounding_places=0)
        inputs['funding.selected_distribution'][3] = '100.01'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('partner.cash_tax_benefit', partner='investor', tax_year=2027), Decimal('-384'))
        self.assertEqual(run.value('partner.after_tax_cash_flow', partner='investor', tax_year=2027), Decimal('-625.67'))
        self.assertEqual(run.value('partner.distribution', partner='investor', month=3), Decimal('90.01'))
        self.assertEqual(run.value('partner.tax_benefit', partner='investor', tax_year=2027), Decimal('-462.28'))

    def test_cash_tax_precision_rejects_implicit_or_unsupported_elections(self):
        structure, _ = example()
        for invalid in (True, False, None, '0', 0.0, 1):
            with self.subTest(invalid=invalid), self.assertRaises(ModelDefinitionError):
                replace(structure, cash_tax_rounding_places=invalid)

    def test_quarterly_returns_preserve_whole_dollar_annual_cash_tax_rounding(self):
        from openhouse_engine.models.lihtc_returns import ReturnTerms
        structure, inputs = example(month_count=9)
        structure = replace(structure, cash_tax_rounding_places=0, return_terms=ReturnTerms('-.99', '10', 80))
        inputs['funding.selected_distribution'][9] = '2000.01'
        inputs['returns.tax_benefit_fraction'] = {m: '1' if m == 9 else '0' for m in range(10)}
        run = calculate(structure, inputs)
        annual = run.value('partner.after_tax_cash_flow', partner='investor', tax_year=2027)
        self.assertEqual(sum(run.series('returns.investor_cash_flow')), annual)
        self.assertEqual(run.value('partner.cash_tax_benefit', partner='investor', tax_year=2027), Decimal('726'))
        self.assertEqual(run.value('partner.distribution', partner='investor', month=9), Decimal('1800.01'))

    def test_construction_precision_flows_once_into_cost_basis_and_funding(self):
        structure, inputs = example()
        structure = replace(structure, construction_rounding_places=None)
        inputs['construction.annual_rate']['bond'] = '.071'
        run = calculate(structure, inputs)
        interest = Decimal('200') * Decimal('.071') / 12
        self.assertAlmostEqual(run.value('construction.interest', facility='bond', month=1), interest, places=26)
        self.assertAlmostEqual(run.value('cost.total', cost='financing'), interest * 3, places=26)
        self.assertEqual(run.value('construction.repayment', facility='bond', month=3), Decimal('200'))
        rounded = calculate(replace(structure, construction_rounding_places=2), inputs)
        self.assertEqual(rounded.value('cost.total', cost='financing'), Decimal('3.54'))
        self.assertAlmostEqual(rounded.value('funding.final_cash') - run.value('funding.final_cash'),
                               interest * 3 - Decimal('3.54'), places=26)


    def test_contingent_loan_paid_interest_basis_flows_through_public_model(self):
        structure, inputs = example()
        loans = tuple(replace(loan, paid_interest_basis='accrual_period')
                      if loan.name == 'developer_fee' else loan for loan in structure.permanent_loans)
        structure = replace(structure, permanent_loans=loans)
        inputs['debt.developer_fee.annual_rate'] = '.12'
        inputs['debt.developer_fee.paid_annual_rate'] = '.06'
        inputs['debt.developer_fee.cash_flow_fraction'] = {m: '1' for m in range(5)}
        run = calculate(structure, inputs)
        self.assertEqual(run.value('debt.developer_fee.interest_paid', month=3), Decimal('.25'))
        self.assertEqual(run.value('debt.developer_fee.principal', month=3), Decimal('50'))
        self.assertEqual(run.value('fee.ending_balance', month=4), Decimal('1.75'))

    def test_full_precision_loan_stack_uses_unrounded_monthly_annuity(self):
        from decimal import localcontext
        structure, inputs = example()
        structure = replace(structure, loan_rounding_places=None)
        inputs['debt.senior.annual_rate'] = '0.12'
        run = calculate(structure, inputs)
        with localcontext() as context:
            context.prec = 34
            rate = Decimal('0.01')
            payment = Decimal('200') * rate / (1 - (1 + rate) ** -12)
            balance = Decimal('200')
            for _ in range(2):
                balance = balance * (1 + rate) - payment
            self.assertLess(abs(run.value('debt.senior.payment') - payment), Decimal('1e-28'))
            self.assertLess(abs(run.value('debt.senior.ending_balance', month=4) - balance), Decimal('1e-28'))
        for invalid in (True, 2.0, 0, 3):
            with self.assertRaises(ModelDefinitionError):
                replace(structure, loan_rounding_places=invalid)

    def test_fixed_equity_tranches_fund_only_their_declared_months(self):
        from openhouse_engine.models.lihtc_payins import EquityInstallment
        structure, inputs = example()
        structure = replace(structure, equity_installments=(EquityInstallment('closing', 0, 'fixed'),
                                                           EquityInstallment('conversion', 3, 'fixed')))
        inputs.pop('equity.closing.fraction')
        inputs.pop('equity.completion.fraction')
        inputs.update({'equity.closing.amount': '100', 'equity.conversion.amount': '153.4'})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('equity.contribution', month=0), Decimal('100'))
        self.assertEqual(run.value('equity.contribution', month=1), Decimal('0'))
        self.assertEqual(run.value('equity.contribution', month=3), Decimal('153.40'))
        self.assertEqual(run.value('equity.payin_total'), run.value('equity.commitment'))
        inputs['equity.conversion.amount'] = '153.41'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'EQUITY_PAYINS_NOT_COMMITMENT')

    def test_december_closing_requires_no_operating_expense_allocation_in_its_closing_year(self):
        from openhouse_engine.operations import AnnualProjectionTerms
        structure, inputs = example(month_count=12, start_month=12)
        structure = replace(structure, expense_projection=AnnualProjectionTerms(('utilities',), 0))
        inputs.pop('operations.expenses')
        inputs.update({'expenses.annual_base': {'utilities': '3600'},
                       'expenses.annual_growth': {('utilities',2027): '0', ('utilities',2028): '0'},
                       'expenses.period_fraction': {2027: '0', 2028: '1'},
                       'expenses.monthly_fraction': {('utilities',m): '1' if m == 12 else '0'
                                                    for m in range(13)}})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('expenses.total', tax_year=2027), Decimal('0'))
        self.assertEqual(run.value('operations.expenses', month=12), Decimal('3600'))

    def test_tax_basis_exclusions_credit_reductions_and_retained_shares_precede_recovery(self):
        structure, inputs = example()
        inputs['tax.asset_excluded_basis'] = {'building': '20', 'loan_cost': '0'}
        inputs['tax.asset_credit_reduction'] = {'building': '10', 'loan_cost': '0'}
        inputs['tax.asset.retained_fraction'] = {'building': '0.5', 'loan_cost': '1'}
        run = calculate(structure, inputs)
        self.assertEqual(run.value('tax.asset.gross_basis', tax_asset='building'), Decimal('200'))
        self.assertEqual(run.value('tax.asset_basis', tax_asset='building'), Decimal('85'))
        self.assertEqual(run.value('tax.depreciation', tax_year=2027), Decimal('8.50'))
        self.assertEqual(run.value('tax.income', tax_year=2027), Decimal('2381.50'))
        inputs['tax.asset_excluded_basis']['building'] = '201'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'TAX_BASIS_REDUCTIONS_EXCEED_BASIS')

    def test_projected_expenses_flow_through_noi_and_tax_with_reviewed_monthly_allocation(self):
        from openhouse_engine.operations import AnnualProjectionTerms
        structure, inputs = example(month_count=23)
        structure = replace(structure, expense_projection=AnnualProjectionTerms(('utilities',), 0))
        inputs.pop('operations.expenses')
        inputs.update({'expenses.annual_base': {'utilities': '3600'},
                       'expenses.annual_growth': {('utilities',2027): '0', ('utilities',2028): '0.1'},
                       'expenses.period_fraction': {2027: '1', 2028: '1'},
                       'expenses.monthly_fraction': {('utilities',m): '1' if m in (11,23) else '0'
                                                    for m in range(24)}})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('operations.expenses', month=11), Decimal('3600'))
        self.assertEqual(run.value('operations.expenses', month=23), Decimal('3960'))
        self.assertEqual(run.value('operations.noi', month=23), Decimal('-3060'))
        self.assertEqual(run.value('tax.noi', tax_year=2027), Decimal('6300'))
        self.assertEqual(run.value('tax.noi', tax_year=2028), Decimal('6840'))
        inputs['expenses.monthly_fraction'][('utilities',23)] = '0.5'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'EXPENSE_ALLOCATION_NOT_ONE')

    def test_quarterly_investor_return_uses_explicit_tax_posting_and_canonical_cash(self):
        from openhouse_engine.models.lihtc_returns import ReturnTerms
        structure, inputs = example(month_count=9)
        structure = replace(structure, return_terms=ReturnTerms('-.99', '10', 80))
        inputs['returns.tax_benefit_fraction'] = {m: '1' if m == 9 else '0' for m in range(10)}
        inputs['funding.selected_distribution'][9] = '2000'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('returns.investor_cash_flow', quarter=0), Decimal('-126.70'))
        self.assertEqual(run.value('returns.investor_cash_flow', quarter=1), Decimal('-126.70'))
        expected = Decimal('1800') + run.value('partner.tax_benefit', partner='investor', tax_year=2027)
        self.assertEqual(run.value('returns.investor_cash_flow', quarter=3), expected)
        self.assertAlmostEqual(run.value('returns.npv'), Decimal('0'), places=17)
        inputs['returns.tax_benefit_fraction'][9] = '0.5'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'RETURN_TAX_POSTING_NOT_ONE')

    def test_distinct_cost_lines_preserve_eligible_basis_and_tax_asset_allocations(self):
        from openhouse_engine.models.lihtc_costs import CostItem
        structure, inputs = example()
        structure = replace(structure, cost_items=structure.cost_items + (CostItem('rehab_design', 'rehab_soft'),))
        inputs['cost.amount'].update({('rehab_design',m): '40' if m == 1 else '0' for m in range(5)})
        inputs['basis.acquisition_fraction']['rehab_design'] = '0'
        inputs['basis.rehab_fraction']['rehab_design'] = '0.5'
        inputs['bond.financed_cost']['rehab_design'] = '0'
        inputs['bond.basis_fraction']['rehab_design'] = '1'
        inputs['tax.asset_cost_fraction'].update({('rehab_design', a): '1' if a == 'loan_cost' else '0'
                                                 for a in ('building','loan_cost')})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('cost.category_total', cost_category='rehab_soft'), Decimal('40'))
        self.assertEqual(run.value('basis.rehab_eligible'), Decimal('320'))
        self.assertEqual(run.value('tax.asset_basis', tax_asset='loan_cost'), Decimal('50'))
        self.assertEqual(run.value('uses.total_development_cost'), Decimal('846'))

    def test_credit_adjusters_use_calculated_delivery_without_changing_payins(self):
        from openhouse_engine.models.lihtc_equity import EquityAdjustment
        structure, inputs = example(month_count=23)
        structure = replace(structure, equity_adjustment=EquityAdjustment(2027, 2028, 11))
        inputs.update({'equity.adjustment.closing_annual_credit': '30',
                       'equity.adjustment.closing_first_year_credit': '10',
                       'equity.adjustment.closing_second_year_credit': '30',
                       'equity.adjustment.first_year_discount_rate': '0',
                       'equity.adjustment.second_year_discount_rate': '0'})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('equity.adjustment.projected_annual_credit'), Decimal('28'))
        self.assertEqual(run.value('equity.adjustment.annual'), Decimal('-18'))
        self.assertEqual(run.value('equity.adjustment.first_year_difference'), Decimal('19'))
        self.assertEqual(run.value('equity.adjustment.total'), Decimal('-18'))
        self.assertEqual(sum(run.series('equity.contribution')), run.value('equity.commitment'))

    def test_investor_buyout_uses_reviewed_outside_basis_and_modeled_debt_once(self):
        from openhouse_engine.models.lihtc_exit import ExitTerms
        structure, inputs = example()
        structure = replace(structure, exit_terms=ExitTerms(4))
        inputs.update({'exit.net_sale_cash': '1', 'exit.investor_distribution': '0',
                       'exit.investor_outside_basis': '100', 'exit.investor_liability_relief': '0',
                       'exit.investor_loss_utilization': '0', 'exit.investor_tax_rate': '0.25'})
        ordinary = calculate(replace(structure, exit_terms=None),
                             {k:v for k,v in inputs.items() if not k.startswith('exit.')})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('exit.debt_payoff'), Decimal('216.66'))
        capital = run.value('partner.ending_capital', partner='investor', tax_year=2027)
        self.assertEqual(run.value('exit.investor_gain'), Decimal('-100'))
        terminal = run.value('exit.investor_after_tax_cash')
        self.assertEqual(run.value('partner.total_after_tax_cash_flow', partner='investor', tax_year=2027),
                         ordinary.value('partner.after_tax_cash_flow', partner='investor', tax_year=2027) + terminal)
        self.assertEqual(run.value('funding.final_cash'), ordinary.value('funding.final_cash'))
        with self.assertRaises(ModelDefinitionError):
            replace(structure, exit_terms=ExitTerms(3))

    def test_deferred_fee_is_noncash_debt_repaid_in_the_declared_loan_priority(self):
        structure, inputs = example()
        fee = LoanTerms('developer_fee', 0, 3, 12, None, 'cash_flow_principal', False,
                        origination='noncash')
        structure = replace(structure, permanent_loans=structure.permanent_loans[:1] + (fee,),
                            deferred_fee_loan='developer_fee')
        inputs.update({'debt.developer_fee.annual_rate': '0',
                       'debt.developer_fee.paid_annual_rate': '0',
                       'debt.developer_fee.payment_cap': '30',
                       'debt.developer_fee.cash_flow_fraction': {m: '1' for m in range(5)}})
        inputs['tax.deductible_interest_fraction'].update({('developer_fee',m): '0' for m in range(5)})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('fee.accrual', month=0), Decimal('50'))
        self.assertEqual(run.value('debt.developer_fee.proceeds', month=0), Decimal('0'))
        self.assertEqual(run.value('funding.sources', month=0), Decimal('826.70'))
        self.assertEqual(run.value('funding.uses', month=0), Decimal('752'))
        self.assertEqual(run.value('fee.repayment', month=3), Decimal('30'))
        self.assertEqual(run.value('fee.repayment', month=4), Decimal('20'))
        self.assertEqual(run.value('fee.ending_balance', month=4), Decimal('0'))
        self.assertEqual(run.value('debt.debt_service', month=3), Decimal('46.67'))
        self.assertEqual(run.value('funding.final_cash'), Decimal('2514.06'))

    def test_deferred_fees_require_one_explicit_owner_and_no_duplicate_cash_advance(self):
        structure, inputs = example()
        no_fee = replace(structure, permanent_loans=structure.permanent_loans[:1], deferred_fee_loan=None)
        no_fee_inputs = {k:v for k,v in inputs.items() if not k.startswith('debt.developer_fee.')}
        no_fee_inputs['tax.deductible_interest_fraction'] = {('senior',m): '1' for m in range(5)}
        with self.assertRaises(EngineError) as err:
            calculate(no_fee, no_fee_inputs)
        self.assertEqual(err.exception.code, 'DEFERRED_FEE_LOAN_REQUIRED')
        no_fee_inputs['fee.deferred_fraction'] = '0'
        self.assertEqual(calculate(no_fee, no_fee_inputs).value('fee.ending_balance', month=4), Decimal('0'))
        with self.assertRaises(ModelDefinitionError):
            replace(structure, deferred_fee_loan='senior')
        with self.assertRaises(ModelDefinitionError):
            replace(structure, deferred_fee_loan='unknown')
        inputs['debt.developer_fee.amount'] = '50'
        with self.assertRaises(EngineError):
            calculate(structure, inputs)

    def test_tax_assets_preserve_reviewed_full_precision_amortization(self):
        structure, inputs = example()
        structure = replace(structure, tax_assets=(structure.tax_assets[0],
                            replace(structure.tax_assets[1], rounding_places=None)))
        inputs['tax.reviewed_recovery_fraction'][('loan_cost',2027)] = '0.3333333333333333333333333333333333'
        run = calculate(structure, inputs)
        self.assertEqual(run.value('tax.amortization', tax_year=2027),
                         Decimal('3.333333333333333333333333333333333'))
        self.assertEqual(run.value('tax.income', tax_year=2027), Decimal('2376.67'))
        structure = replace(structure, tax_assets=(structure.tax_assets[0],
                            TaxAsset('loan_cost', 'amortization', 2027,
                                     StraightLineRecovery(1, 36, 'monthly'), None)))
        inputs['tax.reviewed_recovery_fraction'][('loan_cost',2027)] = '0'
        run = calculate(structure, inputs)
        # Generated recovery covers January through May, retaining full precision.
        self.assertEqual(run.value('tax.amortization', tax_year=2027),
                         Decimal('1.388888888888888888888888888888889'))
        with self.assertRaises(ModelDefinitionError):
            replace(structure.tax_assets[1], rounding_places=True)

    def test_insurance_has_one_cash_owner_and_an_explicit_tax_deduction_share(self):
        structure, inputs = example()
        structure = replace(structure, permanent_loans=(replace(structure.permanent_loans[0],
                            mortgage_insurance_basis='original'),) + structure.permanent_loans[1:])
        inputs['debt.senior.mortgage_insurance_annual_rate'] = '0.12'
        inputs['tax.deductible_mortgage_insurance_fraction'] = {(l,m): '0.5' for l in ('senior','developer_fee') for m in range(5)}
        run = calculate(structure, inputs)
        self.assertEqual(run.value('debt.mortgage_insurance', month=3), Decimal('2'))
        self.assertEqual(run.value('tax.mortgage_insurance', tax_year=2027), Decimal('2'))
        self.assertEqual(run.value('tax.interest', tax_year=2027), Decimal('0'))
        self.assertEqual(run.value('tax.income', tax_year=2027), Decimal('2368.00'))
        self.assertEqual(run.value('funding.uses', month=3), Decimal('218.67'))

    def test_shared_cash_flow_loan_drives_funding_tax_and_minimum_gain(self):
        from openhouse_engine.financing import LoanTerms
        structure, inputs = example()
        structure = replace(structure, permanent_loans=structure.permanent_loans + (
            LoanTerms('seller', 3, 3, 12, None, 'cash_flow_principal', False),),
            nonrecourse_loans=(NonrecourseLoan('senior', False, 'senior'),
                               NonrecourseLoan('junior', True, 'seller')))
        inputs.update({'debt.seller.amount': '1000', 'debt.seller.annual_rate': '0.12',
                       'debt.seller.paid_annual_rate': '0.12', 'debt.seller.payment_cap': '0',
                       'debt.seller.cash_flow_fraction': {m: '0.5' for m in range(5)}})
        inputs['tax.deductible_interest_fraction'].update({('seller',m): '1' for m in range(5)})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('debt.seller.debt_service', month=3), Decimal('291.67'))
        self.assertEqual(run.value('debt.seller.ending_balance', month=3), Decimal('718.33'))
        self.assertEqual(run.value('debt.seller.ending_balance', month=4), Decimal('433.84'))
        self.assertEqual(run.value('minimum_gain.loan_balance', nonrecourse_loan='junior', tax_year=2027), Decimal('433.84'))
        self.assertEqual(run.value('tax.interest', tax_year=2027), Decimal('17.18'))
        self.assertEqual(run.value('funding.sources', month=3), Decimal('1200'))
        self.assertEqual(run.value('debt.debt_service', month=3), Decimal('308.34'))

    def test_accrued_simple_interest_uses_one_balance_owner_and_a_per_loan_tax_share(self):
        structure, inputs = example()
        structure = replace(structure, permanent_loans=structure.permanent_loans + (
            LoanTerms('seller', 3, 3, 12, None, 'cash_flow_interest', False),),
            nonrecourse_loans=(NonrecourseLoan('senior', False, 'senior'),
                               NonrecourseLoan('junior', True, 'seller')))
        inputs.update({'debt.seller.amount': '1000', 'debt.seller.annual_rate': '0.12',
                       'debt.seller.paid_annual_rate': '0.12', 'debt.seller.payment_cap': '0',
                       'debt.seller.cash_flow_fraction': {m: '0' for m in range(5)}})
        inputs['tax.deductible_interest_fraction'].update({('seller',m): '0.5' for m in range(5)})
        run = calculate(structure, inputs)
        self.assertEqual(run.value('debt.seller.debt_service', month=4), Decimal('0'))
        self.assertEqual(run.value('debt.seller.accrued_interest_balance', month=4), Decimal('20'))
        self.assertEqual(run.value('minimum_gain.loan_balance', nonrecourse_loan='junior', tax_year=2027), Decimal('1020'))
        self.assertEqual(run.value('minimum_gain.related', tax_year=2027), Decimal('206.66'))
        self.assertEqual(run.value('tax.interest', tax_year=2027), Decimal('10'))
        inputs['minimum_gain.reviewed_loan_balance'][('junior',2027)] = '1020'
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, 'NONRECOURSE_BALANCE_DUPLICATE')
        with self.assertRaises(ModelDefinitionError):
            replace(structure, nonrecourse_loans=(NonrecourseLoan('senior', False, 'unknown'),))
        with self.assertRaises(ModelDefinitionError):
            replace(structure, nonrecourse_loans=(NonrecourseLoan('senior', False, 'seller'),
                                                NonrecourseLoan('junior', True, 'seller')))

    def test_minimum_gain_reuses_modeled_permanent_balances_without_a_second_assumption(self):
        structure, inputs = example()
        structure = replace(structure, nonrecourse_loans=(NonrecourseLoan("senior", False, "senior"), structure.nonrecourse_loans[1]))
        run = calculate(structure, inputs)
        self.assertEqual(run.value("minimum_gain.loan_balance", nonrecourse_loan="senior", tax_year=2027), Decimal("166.66"))
        inputs["minimum_gain.reviewed_loan_balance"][("senior",2027)] = "10"
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, "NONRECOURSE_BALANCE_DUPLICATE")

    def test_equity_pricing_share_is_distinct_from_the_annual_partner_credit_share(self):
        structure, inputs = example()
        inputs["credits.investor_share"] = "1"
        inputs["partner.investor_credit_share"][2027] = "0.8"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("equity.commitment"), Decimal("255.96"))
        self.assertEqual(run.value("partner.credits", partner="investor", tax_year=2027), Decimal("9.48"))
        self.assertEqual(run.value("partner.credits", partner="sponsor", tax_year=2027), Decimal("2.37"))

    def test_replacement_reserve_expenditures_create_tax_assets_in_the_service_year(self):
        structure, inputs = example(month_count=23)
        structure = replace(structure, tax_assets=(TaxAsset("building", "depreciation", 2028,
                                   StraightLineRecovery(1, 12, "monthly"), 2), structure.tax_assets[1]))
        inputs["tax.asset_cost_fraction"][("acquisition_building","building")] = "0"
        inputs["tax.reviewed_recovery_fraction"][("building",2027)] = "0"
        inputs["reserve.opening_balance"]["replacement"] = "100"
        inputs["reserve.expenditure"][("replacement",12)] = "100"
        inputs["tax.replacement_asset_fraction"][("replacement","building",2028)] = "1"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("tax.asset_basis", tax_asset="building"), Decimal("100"))
        self.assertEqual(run.value("tax.depreciation", tax_year=2028), Decimal("100"))
        self.assertEqual(run.value("reserve.annual_ending_balance", reserve="replacement", tax_year=2028), Decimal("0"))
        self.assertEqual(run.value("minimum_gain.cumulative_asset_additions", tax_year=2028), Decimal("100"))

    def test_reviewed_table_recovery_supports_workbook_whole_dollar_rounding(self):
        structure, inputs = example(month_count=35)
        structure = replace(structure, tax_assets=(replace(structure.tax_assets[0], rounding_places=0), structure.tax_assets[1]))
        inputs["tax.reviewed_recovery_fraction"] = {(a,y): "0.333333" if a == "building" else v
                                                    for (a,y),v in inputs["tax.reviewed_recovery_fraction"].items()}
        run = calculate(structure, inputs)
        self.assertEqual(run.value("tax.depreciation", tax_year=2027), Decimal("67"))
        self.assertEqual(run.value("tax.depreciation", tax_year=2028), Decimal("67"))
        self.assertEqual(run.value("tax.depreciation", tax_year=2029), Decimal("66"))
        self.assertEqual(run.value("tax.asset_remaining_basis", tax_asset="building"), Decimal("0"))

    def test_reserve_yield_keeps_workbook_precision_until_the_tax_bridge(self):
        structure, inputs = example()
        inputs["reserve.opening_balance"]["operating"] = "0.01"
        inputs["reserve.annual_rate"][("operating",2027)] = "0.25"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("reserve.annual_interest", reserve="operating", tax_year=2027), Decimal("0.0025"))
        self.assertEqual(run.value("reserve.annual_ending_balance", reserve="operating", tax_year=2027), Decimal("0.0125"))

    def test_capitalized_reserves_follow_their_separate_funding_milestones(self):
        structure, inputs = example()
        inputs["cost.amount"][("reserves", 0)] = "50"
        inputs["cost.amount"][("reserves", 2)] = "100"
        inputs["reserve.capitalized_fraction"][("operating",2)] = "0"
        inputs["reserve.capitalized_fraction"][("replacement",2)] = "1"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("reserve.ending_balance", reserve="operating", month=2), Decimal("50"))
        self.assertEqual(run.value("reserve.ending_balance", reserve="replacement", month=2), Decimal("100"))

    def test_negative_opening_capital_is_evidence_and_does_not_manufacture_loss_capacity(self):
        structure, inputs = example()
        structure = replace(structure, reallocate_losses=True)
        inputs["tax.other_deductions"][2027] = "2500"
        capital = inputs.pop("partner.opening_capital")
        capital["investor"] = "-1000"
        documents = {"partner.opening_capital": {"name": "synthetic-capital.json", "sha256": "d" * 64}}
        run = calculate(structure, inputs, {"partner.opening_capital": capital}, documents=documents)
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2027), Decimal("0"))
        self.assertEqual(run.value("partner.ending_capital", partner="investor", tax_year=2027), Decimal("-746.60"))

    def test_income_allocation_restores_capital_and_minimum_gain_declines_are_not_new_loss_capacity(self):
        structure, inputs = example(month_count=25)
        structure = replace(structure, reallocate_losses=True, allocation_places=0)
        inputs["minimum_gain.original_asset_basis"] = "100"
        inputs["minimum_gain.reviewed_loan_balance"][("senior", 2027)] = "180"
        inputs["minimum_gain.reviewed_loan_balance"][("senior", 2028)] = "80"
        inputs["partner.capital_reduction"][("investor", 2027)] = "250"
        inputs["tax.other_deductions"].update({2027: "6670", 2028: "7300", 2029: "1000"})
        inputs["partner.gross_income_to_sponsor"][2029] = "10"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("minimum_gain.unrelated_change", tax_year=2028), Decimal("-100"))
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2027), Decimal("-80"))
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2028), Decimal("0"))
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2029), Decimal("152"))
        self.assertEqual(run.value("partner.taxable_income", partner="sponsor", tax_year=2029), Decimal("48"))
        self.assertEqual(run.value("partner.ending_capital", partner="investor", tax_year=2029), Decimal("75.40"))

    def test_straight_line_recovery_calculates_midmonth_partial_years_without_recovery_inputs(self):
        structure, inputs = example(month_count=47)
        structure = replace(structure, tax_assets=(TaxAsset("building", "depreciation", 2027,
                                       StraightLineRecovery(service_month=11, months=24, convention="mid_month"), 2),
                                       structure.tax_assets[1]))
        inputs["tax.reviewed_recovery_fraction"] = {(a,y): "0" if a == "building" else v
                                                    for (a,y),v in inputs["tax.reviewed_recovery_fraction"].items()}
        run = calculate(structure, inputs)
        self.assertEqual(run.value("tax.depreciation", tax_year=2027), Decimal("12.50"))
        self.assertEqual(run.value("tax.depreciation", tax_year=2028), Decimal("100"))
        self.assertEqual(run.value("tax.depreciation", tax_year=2029), Decimal("87.50"))
        self.assertEqual(run.value("tax.asset_remaining_basis", tax_asset="building"), Decimal("0"))
        inputs["tax.reviewed_recovery_fraction"][("building", 2027)] = "0.1"
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, "RECOVERY_METHOD_CONFLICT")

    def test_reserve_funding_reconciles_cents_and_rejects_midyear_overdraws(self):
        structure, inputs = example()
        inputs["cost.amount"][("reserves", 0)] = "0.01"
        inputs["reserve.capitalized_fraction"][("operating",0)] = "0.5"
        inputs["reserve.capitalized_fraction"][("replacement",0)] = "0.5"
        run = calculate(structure, inputs)
        self.assertEqual(sum(run.value("reserve.capitalized_contribution", reserve=r, month=0)
                             for r in ("lease_up", "operating", "replacement", "other_1", "other_2")), Decimal("0.01"))
        inputs["reserve.release"][("replacement", 1)] = "10"
        inputs["reserve.deposit"][("replacement", 4)] = "10"
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, "RESERVE_OVERDRAWN")

    def test_investor_cash_retention_flows_to_operating_reserve_and_earns_interest_next_year(self):
        structure, inputs = example(month_count=13)
        inputs["funding.selected_distribution"][3] = "100"
        inputs["partner.investor_distribution_fraction"][3] = "0.5"
        inputs["reserve.deposit"][("replacement", 3)] = "20"
        inputs["reserve.annual_rate"][("operating", 2028)] = "0.1"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("partner.distribution", partner="investor", month=3), Decimal("45"))
        self.assertEqual(run.value("partner.distribution", partner="sponsor", month=3), Decimal("10"))
        self.assertEqual(run.value("funding.distribution", month=3), Decimal("55"))
        self.assertEqual(run.value("reserve.annual_ending_balance", reserve="operating", tax_year=2027), Decimal("45"))
        self.assertEqual(run.value("reserve.annual_ending_balance", reserve="operating", tax_year=2028), Decimal("49.50"))
        self.assertEqual(run.value("tax.reserve_interest", tax_year=2028), Decimal("4.50"))
        self.assertEqual(run.value("reserve.annual_ending_balance", reserve="replacement", tax_year=2027), Decimal("20"))
        self.assertEqual(run.value("funding.ending_cash", month=3), Decimal("1860.73"))

    def test_loss_reallocation_reduces_investor_credits_with_a_visible_unallocated_balance(self):
        structure, inputs = example()
        structure = replace(structure, reallocate_losses=True, reduce_credits_for_reallocated_losses=True)
        inputs["tax.other_deductions"][2027] = "5000"
        inputs["partner.capital_reduction"][("investor", 2027)] = "3.40"
        run = calculate(structure, inputs)
        self.assertAlmostEqual(run.value("partner.credit_allowable_fraction", tax_year=2027), Decimal(250) / Decimal(2104), places=26)
        self.assertEqual(run.value("partner.credits", partner="investor", tax_year=2027), Decimal("1.39"))
        self.assertEqual(run.value("credits.unallocated", tax_year=2027), Decimal("10.34"))
        self.assertEqual(sum(run.value("partner.credits", partner=p, tax_year=2027) for p in ("investor", "sponsor"))
                         + run.value("credits.unallocated", tax_year=2027), Decimal("11.85"))

    def test_minimum_gain_observes_lien_priority_and_related_party_loss_shift(self):
        structure, inputs = example()
        structure = replace(structure, reallocate_losses=True)
        inputs["minimum_gain.original_asset_basis"] = "100"
        inputs["minimum_gain.reviewed_loan_balance"][("senior", 2027)] = "90"
        inputs["minimum_gain.reviewed_loan_balance"][("junior", 2027)] = "50"
        inputs["tax.other_deductions"][2027] = "2500"
        run = calculate(structure, inputs)
        # Assets net of 20 depreciation = 80; first lien absorbs all of them.
        self.assertEqual(run.value("minimum_gain.unrelated", tax_year=2027), Decimal("10"))
        self.assertEqual(run.value("minimum_gain.related", tax_year=2027), Decimal("50"))
        self.assertEqual(run.value("partner.initial_investor_income", tax_year=2027), Decimal("-104"))
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2027), Decimal("-154"))
        self.assertEqual(run.value("partner.taxable_income", partner="sponsor", tax_year=2027), Decimal("24"))

    def test_capital_limits_reallocate_investor_losses_and_preserve_project_income(self):
        structure, inputs = example()
        structure = replace(structure, reallocate_losses=True)
        inputs["tax.other_deductions"][2027] = "5000"
        inputs["partner.capital_reduction"][("investor", 2027)] = "3.40"
        run = calculate(structure, inputs)
        # Investor contributes 253.40, leaving 250 of capacity after syndication.
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2027), Decimal("-250"))
        self.assertEqual(run.value("partner.taxable_income", partner="sponsor", tax_year=2027), Decimal("-2380"))
        self.assertEqual(run.value("partner.loss_reallocated", tax_year=2027), Decimal("-1854"))
        self.assertEqual(run.value("partner.ending_capital", partner="investor", tax_year=2027), Decimal("0"))

    def test_tax_interest_uses_reviewed_deduction_share_without_deducting_principal(self):
        structure, inputs = example()
        inputs["debt.senior.amount"] = "1200"
        inputs["debt.senior.annual_rate"] = "0.12"
        inputs["tax.deductible_interest_fraction"][("senior",3)] = "0.5"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("tax.interest", tax_year=2027), Decimal("17.05"))
        self.assertEqual(run.value("tax.income", tax_year=2027), Decimal("2352.95"))

    def test_calendar_years_sum_only_their_months_and_do_not_drop_closing_equity(self):
        structure, inputs = example(month_count=13, start_month=11)
        run = calculate(structure, inputs)
        self.assertEqual(run.value("tax.noi", tax_year=2027), Decimal("600"))
        self.assertEqual(run.value("tax.noi", tax_year=2028), Decimal("7200"))
        self.assertEqual(run.value("partner.annual_contribution", partner="investor", tax_year=2027), Decimal("253.40"))
        self.assertEqual(run.value("partner.annual_contribution", partner="investor", tax_year=2028), Decimal("0"))

    def test_cash_allocations_leave_undistributed_cash_and_fee_obligations_visible(self):
        structure, inputs = example()
        inputs["funding.selected_distribution"][3] = "100.01"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("funding.available_distribution", month=3), Decimal("1980.73"))
        self.assertEqual(run.value("funding.ending_cash", month=3), Decimal("1880.72"))
        self.assertEqual(run.value("fee.ending_balance", month=3), Decimal("50"))
        self.assertEqual(sum(run.value("partner.distribution", partner=p, month=3)
                             for p in ("investor", "sponsor")), Decimal("100.01"))

    def test_calendar_and_recovery_boundaries_are_validated(self):
        structure, inputs = example()
        for changes in ({"months": "4"}, {"start_month": 0}, {"start_year": True},
                        {"tax_assets": ()}, {"acquisition_credit_year": 2026}):
            with self.subTest(changes=changes), self.assertRaises(ModelDefinitionError):
                replace(structure, **changes)
        future = replace(structure, allocation_places=2, reallocate_losses=False, reduce_credits_for_reallocated_losses=False,
                          minimum_gain_include_operating_reserve=True, minimum_gain_include_other_reserves=True,
                          nonrecourse_loans=(NonrecourseLoan("senior", False, None), NonrecourseLoan("junior", True, None)),
                          tax_assets=(TaxAsset("building", "depreciation", 2028, None, 2), structure.tax_assets[1]))
        with self.assertRaises(EngineError) as err:
            calculate(future, inputs)
        self.assertEqual(err.exception.code, "RECOVERY_BEFORE_SERVICE")
        structure, inputs = example(month_count=13, start_month=11)
        inputs["tax.reviewed_recovery_fraction"][("building", 2027)] = "0.6"
        inputs["tax.reviewed_recovery_fraction"][("building", 2028)] = "0.6"
        with self.assertRaises(EngineError) as err:
            calculate(structure, inputs)
        self.assertEqual(err.exception.code, "TAX_RECOVERY_EXCEEDS_BASIS")

    def test_new_tax_sources_pin_lineage_and_reject_unreviewed_allocations(self):
        structure, inputs = example()
        recovery = inputs.pop("tax.reviewed_recovery_fraction")
        documents = {"tax.reviewed_recovery_fraction": {"name": "synthetic-recovery.json", "sha256": "c" * 64}}
        run = calculate(structure, inputs, {"tax.reviewed_recovery_fraction": recovery}, documents=documents)
        self.assertEqual(run.lineage["tax.reviewed_recovery_fraction"]["kind"], "source")
        self.assertEqual(run.value("tax.depreciation", tax_year=2027), Decimal("20"))
        for variable, key, value, code in (
            ("tax.asset_cost_fraction", ("land", "building"), "0.1", "NONRECOVERABLE_TAX_BASIS"),
            ("tax.asset_cost_fraction", ("reserves", "loan_cost"), "0.1", "NONRECOVERABLE_TAX_BASIS"),
            ("tax.asset_cost_fraction", ("acquisition_building", "loan_cost"), "0.6", "TAX_BASIS_ALLOCATION_EXCEEDS_COST"),
            ("tax.reviewed_recovery_fraction", ("building", 2027), "1.1", "INPUT_OUT_OF_RANGE"),
            ("partner.investor_cash_share", 3, "1.1", "INPUT_OUT_OF_RANGE"),
            ("partner.loss_utilization", ("investor", 2027), "-0.1", "INPUT_OUT_OF_RANGE"),
        ):
            with self.subTest(variable=variable):
                structure, inputs = example()
                inputs[variable][key] = value
                with self.assertRaises(EngineError) as err:
                    calculate(structure, inputs)
                self.assertEqual(err.exception.code, code)

    def test_after_tax_flows_use_only_reviewed_usable_losses_and_credits(self):
        structure, inputs = example()
        inputs["tax.other_deductions"][2027] = "5000"
        inputs["partner.loss_utilization"][("investor", 2027)] = "0.5"
        inputs["partner.credit_utilization"][("investor", 2027)] = "0.5"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2027), Decimal("-2104"))
        self.assertEqual(run.value("partner.unutilized_loss", partner="investor", tax_year=2027), Decimal("1052"))
        self.assertEqual(run.value("partner.unutilized_credit", partner="investor", tax_year=2027), Decimal("5.86"))
        self.assertEqual(run.value("partner.tax_benefit", partner="investor", tax_year=2027), Decimal("268.87"))

    def test_recovery_rounding_preserves_asset_basis_over_years(self):
        structure, inputs = example(month_count=13)
        inputs["cost.amount"][("acquisition_building", 0)] = "0.06"
        inputs["bond.financed_cost"]["acquisition_building"] = "0"
        inputs["tax.reviewed_recovery_fraction"][("building", 2027)] = "0.5"
        inputs["tax.reviewed_recovery_fraction"][("building", 2028)] = "0.5"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("tax.asset_remaining_basis", tax_asset="building"), Decimal("0"))
        self.assertEqual(run.value("tax.depreciation", tax_year=2027) +
                         run.value("tax.depreciation", tax_year=2028), Decimal("0.03"))

    def test_credit_streams_have_separate_start_years_and_caps_and_reconcile_ten_years(self):
        structure, inputs = example(month_count=143)
        structure = replace(structure, acquisition_credit_year=2028)
        inputs["credits.acquisition_annual_cap"] = "10"
        inputs["credits.rehab_annual_cap"] = "12"
        inputs["credits.acquisition_qualified_fraction"] = {m: "0.5" for m in range(1, 13)}
        inputs["credits.rehab_qualified_fraction"] = {m: "0.25" for m in range(1, 13)}
        run = calculate(structure, inputs)
        self.assertEqual(run.value("credits.acquisition_delivered", tax_year=2027), Decimal("0"))
        self.assertEqual(run.value("credits.acquisition_delivered", tax_year=2028), Decimal("5"))
        self.assertEqual(run.value("credits.acquisition_delivered", tax_year=2038), Decimal("5"))
        self.assertEqual(run.value("credits.rehab_delivered", tax_year=2027), Decimal("3"))
        self.assertEqual(run.value("credits.rehab_delivered", tax_year=2037), Decimal("9"))
        self.assertEqual(sum(run.series("credits.delivered")), Decimal("220"))
        self.assertEqual(run.value("credits.undelivered"), Decimal("0"))
        self.assertEqual(run.value("equity.commitment"), Decimal("196.02"))

    def test_partner_allocations_reconcile_cash_credits_income_and_after_tax_flows(self):
        structure, inputs = example()
        inputs["funding.selected_distribution"][3] = "100.01"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("partner.distribution", partner="investor", month=3), Decimal("90.01"))
        self.assertEqual(run.value("partner.distribution", partner="sponsor", month=3), Decimal("10.00"))
        self.assertEqual(run.value("partner.credits", partner="investor", tax_year=2027), Decimal("11.73"))
        self.assertEqual(run.value("partner.credits", partner="sponsor", tax_year=2027), Decimal("0.12"))
        self.assertEqual(run.value("partner.taxable_income", partner="investor", tax_year=2027), Decimal("1896"))
        self.assertEqual(run.value("partner.tax_benefit", partner="investor", tax_year=2027), Decimal("-462.27"))
        self.assertEqual(run.value("partner.after_tax_cash_flow", partner="investor", tax_year=2027), Decimal("-625.66"))
        self.assertEqual(run.value("partner.after_tax_cash_flow", partner="sponsor", tax_year=2027), Decimal("-584.68"))

    def test_annual_tax_income_deducts_asset_recovery_and_interest_not_principal(self):
        structure, inputs = example()
        inputs["tax.other_income"][2027] = "5"
        inputs["tax.other_deductions"][2027] = "15"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("tax.noi", tax_year=2027), Decimal("2400"))
        self.assertEqual(run.value("tax.depreciation", tax_year=2027), Decimal("20"))
        self.assertEqual(run.value("tax.amortization", tax_year=2027), Decimal("10"))
        self.assertEqual(run.value("tax.income", tax_year=2027), Decimal("2360"))
        self.assertEqual(run.value("tax.asset_remaining_basis", tax_asset="building"), Decimal("180"))

    def test_first_year_credits_defer_the_balance_to_year_eleven(self):
        structure, inputs = example()
        run = calculate(structure, inputs)
        self.assertEqual(run.value("credits.acquisition_delivered", tax_year=2027), Decimal("6.00"))
        self.assertEqual(run.value("credits.rehab_delivered", tax_year=2027), Decimal("5.85"))
        self.assertEqual(run.value("credits.undelivered"), Decimal("272.55"))

    def test_distinct_model_separates_acquisition_and_boosted_rehab_basis(self):
        structure, inputs = example()
        run = calculate(structure, inputs)
        self.assertEqual((run.model_id, run.model_version), ("lihtc-acquisition-rehab", "12.0.0"))
        self.assertEqual(run.value("basis.acquisition_eligible"), Decimal("400"))
        self.assertEqual(run.value("basis.rehab_eligible"), Decimal("300"))
        self.assertEqual(run.value("basis.acquisition_qualified"), Decimal("360"))
        self.assertEqual(run.value("basis.rehab_qualified"), Decimal("351"))
        self.assertEqual(run.value("credits.annual"), Decimal("28.44"))
        self.assertEqual(run.value("equity.commitment"), Decimal("253.40"))

    def test_restricted_rents_and_operating_noi_follow_monthly_occupancy(self):
        structure, inputs = example()
        inputs["rent.occupied_units"][("restricted", 1)] = 5
        run = calculate(structure, inputs)
        self.assertEqual(run.value("operations.noi", month=0), Decimal("0"))
        self.assertEqual(run.value("rent.collected", unit_type="restricted", month=1), Decimal("450"))
        self.assertEqual(run.value("operations.noi", month=1), Decimal("150"))
        self.assertEqual(run.value("operations.noi", month=2), Decimal("600"))

    def test_equity_installments_and_debt_conversion_reconcile_cash(self):
        structure, inputs = example()
        run = calculate(structure, inputs)
        self.assertEqual(run.value("equity.contribution", month=0), Decimal("126.70"))
        self.assertEqual(run.value("construction.ending_balance", facility="bond", month=2), Decimal("200"))
        self.assertEqual(run.value("construction.repayment", facility="bond", month=3), Decimal("200"))
        self.assertEqual(run.value("construction.ending_balance", facility="bond", month=3), Decimal("0"))
        self.assertEqual(run.value("construction.interest", facility="bond", month=3), Decimal("0"))
        self.assertEqual(run.value("debt.senior.payment"), Decimal("16.67"))
        self.assertEqual(run.value("debt.ending_balance", month=4), Decimal("216.66"))
        self.assertEqual(run.value("fee.ending_balance", month=4), Decimal("50"))
        self.assertEqual(run.value("funding.ending_cash", month=0), Decimal("74.70"))
        self.assertEqual(run.value("funding.final_cash"), Decimal("2564.06"))
        self.assertEqual(run.value("funding.maximum_gap"), Decimal("0"))
        self.assertEqual(run.value("bond.financed_fraction"), Decimal("0.25"))
        self.assertEqual(run.value("bond.test_passed"), Decimal("1"))

    def test_funding_shortfall_is_reported_without_an_equity_plug(self):
        structure, inputs = example()
        inputs["funding.sponsor_equity"][0] = "0"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("funding.ending_cash", month=0), Decimal("-425.30"))
        self.assertEqual(run.value("funding.maximum_gap"), Decimal("425.30"))
        self.assertEqual(run.value("funding.final_cash"), Decimal("2064.06"))

    def test_invalid_financing_and_rent_schedules_are_rejected(self):
        for variable, key, value, code in (
            ("construction.draw", ("bond", 3), "1", "DRAW_AFTER_CONVERSION"),
            ("construction.draw", ("bond", 0), "501", "CONSTRUCTION_COMMITMENT_EXCEEDED"),
            ("rent.occupied_units", ("restricted", 1), 11, "OCCUPANCY_EXCEEDS_UNITS"),
            ("rent.utility_allowance", ("restricted", 1), "101", "UTILITY_ALLOWANCE_EXCEEDS_RENT"),
                        ("cost.amount", ("rehab_hard", 3), "1", "COST_AFTER_DEVELOPMENT_CUTOFF"),
            ("funding.selected_distribution", 1, "1", "DISTRIBUTION_BEFORE_CONVERSION"),
            ("funding.selected_distribution", 3, "9999", "DISTRIBUTION_EXCEEDS_CASH"),
        ):
            with self.subTest(variable=variable, key=key):
                structure, inputs = example()
                inputs[variable][key] = value
                with self.assertRaises(EngineError) as err:
                    calculate(structure, inputs)
                self.assertEqual(err.exception.code, code)

    def test_permanent_debt_pays_rounding_residual_at_maturity(self):
        structure, inputs = example()
        structure = replace(structure, permanent_loans=(replace(structure.permanent_loans[0], amortization_months=2, maturity_month=4),) + structure.permanent_loans[1:])
        inputs["debt.senior.amount"] = "100.01"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("debt.debt_service", month=3), Decimal("50.01"))
        self.assertEqual(run.value("debt.debt_service", month=4), Decimal("50.00"))
        self.assertEqual(run.value("debt.senior.ending_balance", month=4), Decimal("0"))

    def test_cost_allocations_allow_split_fees_and_capitalized_financing(self):
        structure, inputs = example()
        structure = replace(structure, equity_installments=(EquityInstallment('closing', 0, 'percentage'),))
        inputs['equity.closing.fraction'] = '1'
        inputs.pop('equity.completion.fraction')
        inputs["basis.acquisition_fraction"]["developer_fee"] = "0.2"
        inputs["basis.rehab_fraction"]["developer_fee"] = "0.8"
        inputs["basis.rehab_fraction"]["financing"] = "0.5"
        inputs["cost.amount"][("financing", 0)] = "100"
        inputs["construction.annual_rate"] = {f: "0" for f in inputs["construction.annual_rate"]}
        run = calculate(structure, inputs)
        self.assertEqual(run.value("basis.acquisition_eligible"), Decimal("420"))
        self.assertEqual(run.value("basis.rehab_eligible"), Decimal("330"))

    def test_equity_rounding_occurs_after_full_credit_pricing(self):
        structure, inputs = example()
        inputs["cost.amount"][("rehab_hard", 0)] = "200.01"
        inputs["equity.rounding_increment"] = "100"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("credits.rehab_annual"), Decimal("14.040468"))
        self.assertEqual(run.value("equity.commitment"), Decimal("300"))
        self.assertEqual(sum(run.series("equity.contribution")), Decimal("300"))

    def test_construction_interest_enters_development_cost_and_reviewed_basis_once(self):
        structure, inputs = example()
        inputs["basis.rehab_fraction"]["financing"] = "1"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("cost.total", cost="financing"), Decimal("6"))
        self.assertEqual(run.value("uses.total_development_cost"), Decimal("806"))
        self.assertEqual(run.value("basis.rehab_eligible"), Decimal("306"))

    def test_source_documents_remain_separate_and_pin_run_lineage(self):
        structure, inputs = example()
        expenses = inputs.pop("operations.expenses")
        sources = {"operations.expenses": expenses}
        documents = {"operations.expenses": {"name": "synthetic-budget.json", "sha256": "a" * 64}}
        run = calculate(structure, inputs, sources, documents=documents)
        self.assertEqual(run.lineage["operations.expenses"]["kind"], "source")
        self.assertEqual(run.lineage["operations.expenses"]["document"], documents["operations.expenses"])
        self.assertEqual(run.digest, calculate(structure, inputs, sources, documents=documents).digest)
        documents["operations.expenses"]["sha256"] = "b" * 64
        self.assertNotEqual(run.digest, calculate(structure, inputs, sources, documents=documents).digest)
        with self.assertRaises(EngineError) as err:
            calculate(structure, {**inputs, **sources}, documents=documents)
        self.assertEqual(err.exception.code, "INPUT_UNKNOWN")

    def test_source_identity_requires_digest_and_can_only_name_sources(self):
        structure, inputs = example()
        for documents in ({"operations.expenses": {"name": "budget.json"}},
                          {"operations.noi": {"name": "budget.json", "sha256": "a" * 64}}):
            with self.subTest(documents=documents), self.assertRaises(ModelDefinitionError):
                calculate(structure, inputs, documents=documents)

    def test_nonzero_rate_payment_and_principal_are_financially_consistent(self):
        structure, inputs = example()
        inputs["debt.senior.amount"] = "1200"
        inputs["debt.senior.annual_rate"] = "0.12"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("debt.senior.payment"), Decimal("106.62"))
        self.assertEqual(run.value("debt.interest", month=3), Decimal("12.00"))
        self.assertEqual(run.value("debt.principal", month=3), Decimal("94.62"))
        self.assertEqual(run.value("debt.ending_balance", month=3), Decimal("1155.38"))
        self.assertEqual(run.value("debt.interest", month=4), Decimal("11.05"))

    def test_bond_test_is_independent_of_lihtc_eligible_basis_and_credit_rates(self):
        structure, inputs = example()
        structure = replace(structure, equity_installments=(EquityInstallment('closing', 0, 'percentage'),))
        inputs['equity.closing.fraction'] = '1'
        inputs.pop('equity.completion.fraction')
        inputs["bond.required_fraction"] = "0.5"
        inputs["basis.rehab_boost"] = "1"
        run = calculate(structure, inputs)
        self.assertEqual(run.value("bond.basis"), Decimal("800"))
        self.assertEqual(run.value("bond.financed_fraction"), Decimal("0.25"))
        self.assertEqual(run.value("bond.test_passed"), Decimal("0"))
        self.assertEqual(run.value("credits.annual"), Decimal("25.20"))

    def test_deferred_fee_rounding_reconciles_to_total_deferral(self):
        structure, inputs = example()
        structure = replace(structure, equity_installments=(EquityInstallment('closing', 0, 'percentage'),))
        inputs['equity.closing.fraction'] = '1'
        inputs.pop('equity.completion.fraction')
        inputs["cost.amount"][("developer_fee", 0)] = "0.03"
        inputs["cost.amount"][("developer_fee", 1)] = "0.03"
        run = calculate(structure, inputs)
        self.assertEqual(sum(run.series("fee.accrual")), Decimal("0.03"))
        self.assertEqual(run.value("fee.ending_balance", month=4), Decimal("0.03"))


if __name__ == "__main__":
    unittest.main()
