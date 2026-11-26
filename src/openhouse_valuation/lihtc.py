"""Versioned data boundary and live Excel export for the canonical LIHTC calculator."""
from dataclasses import asdict, fields, is_dataclass
from decimal import Decimal
from datetime import date
import json
import re
import types
from itertools import product
from typing import get_args, get_origin, get_type_hints

from openhouse_engine import EngineError, evaluate
from openhouse_engine.models.lihtc_acquisition_rehab import MODEL_VERSION, Structure, build

# Snapshots from 11.0.0 predate commercial spaces and compute identically without them.
READABLE_VERSIONS = ('11.0.0', MODEL_VERSION)
# Structure fields added after a saved version; a missing one reads as its empty default.
ADDED_FIELDS = {Structure: {'commercial_spaces'}}
DECIMAL = re.compile(r'^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$')


def _read(cls, value):
    """Decode only the reviewed dataclasses and primitive types in Structure."""
    origin = get_origin(cls)
    if origin is types.UnionType:
        if value is None and type(None) in get_args(cls):
            return None
        return _read(next(t for t in get_args(cls) if t is not type(None)), value)
    if origin is tuple:
        if not isinstance(value, list) or len(value) > 200:
            raise ValueError('Invalid structure array.')
        return tuple(_read(get_args(cls)[0], v) for v in value)
    if is_dataclass(cls):
        hints = get_type_hints(cls)
        names = {f.name for f in fields(cls)}
        if not isinstance(value, dict) or not names - ADDED_FIELDS.get(cls, set()) <= set(value) <= names:
            raise ValueError('Structure fields must be explicit.')
        return cls(**{name: _read(hints[name], v) for name, v in value.items()})
    if cls in (str, int, bool):
        if type(value) is not cls or (cls is str and len(value) > 255):
            raise ValueError('Invalid structure value.')
        return value
    raise ValueError('Unsupported structure type.')


def read_deal(value):
    if (not isinstance(value, dict) or set(value) != {'kind', 'name', 'location', 'model_version', 'structure'}
            or value['kind'] != 'lihtc' or value['model_version'] not in READABLE_VERSIONS
            or not isinstance(value['name'], str) or not 1 <= len(value['name']) <= 255
            or not isinstance(value['location'], str) or len(value['location']) > 255):
        raise ValueError('Invalid LIHTC structure.')
    structure = _read(Structure, value['structure'])
    if value['model_version'] != MODEL_VERSION and structure.commercial_spaces:
        raise ValueError('Commercial spaces require LIHTC model version ' + MODEL_VERSION + '.')
    if (not 12 <= structure.months <= 600 or len(structure.cost_items) > 50
            or len(structure.unit_types) > 20 or len(structure.tax_assets) > 50):
        raise ValueError('LIHTC application size exceeded.')
    return structure


def read_inputs(model, values):
    result = {}
    for name, raw in values.items():
        variable = model.variables.get(name)
        if variable is None or variable.kind != 'input':
            raise EngineError('INPUT_UNKNOWN', 'Unknown model input.', name)
        def number(value):
            if not isinstance(value, str) or len(value) > 64 or not DECIMAL.fullmatch(value):
                raise EngineError('INPUT_INVALID', 'LIHTC amounts require exact decimal strings.', name)
            return value
        if not variable.dims:
            result[name] = number(raw)
        else:
            if not isinstance(raw, list) or len(raw) > 20000:
                raise EngineError('INPUT_INVALID', 'Expected indexed input rows.', name)
            rows = {}
            for row in raw:
                if (not isinstance(row, dict) or set(row) != {'index', 'value'}
                        or not isinstance(row['index'], list) or len(row['index']) != len(variable.dims)):
                    raise EngineError('INPUT_INVALID', 'Invalid input dimensions.', name)
                axes, count = [], 1
                for key in row['index']:
                    if type(key) in (str, int):
                        axis = (key,)
                    elif (isinstance(key, dict) and set(key) == {'start', 'end'}
                          and type(key['start']) is int and type(key['end']) is int
                          and abs(key['start']) <= 9007199254740991 and abs(key['end']) <= 9007199254740991
                          and 0 <= key['end'] - key['start'] <= 600):
                        axis = range(key['start'], key['end'] + 1)
                    else:
                        raise EngineError('INPUT_INVALID', 'Invalid input dimensions or range.', name)
                    axes.append(axis)
                    count *= len(axis)
                if len(rows) + count > 20000:
                    raise EngineError('INPUT_INVALID', 'Indexed input expansion exceeds 20000 rows.', name)
                value = number(row['value'])
                for key in product(*axes):
                    if key in rows:
                        raise EngineError('INPUT_INVALID', 'Duplicate input index.', name)
                    rows[key] = value
            result[name] = rows
    return result


