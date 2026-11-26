"""Reviewed cost line items shared by LIHTC project, basis and tax schedules."""
from dataclasses import dataclass
import re

from .. import Dimension, Item, ModelDefinitionError, const, if_, matches, ref, sum_over


COST_CATEGORIES = {
    'land': 'excluded', 'acquisition_building': 'acquisition',
    'acquisition_costs': 'acquisition', 'rehab_hard': 'rehab', 'rehab_soft': 'rehab',
    'financing': 'reviewed', 'reserves': 'excluded', 'developer_fee': 'rehab',
}


@dataclass(frozen=True)
class CostItem:
    name: str
    category: str

    def __post_init__(self):
        if (not isinstance(self.name, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,63}', self.name) is None
                or not isinstance(self.category, str) or self.category not in COST_CATEGORIES):
            raise ModelDefinitionError('Cost items require a safe name and a supported acquisition/rehab category.')


def declare_costs(model, given, items, *, construction_interest_cost):
    """Declare line-item inputs, totals and category totals in the shared graph.

    Scheduled costs include cash and deferred obligations. Capitalized interest
    comes from the construction schedule and belongs to one explicitly named
    financing item; callers must exclude that interest from scheduled cost inputs.
    Category attributes retain reviewed basis exclusions and fee classification.
    """
    if (not isinstance(items, tuple) or not 1 <= len(items) <= 500
            or any(not isinstance(item, CostItem) for item in items)
            or len({item.name for item in items}) != len(items)
            or not isinstance(construction_interest_cost, str)
            or not any(item.name == construction_interest_cost and item.category == 'financing'
                       for item in items)):
        raise ModelDefinitionError('Distinct cost items require one named financing owner for construction interest.')
    model.dimension(Dimension('cost', [Item(item.name, category=item.category,
        basis=COST_CATEGORIES[item.category], developer_fee=item.category == 'developer_fee',
        financing=item.category == 'financing', land=item.category == 'land',
        reserves=item.category == 'reserves', construction_interest=item.name == construction_interest_cost)
        for item in items]))
    model.dimension(Dimension('cost_category', [Item(category, category=category)
                                               for category in COST_CATEGORIES]))
    given('cost.amount', 'USD', ('cost', 'month'))
    model.calc('cost.scheduled_total', unit='USD', dims=('cost',),
               expr=sum_over('month', ref('cost.amount')))
    model.calc('cost.total', unit='USD', dims=('cost',),
               expr=ref('cost.scheduled_total') + if_(matches('cost', construction_interest=True),
                    sum_over('month', sum_over('facility', ref('construction.capitalized_interest'))), const(0)))
    category_total = const(0)
    for category in COST_CATEGORIES:
        category_total = if_(matches('cost_category', category=category),
                             sum_over('cost', ref('cost.total'), category=category), category_total)
    model.calc('cost.category_total', unit='USD', dims=('cost_category',), expr=category_total)
