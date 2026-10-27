"""Moteur du jumeau : ``run_year(params) -> TwinResults``.

Simulation physique d'une année au pas de 15 min (35 040 pas) avec le port vectorisé
de SustainDC (twin/physics.py), une consigne de refroidissement fixe et une règle
déterministe pour la batterie. Les corrections du modèle vendor sont décrites dans
docs/vendor_patches.md et désactivables via ``params.patches``.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import defaults as D
from . import physics as P
from .battery import dispatch
from .capex import compute_capex
from .datasources import Provenance, get_site, load_carbon_intensity, load_weather, load_workload
from .params import TwinParams
from .pricing import calendar, hourly_prices
from .results import EnergyBreakdown, Flows, Thermal, TwinResults
from .vendor import REPO_ROOT, vendor_dc_config

ENGINE_VERSION = "0.1.1"
STEPS = 35040
STEP_H = 0.25
CACHE_DIR = Path(os.environ.get("TWIN_CACHE_DIR", REPO_ROOT / ".cache" / "twin"))
LOG_PATH = Path(os.environ.get("TWIN_SCENARIO_LOG", REPO_ROOT / "logs" / "scenarios.jsonl"))

log = logging.getLogger(__name__)
_memory_cache: dict[str, TwinResults] = {}


def _fr(value: float, digits: int = 1) -> str:
    """Nombre au format français pour les messages : 1 234,5."""
    return f"{value:,.{digits}f}".replace(",", "\u202f").replace(".", ",").replace("-", "−")


def rack_classes(params: TwinParams, servers_per_rack: float) -> list[P.RackClass]:
    """Rangées de bord (2 par hall) et rangées intérieures, approches de dc_config.json."""
    g = params.geometry
    edge, inner = D.entry("rack_rows", "edge"), D.entry("rack_rows", "inner")
    edge_rows = min(2, g.rows_per_hall)
    inner_rows = g.rows_per_hall - edge_rows
    classes = [P.RackClass(g.n_halls * edge_rows * g.racks_per_row, servers_per_rack,
                           edge["supply_approach_c"], edge["return_approach_c"])]
    if inner_rows:
        classes.append(P.RackClass(g.n_halls * inner_rows * g.racks_per_row, servers_per_rack,
                                   inner["supply_approach_c"], inner["return_approach_c"]))
    return classes


def servers_per_rack(cfg: P.PhysicsConfig, kw_per_rack: float, full_w: float, idle_w: float) -> float:
    """Nombre (continu) de serveurs donnant ``kw_per_rack`` aux conditions de référence."""
    inner = D.entry("rack_rows", "inner")
    inlet = P.clamp_supply_approach(inner["supply_approach_c"]) + D.value("kw_per_rack_reference", "setpoint_c")
    cpu, fan, _ = P.server_power(cfg, full_w, idle_w, inlet, D.value("kw_per_rack_reference", "load_pct"))
    return kw_per_rack * 1000 / float(cpu + fan)


def _monthly(values: np.ndarray, month_of_step: np.ndarray, how: str = "sum") -> list[float]:
    out = []
    for m in range(1, 13):
        chunk = values[month_of_step == m]
        out.append(float(chunk.sum() if how == "sum" else chunk.mean()))
    return out


def simulate(params: TwinParams) -> TwinResults:
    t0 = time.perf_counter()
    warnings: list[str] = []
    provenance: dict[str, Provenance] = {}
    patches = params.patches
    cfg = P.PhysicsConfig.from_vendor_json(vendor_dc_config())
    full_w, idle_w = D.value("server", "full_load_w"), D.value("server", "idle_w")
    setpoint = params.cooling.setpoint_c
    site = get_site(params.site_id)

    # --- données d'entrée
    weather = load_weather(params.site_id, params.data.weather_file)
    provenance["weather"] = weather.provenance
    carbon = load_carbon_intensity(params.site_id, params.data.carbon_intensity_g_per_kwh)
    provenance["carbon_intensity"] = carbon.provenance
    if params.load.mode == "constant":
        load = np.full(STEPS, params.load.utilization)
        provenance["load"] = Provenance(status="manual", source="taux d'utilisation constant",
                                        detail=f"{params.load.utilization:.0%}")
    else:
        series = load_workload(params.load.trace, params.load.trace_file)
        load, provenance["load"] = series.values, series.provenance
    price_h, provenance["price"] = hourly_prices(params.price)
    price = np.repeat(price_h, 4)
    month_h, _, _ = calendar(D.value("price", "calendar_year"))
    month = np.repeat(month_h, 4)

    # --- IT
    n_servers = servers_per_rack(cfg, params.geometry.kw_per_rack, full_w, idle_w)
    racks = rack_classes(params, n_servers)
    floor = D.value("thermal", "min_rack_delta_c") if patches.rack_delta_floor else None
    cpu, fan, avg_return, per_class = P.it_model(cfg, racks, full_w, idle_w, setpoint, load * 100, floor)
    ite = cpu + fan
    if floor is None and any(np.any(c["delta"] < D.value("thermal", "min_rack_delta_c")) for c in per_class):
        warnings.append("ΔT de rack < 2 °C hors du domaine SustainDC (le vendor lèverait une exception).")
    floor_share = float(np.mean([np.mean(c["clamped"]) for c in per_class])) if floor is not None else 0.0
    if floor_share > 0:
        warnings.append(f"Plancher ΔT rack de {_fr(floor)} °C appliqué sur {_fr(floor_share * 100)} % des pas "
                        "(densité ou charge faibles pour le modèle thermique SustainDC).")

    # --- dimensionnement chiller / tour
    if patches.sizing_from_weather_p996:
        sizing_ambient = float(np.percentile(weather.dry_bulb_hourly, 99.6))
    else:
        sizing_ambient = P.VENDOR_SIZING_AMBIENT.get(site.get("sizing_region", ""), P.VENDOR_SIZING_DEFAULT)
    ctafr, ct_rated = P.chiller_sizing(cfg, racks, full_w, idle_w, sizing_ambient, min_rack_delta=floor)

    # --- CVC (modèle air SustainDC)
    hvac = P.hvac_power(cfg, setpoint, avg_return, weather.dry_bulb, ite, ct_rated, ctafr)
    compressor = hvac["compressor_w"]
    if patches.cop_correction:
        compressor = compressor * P.VENDOR_RATED_COP / params.cooling.chiller_cop
    elif params.cooling.chiller_cop != P.VENDOR_RATED_COP:
        warnings.append("COP saisi ignoré : correction COP désactivée (SustainDC fixe le COP à 3,0).")

    if params.cooling.type == "air_free_cooling":
        approach = D.value("free_cooling", "wet_bulb_approach_c")
        band = D.value("free_cooling", "transition_band_c")
        free_share = np.clip((setpoint - (weather.wet_bulb + approach)) / band, 0, 1)
        compressor = compressor * (1 - free_share)
        warnings.append("Free cooling : approximation (compresseur réduit selon T humide + approche).")

    liquid = 0.0
    if params.cooling.type == "liquid":
        liquid = params.cooling.liquid_fraction
        if liquid is None:
            liquid = D.value("liquid_cooling", "liquid_fraction")
        warnings.append(f"Refroidissement liquide : approximation ({_fr(liquid * 100, 0)} % de la chaleur par boucle liquide).")
    air_share = 1 - liquid
    crac_cooling = hvac["crac_cooling_w"] * air_share
    compressor = compressor * air_share
    ct_fan = hvac["ct_fan_w"] * air_share
    liquid_overhead = ite * liquid * D.value("liquid_cooling", "overhead_fraction_of_it")
    if patches.include_auxiliaries:
        crac_fan = hvac["crac_fan_w"] * params.geometry.n_halls
        pumps = (hvac["cw_pump_w"] + hvac["ct_pump_w"]) * params.geometry.n_halls
    else:
        crac_fan = pumps = np.zeros(STEPS)
    cooling = compressor + ct_fan + crac_fan + pumps + liquid_overhead

    if params.cooling.type != "liquid" and params.geometry.kw_per_rack > D.value("thermal", "air_density_warning_kw_per_rack"):
        warnings.append(f"{_fr(params.geometry.kw_per_rack)} kW/rack en refroidissement air : au-delà du domaine usuel.")

    # --- pertes électriques
    ups = D.value("electrical", "ups_efficiency")
    transformer = D.value("electrical", "transformer_efficiency")
    losses = ite * (1 / ups - 1) + (ite / ups + cooling) * (1 / transformer - 1)
    facility = ite + cooling + losses
    facility_mw = facility / 1e6

    # --- batterie
    signal = price if params.battery.strategy == "price" else carbon.values
    rte = params.battery.round_trip_efficiency or D.value("battery", "round_trip_efficiency")
    bat = dispatch(facility_mw, signal, params.battery.power_mw, params.battery.energy_mwh, rte,
                   D.value("battery", "soc_min"), D.value("battery", "soc_max"), params.grid_capacity_mw)
    if params.battery.energy_mwh > 0 and bat.cycles == 0:
        if np.all(facility_mw >= params.grid_capacity_mw):
            warnings.append("Batterie inactive : aucune marge sous la capacité réseau pour la recharger.")
        elif np.ptp(signal) <= 1e-9:
            warnings.append("Batterie inactive : signal de pilotage constant (tarif plat ?).")
        else:
            warnings.append("Batterie inactive.")
    grid_mw = facility_mw + bat.charge_mw - bat.discharge_mw

    # --- agrégats
    def mwh(w):
        return float(np.sum(w) * STEP_H / 1e6)

    grid_mwh_steps = grid_mw * STEP_H
    energy_cost = float(np.sum(price * grid_mwh_steps))
    overload_h = float(np.sum(grid_mw > params.grid_capacity_mw + 1e-9) * STEP_H)
    if overload_h > 0:
        warnings.append(f"Appel réseau supérieur à la capacité de raccordement pendant {_fr(overload_h, 0)} h.")

    water_heat_l = (crac_cooling + compressor) * STEP_H / 1000 * 3600 / D.value("water", "latent_heat_kj_per_kg")
    coc = D.value("water", "cycles_of_concentration")
    water_heat_m3 = float(np.sum(water_heat_l) * (1 + 1 / (coc - 1) + D.value("water", "drift_rate")) / 1000)
    water_vendor_m3 = float(np.sum(P.vendor_water_usage_l_per_step(avg_return, setpoint, weather.wet_bulb)) / 1000)
    if not patches.water_heat_based:
        warnings.append("Eau : formule SustainDC brute, indépendante de la charge.")

    inlet_by_class = {name: float(P.rack_inlet_temp(rack, setpoint))
                      for name, rack in zip(("edge", "inner"), racks)}
    lo, hi = D.value("thermal", "ashrae_recommended_inlet_c")
    inlet_ok = all(lo <= t <= hi for t in inlet_by_class.values())
    if not inlet_ok:
        warnings.append(f"Température d'entrée des racks hors plage ASHRAE recommandée ({lo}–{hi} °C).")
    weights = np.array([r.count for r in racks], dtype=float)
    outlet = sum(w * np.broadcast_to(c["outlet"], (STEPS,)) for w, c in zip(weights, per_class)) / weights.sum()
    load_factor = np.where(ct_rated > 0, hvac["crac_cooling_w"] / ct_rated, 0.0)

    it_mwh, facility_mwh = mwh(ite), mwh(facility)
    hourly_grid = grid_mw.reshape(8760, 4).mean(axis=1)
    flows_series = {"grid": grid_mw, "it": ite / 1e6, "cooling": cooling / 1e6, "losses": losses / 1e6,
                    "battery_charge": bat.charge_mw, "battery_discharge": bat.discharge_mw,
                    "compressor": compressor / 1e6}

    results = TwinResults(
        engine_version=ENGINE_VERSION,
        params_hash=params.cache_key(ENGINE_VERSION),
        duration_s=0.0,
        it_capacity_mw=params.geometry.it_capacity_mw,
        n_racks=params.geometry.n_racks,
        servers_per_rack=n_servers,
        energy=EnergyBreakdown(
            it_mwh=it_mwh, cooling_mwh=mwh(cooling), losses_mwh=mwh(losses), facility_mwh=facility_mwh,
            battery_charge_mwh=float(bat.charge_mw.sum() * STEP_H),
            battery_discharge_mwh=float(bat.discharge_mw.sum() * STEP_H),
            battery_losses_mwh=bat.losses_mwh, grid_mwh=float(grid_mwh_steps.sum()),
            compressor_mwh=mwh(compressor), cooling_tower_fan_mwh=mwh(ct_fan), crac_fan_mwh=mwh(crac_fan),
            pumps_mwh=mwh(pumps), liquid_overhead_mwh=mwh(liquid_overhead)),
        pue_annual=facility_mwh / it_mwh,
        pue_monthly=[f / i for f, i in zip(_monthly(facility, month), _monthly(ite, month))],
        peak_facility_mw=float(facility_mw.max()),
        peak_grid_mw=float(grid_mw.max()),
        grid_capacity_mw=params.grid_capacity_mw,
        grid_overload_hours=overload_h,
        water_m3=water_heat_m3 if patches.water_heat_based else water_vendor_m3,
        water_m3_vendor_formula=water_vendor_m3,
        co2_t=float(np.sum(carbon.values * grid_mwh_steps) / 1000),
        energy_cost_usd=energy_cost,
        effective_price_usd_per_mwh=energy_cost / float(grid_mwh_steps.sum()),
        battery_cycles=bat.cycles,
        monthly_it_mwh=[v * STEP_H / 1e6 for v in _monthly(ite, month)],
        monthly_facility_mwh=[v * STEP_H / 1e6 for v in _monthly(facility, month)],
        monthly_grid_mwh=_monthly(grid_mwh_steps, month),
        monthly_energy_cost_usd=_monthly(price * grid_mwh_steps, month),
        hourly_grid_mw=hourly_grid.round(6).tolist(),
        hourly_price_usd_per_mwh=price_h.round(6).tolist(),
        thermal=Thermal(
            rack_inlet_c=inlet_by_class, rack_outlet_mean_c=float(outlet.mean()), rack_outlet_max_c=float(outlet.max()),
            ashrae_recommended_c=(lo, hi), inlet_within_ashrae=inlet_ok, rack_delta_floor_share=floor_share,
            chiller_rated_cooling_mw=ct_rated / 1e6, chiller_load_factor_mean=float(load_factor.mean()),
            chiller_load_factor_monthly=_monthly(load_factor, month, how="mean"), sizing_ambient_c=sizing_ambient),
        flows_mw=Flows(mean={k: float(v.mean()) for k, v in flows_series.items()},
                       peak={k: float(v.max()) for k, v in flows_series.items()}),
        capex=compute_capex(params),
        provenance=provenance,
        warnings=warnings,
    )
    results.duration_s = time.perf_counter() - t0
    return results


def run_year(params: TwinParams, use_cache: bool = True) -> TwinResults:
    """Simule une année ; résultats mis en cache par hash des paramètres et journalisés."""
    key = params.cache_key(ENGINE_VERSION)
    if use_cache:
        cached = _memory_cache.get(key) or _read_disk_cache(key)
        if cached is not None:
            _memory_cache[key] = cached
            return cached.model_copy(update={"from_cache": True})
    t0 = time.perf_counter()
    results = simulate(params)
    results.duration_s = time.perf_counter() - t0
    _memory_cache[key] = results
    _write_disk_cache(key, results)
    log_scenario(params, results)
    return results


def _read_disk_cache(key: str) -> TwinResults | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return TwinResults.model_validate_json(path.read_text())
    except ValueError:
        return None


def _write_disk_cache(key: str, results: TwinResults) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / f"{key}.json.tmp"
    tmp.write_text(results.model_dump_json())
    tmp.replace(CACHE_DIR / f"{key}.json")


SUMMARY_FIELDS = ("it_capacity_mw", "pue_annual", "peak_grid_mw", "water_m3", "co2_t", "energy_cost_usd",
                  "effective_price_usd_per_mwh", "battery_cycles")


def log_scenario(params: TwinParams, results: TwinResults) -> None:
    """Journal JSONL de chaque simulation : paramètres, durée, sorties principales."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "physics",
        "params_hash": results.params_hash,
        "engine_version": results.engine_version,
        "duration_s": round(results.duration_s, 4),
        "params": params.model_dump(mode="json"),
        "outputs": {f: getattr(results, f) for f in SUMMARY_FIELDS}
        | {"it_mwh": results.energy.it_mwh, "cooling_mwh": results.energy.cooling_mwh,
           "facility_mwh": results.energy.facility_mwh, "capex_total_usd": results.capex.total_usd},
        "warnings": results.warnings,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info("scénario %s simulé en %.3f s", results.params_hash, results.duration_s)
