"""Commercial leases in the LIHTC project: lease-based income, not residential occupancy."""
from dataclasses import replace
from decimal import Decimal
import unittest

from openhouse_engine import ModelDefinitionError
from openhouse_engine.commercial import CommercialSpace
from openhouse_engine.operations import AnnualProjectionTerms
from openhouse_engine.models.lihtc_acquisition_rehab import build, calculate
from openhouse_engine.models.lihtc_example import build_example
from test_lihtc_annual_project import annual_project

SPACES = (CommercialSpace('market', 'Corner market', 3000, 'nnn'),
          CommercialSpace('clinic', 'Community clinic', 2400, 'gross'))


def lease_inputs(months):
    return {
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
        'commercial.management_fraction': '.04',
        'commercial.recoverable_costs': {m: '2500' for m in months},
    }


def commercial_example(horizon=180):
    structure, inputs = build_example(horizon)
    inputs.update(lease_inputs(range(horizon + 1)))
    # Taxable commercial income turns later investor flows negative; returns are not under test.
    return replace(structure, commercial_spaces=SPACES, return_terms=None), inputs


class LihtcCommercialTest(unittest.TestCase):
    def test_lease_income_reaches_revenue_and_noi_independent_of_residential_occupancy(self):
        structure, inputs = commercial_example()
        full = calculate(structure, inputs)
        inputs['rent.occupied_units'] = {k: 12 for k in inputs['rent.occupied_units']}
        half = calculate(structure, inputs)
        for month in (0, 1, 7, 24, 25, 40, 61, 180):
            income = full.value('commercial.income', month=month)
            self.assertEqual(half.value('commercial.income', month=month), income)
            residential = full.value('rent.collected', unit_type='restricted', month=month)
            fee = full.value('operations.commercial_management_fee', month=month)
            self.assertAlmostEqual(fee, income * Decimal('.04'), places=18)
            self.assertAlmostEqual(full.value('operations.revenue', month=month), residential + income, places=18)
            self.assertAlmostEqual(full.value('operations.noi', month=month),
                                   residential + income - (full.value('operations.expenses', month=month) + fee if month else 0),
                                   places=18)
            self.assertAlmostEqual(full.value('operations.revenue', month=month) - half.value('operations.revenue', month=month),
                                   residential / 2, places=18)
        self.assertEqual(full.value('commercial.income', month=0), 0)
        self.assertEqual(full.value('commercial.base_rent_total', month=1), Decimal(14000))
        # The NNN tenant reimburses 40% of the reviewed recoverable pool; the gross tenant nothing.
        self.assertEqual(full.value('commercial.recoveries_total', month=1), Decimal(1000))
        self.assertEqual(full.value('commercial.income', month=1), Decimal(15000) * Decimal('.98'))

    def test_leasing_costs_are_capital_paid_from_cash_not_noi(self):
        structure, inputs = commercial_example()
        run = calculate(structure, inputs)
        leasing = run.value('commercial.leasing_costs_total', month=25)
        self.assertEqual(leasing, Decimal('.5') * 2400 * 31)
        base = replace(build_example()[0], return_terms=None)
        plain = dict(inputs)
        for name in tuple(plain):
            if name.startswith('commercial.'):
                plain.pop(name)
        without = calculate(base, plain)
        uses = run.value('funding.uses', month=25) - without.value('funding.uses', month=25)
        debt_service = run.value('debt.debt_service', month=25) - without.value('debt.debt_service', month=25)
        self.assertEqual(uses - debt_service, leasing)

    def test_without_spaces_the_model_declares_no_commercial_lease_variables(self):
        structure, _ = build_example()
        self.assertFalse([n for n in build(structure).variables if n.startswith('commercial.')])

    def test_annual_projection_sums_monthly_leases_and_recovers_property_taxes(self):
        structure, inputs = annual_project()
        structure = replace(structure, commercial_spaces=SPACES,
                            expense_projection=AnnualProjectionTerms(('base', 'property_taxes'), 0))
        leases = lease_inputs(range(36))
        leases.pop('commercial.recoverable_costs')
        leases.pop('commercial.management_fraction')
        inputs.update(leases)
        for name in ('commercial_annual_base', 'commercial_growth', 'first_commercial_fraction',
                     'commercial_vacancy_fraction'):
            inputs.pop('annual_operations.' + name)
        inputs['expenses.annual_base'] = {'base': '100', 'property_taxes': '24000'}
        inputs['expenses.annual_growth'] = {(e, y): '0' for e in ('base', 'property_taxes') for y in (2027, 2028, 2029)}
        run = calculate(structure, inputs)
        model = build(structure)
        self.assertNotIn('annual_operations.commercial_annual_base', model.variables)
        self.assertEqual(model.variables['commercial.recoverable_costs'].kind, 'calculation')
        p = 'annual_operations'
        for year in (2027, 2028, 2029):
            months = [m for m in range(36) if 2027 + m // 12 == year]
            rent = sum(run.value('commercial.base_rent_total', month=m) + run.value('commercial.recoveries_total', month=m)
                       for m in months)
            self.assertAlmostEqual(run.value(p + '.commercial_rent', tax_year=year), rent, places=18)
            effective = sum(run.value('commercial.income', month=m) for m in months)
            self.assertAlmostEqual(run.value(p + '.commercial_effective_income', tax_year=year), effective, places=18)
            residential = run.value(p + '.residential_effective_income', tax_year=year)
            self.assertAlmostEqual(run.value(p + '.revenue', tax_year=year), residential + effective, places=18)
            self.assertAlmostEqual(run.value(p + '.management_fee', tax_year=year),
                                   residential * Decimal('.05') + effective * Decimal('.1'), places=18)
        # Property taxes post at each year end; the NNN tenant recovers 40% of the year's taxes there.
        self.assertEqual(run.value('commercial.recoveries_total', month=23), Decimal(24000) * Decimal('.4'))
        self.assertEqual(run.value('commercial.recoveries_total', month=22), 0)

    def test_spaces_are_distinct_and_bounded(self):
        structure, _ = build_example()
        with self.assertRaises(ModelDefinitionError):
            replace(structure, commercial_spaces=(SPACES[0], SPACES[0]))
        with self.assertRaises(ModelDefinitionError):
            replace(structure, commercial_spaces=tuple(CommercialSpace(f's{i}', 'Space', 100, 'gross') for i in range(21)))
        with self.assertRaises(ModelDefinitionError):
            replace(structure, commercial_spaces=(CommercialSpace('Bad Key', 'Space', 100, 'gross'),))


if __name__ == '__main__':
    unittest.main()
