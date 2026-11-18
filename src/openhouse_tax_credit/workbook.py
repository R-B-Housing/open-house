"""Live LIHTC workbook: a summary of sources and uses, the assumptions, and basis by cost line."""
from openhouse_engine import evaluate
from openhouse_engine.workbook import compile_workbook, Layout, Sheet, Row, Heading
from openhouse_valuation.branding import SPONSOR
from .model import build_model

LABELS = {
    'land_cost': 'Land', 'cost': 'Development cost', 'basis_fraction': 'Share in eligible basis',
    'basis_reductions': 'Basis reductions (federal grants, etc.)', 'high_cost_boost': 'High-cost (DDA/QCT) basis boost',
    'total_units': 'Total units', 'lihtc_units': 'LIHTC units', 'total_sqft': 'Total residential floor area',
    'lihtc_sqft': 'LIHTC floor area', 'credit_rate': 'Credit rate', 'annual_credit_cap': 'Competitive (9%) annual credit award',
    'investor_share': "Investor's share of credits", 'credit_price': 'Equity price per dollar of credit',
    'permanent_loan': 'Permanent loan', 'soft_sources': 'Soft loans and grants', 'deferred_developer_fee': 'Deferred developer fee',
    'tax_exempt_bonds': 'Tax-exempt bonds issued', 'bond_financed': 'Bond-financed 4% deal (1) or competitive 9% award (0)',
    'bond_test_threshold': 'Bond test: required share of aggregate basis',
    'basis.line_eligible': 'Eligible basis', 'total_development_cost': 'Total development cost', 'cost_per_unit': 'Cost per unit',
    'basis.eligible_before_reductions': 'Eligible basis before reductions', 'basis.eligible': 'Eligible basis',
    'basis.unit_fraction': 'Unit fraction', 'basis.floor_area_fraction': 'Floor area fraction',
    'basis.applicable_fraction': 'Applicable fraction (lower of the two)', 'basis.qualified': 'Qualified basis',
    'credits.supported_by_basis': 'Annual credits supported by basis', 'credits.annual': 'Annual credits',
    'credits.ten_year_total': 'Ten-year credits', 'tax_credit_equity': 'Tax credit equity',
    'equity_per_lihtc_unit': 'Equity per LIHTC unit', 'total_sources': 'Total sources', 'funding_gap': 'Funding gap',
    'funding_surplus': 'Funding surplus', 'equity_share_of_cost': 'Tax credit equity as a share of cost',
    'bond_test.aggregate_basis': 'Aggregate basis (land plus eligible basis)', 'bond_test.financed_share': 'Share financed by bonds',
    'bond_test.bonds_required': 'Bonds required',
}
SUMMARY = (
    ('Uses', ('total_development_cost', 'cost_per_unit')),
    ('Basis', ('basis.eligible_before_reductions', 'basis.eligible', 'basis.unit_fraction', 'basis.floor_area_fraction',
               'basis.applicable_fraction', 'basis.qualified')),
    ('Credits and equity', ('credits.supported_by_basis', 'credits.annual', 'credits.ten_year_total', 'tax_credit_equity',
                            'equity_per_lihtc_unit', 'equity_share_of_cost')),
    ('Sources and uses', ('total_sources', 'funding_gap', 'funding_surplus')),
    ('Bond test (4% deals)', ('bond_test.aggregate_basis', 'bond_test.financed_share', 'bond_test.bonds_required')),
)
TOTALS = {'total_development_cost', 'basis.qualified', 'tax_credit_equity', 'total_sources', 'funding_gap'}


def write_workbook(deal, inputs, path, sponsor=SPONSOR):
    model = build_model(deal)
    run = evaluate(model, inputs)
    row = lambda name: Row(name, LABELS.get(name, name), total=name in TOTALS)
    summary = [Heading(deal.name), Heading('Simple LIHTC sizing; review every input against current program rules')]
    for title, names in SUMMARY:
        summary += [Heading(title), *(row(n) for n in names)]
    inputs_sheet = [row(n) for n, v in model.variables.items() if v.kind == 'input' and not v.dims]
    basis = [Heading('Development cost and eligible basis by line'), row('cost'), row('basis_fraction'), row('basis.line_eligible')]
    layout = Layout((Sheet('Summary', tuple(summary)), Sheet('Assumptions', tuple(inputs_sheet)), Sheet('Basis', tuple(basis))),
                    units={'usd/credit': 'USD per credit'}, header=sponsor.upper(), footer='Draft LIHTC sources and uses')
    compiled = compile_workbook(model, run, layout)
    if 'Dimensions' in compiled.workbook.sheetnames:
        compiled.workbook['Dimensions'].sheet_state = 'hidden'
    compiled.save(path)
    return model, run, compiled
