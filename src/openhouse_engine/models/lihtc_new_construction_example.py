"""Synthetic ground-up 4% bond / state credit deal for demonstrations and tests.

Every figure is invented: a 64-unit family project in the fictional town of
Sampleton with a city construction loan, a state permanent loan, a state gap
loan and an infrastructure grant. Rent limits, utility allowances, per-unit
basis limits and credit pricing are placeholders shaped like published tables,
not TCAC, HUD or market figures. It is not a deal or a quote.
"""
from .lihtc_new_construction import CostItem, ExpenseLine, SoftLoan, Structure, UnitType

# key, label, category, cost, eligible-basis fraction, deferred to conversion, 50%-test fraction.
COSTS = (
    ("land", "Land", "land", 3200000, "0", 0, "1"),
    ("closing_acquisition", "Acquisition closing costs", "acquisition", 90000, "0", 0, "1"),
    ("offsite", "Off-site improvements", "acquisition", 150000, "1", 0, "0"),
    ("hard_building", "Building construction", "hard", 21500000, "1", 0, "1"),
    ("site_work", "Site work", "hard", 1600000, "1", 0, "1"),
    ("gc_fee", "General contractor fee and conditions", "hard", 2300000, "1", 0, "1"),
    ("hard_contingency", "Hard cost contingency", "hard", 1250000, "1", 0, "1"),
    ("architecture", "Architecture and engineering", "soft", 1100000, "1", 0, "1"),
    ("permits", "Permits and impact fees", "soft", 900000, "1", 0, "1"),
    ("utility_fees", "Utility connection fees", "soft", 450000, "1", 0, "1"),
    ("construction_insurance", "Insurance and taxes during construction", "soft", 260000, "1", 0, "1"),
    ("consultants", "Consultants and reports", "soft", 240000, "1", 0, "1"),
    ("legal", "Legal and organizational", "soft", 180000, "0.5", 0, "0.5"),
    ("marketing", "Marketing and lease-up", "soft", 60000, "0", 0, "0"),
    ("soft_contingency", "Soft cost contingency", "soft", 200000, "1", 0, "1"),
    ("construction_interest", "Construction loan interest", "financing", 1700000, "0.7", 0, "0.7"),
    ("construction_fees", "Construction lender and bond fees", "financing", 420000, "0.3", 0, "0.3"),
    ("permanent_fees", "Permanent loan fees", "financing", 60000, "0", 60000, "0"),
    ("operating_reserve", "Capitalized operating reserve", "reserve", 330000, "0", 330000, "0"),
    ("developer_fee", "Developer fee", "developer_fee", 2400000, "1", 900000, "1"),
)

# key, label, bedrooms, AMI target, kind, units, floor area, gross rent limit, UA, subsidized units, contract rent, per-unit basis limit.
UNITS = (
    ("one_30", "1BR 30% AMI", 1, 30, "lihtc", 8, 600, 700, 45, 6, 1700, 400000),
    ("one_50", "1BR 50% AMI", 1, 50, "lihtc", 10, 600, 1170, 45, 0, 0, 400000),
    ("two_50", "2BR 50% AMI", 2, 50, "lihtc", 16, 850, 1400, 60, 0, 0, 480000),
    ("two_60", "2BR 60% AMI", 2, 60, "lihtc", 14, 850, 1680, 60, 0, 0, 480000),
    ("three_60", "3BR 60% AMI", 3, 60, "lihtc", 15, 1100, 1940, 75, 0, 0, 610000),
    ("manager", "Manager 2BR", 2, 0, "manager", 1, 850, 0, 0, 0, 0, 480000),
)

# Base-year operating budget.
EXPENSES = (
    ("administrative", "Administrative", "operating", 120000),
    ("management_fee", "Management fee", "operating", 52000),
    ("utilities", "Utilities", "operating", 90000),
    ("payroll", "Payroll and benefits", "operating", 110000),
    ("insurance", "Insurance", "operating", 64000),
    ("maintenance", "Repairs and maintenance", "operating", 85000),
    ("resident_services", "Resident services", "operating", 40000),
    ("real_estate_taxes", "Real estate taxes", "property_tax", 6000),
)

