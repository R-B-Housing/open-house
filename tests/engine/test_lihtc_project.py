"""One source-backed LIHTC project run reconciles all canonical schedule owners."""
from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import unittest

from openhouse_engine.models.lihtc_acquisition_rehab import calculate
from openhouse_engine.models.lihtc_costs import CostItem
from openhouse_engine.models.lihtc_exit import ExitTerms
from openhouse_engine.models.lihtc_payins import EquityInstallment
from openhouse_engine.models.lihtc_returns import ReturnTerms
from openhouse_engine.operations import AnnualProjectionTerms
from test_lihtc_acquisition_rehab import example


class LihtcProjectTest(unittest.TestCase):
    def test_eighteen_year_project_reconciles_cash_tax_credits_and_terminal_source_lineage(self):
        horizon = 216
        structure, inputs = example(month_count=horizon)
        structure = replace(structure,
            cost_items=structure.cost_items + (CostItem('rehab_design', 'rehab_soft'),),
            equity_installments=(EquityInstallment('closing', 0, 'percentage'),
                                 EquityInstallment('completion', 1, 'fixed')),
            expense_projection=AnnualProjectionTerms(('utilities',), 0),
            exit_terms=ExitTerms(horizon), return_terms=ReturnTerms('-.99', '10', 80))
        months = range(horizon + 1)
        years = range(structure.start_year, structure.last_year + 1)
        inputs['cost.amount'].update({('rehab_design', m): '40' if m == 1 else '0' for m in months})
        inputs['basis.acquisition_fraction']['rehab_design'] = '0'
        inputs['basis.rehab_fraction']['rehab_design'] = '.5'
        inputs['bond.financed_cost']['rehab_design'] = '0'
        inputs['bond.basis_fraction']['rehab_design'] = '1'
        inputs['tax.asset_cost_fraction'].update({('rehab_design', a): '1' if a == 'loan_cost' else '0'
                                                 for a in ('building', 'loan_cost')})
        inputs['tax.asset_excluded_basis']['building'] = '20'
        inputs['tax.asset_credit_reduction']['building'] = '10'
        inputs['tax.asset.retained_fraction']['building'] = '.8'
        inputs.pop('equity.completion.fraction')
        inputs['equity.completion.amount'] = '130.87'
        inputs.pop('operations.expenses')
        year_end = {y: max(m for m in months if (structure.start_month - 1 + m) // 12
                          + structure.start_year == y) for y in years}
        inputs.update({
            'expenses.annual_base': {'utilities': '1200'},
            'expenses.annual_growth': {('utilities', y): '0' if y == 2027 else '.02' for y in years},
            'expenses.period_fraction': {y: '0.08333333333333333333333333333333333'
                                         if y == structure.last_year else '1' for y in years},
            'expenses.monthly_fraction': {('utilities', m): '1' if m in year_end.values() else '0'
                                          for m in months},
            'returns.tax_benefit_fraction': {m: '1' if m in year_end.values() else '0' for m in months},
            'exit.net_sale_cash': '1', 'exit.investor_distribution': '1', 'exit.investor_outside_basis': '100', 'exit.investor_liability_relief': '0',
                       'exit.investor_loss_utilization': '0', 'exit.investor_tax_rate': '.01',
        })
        inputs['partner.investor_cash_share'] = {m: '1' for m in months}
        inputs['partner.investor_income_share'] = {y: '0' for y in years}
        inputs['funding.selected_distribution'] = {m: '100' if m >= 3 else '0' for m in months}
        inputs['debt.developer_fee.cash_flow_fraction'] = {m: '1' for m in months}
        sources = {name: inputs.pop(name) for name in
                   ('cost.amount', 'tax.asset_cost_fraction', 'expenses.annual_base', 'rent.maximum_gross')}
        documents = {name: {'name': 'synthetic-reviewed-project', 'sha256': 'd' * 64} for name in sources}
        run = calculate(structure, inputs, sources, documents=documents)

        # Independent project economics: costs plus six dollars construction
        # interest; eligible allocations and credit pricing use those same costs.
        self.assertEqual(run.value('uses.total_development_cost'), Decimal('846'))
        self.assertEqual(run.value('basis.acquisition_eligible'), Decimal('400'))
        self.assertEqual(run.value('basis.rehab_eligible'), Decimal('320'))
        annual_credit = Decimal('400') * Decimal('.9') * Decimal('.04') \
            + Decimal('320') * Decimal('.9') * Decimal('1.3') * Decimal('.04')
        commitment = (annual_credit * 10 * Decimal('.99') * Decimal('.9')).quantize(Decimal('.01'))
        self.assertEqual(commitment, Decimal('261.74'))
        self.assertEqual(sum(run.series('credits.delivered')), annual_credit * 10)
        self.assertEqual(sum(run.series('equity.contribution')), commitment)
        self.assertEqual(run.value('tax.asset_basis', tax_asset='building'), Decimal('136'))
        self.assertEqual(run.value('tax.asset_basis', tax_asset='loan_cost'), Decimal('50'))
        self.assertEqual(run.value('tax.income', tax_year=2027), Decimal('8636.40'))
        self.assertEqual(run.value('tax.income', tax_year=2028), Decimal('9576.00'))

        # Deferred cost produces an obligation, then follows senior priority.
        self.assertEqual(run.value('debt.developer_fee.proceeds', month=0), Decimal('0'))
        self.assertEqual(run.value('debt.senior.principal', month=3), Decimal('16.67'))
        self.assertEqual(run.value('fee.repayment', month=3), Decimal('50'))
        self.assertEqual(run.value('debt.total_owed', month=horizon), Decimal('0'))
        self.assertEqual(sum(run.series('debt.principal')), Decimal('250'))
        full_expense, expenses = Decimal('1200'), Decimal(0)
        for year in years:
            if year > 2027:
                full_expense = (full_expense * Decimal('1.02')).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            expenses += ((full_expense / 12).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                         if year == structure.last_year else full_expense)
        expected_cash = commitment + 500 + 200 + 200 + 900 * horizon - expenses \
            - (840 - 50 + 6 + 200 + 200 + 50 + 100 * (horizon - 2))
        self.assertEqual(run.value('funding.final_cash'), expected_cash)
        self.assertEqual(run.value('funding.maximum_gap'), Decimal('0'))

        # Investor exit uses capital from the same contributions/distributions.
        capital = commitment - 100 * (horizon - 2)
        terminal_tax = Decimal('0')  # Reviewed loss utilization is zero.
        self.assertEqual(run.value('exit.investor_tax'), terminal_tax)
        self.assertEqual(run.value('returns.investor_cash_flow', quarter=72), 300 + 1 - terminal_tax)
        self.assertAlmostEqual(run.value('returns.npv'), Decimal('0'), places=14)
        flows = run.series('returns.investor_cash_flow')
        rate = run.value('returns.periodic_irr')
        independent_npv = sum((cash / (1 + rate) ** period for period, cash in enumerate(flows)), Decimal(0))
        self.assertAlmostEqual(independent_npv, Decimal('0'), places=14)

        visited = set()
        def visit(name):
            if name in visited:
                return
            visited.add(name)
            for dependency in run.lineage[name].get('dependsOn', ()):
                visit(dependency)
        visit('returns.investor_cash_flow')
        for name in sources:
            self.assertIn(name, visited)
            self.assertEqual(run.lineage[name]['kind'], 'source')
            self.assertEqual(run.lineage[name]['document'], documents[name])
