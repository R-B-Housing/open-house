"""LIHTC unit mix, applicable fraction, TCAC threshold basis limit, federal/state credits and equity.

Shared by LIHTC models (new construction now; acquisition/rehab can compute its
applicable fraction from the same unit mix). Each `declare_*` takes the
model's `given(name, unit, dims=(), low=0, high=None)` input declarer, so a
model keeps its own input conventions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .. import Dimension, Item, Model, attr, min_, ref, round_to, sum_over

UNIT_KINDS = ("lihtc", "manager", "market")
Given = Callable[..., None]


@dataclass(frozen=True)
class UnitType:
    """One row of the unit mix: a bedroom count at one income target."""
    key: str
    label: str
    bedrooms: int
    ami: int  # Targeted percent of area median income; 0 for manager and market units.
    kind: str  # lihtc | manager | market


def unit_dimension(unit_types: Sequence[UnitType], name: str = "unit_type") -> Dimension:
    """Unit types with `kind`, `ami`, `bedrooms` and the TCAC targeting bands as attributes."""
    if not unit_types or len({u.key for u in unit_types}) != len(unit_types):
        raise ValueError("Unit type keys must be present and unique.")
    if any(u.kind not in UNIT_KINDS or not 0 <= u.bedrooms <= 5 or not 0 <= u.ami <= 120 for u in unit_types):
        raise ValueError("Unit types need a kind, 0-5 bedrooms and an AMI target of 0-120.")
    if not any(u.kind == "lihtc" for u in unit_types):
        raise ValueError("At least one unit type must be a LIHTC unit.")
    return Dimension(name, [Item(u.key, label=u.label, bedrooms=u.bedrooms, ami=u.ami, kind=u.kind,
                                 at_35=u.kind == "lihtc" and u.ami <= 35,
                                 at_50=u.kind == "lihtc" and 35 < u.ami <= 50) for u in unit_types])


def declare_unit_mix(m: Model, given: Given, *, unit_dim: str = "unit_type") -> None:
    """Units and floor area by unit type; totals, average AMI and the applicable fraction.

    The applicable fraction is the lesser of the LIHTC unit and floor-area
    shares; manager units are in neither (IRC §42(c)(1)).
    """
    ut = (unit_dim,)
    given("units", "units", ut)
    m.check("units.whole", dims=ut, condition=ref("units") == round_to(ref("units"), 0),
            code="UNITS_NOT_WHOLE", message="Unit counts must be whole.")
    given("unit.floor_area", "sf/unit", ut)
    m.calc("units.total", unit="units", expr=sum_over(unit_dim, ref("units")))
    m.calc("units.lihtc", unit="units", expr=sum_over(unit_dim, ref("units"), kind="lihtc"))
    m.calc("units.average_ami", unit="ratio",
           expr=sum_over(unit_dim, ref("units") * attr(unit_dim, "ami"), kind="lihtc") / ref("units.lihtc") / 100)
    for name, body in (("units", ref("units")), ("area", ref("units") * ref("unit.floor_area"))):
        m.calc(f"basis.{name}_fraction", unit="ratio",
               expr=sum_over(unit_dim, body, kind="lihtc")
               / (sum_over(unit_dim, body, kind="lihtc") + sum_over(unit_dim, body, kind="market")))
    m.calc("basis.applicable_fraction", unit="ratio", expr=min_(ref("basis.units_fraction"), ref("basis.area_fraction")))


def declare_qualified_basis(m: Model, given: Given, *, eligible_basis) -> None:
    """Eligible basis times the high-cost (DDA/QCT) boost and the applicable fraction."""
    given("basis.high_cost_boost", "multiple", low=1, high="1.3")
    m.calc("basis.adjusted", unit="usd", expr=eligible_basis * ref("basis.high_cost_boost"))
    m.calc("basis.qualified", unit="usd", expr=ref("basis.adjusted") * ref("basis.applicable_fraction"))


def declare_threshold_basis_limit(m: Model, given: Given, *, eligible_basis, cost_containment_basis,
                                  unit_dim: str = "unit_type") -> None:
    """TCAC threshold basis limit for a 4% project (CCR §10327(c)(5)), with reported tests.

    Per-unit limits times (1 + adjustment boosts, at most 39%, + efficiency
    boosts, at most 10%), plus local impact fees and other additions, plus the
    4% targeting boosts on the base: 1% per 1% of LIHTC units at 36-50% AMI and
    2% per 1% at or below 35% AMI, shares rounded to whole percents.
    `cost_containment_basis` is basis for CDLAC cost containment (eligible
    basis with the deferred fee and GP fee contribution).
    """
    given("tbl.unit_limit", "usd/unit", (unit_dim,))
    given("tbl.adjustment_boost", "ratio", high="0.39")
    given("tbl.efficiency_boost", "ratio", high="0.1")
    given("tbl.local_impact_fees", "usd")
    given("tbl.other_additions", "usd")
    m.calc("tbl.base", unit="usd", expr=sum_over(unit_dim, ref("units") * ref("tbl.unit_limit")))
    for band in ("35", "50"):
        m.calc(f"tbl.share_at_{band}", unit="ratio",
               expr=round_to(sum_over(unit_dim, ref("units"), **{f"at_{band}": True}) / ref("units.lihtc"), 2))
    m.calc("tbl.targeting_boost", unit="ratio", expr=ref("tbl.share_at_50") + 2 * ref("tbl.share_at_35"))
    m.calc("tbl.adjusted", unit="usd",
           expr=ref("tbl.base") * (1 + ref("tbl.adjustment_boost") + ref("tbl.efficiency_boost"))
           + ref("tbl.local_impact_fees") + ref("tbl.other_additions"))
    m.calc("tbl.total", unit="usd", expr=ref("tbl.adjusted") + ref("tbl.base") * ref("tbl.targeting_boost"))
    m.calc("tbl.eligible_basis_share", unit="ratio", expr=eligible_basis / ref("tbl.total"))
    m.test("tbl.within_limit", condition=eligible_basis <= ref("tbl.total"), code="BASIS_ABOVE_LIMIT",
           message="Eligible basis exceeds the threshold basis limit.")
    m.calc("tbl.cost_containment", unit="ratio",
           expr=(ref("tbl.adjusted") - cost_containment_basis) / cost_containment_basis)


def declare_credits_and_equity(m: Model, given: Given) -> None:
    """Ten-year federal credits and a California-style state credit, priced into investor equity.

    Federal: qualified basis times the annual rate, capped by the annual limit
    (a 9% award; a large limit for 4% bonds), ten years. State: its total rate
    on qualified basis, capped by the reservation; years 1-3 at the annual rate
    and year 4 the remainder. Equity: each credit total times the investor
    share and its price, rounded to the dollar.
    """
    given("credits.federal_rate", "ratio/year", high="0.1")
    given("credits.federal_annual_limit", "usd/year")
    given("credits.state_total_rate", "ratio", high="0.35")
    given("credits.state_annual_rate", "ratio/year", high="0.1")
    given("credits.state_reservation", "usd")
    given("credits.investor_share", "ratio", high=1)
    given("credits.federal_price", "usd/usd-credit", high=2)
    given("credits.state_price", "usd/usd-credit", high=2)
    qualified = ref("basis.qualified")
    m.calc("credits.federal_potential", unit="usd/year", expr=qualified * ref("credits.federal_rate"))
    m.calc("credits.federal_annual_exact", unit="usd/year",
           expr=min_(ref("credits.federal_potential"), ref("credits.federal_annual_limit")))
    m.calc("credits.federal_annual", unit="usd/year", expr=round_to(ref("credits.federal_annual_exact"), 0))
    m.calc("credits.federal_total", unit="usd", expr=round_to(ref("credits.federal_annual_exact") * 10, 0))
    m.calc("credits.state_maximum", unit="usd", expr=qualified * ref("credits.state_total_rate"))
    m.calc("credits.state_total", unit="usd",
           expr=round_to(min_(ref("credits.state_maximum"), ref("credits.state_reservation")), 0))
    m.calc("credits.state_early_years", unit="usd/year",
           expr=round_to(min_(qualified * ref("credits.state_annual_rate"), ref("credits.state_total") / 3), 0))
    m.calc("credits.state_fourth_year", unit="usd/year",
           expr=ref("credits.state_total")
           - round_to(min_(qualified * ref("credits.state_annual_rate") * 3, ref("credits.state_total")), 0))
    m.calc("credits.total", unit="usd", expr=ref("credits.federal_total") + ref("credits.state_total"))
    m.calc("credits.state_per_unit", unit="usd/unit", expr=ref("credits.state_total") / ref("units.total"))
    m.calc("equity.federal", unit="usd",
           expr=ref("credits.federal_total") * ref("credits.investor_share") * ref("credits.federal_price"))
    m.calc("equity.state", unit="usd",
           expr=ref("credits.state_total") * ref("credits.investor_share") * ref("credits.state_price"))
    m.calc("equity.investor", unit="usd", expr=round_to(ref("equity.federal") + ref("equity.state"), 0))
