"""KPI du cockpit (base, scénario, écart, sens favorable, paramètres pilotes) et alertes."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from bridge.bridge import WorkbookResults
from twin.results import TwinResults

from .catalog import catalog_by_path

Better = Literal["higher", "lower"]
GEOMETRY = ["params.geometry.n_halls", "params.geometry.rows_per_hall", "params.geometry.racks_per_row",
            "params.geometry.kw_per_rack"]
PHYSICS = ["params.cooling.type", "params.cooling.chiller_cop", "params.cooling.setpoint_c", "params.site_id",
           "params.load.utilization"]
ENERGY_PRICE = ["params.price.flat_usd_per_mwh", "params.price.mode", "params.battery.power_mw",
                "params.battery.energy_mwh", "params.battery.strategy"]
REVENUE = ["market.rent_usd_per_kw_month", "market.rent_growth", "market.absorption_multiplier"]
FINANCE_COMMON = GEOMETRY + PHYSICS + ENERGY_PRICE + REVENUE + ["market.idx_energy", "market.idx_opex",
                                                                "market.carbon_price_usd_per_t",
                                                                "market.water_price_usd_per_m3"]


class KpiDefinition(BaseModel):
    id: str
    label: str
    unit: str
    better: Better
    source: Literal["workbook", "twin"]
    field: str
    drivers: list[str]
    cockpit: bool = True


KPIS: list[KpiDefinition] = [
    KpiDefinition(id="irr_equity", label="TRI equity", unit="%", better="higher", source="workbook",
                  field="out_irr_equity", drivers=FINANCE_COMMON + ["market.perm_debt"]),
    KpiDefinition(id="irr_project", label="TRI projet", unit="%", better="higher", source="workbook",
                  field="out_irr_project", drivers=FINANCE_COMMON),
    KpiDefinition(id="npv", label="VAN", unit="$", better="higher", source="workbook", field="out_npv",
                  drivers=FINANCE_COMMON + ["market.discount_rate"]),
    KpiDefinition(id="dscr_min", label="DSCR min", unit="x", better="higher", source="workbook",
                  field="out_dscr_min", drivers=["market.perm_debt"] + FINANCE_COMMON),
    KpiDefinition(id="dscr_avg", label="DSCR moyen", unit="x", better="higher", source="workbook",
                  field="out_dscr_avg", drivers=["market.perm_debt"] + FINANCE_COMMON),
    KpiDefinition(id="llcr", label="LLCR", unit="x", better="higher", source="workbook", field="out_llcr",
                  drivers=["market.perm_debt"] + FINANCE_COMMON),
    KpiDefinition(id="capex_total", label="CAPEX total", unit="$", better="lower", source="workbook",
                  field="out_capex_total",
                  drivers=GEOMETRY + ["params.cooling.type", "params.battery.power_mw", "params.battery.energy_mwh",
                                      "params.grid_capacity_mw"] + REVENUE),
    KpiDefinition(id="opex_energy_y1", label="OPEX énergie année 1", unit="$", better="lower", source="workbook",
                  field="out_opex_energy_y1",
                  drivers=GEOMETRY + PHYSICS + ENERGY_PRICE + ["market.carbon_price_usd_per_t",
                                                               "market.water_price_usd_per_m3"]),
    KpiDefinition(id="pue", label="PUE", unit="", better="lower", source="twin", field="pue_annual",
                  drivers=PHYSICS + ["params.geometry.kw_per_rack"]),
    KpiDefinition(id="energy_cost_effective", label="Coût effectif de l'énergie", unit="$/MWh", better="lower",
                  source="twin", field="effective_price_usd_per_mwh", drivers=ENERGY_PRICE),
    # hors cockpit : utiles aux graphiques et aux comparaisons
    KpiDefinition(id="it_capacity", label="Capacité IT", unit="MW", better="higher", source="twin",
                  field="it_capacity_mw", drivers=GEOMETRY, cockpit=False),
    KpiDefinition(id="peak_grid", label="Pointe réseau", unit="MW", better="lower", source="twin",
                  field="peak_grid_mw", drivers=GEOMETRY + PHYSICS + ENERGY_PRICE, cockpit=False),
    KpiDefinition(id="co2", label="Émissions", unit="tCO2/an", better="lower", source="twin", field="co2_t",
                  drivers=GEOMETRY + PHYSICS + ["params.battery.strategy"], cockpit=False),
    KpiDefinition(id="water", label="Eau", unit="m³/an", better="lower", source="twin", field="water_m3",
                  drivers=GEOMETRY + PHYSICS, cockpit=False),
    KpiDefinition(id="equity", label="Equity requise", unit="$", better="lower", source="workbook",
                  field="out_equity", drivers=GEOMETRY + REVENUE, cockpit=False),
]
KPIS_BY_ID = {k.id: k for k in KPIS}


class Driver(BaseModel):
    path: str
    label: str


class KpiValue(BaseModel):
    id: str
    label: str
    unit: str
    better: Better
    cockpit: bool
    value: float | None
    base: float | None
    delta: float | None
    delta_pct: float | None
    favorable: bool | None
    drivers: list[Driver]


def kpi_raw(kpi: KpiDefinition, twin: TwinResults | None, workbook: WorkbookResults | dict | None) -> float | None:
    if kpi.source == "twin":
        return getattr(twin, kpi.field) if twin is not None else None
    if workbook is None:
        return None
    outputs = workbook.outputs if isinstance(workbook, WorkbookResults) else workbook
    value = outputs.get(kpi.field)
    return float(value) if isinstance(value, (int, float)) else None


def compute_kpis(twin, workbook, base_twin, base_workbook) -> list[KpiValue]:
    labels = catalog_by_path()
    out = []
    for kpi in KPIS:
        value, base = kpi_raw(kpi, twin, workbook), kpi_raw(kpi, base_twin, base_workbook)
        delta = value - base if value is not None and base is not None else None
        favorable = None
        if delta is not None and abs(delta) > 1e-12 * max(1.0, abs(base)):
            favorable = (delta > 0) == (kpi.better == "higher")
        out.append(KpiValue(
            id=kpi.id, label=kpi.label, unit=kpi.unit, better=kpi.better, cockpit=kpi.cockpit, value=value,
            base=base, delta=delta, delta_pct=delta / abs(base) if delta is not None and base else None,
            favorable=favorable,
            drivers=[Driver(path=p, label=labels[p].label) for p in dict.fromkeys(kpi.drivers) if p in labels]))
    return out


class Alert(BaseModel):
    id: str
    severity: Literal["critical", "warning", "info"]
    message: str
    target: str  # équipement visé par la caméra : campus, substation, hall, cooling_plant, battery, site
    value: float | None = None
    threshold: float | None = None


def compute_alerts(twin: TwinResults | None, workbook: WorkbookResults | dict | None, covenant: float) -> list[Alert]:
    alerts: list[Alert] = []
    outputs = (workbook.outputs if isinstance(workbook, WorkbookResults) else workbook) if workbook else {}
    dscr = outputs.get("out_dscr_min")
    if isinstance(dscr, (int, float)) and dscr < covenant:
        alerts.append(Alert(id="dscr_covenant", severity="critical", target="campus", value=dscr, threshold=covenant,
                            message=f"DSCR minimum {dscr:.2f}x sous le covenant de {covenant:.2f}x"))
    if twin is None:
        return alerts
    if twin.peak_grid_mw > twin.grid_capacity_mw + 1e-9:
        alerts.append(Alert(id="grid_capacity", severity="critical", target="substation", value=twin.peak_grid_mw,
                            threshold=twin.grid_capacity_mw,
                            message=f"Appel réseau {twin.peak_grid_mw:.1f} MW supérieur à la capacité de "
                                    f"raccordement ({twin.grid_capacity_mw:.1f} MW) pendant {twin.grid_overload_hours:g} h"))
    lo, hi = twin.thermal.ashrae_recommended_c
    for row_class, inlet in twin.thermal.rack_inlet_c.items():
        if not lo <= inlet <= hi:
            alerts.append(Alert(id=f"ashrae_{row_class}", severity="warning", target="hall", value=inlet,
                                threshold=hi if inlet > hi else lo,
                                message=f"Température d'entrée des racks ({'bord' if row_class == 'edge' else 'intérieur'}) "
                                        f"{inlet:.1f} °C hors plage ASHRAE recommandée {lo:g}–{hi:g} °C"))
    for i, warning in enumerate(twin.warnings):
        target = ("battery" if "Batterie" in warning else "substation" if "réseau" in warning
                  else "cooling_plant" if any(w in warning for w in ("Free cooling", "liquide", "COP", "Eau"))
                  else "hall")
        if "capacité de raccordement" in warning:
            continue  # déjà couvert par l'alerte critique
        alerts.append(Alert(id=f"twin_{i}", severity="info", target=target, message=warning))
    for key, prov in twin.provenance.items():
        if "approximation" in prov.detail:
            alerts.append(Alert(id=f"data_{key}", severity="info", target="site",
                                message=f"{key} : {prov.source} — {prov.detail}"))
    return alerts
