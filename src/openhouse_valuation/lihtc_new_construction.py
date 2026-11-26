"""Versioned data boundary and live Excel export for the LIHTC new construction sizing model."""
from dataclasses import asdict, fields
import base64
import json
import tempfile
from pathlib import Path

from openhouse_engine import evaluate
from openhouse_engine.models.lihtc_new_construction import (
    MODEL_VERSION, CommercialSpace, CostItem, ExpenseLine, SoftLoan, Structure, UnitType, build,
)
from .lihtc import encode_inputs, read_inputs

KIND = 'lihtc_new_construction'
ROWS = {'unit_types': UnitType, 'cost_items': CostItem, 'expense_lines': ExpenseLine, 'soft_loans': SoftLoan,
        'commercial_spaces': CommercialSpace}
LIMITS = {'unit_types': 30, 'cost_items': 120, 'expense_lines': 60, 'soft_loans': 12, 'commercial_spaces': 20}
OPTIONAL = {'gap', 'recoverable'}
BOOLEAN = {'construction', 'residual_receipts', 'gap', 'recoverable'}
INTEGER = {'bedrooms', 'ami', 'sf'}
# Sheets in application-workbook page order; a variable goes to the first sheet whose prefix it carries.
SHEETS = (
    ('Sources and Uses', ('uses.', 'sources.', 'perm.', 'soft.', 'construction.', 'bond.', 'fee.', 'equity.')),
    ('Commercial Leases', ('commercial.',)),
    ('Development Costs', ('cost.', 'basis.eligible_cost')),
    ('Unit Mix', ('units', 'unit.', 'rent.', 'subsidy.')),
    ('Tax Credits', ('basis.', 'tbl.', 'credits.')),
    ('Base Year', ('base.',)),
)


def read_deal(value):
    if (not isinstance(value, dict) or set(value) != {'kind', 'name', 'location', 'model_version', 'structure'}
            or value['kind'] != KIND or value['model_version'] != MODEL_VERSION
            or not isinstance(value['name'], str) or not 1 <= len(value['name']) <= 255
            or not isinstance(value['location'], str) or len(value['location']) > 255):
        raise ValueError('Invalid LIHTC new construction structure.')
    raw = value['structure']
    names = {f.name for f in fields(Structure)}
    if not isinstance(raw, dict) or not names - {'commercial_spaces'} <= set(raw) <= names:
        raise ValueError('Structure fields must be explicit.')
    raw = {'commercial_spaces': [], **raw}
    data = {}
    for name, cls in ROWS.items():
        rows = raw[name]
        if not isinstance(rows, list) or not (0 if name == 'commercial_spaces' else 1) <= len(rows) <= LIMITS[name]:
            raise ValueError('Invalid structure size.')
        names = {f.name for f in fields(cls)}
        required = names - OPTIONAL
        if any(not isinstance(r, dict) or not required <= set(r) <= names for r in rows):
            raise ValueError('Structure fields must be explicit.')
        for r in rows:
            for key, item in r.items():
                expected = bool if key in BOOLEAN else int if key in INTEGER else str
                if type(item) is not expected or (expected is str and not 1 <= len(item) <= 255):
                    raise ValueError('Invalid structure value.')
        data[name] = tuple(cls(**r) for r in rows)
    for name in ('years', 'first_year'):
        if type(raw[name]) is not int:
            raise ValueError('Invalid structure value.')
        data[name] = raw[name]
    structure = Structure(**data)
    build(structure)  # Rejects inconsistent structure before inputs are read.
    return structure


def example_snapshot():
    from openhouse_engine.models.lihtc_new_construction_example import build_example
    structure, inputs = build_example()
    return {'deal': {'kind': KIND, 'name': 'Sampleton Family Housing (synthetic)', 'location': 'Sampleton, CA',
                     'model_version': MODEL_VERSION, 'structure': json.loads(json.dumps(asdict(structure)))},
            'inputs': encode_inputs(inputs)}


