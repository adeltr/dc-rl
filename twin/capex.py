"""CAPEX paramétrique par composant, ventilé sur les lignes de coûts durs du classeur."""
from __future__ import annotations

from pydantic import BaseModel

from . import defaults as D
from .params import TwinParams


class CapexLine(BaseModel):
    key: str
    component: str
    amount_usd: float
    unit_cost: float
    unit: str
    quantity: float
    excel_cell: str | None
    source: str


class CapexResult(BaseModel):
    lines: list[CapexLine]
    total_usd: float
    by_component: dict[str, float]


def compute_capex(params: TwinParams, grid_mw: float | None = None) -> CapexResult:
    """``grid_mw`` : capacité de raccordement retenue (renforcée jusqu'à la pointe) ; défaut = saisie."""
    grid_mw = params.grid_capacity_mw if grid_mw is None else grid_mw
    it_kw = params.geometry.it_capacity_mw * 1000
    over = params.capex
    lines: list[CapexLine] = []

    building = D.entry("capex", "building_usd_per_kw_it")
    base_building = sum(item["value"] for item in building.values())
    for key, item in building.items():
        unit = item["value"]
        source = item["source"]
        if over.building_usd_per_kw_it is not None:  # répartition au prorata des lignes de base
            unit = over.building_usd_per_kw_it * item["value"] / base_building
            source = "manual"
        lines.append(CapexLine(key=key, component="building", amount_usd=unit * it_kw, unit_cost=unit,
                               unit="$/kW IT", quantity=it_kw, excel_cell=item.get("cell"), source=source))

    mech = D.entry("capex", "mechanical_usd_per_kw_it", params.cooling.type)
    mech_unit = over.mechanical_usd_per_kw_it if over.mechanical_usd_per_kw_it is not None else mech["value"]
    lines.append(CapexLine(key="mechanical", component="mechanical", amount_usd=mech_unit * it_kw,
                           unit_cost=mech_unit, unit="$/kW IT", quantity=it_kw,
                           excel_cell=D.entry("capex", "mechanical_usd_per_kw_it", "air_chiller")["cell"],
                           source="manual" if over.mechanical_usd_per_kw_it is not None else mech["source"]))

    elec = D.entry("capex", "electrical_usd_per_kw_it")
    elec_unit = over.electrical_usd_per_kw_it if over.electrical_usd_per_kw_it is not None else elec["value"]
    lines.append(CapexLine(key="electrical", component="electrical", amount_usd=elec_unit * it_kw,
                           unit_cost=elec_unit, unit="$/kW IT", quantity=it_kw, excel_cell=elec["cell"],
                           source="manual" if over.electrical_usd_per_kw_it is not None else elec["source"]))

    grid = D.entry("capex", "grid_usd_per_mw")
    grid_unit = over.grid_usd_per_mw if over.grid_usd_per_mw is not None else grid["value"]
    lines.append(CapexLine(key="grid", component="grid", amount_usd=grid_unit * grid_mw,
                           unit_cost=grid_unit, unit="$/MW réseau", quantity=grid_mw,
                           excel_cell=grid["cell"],
                           source="manual" if over.grid_usd_per_mw is not None else grid["source"]))

    kwh_unit = over.battery_usd_per_kwh if over.battery_usd_per_kwh is not None else D.value("capex", "battery_usd_per_kwh")
    kw_unit = over.battery_usd_per_kw if over.battery_usd_per_kw is not None else D.value("capex", "battery_usd_per_kw")
    active = params.battery.active  # saisie incomplète : ni stockage ni CAPEX
    energy_kwh = params.battery.energy_mwh * 1000 if active else 0.0
    power_kw = params.battery.power_mw * 1000 if active else 0.0
    lines.append(CapexLine(key="battery", component="battery", amount_usd=kwh_unit * energy_kwh + kw_unit * power_kw,
                           unit_cost=kwh_unit, unit="$/kWh (+ $/kW PCS)", quantity=energy_kwh, excel_cell="K51",
                           source="manual" if over.battery_usd_per_kwh is not None else "default"))

    by_component: dict[str, float] = {}
    for line in lines:
        by_component[line.component] = by_component.get(line.component, 0.0) + line.amount_usd
    return CapexResult(lines=lines, total_usd=sum(l.amount_usd for l in lines), by_component=by_component)
