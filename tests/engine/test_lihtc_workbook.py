"""The public LIHTC graph exports as recalculating Excel formulas."""
import tempfile
import sys
import importlib.util
import unittest
from pathlib import Path
from openhouse_engine.models.lihtc_example import build_example
from openhouse_engine.models.lihtc_acquisition_rehab import build, calculate
from openhouse_engine.workbook import compile_workbook


@unittest.skipUnless(importlib.util.find_spec("openpyxl"), "openpyxl is required")
class LihtcWorkbookTest(unittest.TestCase):
    def test_complete_example_exports_every_calculation_as_live_cached_formula(self):
        from openpyxl import load_workbook
        structure, inputs = build_example()
        model, run = build(structure), calculate(structure, inputs)
        compiled = compile_workbook(model, run)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lihtc.xlsx')
            compiled.save(path)
            formulas = load_workbook(path)
            cached = load_workbook(path, data_only=True)
            for name, variable in model.variables.items():
                for index, address in compiled.cells[name].items():
                    sheet, cell = address.rsplit('!', 1)
                    sheet = sheet.strip("'")
                    if variable.kind == 'calculation':
                        self.assertEqual(formulas[sheet][cell].data_type, 'f', name)
                        self.assertLessEqual(len(formulas[sheet][cell].value), 8192, name)
                    self.assertAlmostEqual(float(run.values[name][index]), cached[sheet][cell].value,
                                           delta=max(1e-9, abs(float(run.values[name][index])) * 1e-14), msg=name)


    def test_complete_fifty_year_forecast_compiles_within_excel_formula_limit(self):
        structure, inputs = build_example(horizon=600)
        inputs['exit.investor_liability_relief'] = '0'  # All debt has amortized by this later exit.
        model, run = build(structure), calculate(structure, inputs)
        compiled = compile_workbook(model, run)
        for sheet in compiled.workbook:
            for row in sheet:
                for cell in row:
                    if cell.data_type == 'f':
                        self.assertLessEqual(len(cell.value), 8192)
