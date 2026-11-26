"""Runnable synthetic pressure fixtures.

PYTHONPATH=src python3 -m examples.lihtc_pressure
"""
from dataclasses import replace
import json

from openhouse_engine import EngineError
from openhouse_engine.models.lihtc_acquisition_rehab import ConstructionTiming, calculate
from openhouse_engine.models.lihtc_payins import EquityInstallment
from .lihtc_acquisition_rehab import build_example


CASES = ('baseline', 'missing_sponsor', 'delayed_equity', 'operating_downturn',
         'retained_cash', 'partial_construction_payoff', 'reserve_overdraw',
         'unfunded_distribution')
EXPECTED_ERRORS = {'reserve_overdraw': 'RESERVE_OVERDRAWN',
                   'unfunded_distribution': 'DISTRIBUTION_EXCEEDS_CASH'}


def build_pressure_fixture(case):
    """Return an independent fixture through the complete example's contract.

    Returns are disabled so liquidity and accounting can be inspected even
    when stressed investor cash flows do not have a conventional IRR.
    """
    if case not in CASES:
        raise ValueError('Unknown pressure fixture.')
    structure, inputs = build_example()
    structure = replace(structure, return_terms=None)
    months = range(structure.months + 1)
    if case in ('missing_sponsor', 'delayed_equity', 'operating_downturn'):
        inputs['funding.selected_distribution'] = {m: '0' for m in months}
    if case == 'missing_sponsor':
        inputs['funding.sponsor_equity'][0] = '0'
    elif case == 'delayed_equity':
        structure = replace(structure, equity_installments=(
            EquityInstallment('closing', 12, 'percentage'),))
        inputs['funding.sponsor_equity'][0] = '100000'
    elif case == 'operating_downturn':
        inputs['operations.expenses'] = {
            m: '25000' if m >= 13 else '10000' for m in months}
    elif case == 'retained_cash':
        inputs['partner.investor_distribution_fraction'] = {m: '.5' for m in months}
    elif case == 'partial_construction_payoff':
        structure = replace(structure, construction_timing=ConstructionTiming(
            12, 12, 12, 1, repayment='reviewed_amount'))
        inputs['construction.settlement_amount'] = {
            'bond': '1000000', 'taxable': '0', 'equity_bridge': '0'}
    elif case == 'reserve_overdraw':
        inputs['reserve.release'][('replacement', 1)] = '1001'
    elif case == 'unfunded_distribution':
        inputs['funding.selected_distribution'][13] = '10000000'
    return structure, inputs


def run_pressure_fixtures():
    """Summarize outcomes; unexpected errors or accepted invalid deals fail."""
    outcomes = []
    for case in CASES:
        structure, inputs = build_pressure_fixture(case)
        try:
            run = calculate(structure, inputs)
        except EngineError as error:
            if EXPECTED_ERRORS.get(case) != error.code:
                raise
            outcomes.append({'fixture': case, 'rejected': error.code})
            continue
        if case in EXPECTED_ERRORS:
            raise AssertionError(f'{case} accepted invalid assumptions')
        outcomes.append({'fixture': case, **{
            name: str(run.value(name)) for name in (
                'funding.cash_funded', 'funding.maximum_gap',
                'funding.shortfall_months', 'funding.final_cash',
                'funding.final_debt_owed')}})
    return outcomes


if __name__ == '__main__':
    print(json.dumps(run_pressure_fixtures(), indent=2))
