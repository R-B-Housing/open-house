"""Closing a capital stack with a gap source whose own payment constrains the senior loan.

Affordable deals size the senior loan on coverage, then close the remaining
cost with a soft lender (HCD MHP, a city loan, a seller note). When that gap
lender takes a mandatory annual payment, its size reduces the senior loan's
coverage capacity, which in turn enlarges the gap. With a payment that is a
rate on principal the fixed point is linear and is solved here in closed form,
so no iteration or circular reference reaches a workbook.
"""
from __future__ import annotations

from dataclasses import dataclass

from .expressions import Expr, max_, min_, ref
from .model import Model


@dataclass(frozen=True)
class GapSource:
    assumed: Expr  # The gap that sizes the senior loan.
    amount: Expr  # The gap after the senior loan is sized (and rounded).
    surplus: Expr  # Sources less need: negative when the gap is capped below what is needed.


def build_gap_source(model: Model, *, prefix: str, need: Expr, payment_rate: Expr, maximum: Expr,
                     senior_capacity: Expr, senior_constant: Expr, senior_amount: Expr) -> GapSource:
    """A source sized to `need` less the senior loan, at most `maximum`.

    `need` is the cost to fund from the senior loan and this source together.
    `senior_capacity` is the senior loan's annual payment capacity before this
    source's payment; `senior_constant` its annual debt service per dollar
    (payment and fees). `payment_rate` is this source's mandatory annual payment
    per dollar of principal. Pass the result's `assumed` gap to the senior
    sizing as a prior payment (`payment_rate * assumed`) and the sized senior
    amount back as `senior_amount`; the senior rounding then moves into `amount`.
    """
    interior = (senior_capacity - payment_rate * need) / (senior_constant - payment_rate)
    model.calc(f'{prefix}.assumed', unit='usd', expr=min_(max_(need - interior, 0), maximum))
    model.calc(f'{prefix}.amount', unit='usd', expr=min_(max_(need - senior_amount, 0), maximum))
    model.calc(f'{prefix}.surplus', unit='usd', expr=senior_amount + ref(f'{prefix}.amount') - need)
    return GapSource(ref(f'{prefix}.assumed'), ref(f'{prefix}.amount'), ref(f'{prefix}.surplus'))