def encode_inputs(inputs):
    """Keep every value explicit, coalescing equal consecutive integer indices."""
    encoded = {}
    for name, raw in inputs.items():
        if not isinstance(raw, dict):
            encoded[name] = format(Decimal(str(raw)), 'f')
            continue
        groups, rows = {}, []
        for key, value in raw.items():
            index = list(key) if isinstance(key, tuple) else [key]
            row = {'index': index, 'value': format(Decimal(str(value)), 'f')}
            if type(index[-1]) is int:
                groups.setdefault(tuple(index[:-1]), []).append(row)
            else:
                rows.append(row)
        for prefix, items in groups.items():
            items.sort(key=lambda row: row['index'][-1])
            first = last = items[0]['index'][-1]
            value = items[0]['value']
            def emit():
                rows.append({'index': [*prefix, {'start': first, 'end': last} if last > first else first],
                             'value': value})
            for row in items[1:]:
                index = row['index'][-1]
                if index == last + 1 and row['value'] == value:
                    last = index
                else:
                    emit()
                    first = last = index
                    value = row['value']
            emit()
        encoded[name] = rows
    return encoded


def example_snapshot():
    from openhouse_engine.models.lihtc_example import build_example
    structure, inputs = build_example()
    return {'deal': {'kind': 'lihtc', 'name': 'Synthetic LIHTC acquisition/rehab',
                     'location': 'Synthetic', 'model_version': MODEL_VERSION, 'structure': json.loads(json.dumps(asdict(structure)))},
            'inputs': encode_inputs(inputs)}