# key, label, construction, residual receipts, gap, amount, rate, mandatory rate.
SOFT = (
    ("city", "City housing loan", True, True, False, 3000000, "0.03", "0"),
    ("state", "State multifamily loan", False, True, False, 5000000, "0.03", "0.0042"),
    ("gap", "State gap loan", False, True, True, None, "0.03", "0.0042"),
    ("grant", "Infrastructure grant", True, False, False, 1500000, "0", "0"),
)


def build_example():
    """Return the synthetic Structure and complete inputs."""
    structure = Structure(
        unit_types=tuple(UnitType(k, label, br, ami, kind) for k, label, br, ami, kind, *_ in UNITS),
        cost_items=tuple(CostItem(k, label, category) for k, label, category, *_ in COSTS),
        expense_lines=tuple(ExpenseLine(k, label, kind) for k, label, kind, _ in EXPENSES),
        soft_loans=tuple(SoftLoan(k, label, construction, residual, gap) for k, label, construction, residual, gap, *_ in SOFT),
        years=17, first_year=2028)
    by_unit = lambda column: {u[0]: str(u[column]) for u in UNITS}
    inputs = {
        "units": by_unit(5), "unit.floor_area": by_unit(6), "rent.gross_limit": by_unit(7),
        "rent.utility_allowance": by_unit(8), "subsidy.units": by_unit(9), "subsidy.contract_rent": by_unit(10),
        "rent.market": {u[0]: "2400" for u in UNITS},
        "tbl.unit_limit": by_unit(11),
        "cost.amount": {c[0]: str(c[3]) for c in COSTS},
        "basis.eligible_fraction": {c[0]: c[4] for c in COSTS},
        "cost.deferred_to_conversion": {c[0]: str(c[5]) for c in COSTS},
        "basis.bond_test_fraction": {c[0]: c[6] for c in COSTS},
        "fee.limit": "2400000", "fee.cash": "1500000",
        "equity.gp_fee_contribution": "0", "equity.gp_other_contribution": "0",
        "basis.high_cost_boost": "1",
        "tbl.adjustment_boost": "0.30", "tbl.efficiency_boost": "0",
        "tbl.local_impact_fees": "900000", "tbl.other_additions": "0",
        "credits.federal_rate": "0.04", "credits.federal_annual_limit": "999999999",
        "credits.state_total_rate": "0.30", "credits.state_annual_rate": "0.04",
        "credits.state_reservation": "9000000",
        "credits.investor_share": "0.9999", "credits.federal_price": "0.88", "credits.state_price": "0.78",
        "equity.syndication_costs": "120000", "equity.construction_fraction": "0.15",
        "income.other_annual": "9000",
        "vacancy.residential": "0.05", "vacancy.subsidy": "0.05",
        "expense.amount": {e[0]: str(e[3]) for e in EXPENSES},
        "reserve.replacement_annual": "32000",
        "soft.amount": {s[0]: str(s[5]) for s in SOFT if not s[4]},
        "soft.gap_maximum": "999999999",
        "soft.rate": {s[0]: s[6] for s in SOFT}, "soft.mandatory_rate": {s[0]: s[7] for s in SOFT},
        "soft.mandatory_first_year": "2",
        "perm.annual_rate": "0.065", "perm.fee_rate": "0.001", "perm.dscr": "1.15",
        "perm.amortization_years": "35", "perm.rounding": "1000", "perm.maximum": "999999999",
        "perm.first_year_months": "6", "perm.fee_first_year": "2",
        "construction.bond_fraction": "0.52", "construction.bond_test_minimum": "0.50",
        "growth.rent": "0.025", "growth.subsidy": "0.02",
        "growth.expenses": "0.035", "growth.property_tax": "0.02", "growth.reserve": "0",
        "waterfall.lp_fee": "7500", "waterfall.lp_fee_growth": "0.03",
        "waterfall.lp_fee_growth_years": "40", "waterfall.lp_fee_later_growth": "0.03",
        "waterfall.gp_fee": "15000", "waterfall.gp_fee_growth": "0.03",
        "waterfall.gp_fee_growth_years": "40", "waterfall.gp_fee_later_growth": "0.03",
        "waterfall.first_year_fraction": "0.5", "waterfall.deferred_fee_rate": "0",
        "waterfall.lender_share": "0.5", "waterfall.gp_residual_share": "0.9",
        "tcac.minimum_dscr": "1.15", "tcac.cash_flow_limit": "0.25", "tcac.gross_income_limit": "0.08",
    }
    return structure, inputs
