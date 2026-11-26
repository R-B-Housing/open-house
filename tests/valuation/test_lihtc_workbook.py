"""Recalculate the actual delivered LIHTC report, including its Summary and Checks."""
import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path
from openhouse_engine import evaluate
from openhouse_engine.models.lihtc_acquisition_rehab import build
from openhouse_valuation.lihtc import compile_report, example_snapshot, read_deal, read_inputs


class LiveLihtcReportTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pycel"), "pycel is required for independent recalculation")
    def test_excel_recalculates_and_flexes_the_complete_example(self):
        from decimal import Decimal
        from openhouse_engine.parity import check_parity, Tolerance
        snapshot = example_snapshot()
        structure = read_deal(snapshot['deal'])
        model = build(structure)
        inputs = read_inputs(model, snapshot['inputs'])
        run = evaluate(model, inputs)
        compiled = compile_report(snapshot['deal'], model, run, {})
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lihtc.xlsx')
            compiled.save(path)
            # pycel recursively invalidates long monthly dependency chains.
            original_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(10000)
            self.addCleanup(sys.setrecursionlimit, original_limit)
            report = check_parity(path, compiled, model, run,
                                  tolerance=Tolerance(Decimal('0.005'), Decimal('1e-10')),
                                  flex={'debt.senior.annual_rate': {(): '0.045'}}, inputs=inputs)
            self.assertTrue(report.ok, report.mismatches[:10])
            self.assertGreater(report.compared, 10000)

    @unittest.skipUnless(importlib.util.find_spec('pycel'), 'pycel is required for independent recalculation')
    def test_exactly_funded_report_keeps_funded_status_after_recalculation(self):
        from decimal import Decimal
        from pycel import ExcelCompiler
        from openhouse_engine.parity import _strip_cached
        snapshot = example_snapshot()
        snapshot['deal']['structure']['return_terms'] = None
        model = build(read_deal(snapshot['deal']))
        inputs = read_inputs(model, snapshot['inputs'])
        inputs['funding.sponsor_equity'] = {i: '0' for i in inputs['funding.sponsor_equity']}
        inputs['funding.selected_distribution'] = {i: '0' for i in inputs['funding.selected_distribution']}
        unfunded = evaluate(model, inputs)
        inputs['funding.sponsor_equity'][(0,)] = str(unfunded.value('funding.maximum_gap'))
        run = evaluate(model, inputs)
        self.assertEqual(run.value('funding.maximum_gap'), Decimal(0))
        compiled = compile_report(snapshot['deal'], model, run, {})
        with tempfile.TemporaryDirectory() as directory:
            path, bare = str(Path(directory) / 'report.xlsx'), str(Path(directory) / 'bare.xlsx')
            compiled.save(path)
            _strip_cached(path, bare)
            original_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(10000)
            self.addCleanup(sys.setrecursionlimit, original_limit)
            xl = ExcelCompiler(filename=bare)
            self.assertEqual(xl.evaluate('Summary!B3'), 'Funded')
            self.assertEqual(xl.evaluate('Summary!B5'), 0)
            self.assertEqual(xl.evaluate('Summary!B11'), 'Passed')


def commercial_snapshot():
    """The example with one NNN and one gross space, as a saved 12.0.0 snapshot."""
    from openhouse_valuation.lihtc import encode_inputs
    snapshot = example_snapshot()
    structure = snapshot['deal']['structure']
    structure['return_terms'] = None  # Taxable commercial income makes later investor flows negative.
    structure['commercial_spaces'] = [{'key': 'market', 'label': 'Corner market', 'sf': 3000, 'lease_type': 'nnn'},
                                      {'key': 'clinic', 'label': 'Community clinic', 'sf': 2400, 'lease_type': 'gross'}]
    months = range(structure['months'] + 1)
    snapshot['inputs'].update(encode_inputs({
        'commercial.rent': {'market': '120000', 'clinic': '48000'},
        'commercial.bump': {'market': '.03', 'clinic': '.02'},
        'commercial.bump_month': {'market': '7', 'clinic': '1'},
        'commercial.expiry_month': {'market': '60', 'clinic': '24'},
        'commercial.option_exercised': {'market': '0', 'clinic': '0'},
        'commercial.option_months': {'market': '0', 'clinic': '0'},
        'commercial.renewal_probability': {'market': '.6', 'clinic': '.5'},
        'commercial.market_rent': {'market': '22', 'clinic': '20'},
        'commercial.downtime_months': {'market': '6', 'clinic': '9'},
        'commercial.ti': {'market': '30', 'clinic': '25'},
        'commercial.lc': {'market': '8', 'clinic': '6'},
        'commercial.recovery_share': {'market': '.4'},
        'commercial.market_growth': '.03', 'commercial.new_lease_bump': '.03', 'commercial.credit_loss_rate': '.02',
        'commercial.management_fraction': '.04', 'commercial.recoverable_costs': {m: '2500' for m in months}}))
    return snapshot


class CommercialLihtcReportTest(unittest.TestCase):
    def test_saved_versions_read_with_and_without_commercial_spaces(self):
        snapshot = example_snapshot()
        self.assertEqual(snapshot['deal']['structure']['commercial_spaces'], [])
        old = {**snapshot['deal'], 'model_version': '11.0.0',
               'structure': {k: v for k, v in snapshot['deal']['structure'].items() if k != 'commercial_spaces'}}
        self.assertEqual(read_deal(old), read_deal(snapshot['deal']))
        deal = commercial_snapshot()['deal']
        self.assertEqual(len(read_deal(deal).commercial_spaces), 2)
        with self.assertRaises(ValueError):
            read_deal({**deal, 'model_version': '11.0.0'})
        with self.assertRaises(ValueError):
            read_deal({**deal, 'model_version': '10.0.0'})

    @unittest.skipUnless(importlib.util.find_spec("pycel"), "pycel is required for independent recalculation")
    def test_excel_shows_commercial_leases_and_recalculates_a_flexed_lease(self):
        from decimal import Decimal
        from openhouse_engine.parity import check_parity, Tolerance
        snapshot = commercial_snapshot()
        model = build(read_deal(snapshot['deal']))
        inputs = read_inputs(model, snapshot['inputs'])
        run = evaluate(model, inputs)
        self.assertGreater(run.value('commercial.income', month=1), 0)
        compiled = compile_report(snapshot['deal'], model, run, {})
        self.assertIn('Commercial Leases Monthly', compiled.workbook.sheetnames)
        self.assertTrue(compiled.cells['commercial.income'][(1,)].startswith("'Commercial Leases Monthly'!"))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lihtc.xlsx')
            compiled.save(path)
            original_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(10000)
            self.addCleanup(sys.setrecursionlimit, original_limit)
            report = check_parity(path, compiled, model, run,
                                  tolerance=Tolerance(Decimal('0.005'), Decimal('1e-10')),
                                  flex={'commercial.expiry_month': {('clinic',): '36'},
                                        'commercial.recovery_share': {('market',): '.5'}}, inputs=inputs)
            self.assertTrue(report.ok, report.mismatches[:10])
            self.assertGreater(report.compared, 10000)