def compile_report(deal, model, run, context):
    from openpyxl.styles import Font, PatternFill, Alignment, Protection
    from openpyxl.utils import get_column_letter
    from openhouse_engine.workbook import compile_workbook, Layout, Sheet, Row
    groups = [
        ('Sources and Uses', ('funding.', 'uses.', 'equity.', 'fee.', 'construction.')),
        ('Development Costs', ('cost.', 'basis.', 'bond.')),
        ('Debt', ('debt.',)), ('Operations', ('operations.', 'rent.', 'annual_operations.', 'expenses.', 'units')),
        ('Commercial Leases', ('commercial.',)),
        ('Reserves', ('reserve.',)), ('Tax Credits', ('credits.',)),
        ('Partner Benefits', ('partner.', 'tax.', 'minimum_gain.')),
        ('Returns and Exit', ('returns.', 'exit.')),
    ]
    sheets, assigned = [], set()
    for title, prefixes in [('Inputs', None)] + groups + [('Other Calculations', ())]:
        names = tuple(name for name, variable in model.variables.items()
                      if name not in assigned and
                      (variable.kind == 'input' if prefixes is None else
                       not prefixes or name.startswith(prefixes)))
        if names:
            assigned.update(names)
            monthly = tuple(n for n in names if 'month' in model.variables[n].dims)
            flat = tuple(n for n in names if n not in monthly)
            annual = tuple(n for n in flat if 'tax_year' in model.variables[n].dims)
            remaining = tuple(n for n in flat if n not in annual)
            if remaining:
                sheets.append(Sheet(title, tuple(Row(n, label=n.replace('.', ' / ').replace('_', ' ').title()) for n in remaining)))
            if annual:
                sheets.append(Sheet(title + ' Annual', tuple(Row(n, label=n.replace('.', ' / ').replace('_', ' ').title()) for n in annual), 'tax_year'))
            if monthly:
                sheets.append(Sheet(title + ' Monthly', tuple(Row(n, label=n.replace('.', ' / ').replace('_', ' ').title()) for n in monthly), 'month'))
    compiled = compile_workbook(model, run, Layout(tuple(sheets), formats={
        'USD': '#,##0.00;[Red](#,##0.00)', 'nominal_ratio/year': '0.00%',
        'effective_ratio/year': '0.00%', 'ratio': '0.00%', 'count': '0',
    }), include_checks=True)
    book = compiled.workbook
    for spec in sheets:
        if spec.columns == 'month':
            for column, month in enumerate(model.dimensions['month'].keys(), 3):
                absolute = deal['structure']['start_year'] * 12 + deal['structure']['start_month'] - 1 + month
                cell = book[spec.name].cell(1, column, date(absolute // 12, absolute % 12 + 1, 1))
                cell.number_format = 'mmm-yy'
    for name, rows in compiled.cells.items():
        if name.startswith(('returns.iteration_', 'returns.lower.', 'returns.upper.', 'returns.result.')):
            for address in rows.values():
                sheet, coordinate = address.rsplit('!', 1)
                row = book[sheet.strip("'")][coordinate].row
                book[sheet.strip("'")].row_dimensions[row].hidden = True
                book[sheet.strip("'")].row_dimensions[row].outlineLevel = 1
    summary = book.create_sheet('Summary', 0)
    summary.append(['LIHTC acquisition/rehab', deal['name']])
    summary.append(['Calculation status', 'Calculated; review Checks after editing inputs'])
    summary.append(['Funding status'])
    compiled.derive(summary.cell(3, 2),
                    f'IF({compiled.cells["funding.cash_funded"][()]}>0,"Funded","Unfunded")',
                    lambda r: 'Funded' if r.value('funding.cash_funded') else 'Unfunded', run)
    def scalar(label, name):
        row = summary.max_row + 1
        summary.cell(row, 1, label)
        if name in compiled.cells:
            compiled.derive(summary.cell(row, 2), compiled.cells[name][()],
                            lambda r, n=name: r.value(n), run)
            summary.cell(row, 2).number_format = '#,##0.00;[Red](#,##0.00)'
        else:
            summary.cell(row, 2, 'Unavailable')
    scalar('Maximum funding gap', 'funding.maximum_gap')
    scalar('Shortfall months', 'funding.shortfall_months')
    summary.cell(summary.max_row, 2).number_format = '0'
    scalar('Development cost', 'uses.total_development_cost')
    scalar('Investor equity commitment', 'equity.commitment')
    scalar('Final project cash', 'funding.final_cash')
    scalar('Final debt owed', 'funding.final_debt_owed')
    scalar('Investor annual IRR', 'returns.annual_irr')
    summary.cell(summary.max_row, 2).number_format = '0.00%'
    checks = book['Checks']
    summary.append(['Input validation'])
    compiled.derive(summary.cell(summary.max_row, 2),
                    f'IF(COUNTIF(Checks!C2:C{checks.max_row},0)>0,"INVALID INPUTS - review Checks","Passed")',
                    lambda r: 'Passed', run)
    summary.append(['Returns convention', deal['structure']['return_terms']['frequency']
                    if deal['structure']['return_terms'] else 'Not elected'])
    summary.append(['Model version', run.model_version])
    summary.append(['Engine version', run.engine_version])
    summary.append(['Run digest', run.digest])
    for label, key in (('Scenario version ID', 'scenarioVersionId'), ('Input digest', 'inputDigest')):
        if context.get(key):
            summary.append([label, context[key]])
    summary.append(['Review status', 'Draft; verify inputs and financing terms before relying on results'])
    summary.append(['Workbook', 'Live formulas; blue cells are editable inputs. Structure is fixed.'])
    summary.append(['Run', 'The digest identifies the model run that produced this workbook. Edits in Excel stay in this file.'])
    audit = book.create_sheet('Audit Map')
    audit.append(['Variable', 'Index', 'Cell', 'Unit'])
    for name, rows in compiled.cells.items():
        for index, address in rows.items():
            audit.append([name, json.dumps(index), address, model.variables[name].unit])
    audit.sheet_state = 'hidden'
    assumptions = book.create_sheet('Assumptions')
    assumptions.append(['Structure field', 'Exact JSON value'])
    for key, value in deal.items():
        entries = value.items() if key == 'structure' else [(key, value)]
        for field, item in entries:
            encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if len(encoded) > 32767:
                raise ValueError('Excel cell exceeds size limit.')
            assumptions.append([field, encoded])
    basis = book.create_sheet('Input Basis')
    basis.append(['Input', 'Basis', 'Reason', 'Exact source', 'References / quotes', 'Pinned provenance'])
    basis.append(['Scenario note', context.get('note', '')])
    for key, value in sorted(context.get('basis', {}).items()):
        basis.append([key, value['kind'], value['reason'], value.get('versionId', value.get('runId', '')),
                      json.dumps(value.get('references', []), ensure_ascii=False),
                      json.dumps(context.get('provenance', {}).get(key, {}), ensure_ascii=False)])
    for sheet in (summary, assumptions, basis):
        sheet.freeze_panes = 'B2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='173F35')
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str) and cell.data_type != 'f':
                    # Sources and notes remain literal even if they begin with '='.
                    cell.data_type = 's'
                    if len(cell.value) > 32767:
                        raise ValueError('Excel cell exceeds size limit.')
                elif isinstance(cell.value, float):
                    cell.number_format = '#,##0.00;[Red](#,##0.00)'
                elif isinstance(cell.value, date):
                    cell.number_format = 'yyyy-mm-dd'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        sheet.column_dimensions['A'].width = 45
        for i in range(2, sheet.max_column + 1):
            sheet.column_dimensions[get_column_letter(i)].width = 90 if sheet == summary else 38
    for sheet in book:
        sheet.protection.sheet = True
        sheet.protection.autoFilter = False
        sheet.protection.formatColumns = False
        sheet.protection.formatRows = False
    for name, rows in compiled.cells.items():
        if model.variables[name].kind == 'input':
            for address in rows.values():
                sheet, cell = address.rsplit('!', 1)
                book[sheet.strip("'")][cell].protection = Protection(locked=False)
    return compiled


def workbook(deal, model, run, context):
    import tempfile
    from pathlib import Path
    compiled = compile_report(deal, model, run, context)
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'lihtc.xlsx')
        compiled.save(path)
        return Path(path).read_bytes()


