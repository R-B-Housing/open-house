"""LIHTC through the same data-only public worker used for saved runs."""
import base64
from dataclasses import asdict
from decimal import Decimal
from io import BytesIO
import json
import subprocess
import sys
import unittest
from openpyxl import load_workbook
from examples.lihtc_acquisition_rehab import build_example
from openhouse_engine.models.lihtc_acquisition_rehab import calculate


def snapshot():
    structure, inputs = build_example()
    values = {name: ([{'index': list(key) if isinstance(key, tuple) else [key], 'value': format(Decimal(str(value)), 'f')}
                      for key, value in raw.items()] if isinstance(raw, dict) else format(Decimal(str(raw)), 'f'))
              for name, raw in inputs.items()}
    return {'deal': {'kind': 'lihtc', 'name': 'Synthetic LIHTC', 'location': 'Testville',
                     'model_version': '12.0.0', 'structure': asdict(structure)}, 'inputs': values}


def invoke(value, operation='run'):
    p = subprocess.run([sys.executable, '-m', 'openhouse_valuation.service'],
                       input=json.dumps({'contractVersion': '1', 'operation': operation,
                                         'snapshot': value}), text=True, capture_output=True, check=True)
    return json.loads(p.stdout)


class LihtcServiceTest(unittest.TestCase):
    def test_explicit_index_ranges_preserve_every_canonical_calculated_value(self):
        expanded = snapshot()
        compact = snapshot()
        compact['inputs']['funding.sponsor_equity'] = [
            {'index': [0], 'value': '800000'},
            {'index': [{'start': 1, 'end': 180}], 'value': '0'},
        ]
        baseline = invoke(expanded, 'validate')
        response = invoke(compact, 'validate')
        self.assertEqual(response['status'], 'succeeded', response)
        self.assertEqual(response['result']['run'], baseline['result']['run'])

    def test_saved_run_workbook_matches_canonical_funded_calculation_without_recalculation(self):
        response = invoke(snapshot())
        self.assertEqual(response['status'], 'succeeded', response)
        result = response['result']
        structure, inputs = build_example()
        expected = calculate(structure, inputs)
        self.assertEqual(result['run']['digest'], expected.digest)
        self.assertEqual(result['run']['modelId'], 'lihtc-acquisition-rehab')
        self.assertEqual(result['run']['modelVersion'], '12.0.0')
        book = load_workbook(BytesIO(base64.b64decode(result['workbookBase64'])), data_only=True)
        summary = dict(book['Summary'].iter_rows(min_row=2, max_col=2, values_only=True))
        self.assertEqual(summary['Funding status'], 'Funded')
        self.assertEqual(Decimal(str(summary['Maximum funding gap'])), expected.value('funding.maximum_gap'))
        self.assertTrue({'Summary', 'Sources and Uses', 'Development Costs', 'Debt', 'Operations Monthly',
                         'Reserves Monthly', 'Tax Credits Annual', 'Partner Benefits Annual', 'Returns and Exit',
                         'Assumptions', 'Input Basis'} <= set(book.sheetnames))
        self.assertEqual(summary['Run digest'], expected.digest)
        formulas = load_workbook(BytesIO(base64.b64decode(result['workbookBase64'])))
        self.assertTrue(any(c.data_type == 'f' for sheet in formulas for row in sheet for c in row))
        self.assertEqual(formulas['Summary']['B4'].data_type, 'f')
        self.assertTrue(formulas['Dimensions'].protection.sheet)
        for name, index, address, unit in formulas['Audit Map'].iter_rows(min_row=2, values_only=True):
            sheet, cell = address.rsplit('!', 1)
            editable = expected.lineage[name]['kind'] == 'input'
            self.assertEqual(formulas[sheet.strip("'")][cell].protection.locked, not editable, name)
        self.assertEqual(summary['Input validation'], 'Passed')
        self.assertGreater(formulas['Checks'].max_row, 1000)
        self.assertEqual(formulas['Debt Monthly']['C1'].value.year, structure.start_year)

    def test_valid_unfunded_case_stays_completed_with_visible_gaps_and_missing_return_disclosure(self):
        value = snapshot()
        value['deal']['structure']['return_terms'] = None
        for row in value['inputs']['funding.sponsor_equity']:
            row['value'] = '0'
        for row in value['inputs']['funding.selected_distribution']:
            row['value'] = '0'
        response = invoke(value)
        self.assertEqual(response['status'], 'succeeded', response)
        self.assertEqual(response['result']['run']['fundingStatus'], 'unfunded')
        self.assertEqual(response['result']['run']['returnAvailability'], 'not_elected')
        book = load_workbook(BytesIO(base64.b64decode(response['result']['workbookBase64'])), data_only=True)
        summary = dict(book['Summary'].iter_rows(min_row=2, max_col=2, values_only=True))
        self.assertEqual(summary['Funding status'], 'Unfunded')
        self.assertGreater(summary['Maximum funding gap'], 0)
        self.assertEqual(summary['Investor annual IRR'], 'Unavailable')
        canonical = response['result']['run']['values']['funding.maximum_gap'][0]['value']
        self.assertEqual(Decimal(str(summary['Maximum funding gap'])), Decimal(canonical))

    def test_description_supplies_complete_example_dimensions_and_units(self):
        response = invoke({'deal': snapshot()['deal'], 'inputs': {}}, 'describe')
        self.assertEqual(response['status'], 'succeeded', response)
        example = response['result']['exampleSnapshot']
        validated = invoke(example, 'validate')
        self.assertEqual(validated['status'], 'succeeded')
        self.assertEqual(validated['result']['run'], invoke(snapshot(), 'validate')['result']['run'])
        self.assertLess(len(json.dumps(example)), 25000)
        self.assertIn('dimensions', response['result']['model'])

    def test_range_overlaps_unknown_indices_and_unbounded_expansion_are_rejected(self):
        invalid_ranges = [
            {'start': 12, 'end': 1}, {'start': 0, 'end': 601},
            {'start': True, 'end': 12}, {'start': 0, 'end': 12, 'extra': 1},
        ]
        for index in invalid_ranges:
            with self.subTest(index=index):
                value = snapshot()
                value['inputs']['funding.sponsor_equity'] = [{'index': [index], 'value': '0'}]
                response = invoke(value, 'validate')
                self.assertEqual(response['status'], 'invalid')
                self.assertEqual(response['finding']['code'], 'INPUT_INVALID')
        value = snapshot()
        value['inputs']['funding.sponsor_equity'] = [
            {'index': [{'start': 0, 'end': 180}], 'value': '0'}, {'index': [0], 'value': '0'}]
        self.assertIn('Duplicate', invoke(value, 'validate')['finding']['message'])
        value['inputs']['funding.sponsor_equity'] = [
            {'index': [{'start': 0, 'end': 180}], 'value': '0'}, {'index': [181], 'value': '0'}]
        self.assertEqual(invoke(value, 'validate')['finding']['code'], 'INPUT_UNKNOWN')
        value = snapshot()
        value['inputs']['cost.amount'] = [{'index': [{'start': 0, 'end': 200}, {'start': 0, 'end': 100}], 'value': '0'}]
        response = invoke(value, 'validate')
        self.assertEqual(response['finding']['code'], 'INPUT_INVALID')
        self.assertIn('20000', response['finding']['message'])
        value = snapshot()
        value['inputs']['funding.sponsor_equity'] = [{'index': [0], 'value': '800000'}]
        self.assertEqual(invoke(value, 'validate')['finding']['code'], 'INPUT_MISSING')

    def test_invalid_indices_versions_and_missing_inputs_are_refused_without_echoing_values(self):
        value = snapshot()
        del value['inputs']['exit.investor_outside_basis']
        response = invoke(value, 'validate')
        self.assertEqual(response['status'], 'invalid')
        self.assertEqual(response['finding']['key'], 'exit.investor_outside_basis')
        value = snapshot()
        value['inputs']['cost.amount'].append(value['inputs']['cost.amount'][0])
        self.assertEqual(invoke(value, 'validate')['status'], 'invalid')
        value = snapshot()
        value['deal']['model_version'] = '10.0.0'
        self.assertEqual(invoke(value, 'validate')['status'], 'invalid')
        value = snapshot()
        value['inputs']['credits.price'] = 'private-value-never-echo'
        response = invoke(value, 'validate')
        self.assertEqual(response['status'], 'invalid')
        self.assertNotIn('private-value-never-echo', json.dumps(response))
