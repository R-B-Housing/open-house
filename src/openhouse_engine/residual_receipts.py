"""Distribution of cash flow after must-pay debt in affordable housing.

Below the senior loan, regulated partnerships pay in a fixed priority: fees to
the partners (which accrue when unpaid), the deferred developer fee or other
cash-flow notes, then residual receipts shared with the soft lenders pro rata
by principal, the rest to the partnership. Each piece is a component a model
composes in its own order over any period dimension (months or years).
Nothing is rounded; callers own the scheduled amounts, rates and shares.
"""
from __future__ import annotations

from dataclasses import dataclass

from .expressions import Expr, if_, lag, matches, min_, ref, sum_over
from .model import Model


@dataclass(frozen=True)
class Payment:
    due: Expr
    paid: Expr
    accrued: Expr
    remaining: Expr  # Cash left for the next priority.


def build_accruing_payment(model: Model, *, prefix: str, period_dim: str, scheduled: Expr,
                           available: Expr) -> Payment:
    """A scheduled payment from available cash; any unpaid amount is due first next period."""
    dims = (period_dim,)
    model.calc(f'{prefix}.due', unit='usd', dims=dims, expr=scheduled + lag(f'{prefix}.accrued', period_dim, initial=0))
    model.calc(f'{prefix}.paid', unit='usd', dims=dims, expr=min_(ref(f'{prefix}.due'), available))
    model.calc(f'{prefix}.accrued', unit='usd', dims=dims, expr=ref(f'{prefix}.due') - ref(f'{prefix}.paid'))
    return Payment(ref(f'{prefix}.due'), ref(f'{prefix}.paid'), ref(f'{prefix}.accrued'), available - ref(f'{prefix}.paid'))


@dataclass(frozen=True)
class CashFlowNote:
    opening: Expr
    paid: Expr
    closing: Expr
    remaining: Expr


def build_cash_flow_note(model: Model, *, prefix: str, period_dim: str, principal: Expr, rate: Expr,
                         available: Expr) -> CashFlowNote:
    """A note repaid only from available cash, such as a deferred developer fee.

    Payment comes at the start of each period; `rate` per period accrues
    (compounding) on the balance left unpaid.
    """
    dims = (period_dim,)
    model.calc(f'{prefix}.opening', unit='usd', dims=dims, expr=lag(f'{prefix}.closing', period_dim, initial=principal))
    model.calc(f'{prefix}.paid', unit='usd', dims=dims, expr=min_(ref(f'{prefix}.opening'), available))
    model.calc(f'{prefix}.closing', unit='usd', dims=dims,
               expr=(ref(f'{prefix}.opening') - ref(f'{prefix}.paid')) * (1 + rate))
    return CashFlowNote(ref(f'{prefix}.opening'), ref(f'{prefix}.paid'), ref(f'{prefix}.closing'),
                        available - ref(f'{prefix}.paid'))


@dataclass(frozen=True)
class ResidualReceipts:
    share: Expr  # By lender.
    payment: Expr  # By lender and period.
    lender_total: Expr  # By period.
    remaining: Expr  # The partnership's share, by period.


def build_residual_receipts(model: Model, *, prefix: str, period_dim: str, lender_dim: str, principal: Expr,
                            available: Expr, lender_share: Expr, **eligible) -> ResidualReceipts:
    """`lender_share` of available cash to the lenders matching `eligible`, pro rata by principal."""
    model.calc(f'{prefix}.pool', unit='usd', expr=sum_over(lender_dim, principal, **eligible))
    pool = ref(f'{prefix}.pool')
    model.calc(f'{prefix}.share', unit='rate', dims=(lender_dim,),
               expr=if_(matches(lender_dim, **eligible), if_(pool > 0, principal / pool, 0), 0))
    model.calc(f'{prefix}.payment', unit='usd', dims=(lender_dim, period_dim),
               expr=available * lender_share * ref(f'{prefix}.share'))
    model.calc(f'{prefix}.lender_total', unit='usd', dims=(period_dim,), expr=sum_over(lender_dim, ref(f'{prefix}.payment')))
    model.calc(f'{prefix}.partnership', unit='usd', dims=(period_dim,), expr=available - ref(f'{prefix}.lender_total'))
    return ResidualReceipts(ref(f'{prefix}.share'), ref(f'{prefix}.payment'), ref(f'{prefix}.lender_total'),
                            ref(f'{prefix}.partnership'))


def build_simple_interest_balances(model: Model, *, prefix: str, lender_dim: str, period_dim: str,
                                   principal: Expr, rate: Expr, payments: Expr) -> Expr:
    """Soft-loan balances: simple interest on principal each period, less payments received."""
    dims = (lender_dim, period_dim)
    model.calc(f'{prefix}.interest', unit='usd', dims=dims, expr=principal * rate)
    model.calc(f'{prefix}.balance', unit='usd', dims=dims,
               expr=lag(f'{prefix}.balance', period_dim, initial=principal) + ref(f'{prefix}.interest') - payments)
    return ref(f'{prefix}.balance')