def execute(snapshot, operation, context, serialize):
    if operation == 'describe' and snapshot['deal'] == {'kind': 'lihtc'}:
        snapshot = {'deal': example_snapshot()['deal'], 'inputs': {}}
    structure = read_deal(snapshot['deal'])
    model = build(structure)
    if operation == 'describe':
        return {'model': model.describe(), 'exampleSnapshot': example_snapshot(),
                'inputEncoding': 'Exact decimal strings; dimensioned inputs are [{index: [...], value: decimal string}]. An integer index may be {start: integer, end: integer}, inclusive and ascending, to explicitly repeat that row value. Maximum 601 indices per range and 20000 expanded rows per input; overlapping or missing indices are rejected. No implicit defaults.',
                'workbookKind': 'live_model', 'limits': {'months': 600, 'costItems': 50}}
    run = evaluate(model, read_inputs(model, snapshot['inputs']))
    result = {'run': serialize(run, model)}
    result['run']['fundingStatus'] = 'funded' if run.value('funding.cash_funded') else 'unfunded'
    result['run']['returnAvailability'] = 'available' if structure.return_terms else 'not_elected'
    if operation == 'run':
        import base64
        data = workbook(snapshot['deal'], model, run, context)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError('Workbook exceeds artifact limit.')
        result['workbookBase64'] = base64.b64encode(data).decode('ascii')
    return result
