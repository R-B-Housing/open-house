import base64, importlib.util, json, subprocess, sys, tempfile, unittest
from dataclasses import asdict
from decimal import Decimal as D
from io import BytesIO
from openhouse_engine import evaluate
from openhouse_tax_credit.example import example_deal, example_inputs
from openhouse_tax_credit.model import build_model


def run(**changes):
    return evaluate(build_model(example_deal()), example_inputs() | changes)


class LihtcModelTest(unittest.TestCase):
    def test_four_percent_example_sizes_credits_from_boosted_qualified_basis(self):
        r = run()
        value = lambda name: r.values[name][()]
        # Eligible: 24,000,000 + 0.95 x 3,200,000 + 0.70 x 1,400,000 + 3,200,000 (land, permanent costs and reserves excluded).
        self.assertEqual(value('basis.eligible'), D('31220000'))
        self.assertEqual(value('basis.qualified'), D('31220000') * D('1.30'))
        self.assertEqual(value('credits.annual'), D('31220000') * D('1.30') * D('0.04'))
        self.assertEqual(value('tax_credit_equity'), value('credits.annual') * 10 * D('0.9999') * D('0.88'))
        self.assertEqual(value('total_development_cost'), D('35300000'))
        self.assertEqual(value('funding_gap'), 0)
        self.assertTrue(all(t['passed'] for t in r.tests.values()), r.tests)

    def test_applicable_fraction_is_the_lower_of_units_and_floor_area(self):
        r = run(lihtc_units=60, lihtc_sqft='51200')
        self.assertEqual(r.values['basis.applicable_fraction'][()], D('0.75'))

    def test_competitive_award_caps_credits_and_bonds_are_not_required(self):
        r = run(bond_financed=0, credit_rate='0.09', high_cost_boost=0, annual_credit_cap='2000000', tax_exempt_bonds=0)
        self.assertEqual(r.values['credits.supported_by_basis'][()], D('31220000') * D('0.09'))
        self.assertEqual(r.values['credits.annual'][()], D('2000000'))
        self.assertTrue(r.tests['bond_test']['passed'])
        short = run(bond_financed=0, credit_rate='0.09', high_cost_boost=0, annual_credit_cap='3000000')
        self.assertFalse(short.tests['basis_supports_allocation']['passed'])

    def test_gaps_and_a_failed_bond_test_are_flagged_without_failing_the_run(self):
        r = run(soft_sources=0, tax_exempt_bonds='8000000')
        self.assertFalse(r.tests['funded']['passed'])
        self.assertFalse(r.tests['bond_test']['passed'])
        self.assertGreater(r.values['funding_gap'][()], 0)


class LihtcServiceTest(unittest.TestCase):
    def invoke(self, operation, inputs):
        request = {'contractVersion': '1', 'operation': operation,
                   'snapshot': {'deal': asdict(example_deal()), 'inputs': inputs}, 'context': {'note': 'Synthetic', 'basis': {}}}
        done = subprocess.run([sys.executable, '-m', 'openhouse_valuation.service'], input=json.dumps(request), text=True, capture_output=True, check=True)
        return json.loads(done.stdout)

    @unittest.skipUnless(importlib.util.find_spec('openpyxl'), 'openpyxl required')
    def test_run_returns_the_lihtc_workbook(self):
        response = self.invoke('run', example_inputs())
        self.assertEqual(response['status'], 'succeeded', response)
        self.assertEqual(response['result']['run']['modelId'], 'lihtc-sources-uses')
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(base64.b64decode(response['result']['workbookBase64'])))
        self.assertTrue({'Summary', 'Assumptions', 'Basis', 'Input Basis'} <= set(book.sheetnames))

    def test_more_lihtc_units_than_units_is_invalid(self):
        self.assertEqual(self.invoke('validate', example_inputs() | {'lihtc_units': 81})['status'], 'invalid')


@unittest.skipUnless(all(importlib.util.find_spec(n) for n in ('openpyxl', 'pycel')), 'Workbook parity dependencies required')
class LihtcWorkbookTest(unittest.TestCase):
    def test_workbook_recalculates_and_flexes(self):
        from openhouse_engine.parity import Tolerance, check_parity
        from openhouse_tax_credit.workbook import write_workbook
        with tempfile.TemporaryDirectory() as d:
            path = d + '/lihtc.xlsx'
            model, run_, compiled = write_workbook(example_deal(), example_inputs(), path)
            tolerance = Tolerance(absolute=D('.000001'), relative=D('1e-9'))
            self.assertTrue(check_parity(path, compiled, model, run_, tolerance=tolerance).ok)
            flex = {'bond_financed': {(): 0}, 'credit_rate': {(): '0.09'}, 'annual_credit_cap': {(): '1500000'},
                    'lihtc_units': {(): 70}, 'cost': {('hard',): '26000000'}, 'basis_fraction': {('soft',): '0.8'}}
            result = check_parity(path, compiled, model, run_, tolerance=tolerance, flex=flex, inputs=example_inputs())
            self.assertTrue(result.ok, result.mismatches[:5])
