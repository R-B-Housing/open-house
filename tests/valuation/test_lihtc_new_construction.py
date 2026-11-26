"""LIHTC new construction through the data-only worker used for saved runs, and its live workbook."""
import base64
import importlib.util
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from openpyxl import load_workbook
from openhouse_engine import evaluate
from openhouse_engine.models.lihtc_new_construction import build
from openhouse_engine.models.lihtc_new_construction_example import build_example
from openhouse_valuation.lihtc_new_construction import compile_report, example_snapshot, read_deal, read_inputs


def invoke(snapshot, operation='run'):
    p = subprocess.run([sys.executable, '-m', 'openhouse_valuation.service'],
                       input=json.dumps({'contractVersion': '1', 'operation': operation, 'snapshot': snapshot}),
                       text=True, capture_output=True, check=True)
    return json.loads(p.stdout)


class LihtcNewConstructionServiceTest(unittest.TestCase):
    def test_describe_returns_the_synthetic_example(self):
        response = invoke({'deal': {'kind': 'lihtc_new_construction'}, 'inputs': {}}, 'describe')
        self.assertEqual(response['status'], 'succeeded', response)
        self.assertEqual(response['result']['model']['modelId'], 'lihtc-new-construction')
        self.assertEqual(response['result']['exampleSnapshot'], example_snapshot())

    def test_saved_run_matches_the_canonical_calculation(self):
        response = invoke(example_snapshot())
        self.assertEqual(response['status'], 'succeeded', response)
        result = response['result']['run']
        expected = evaluate(build(build_example()[0]), build_example()[1])
        self.assertEqual(result['digest'], expected.digest)
        self.assertEqual((result['modelId'], result['modelVersion']), ('lihtc-new-construction', '0.1.0'))
        self.assertEqual(result['fundingStatus'], 'funded')
        book = load_workbook(BytesIO(base64.b64decode(response['result']['workbookBase64'])), data_only=True)
        summary = dict(book['Summary'].iter_rows(min_row=2, max_col=2, values_only=True))
        self.assertEqual(Decimal(str(summary['Permanent loan'])), expected.value('perm.amount'))
        self.assertEqual(summary['Run digest'], expected.digest)

    def test_invalid_data_is_rejected_with_a_finding(self):
        snapshot = example_snapshot()
        snapshot['deal']['structure']['soft_loans'][2]['gap'] = False
        self.assertEqual(invoke(snapshot, 'validate')['status'], 'invalid')
        snapshot = example_snapshot()
        snapshot['inputs']['perm.dscr'] = '0.9'
        response = invoke(snapshot, 'validate')
        self.assertEqual(response['finding']['key'], 'perm.dscr')

    @unittest.skipUnless(importlib.util.find_spec('pycel'), 'pycel is required for independent recalculation')
    def test_excel_recalculates_and_flexes(self):
        from openhouse_engine.parity import Tolerance, check_parity
        snapshot = example_snapshot()
        model = build(read_deal(snapshot['deal']))
        inputs = read_inputs(model, snapshot['inputs'])
        run = evaluate(model, inputs)
        compiled = compile_report(snapshot['deal'], model, run, {})
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lihtc.xlsx')
            compiled.save(path)
            original_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(10000)
            self.addCleanup(sys.setrecursionlimit, original_limit)
            report = check_parity(path, compiled, model, run,
                                  tolerance=Tolerance(Decimal('0.005'), Decimal('1e-10')),
                                  flex={'perm.annual_rate': {(): '0.06'}, 'cost.amount': {('hard_building',): '23000000'},
                                        'perm.maximum': {(): '5000000'}}, inputs=inputs)
            self.assertTrue(report.ok, report.mismatches[:10])
            self.assertGreater(report.compared, 1200)  # The synthetic deal compiles to ~1,400 cells.


def commercial_snapshot():
    from openhouse_valuation.lihtc import encode_inputs
    snapshot = example_snapshot()
    structure = snapshot['deal']['structure']
    structure['commercial_spaces'] = [{'key': 'retail', 'label': 'Ground-floor retail', 'sf': 4000, 'lease_type': 'nnn'}]
    for line in structure['expense_lines']:
        line['recoverable'] = line['key'] in ('insurance', 'real_estate_taxes')
    snapshot['inputs'].update(encode_inputs({
        'commercial.rent': {'retail': '80000'}, 'commercial.bump': {'retail': '.03'},
        'commercial.bump_month': {'retail': '1'}, 'commercial.expiry_month': {'retail': '60'},
        'commercial.option_exercised': {'retail': '0'}, 'commercial.option_months': {'retail': '0'},
        'commercial.renewal_probability': {'retail': '.5'}, 'commercial.market_rent': {'retail': '20'},
        'commercial.downtime_months': {'retail': '6'}, 'commercial.ti': {'retail': '30'},
        'commercial.lc': {'retail': '8'}, 'commercial.recovery_share': {'retail': '.06'},
        'commercial.market_growth': '.03', 'commercial.new_lease_bump': '.03', 'commercial.credit_loss_rate': '.05'}))
    return snapshot


class CommercialNewConstructionTest(unittest.TestCase):
    def test_commercial_space_saves_and_runs_through_the_worker(self):
        response = invoke(commercial_snapshot(), 'validate')
        self.assertEqual(response['status'], 'succeeded', response)
        values = response['result']['run']['values']
        self.assertGreater(Decimal(values['cf.commercial'][0]['value']), 0)

    @unittest.skipUnless(importlib.util.find_spec('pycel'), 'pycel is required for independent recalculation')
    def test_excel_recalculates_a_flexed_lease(self):
        from openhouse_engine.parity import Tolerance, check_parity
        snapshot = commercial_snapshot()
        model = build(read_deal(snapshot['deal']))
        inputs = read_inputs(model, snapshot['inputs'])
        run = evaluate(model, inputs)
        compiled = compile_report(snapshot['deal'], model, run, {})
        self.assertIn('Commercial Leases', ' '.join(compiled.workbook.sheetnames))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lihtc.xlsx')
            compiled.save(path)
            original_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(10000)
            self.addCleanup(sys.setrecursionlimit, original_limit)
            report = check_parity(path, compiled, model, run,
                                  tolerance=Tolerance(Decimal('0.005'), Decimal('1e-10')),
                                  flex={'commercial.expiry_month': {('retail',): '36'},
                                        'expense.amount': {('insurance',): '80000'}}, inputs=inputs)
            self.assertTrue(report.ok, report.mismatches[:10])


if __name__ == '__main__':
    unittest.main()
