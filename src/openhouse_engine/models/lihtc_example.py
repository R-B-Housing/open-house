"""Complete synthetic 24-unit acquisition/rehab with invented values.

Run from the repository with:
    PYTHONPATH=src python3 -m examples.lihtc_acquisition_rehab

All amounts are explicit assumptions. The 15-year forecast has a one-year
construction loan, rehabilitation paid over twelve months, tax-credit equity,
permanent senior and cash-flow loans,
deferred developer fee, restricted reserves, tax allocations and investor
buyout. The buyout is a valuation, not project liquidation or a cash source.
"""
from openhouse_engine.financing import LoanTerms
from openhouse_engine.models.lihtc_acquisition_rehab import (
    NonrecourseLoan, StraightLineRecovery, Structure, TaxAsset, calculate,
)
from openhouse_engine.models.lihtc_costs import CostItem
from openhouse_engine.models.lihtc_exit import ExitTerms
from openhouse_engine.models.lihtc_payins import EquityInstallment
from openhouse_engine.models.lihtc_returns import ReturnTerms


def build_example(horizon=180):
    """Return fresh public Structure and assumptions, ready for calculate()."""
    cost_names = ('land', 'acquisition_building', 'acquisition_costs',
                  'rehab_hard', 'rehab_soft', 'financing', 'reserves', 'developer_fee')
    assets = ('acquisition_building', 'rehab_building', 'loan_cost', 'replacement_asset')
    reserves = ('lease_up', 'operating', 'replacement', 'other_1', 'other_2')
    facilities = ('bond', 'taxable', 'equity_bridge')
    loans = ('senior', 'soft_loan', 'developer_fee')
    partners = ('investor', 'sponsor')
    structure = Structure(
        unit_types=('restricted',), cost_items=tuple(CostItem(c, c) for c in cost_names),
        construction_interest_cost='financing', months=horizon, conversion_month=12,
        permanent_loans=(
            LoanTerms('senior', 12, 12, 360, None, 'amortizing', False),
            LoanTerms('soft_loan', 12, 12, 180, None, 'cash_flow_principal', False),
            LoanTerms('developer_fee', 0, 12, 180, None, 'cash_flow_principal', False,
                      origination='noncash')),
        deferred_fee_loan='developer_fee', start_year=2027, start_month=1,
        acquisition_credit_year=2028, rehab_credit_year=2028,
        # This synthetic investor funds its entire commitment at closing.
        # Annual returns place closing cash at period zero, calendar-year
        # benefits at annual endpoints, and the final partial year at one
        # additional annual interval; these are not date-weighted returns.
        equity_installments=(EquityInstallment('closing', 0, 'percentage'),),
        tax_assets=(TaxAsset('acquisition_building', 'depreciation', 2027,
                             StraightLineRecovery(1, 330, 'mid_month'), 2),
                    TaxAsset('rehab_building', 'depreciation', 2028,
                             StraightLineRecovery(1, 330, 'mid_month'), 2),
                    TaxAsset('loan_cost', 'amortization', 2028,
                             StraightLineRecovery(1, 180, 'monthly'), 2),
                    TaxAsset('replacement_asset', 'depreciation', 2037,
                             StraightLineRecovery(1, 330, 'monthly'), 2)),
        nonrecourse_loans=(NonrecourseLoan('senior', False, 'senior'),
                          NonrecourseLoan('soft_loan', False, 'soft_loan'),
                          NonrecourseLoan('developer_fee', True, 'developer_fee')),
        allocation_places=2, reallocate_losses=False,
        reduce_credits_for_reallocated_losses=False,
        minimum_gain_include_operating_reserve=True,
        minimum_gain_include_other_reserves=True, exit_terms=ExitTerms(horizon),
        return_terms=ReturnTerms('-.99', '10', 80, frequency='annual'))
    months = range(horizon + 1)
    years = range(structure.start_year, structure.last_year + 1)
    costs = {'land': '200000', 'acquisition_building': '1000000',
             'acquisition_costs': '0', 'rehab_hard': '500000', 'rehab_soft': '50000',
             'financing': '50000', 'reserves': '100000', 'developer_fee': '200000'}
    scheduled_costs = {(c, m): costs[c] if m == 0 else '0' for c in cost_names for m in months}
    # Each schedule has eleven equal rounded payments and an explicit final
    # payment, keeping every modeled cost exact without a funding plug.
    for c, regular, final in (('rehab_hard', '41666.67', '41666.63'),
                              ('developer_fee', '16666.67', '16666.63')):
        for m in months:
            scheduled_costs[(c, m)] = regular if m < 11 else final if m == 11 else '0'
    inputs = {
        'cost.amount': scheduled_costs,
        'basis.acquisition_fraction': {c: '1' if c == 'acquisition_building' else '0' for c in cost_names},
        'basis.rehab_fraction': {c: '1' if c in ('rehab_hard', 'rehab_soft', 'developer_fee') else '0' for c in cost_names},
        'basis.applicable_fraction': '.9', 'basis.rehab_boost': '1.3',
        'credits.acquisition_rate': '.04', 'credits.rehab_rate': '.04',
        'credits.acquisition_annual_cap': '1000000', 'credits.rehab_annual_cap': '1000000',
        'credits.investor_share': '.99', 'credits.price': '.9',
        'credits.acquisition_qualified_fraction': {m: '1' for m in range(1, 13)},
        'credits.rehab_qualified_fraction': {m: '1' for m in range(1, 13)},
        'equity.rounding_increment': '.01', 'equity.closing.fraction': '1',
        'bond.financed_cost': {c: '1000000' if c == 'acquisition_building' else '200000' if c == 'rehab_hard' else '0' for c in cost_names},
        'bond.basis_fraction': {c: '0' if c in ('financing', 'reserves') else '1' for c in cost_names},
        'bond.required_fraction': '.5',
        'construction.commitment': {f: '1200000' if f == 'bond' else '0' for f in facilities},
        'construction.annual_rate': {f: '.06' if f == 'bond' else '0' for f in facilities},
        'construction.draw': {(f, m): '1200000' if f == 'bond' and m == 0 else '0' for f in facilities for m in months},
        'debt.senior.amount': '1200000', 'debt.senior.annual_rate': '.05',
        'debt.soft_loan.amount': '200000', 'debt.soft_loan.annual_rate': '0',
        'debt.soft_loan.paid_annual_rate': '0', 'debt.soft_loan.payment_cap': '0',
        'debt.soft_loan.cash_flow_fraction': {m: '.5' for m in months},
        'debt.developer_fee.annual_rate': '0', 'debt.developer_fee.paid_annual_rate': '0',
        'debt.developer_fee.payment_cap': '0',
        'debt.developer_fee.cash_flow_fraction': {m: '.5' for m in months},
        'fee.deferred_fraction': '.5',
        'funding.sponsor_equity': {m: '800000' if m == 0 else '0' for m in months},
        'funding.other_sources': {m: '0' for m in months},
        'funding.selected_distribution': {m: '3000' if m >= 13 else '0' for m in months},
        'units': {'restricted': 24},
        'rent.market': {('restricted', m): '1100' for m in months},
        'rent.maximum_gross': {('restricted', m): '1000' for m in months},
        'rent.utility_allowance': {('restricted', m): '100' for m in months},
        'rent.occupied_units': {('restricted', m): 24 for m in months},
        'operations.other_income': {m: '0' for m in months},
        'operations.expenses': {m: '10000' for m in months},
        "reserve.investor_retained_release": {m: "0" for m in months},
        "reserve.investor_retained_opening_balance": "0",
        'reserve.opening_balance': {r: '0' for r in reserves},
        'reserve.capitalized_fraction': {(r, m): '1' if r == 'operating' else '0' for r in reserves for m in months},
        'reserve.annual_rate': {(r, y): '0' for r in reserves for y in years},
        'reserve.deposit': {(r, m): '1000' if r == 'replacement' and m > 0 else '0' for r in reserves for m in months},
        'reserve.release': {(r, m): '0' for r in reserves for m in months},
        'reserve.expenditure': {(r, m): '5000' if r == 'replacement' and m == 120 else '0' for r in reserves for m in months},
        'tax.asset_cost_fraction': {(c, a): '1' if (a == 'acquisition_building' and c == 'acquisition_building')
                                   or (a == 'rehab_building' and c in ('rehab_hard', 'rehab_soft', 'developer_fee'))
                                   or (a == 'loan_cost' and c == 'financing') else '0' for c in cost_names for a in assets},
        'tax.asset_excluded_basis': {a: '0' for a in assets},
        'tax.asset_credit_reduction': {a: '0' for a in assets},
        'tax.asset.retained_fraction': {a: '1' for a in assets},
        'tax.reviewed_recovery_fraction': {(a, y): '0' for a in assets for y in years},
        'tax.replacement_asset_fraction': {(r, a, y): '1' if r == 'replacement' and a == 'replacement_asset' and y == 2037 else '0' for r in reserves for a in assets for y in years},
        'tax.construction_deductible_interest_fraction': {(f, m): '0' for f in facilities for m in months},
        'tax.deductible_interest_fraction': {(l, m): '1' for l in loans for m in months},
        'tax.other_income': {y: '0' for y in years}, 'tax.other_deductions': {y: '0' for y in years},
        'partner.opening_capital': {p: '0' for p in partners},
        'partner.capital_reduction': {(p, y): '0' for p in partners for y in years},
        'partner.gross_income_to_sponsor': {y: '0' for y in years},
        'partner.investor_cash_share': {m: '.9' for m in months},
        'partner.investor_distribution_fraction': {m: '1' for m in months},
        'partner.investor_credit_share': {y: '.99' for y in years},
        'partner.investor_income_share': {y: '.9' for y in years},
        'partner.tax_rate': {(p, y): '.25' if p == 'investor' else '.2' for p in partners for y in years},
        'partner.credit_utilization': {(p, y): '1' for p in partners for y in years},
        'partner.loss_utilization': {(p, y): '1' for p in partners for y in years},
        'minimum_gain.original_asset_basis': '1872000',
        'minimum_gain.other_asset_additions': {y: '0' for y in years},
        'minimum_gain.basis_reduction': {y: '0' for y in years},
        'minimum_gain.reviewed_loan_balance': {(l, y): '0' for l in loans for y in years},
        'exit.net_sale_cash': '500000', 'exit.investor_distribution': '400000',
        'exit.investor_outside_basis': '300000', 'exit.investor_liability_relief': '200000',
        'exit.investor_loss_utilization': '0', 'exit.investor_tax_rate': '.25',
    }
    return structure, inputs


def calculate_example():
    """Calculate the synthetic deal through the canonical public entry point."""
    structure, inputs = build_example()
    return calculate(structure, inputs)


if __name__ == '__main__':
    result = calculate_example()
    for name in ('uses.total_development_cost', 'equity.commitment',
                 'funding.cash_funded', 'funding.maximum_gap', 'funding.shortfall_months',
                 'funding.final_cash', 'funding.final_debt_owed', 'exit.sale_price',
                 'returns.annual_irr'):
        print(f'{name}: {result.value(name)}')
