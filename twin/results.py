"""Résultats annuels du jumeau (pydantic)."""
from __future__ import annotations

from pydantic import BaseModel

from .capex import CapexResult
from .datasources import Provenance


class EnergyBreakdown(BaseModel):
    it_mwh: float
    cooling_mwh: float
    losses_mwh: float
    facility_mwh: float          # IT + refroidissement + pertes
    battery_charge_mwh: float    # soutiré au réseau pour charger
    battery_discharge_mwh: float # fourni au site par la batterie
    battery_losses_mwh: float
    grid_mwh: float              # facility + charge − décharge
    compressor_mwh: float
    cooling_tower_fan_mwh: float
    crac_fan_mwh: float
    pumps_mwh: float
    liquid_overhead_mwh: float


class Thermal(BaseModel):
    rack_inlet_c: dict[str, float]          # par classe de rangée
    rack_outlet_mean_c: float
    rack_outlet_max_c: float
    ashrae_recommended_c: tuple[float, float]
    inlet_within_ashrae: bool
    rack_delta_floor_share: float           # part des pas où le plancher de ΔT a joué
    chiller_rated_cooling_mw: float
    chiller_load_factor_mean: float
    chiller_load_factor_monthly: list[float]
    sizing_ambient_c: float


class Flows(BaseModel):
    """Puissances moyennes et de pointe (MW) entre les équipements, pour la scène 3D."""

    mean: dict[str, float]
    peak: dict[str, float]


class TwinResults(BaseModel):
    engine_version: str
    params_hash: str
    duration_s: float
    from_cache: bool = False
    it_capacity_mw: float
    n_racks: int
    servers_per_rack: float
    energy: EnergyBreakdown
    pue_annual: float
    pue_monthly: list[float]
    peak_facility_mw: float
    peak_grid_mw: float
    grid_capacity_mw: float
    grid_overload_hours: float
    water_m3: float
    water_m3_vendor_formula: float
    co2_t: float
    energy_cost_usd: float
    effective_price_usd_per_mwh: float
    battery_cycles: float
    monthly_it_mwh: list[float]
    monthly_facility_mwh: list[float]
    monthly_grid_mwh: list[float]
    monthly_energy_cost_usd: list[float]
    hourly_grid_mw: list[float]          # 8 760 h (heatmap 24 x 365)
    hourly_price_usd_per_mwh: list[float]
    thermal: Thermal
    flows_mw: Flows
    capex: CapexResult
    provenance: dict[str, Provenance]
    warnings: list[str]