def compile_report(deal, model, run, context):
    from openpyxl.styles import Alignment, Font, PatternFill, Protection
    from openhouse_engine.workbook import Layout, Row, Sheet, compile_workbook
    label = lambda n: n.replace('.', ' / ').replace('_', ' ').title()
    placed, sheets = set(), []
    def add(title, names, columns=None):
        if names:
            placed.update(names)
            sheets.append(Sheet(title, tuple(Row(n, label=label(n)) for n in names), columns))
    variables = model.variables
    add('Inputs', tuple(n for n, v in variables.items() if v.kind == 'input'))
    add('Cash Flow', tuple(n for n, v in variables.items() if n not in placed and 'year' in v.dims), 'year')
    for title, prefixes in SHEETS:
        add(title, tuple(n for n in variables if n not in placed and n.startswith(prefixes)))
    add('Other Calculations', tuple(n for n in variables if n not in placed))
    compiled = compile_workbook(model, run, Layout(tuple(sheets), formats={
        'usd': '#,##0;[Red](#,##0)', 'usd/year': '#,##0;[Red](#,##0)', 'ratio': '0.00%', 'rate': '0.00%',
        'ratio/year': '0.000%', 'multiple': '0.00', 'units': '0',
    }), include_checks=True)
    book = compiled.workbook
    summary = book.create_sheet('Summary', 0)
    summary.append(['LIHTC new construction', deal['name']])
    rows = (('Total development cost', 'uses.total_development_cost', '#,##0'),
            ('TDC per unit', 'uses.per_unit', '#,##0'),
            ('Eligible basis', 'basis.eligible', '#,##0'),
            ('Annual federal credit', 'credits.federal_annual', '#,##0'),
            ('Total state credit', 'credits.state_total', '#,##0'),
            ('Investor equity', 'equity.investor', '#,##0'),
            ('Permanent loan', 'perm.amount', '#,##0'),
            ('Gap loan', 'soft.gap.amount', '#,##0'),
            ('Deferred developer fee', 'fee.deferred', '#,##0'),
            ('Permanent sources surplus / (shortfall)', 'soft.gap.surplus', '#,##0;[Red](#,##0)'),
            ('Tax-exempt bond loan', 'construction.bond_loan', '#,##0'),
            ('Taxable construction loan', 'construction.taxable_loan', '#,##0'),
            ('50% test', 'bond.test_ratio', '0.00%'),
            ('Threshold basis limit', 'tbl.total', '#,##0'),
            ('Deferred fee unpaid at end', 'ddf.unpaid', '#,##0'))
    for text, name, number_format in rows:
        row = summary.max_row + 1
        summary.cell(row, 1, text)
        compiled.derive(summary.cell(row, 2), compiled.cells[name][()], lambda r, n=name: r.value(n), run)
        summary.cell(row, 2).number_format = number_format
    checks = book['Checks']
    summary.append(['Input validation'])
    compiled.derive(summary.cell(summary.max_row, 2),
                    f'IF(COUNTIF(Checks!C2:C{checks.max_row},0)>0,"INVALID INPUTS - review Checks","Passed")',
                    lambda r: 'Passed', run)
    for name, test in run.tests.items():
        summary.append([f'Test: {name}', 'Passed' if test['passed'] else f"Breached ({test['breaches']}): {test['message']}"])
    saved = (('Scenario version ID', context.get('scenarioVersionId')), ('Input digest', context.get('inputDigest')))
    for text, value in (('Model version', run.model_version), ('Engine version', run.engine_version),
                        ('Run digest', run.digest), *((text, value) for text, value in saved if value),
                        ('Review status', 'Draft; verify rents, basis allocations and financing terms before relying on results'),
                        ('Workbook', 'Live formulas; blue cells are editable inputs. Structure is fixed.')):
        summary.append([text, value])
    assumptions = book.create_sheet('Assumptions')
    assumptions.append(['Structure field', 'Exact JSON value'])
    for key, value in deal['structure'].items():
        assumptions.append([key, json.dumps(value, ensure_ascii=False, sort_keys=True)])
    basis = book.create_sheet('Input Basis')
    basis.append(['Input', 'Basis', 'Reason', 'Exact source', 'References / quotes', 'Pinned provenance'])
    basis.append(['Scenario note', context.get('note', '')])
    for key, value in sorted(context.get('basis', {}).items()):
        basis.append([key, value['kind'], value['reason'], value.get('versionId', value.get('runId', '')),
                      json.dumps(value.get('references', []), ensure_ascii=False),
                      json.dumps(context.get('provenance', {}).get(key, {}), ensure_ascii=False)])
    for sheet in (summary, assumptions, basis):
        sheet.freeze_panes = 'B2'
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='173F35')
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str) and cell.data_type != 'f':
                    cell.data_type = 's'  # Sources and notes remain literal even if they begin with '='.
                    if len(cell.value) > 32767:
                        raise ValueError('Excel cell exceeds size limit.')
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        sheet.column_dimensions['A'].width = 45
        sheet.column_dimensions['B'].width = 60
    for sheet in book:
        sheet.protection.sheet = True
        sheet.protection.formatColumns = False
        sheet.protection.formatRows = False
    for name, cells in compiled.cells.items():
        if variables[name].kind == 'input':
            for address in cells.values():
                sheet, cell = address.rsplit('!', 1)
                book[sheet.strip("'")][cell].protection = Protection(locked=False)
    return compiled


def execute(snapshot, operation, context, serialize):
    if operation == 'describe' and snapshot['deal'] == {'kind': KIND}:
        snapshot = {'deal': example_snapshot()['deal'], 'inputs': {}}
    structure = read_deal(snapshot['deal'])
    model = build(structure)
    if operation == 'describe':
        return {'model': model.describe(), 'exampleSnapshot': example_snapshot(),
                'inputEncoding': 'Exact decimal strings; dimensioned inputs are [{index: [...], value: decimal string}]. No implicit defaults.',
                'workbookKind': 'live_model', 'limits': {'years': 40, **{k: v for k, v in LIMITS.items()}}}
    run = evaluate(model, read_inputs(model, snapshot['inputs']))
    result = {'run': serialize(run, model)}
    result['run']['fundingStatus'] = 'funded' if run.tests['sources.permanent_funded']['passed'] else 'unfunded'
    if operation == 'run':
        compiled = compile_report(snapshot['deal'], model, run, context)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lihtc-new-construction.xlsx')
            compiled.save(path)
            data = Path(path).read_bytes()
        if len(data) > 10 * 1024 * 1024:
            raise ValueError('Workbook exceeds artifact limit.')
        result['workbookBase64'] = base64.b64encode(data).decode('ascii')
    return result
