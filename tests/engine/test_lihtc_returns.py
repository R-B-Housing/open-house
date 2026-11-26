"""LIHTC quarterly return cash flows follow explicit reviewed tax posting."""
from decimal import Decimal
from types import SimpleNamespace
import unittest
from openhouse_engine import DecimalPolicy, Dimension, EngineError, Item, Model, ModelDefinitionError, evaluate
from openhouse_engine.models.lihtc_returns import ReturnTerms, declare_returns


class LihtcReturnsTest(unittest.TestCase):
    def test_public_annual_returns_preserve_closing_cash_and_terminal_cash_without_tax_posting(self):
        from dataclasses import replace
        from test_lihtc_acquisition_rehab import example
        from openhouse_engine.models.lihtc_acquisition_rehab import build, calculate
        from openhouse_engine.models.lihtc_exit import ExitTerms
        structure, inputs = example(month_count=191)
        structure = replace(structure, return_terms=ReturnTerms('-.99', '10', 80, frequency='annual'),
                            exit_terms=ExitTerms(191))
        inputs['partner.tax_rate'] = {key: '0' for key in inputs['partner.tax_rate']}
        inputs.update({'exit.net_sale_cash': '100', 'exit.investor_distribution': '100',
                       'exit.investor_outside_basis': '100', 'exit.investor_liability_relief': '0',
                       'exit.investor_loss_utilization': '0', 'exit.investor_tax_rate': '0'})
        model = build(structure)
        self.assertNotIn('returns.tax_benefit_fraction', model.variables)
        self.assertNotIn('quarter', model.dimensions)
        run = calculate(structure, inputs)
        closing = run.value('partner.distribution', partner='investor', month=0) - run.value(
            'partner.contribution', partner='investor', month=0)
        self.assertLess(closing, 0)
        flows = run.series('returns.investor_cash_flow')
        self.assertEqual(flows[0], closing)
        self.assertEqual(flows[1], run.value('partner.after_tax_cash_flow', partner='investor', tax_year=2027) - closing)
        self.assertEqual(flows[-1], run.value('partner.after_tax_cash_flow', partner='investor', tax_year=2042) + Decimal('100'))
        annual_cash = sum(run.value('partner.after_tax_cash_flow', partner='investor', tax_year=y)
                          for y in range(2027, 2043))
        self.assertEqual(sum(flows), annual_cash + Decimal('100'))
        rate = run.value('returns.annual_irr')
        self.assertAlmostEqual(rate, run.value('returns.periodic_irr'), places=30)
        npv = sum(cash / (1 + rate) ** period for period, cash in enumerate(flows))
        self.assertAlmostEqual(npv, Decimal(0), places=18)

    def test_public_annual_returns_keep_an_initial_outflow_when_first_year_net_cash_is_positive(self):
        from dataclasses import replace
        from test_lihtc_acquisition_rehab import example
        from openhouse_engine.models.lihtc_acquisition_rehab import calculate
        structure, inputs = example(month_count=4)
        structure = replace(structure, return_terms=ReturnTerms('-.99', '10', 80, frequency='annual'))
        inputs['partner.tax_rate'] = {key: '0' for key in inputs['partner.tax_rate']}
        inputs['funding.selected_distribution'][4] = '1000'
        run = calculate(structure, inputs)
        annual = run.value('partner.after_tax_cash_flow', partner='investor', tax_year=2027)
        self.assertGreater(annual, 0)
        initial, final = run.series('returns.investor_cash_flow')
        self.assertLess(initial, 0)
        self.assertEqual(initial + final, annual)
        self.assertAlmostEqual(run.value('returns.annual_irr'), final / -initial - 1, places=20)

    def test_return_frequency_is_explicit_and_quarterly_is_preserved_by_default(self):
        self.assertEqual(ReturnTerms('-.99', '10', 80).frequency, 'quarterly')
        for frequency in ('monthly', '', None, True, 1):
            with self.subTest(frequency=frequency), self.assertRaises(ModelDefinitionError):
                ReturnTerms('-.99', '10', 80, frequency=frequency)

    def test_reviewed_tax_posting_and_terminal_cash_enter_quarterly_return_once(self):
        m = Model('synthetic-quarter-return', '1', DecimalPolicy(34, 'ROUND_HALF_UP'))
        m.dimension(Dimension('tax_year', [Item(2026)]))
        m.dimension(Dimension('partner', [Item('investor', investor=True), Item('sponsor', investor=False)]))
        m.dimension(Dimension('month', [Item(i, tax_year=2026, return_period=(i+2)//3, last=i==9)
                                       for i in range(10)], parent='tax_year'))
        m.input('partner.distribution', unit='USD', dims=('partner','month'))
        m.input('partner.contribution', unit='USD', dims=('partner','month'))
        m.input('partner.tax_benefit', unit='USD', dims=('partner','tax_year'))
        m.input('exit.investor_after_tax_cash', unit='USD')
        def given(name, unit, dims=(), low=0, high=None):
            m.input(name, unit=unit, dims=dims, minimum=low, maximum=high)
        s = SimpleNamespace(months=9, exit_terms=object(), return_terms=ReturnTerms('-.99','10',80))
        declare_returns(m,s,given)
        values={'partner.distribution':{(p,i):'20' if p=='investor' and i==9 else '0'
                                        for p in ('investor','sponsor') for i in range(10)},
                'partner.contribution':{(p,i):'100' if p=='investor' and i==0 else '0'
                                        for p in ('investor','sponsor') for i in range(10)},
                'partner.tax_benefit':{('investor',2026):'90',('sponsor',2026):'999'},
                'exit.investor_after_tax_cash':'10',
                'returns.tax_benefit_fraction':{i:'1' if i==6 else '0' for i in range(10)}}
        r=evaluate(m,values)
        self.assertEqual([r.value('returns.investor_cash_flow',quarter=q) for q in range(4)],
                         [Decimal('-100'),Decimal('0'),Decimal('90'),Decimal('30')])
        self.assertEqual(r.value('returns.investor_monthly_cash',month=9),Decimal('30'))
        self.assertAlmostEqual(r.value('returns.npv'),Decimal('0'),places=19)

        values['returns.tax_benefit_fraction'][6]='.5'
        with self.assertRaises(EngineError) as err:
            evaluate(m,values)
        self.assertEqual(err.exception.code,'RETURN_TAX_POSTING_NOT_ONE')

    def test_invalid_return_terms_and_partial_quarters_are_rejected(self):
        for terms in (('-1','10',80),('0','0',80),('NaN','10',80),('-.99','10',True)):
            with self.assertRaises(ModelDefinitionError):
                ReturnTerms(*terms)
        m=Model('synthetic-return','1',DecimalPolicy(34,'ROUND_HALF_UP'))
        s=SimpleNamespace(months=10,return_terms=ReturnTerms('-.99','10',80),exit_terms=None)
        with self.assertRaises(ModelDefinitionError):
            declare_returns(m,s,None)

    def test_returns_without_exit_require_no_terminal_inputs(self):
        m=Model('synthetic-quarter-return','1',DecimalPolicy(34,'ROUND_HALF_UP'))
        m.dimension(Dimension('tax_year',[Item(2026)]))
        m.dimension(Dimension('partner',[Item('investor',investor=True)]))
        m.dimension(Dimension('month',[Item(i,tax_year=2026,return_period=(i+2)//3,last=i==3)
                                      for i in range(4)],parent='tax_year'))
        m.input('partner.distribution',unit='USD',dims=('partner','month'))
        m.input('partner.contribution',unit='USD',dims=('partner','month'))
        m.input('partner.tax_benefit',unit='USD',dims=('partner','tax_year'))
        def given(name,unit,dims=(),low=0,high=None):
            m.input(name,unit=unit,dims=dims,minimum=low,maximum=high)
        s=SimpleNamespace(months=3,exit_terms=None,return_terms=ReturnTerms('-.99','10',80))
        declare_returns(m,s,given)
        values={'partner.distribution':{('investor',i):0 for i in range(4)},
                'partner.contribution':{('investor',i):100 if i==0 else 0 for i in range(4)},
                'partner.tax_benefit':{('investor',2026):110},
                'returns.tax_benefit_fraction':{i:1 if i==3 else 0 for i in range(4)}}
        r=evaluate(m,values)
        self.assertEqual(r.value('returns.investor_monthly_cash',month=3),Decimal('110'))
        self.assertAlmostEqual(r.value('returns.annual_irr'),Decimal('.4641'),places=20)

    def test_sparse_months_cannot_silently_drop_investor_cash(self):
        m=Model('synthetic-return','1',DecimalPolicy(34,'ROUND_HALF_UP'))
        m.dimension(Dimension('tax_year',[Item(2026)]))
        m.dimension(Dimension('month',[Item(i,tax_year=2026,return_period=(i+2)//3) for i in (0,1,3)],parent='tax_year'))
        s=SimpleNamespace(months=3,return_terms=ReturnTerms('-.99','10',80),exit_terms=None)
        with self.assertRaises(ModelDefinitionError):
            declare_returns(m,s,lambda *args,**kwargs:None)
