"""Structure of a LIHTC sources-and-uses model: the deal's name and its development cost lines."""
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class CostLine:
    key: str
    label: str


@dataclass(frozen=True)
class TaxCreditDeal:
    kind: str
    name: str
    location: str
    cost_lines: tuple[CostLine, ...]


def read_deal(value):
    if not isinstance(value, dict) or set(value) != {f.name for f in fields(TaxCreditDeal)}:
        raise ValueError('Every tax credit structure field is required.')
    data = dict(value)
    if data['kind'] != 'lihtc':
        raise ValueError('Invalid tax credit kind.')
    rows = data['cost_lines']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError('A tax credit model has 1 to 50 cost lines.')
    data['cost_lines'] = tuple(CostLine(**row) for row in rows)
    if len({line.key for line in data['cost_lines']}) != len(rows):
        raise ValueError('Cost line keys must be unique.')
    return TaxCreditDeal(**data)
