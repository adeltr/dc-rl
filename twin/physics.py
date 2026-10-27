"""Port vectorisé (numpy, sur toute l'année) des équations SustainDC.

Chaque fonction reproduit à l'identique une fonction de vendor/sustaindc :

- ``server_power``         <- ``Rack.compute_instantaneous_pwr_vecd`` (envs/datacenter.py)
- ``rack_outlet_temp``     <- ``DataCenter_ITModel.compute_datacenter_IT_load_outlet_temp``
- ``chiller_power``        <- ``calculate_chiller_power``
- ``hvac_power``           <- ``calculate_HVAC_power``
- ``chiller_sizing``       <- ``chiller_sizing`` (appelé par utils/make_envs_pyenv.py)
- ``vendor_water_usage``   <- ``DataCenter_ITModel.calculate_cooling_tower_water_usage``

La boucle Python de SustainDC (une itération par pas de 15 min et par rack) coûte
~1 s par rack et par an. Ici, les racks identiques sont regroupés en classes et le
temps est vectorisé ; le test tests/test_vendor_parity.py vérifie l'égalité avec
l'environnement Gymnasium d'origine.

Les corrections du jumeau (COP, auxiliaires, eau, free cooling, liquide) ne sont pas
ici : elles sont appliquées dans twin/engine.py et documentées dans docs/vendor_patches.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Constantes codées en dur dans envs/datacenter.py
RACK_M_COEFFICIENT = 10
RACK_C_COEFFICIENT = 5
RACK_IT_SLOPE = 20
OUTLET_C, OUTLET_D, OUTLET_E, OUTLET_F, OUTLET_G = 1.918, 1.096, 0.824, 0.526, -14.01
SUPPLY_APPROACH_CLAMP = (3.8, 5.3)
VENDOR_RATED_COP = 3.0  # rated_cop dans calculate_chiller_power
# Bornes de consigne codées dans make_dc_pyeplus_env
SETPOINT_MIN, SETPOINT_MAX = 15.0, 21.6
# Table de dimensionnement de make_dc_pyeplus_env (température extérieure max, °C)
VENDOR_SIZING_AMBIENT = {"NY": 30.0, "AZ": 50.0, "WA": 20.0}
VENDOR_SIZING_DEFAULT = 50.0


@dataclass(frozen=True)
class PhysicsConfig:
    """Sous-ensemble de utils/dc_config.json utilisé par les équations."""

    c_air: float
    rho_air: float
    crac_supply_air_flow_rate_pu: float
    crac_reference_air_flow_rate_pu: float
    crac_fan_ref_p: float
    cw_pressure_drop: float
    cw_water_flow_rate: float
    cw_pump_efficiency: float
    ct_pressure_drop: float
    ct_water_flow_rate: float
    ct_pump_efficiency: float
    cpu_power_ratio_lb: tuple[float, float]
    cpu_power_ratio_ub: tuple[float, float]
    it_fan_airflow_ratio_lb: tuple[float, float]
    it_fan_airflow_ratio_ub: tuple[float, float]
    it_fan_full_load_v: float
    itfan_ref_v_ratio: float
    itfan_ref_p: float
    inlet_temp_range: tuple[float, float]

    @classmethod
    def from_vendor_json(cls, cfg: dict) -> "PhysicsConfig":
        h, s = cfg["hvac_configuration"], cfg["server_characteristics"]
        return cls(
            c_air=h["C_AIR"],
            rho_air=h["RHO_AIR"],
            crac_supply_air_flow_rate_pu=h["CRAC_SUPPLY_AIR_FLOW_RATE_pu"],
            crac_reference_air_flow_rate_pu=h["CRAC_REFRENCE_AIR_FLOW_RATE_pu"],
            crac_fan_ref_p=h["CRAC_FAN_REF_P"],
            cw_pressure_drop=h["CW_PRESSURE_DROP"],
            cw_water_flow_rate=h["CW_WATER_FLOW_RATE"],
            cw_pump_efficiency=h["CW_PUMP_EFFICIENCY"],
            ct_pressure_drop=h["CT_PRESSURE_DROP"],
            ct_water_flow_rate=h["CT_WATER_FLOW_RATE"],
            ct_pump_efficiency=h["CT_PUMP_EFFICIENCY"],
            cpu_power_ratio_lb=tuple(s["CPU_POWER_RATIO_LB"]),
            cpu_power_ratio_ub=tuple(s["CPU_POWER_RATIO_UB"]),
            it_fan_airflow_ratio_lb=tuple(s["IT_FAN_AIRFLOW_RATIO_LB"]),
            it_fan_airflow_ratio_ub=tuple(s["IT_FAN_AIRFLOW_RATIO_UB"]),
            it_fan_full_load_v=s["IT_FAN_FULL_LOAD_V"],
            itfan_ref_v_ratio=s["ITFAN_REF_V_RATIO"],
            itfan_ref_p=s["ITFAN_REF_P"],
            inlet_temp_range=tuple(s["INLET_TEMP_RANGE"]),
        )


@dataclass(frozen=True)
class RackClass:
    """Groupe de racks identiques (même approche de soufflage/reprise, mêmes serveurs)."""

    count: int
    servers_per_rack: float
    supply_approach: float
    return_approach: float


def server_power(cfg: PhysicsConfig, full_load_w: float, idle_w: float, inlet_temp, load_pct):
    """Puissance CPU, puissance ventilateur et débit ventilateur d'UN serveur.

    ``load_pct`` en % (0–100), scalaire ou tableau. Reproduit CPU.cpu_curve1,
    CPU.itfan_curve2 et Rack.compute_instantaneous_pwr_vecd.
    """
    t0, t1 = cfg.inlet_temp_range
    m_cpu = (cfg.cpu_power_ratio_ub[0] - cfg.cpu_power_ratio_lb[0]) / (t1 - t0)
    c_cpu = cfg.cpu_power_ratio_ub[0] - m_cpu * t1
    shift_cpu = cfg.cpu_power_ratio_lb[1] - cfg.cpu_power_ratio_lb[0]
    m_fan = (cfg.it_fan_airflow_ratio_ub[0] - cfg.it_fan_airflow_ratio_lb[0]) / (t1 - t0)
    c_fan = cfg.it_fan_airflow_ratio_ub[0] - m_fan * t1
    shift_fan = cfg.it_fan_airflow_ratio_lb[1] - cfg.it_fan_airflow_ratio_lb[0]

    load_pct = np.asarray(load_pct, dtype=float)
    base_cpu_ratio = (m_cpu + 0.05) * inlet_temp + c_cpu
    cpu_ratio = base_cpu_ratio + shift_cpu * (load_pct / 100)
    cpu_w = np.maximum(idle_w, full_load_w * cpu_ratio)

    base_fan_v_ratio = m_fan * RACK_M_COEFFICIENT * inlet_temp + c_fan * RACK_C_COEFFICIENT
    fan_v_ratio = base_fan_v_ratio + shift_fan * (load_pct / RACK_IT_SLOPE)
    fan_w = cfg.itfan_ref_p * (fan_v_ratio / cfg.itfan_ref_v_ratio)
    fan_v = cfg.it_fan_full_load_v * fan_v_ratio
    return cpu_w, fan_w, fan_v


def clamp_supply_approach(value: float) -> float:
    return max(SUPPLY_APPROACH_CLAMP[0], min(value, SUPPLY_APPROACH_CLAMP[1]))


def rack_inlet_temp(rack: RackClass, setpoint: float) -> float:
    return clamp_supply_approach(rack.supply_approach) + setpoint


def rack_outlet_temp(cfg: PhysicsConfig, inlet_temp, rack_power_w, rack_fan_v):
    power_term = rack_power_w**OUTLET_D
    airflow_term = cfg.c_air * cfg.rho_air * rack_fan_v**OUTLET_E * OUTLET_F
    return inlet_temp + OUTLET_C * power_term / airflow_term + OUTLET_G


def it_model(cfg: PhysicsConfig, racks: list[RackClass], full_load_w: float, idle_w: float,
             setpoint: float, load_pct, min_rack_delta: float | None = None):
    """Puissance IT totale (W), ventilateurs IT (W) et température moyenne de reprise CRAC.

    Retourne aussi, par classe, les températures d'entrée et de sortie des racks.
    ``min_rack_delta`` : plancher de ΔT sortie − entrée (°C). Le vendor lève une
    exception sous 2 °C ; ``None`` reproduit le calcul vendor sans plancher.
    """
    load_pct = np.asarray(load_pct, dtype=float)
    total_cpu = np.zeros_like(load_pct)
    total_fan = np.zeros_like(load_pct)
    return_sum = np.zeros_like(load_pct)
    n_racks = 0
    per_class = []
    for rack in racks:
        inlet = rack_inlet_temp(rack, setpoint)
        cpu_w, fan_w, fan_v = server_power(cfg, full_load_w, idle_w, inlet, load_pct)
        rack_cpu, rack_fan = rack.servers_per_rack * cpu_w, rack.servers_per_rack * fan_w
        rack_v = rack.servers_per_rack * fan_v
        raw_outlet = rack_outlet_temp(cfg, inlet, rack_cpu + rack_fan, rack_v)
        outlet = raw_outlet if min_rack_delta is None else np.maximum(raw_outlet, inlet + min_rack_delta)
        total_cpu = total_cpu + rack.count * rack_cpu
        total_fan = total_fan + rack.count * rack_fan
        return_sum = return_sum + rack.count * (rack.return_approach + outlet)
        n_racks += rack.count
        per_class.append({"inlet": inlet, "outlet": outlet, "delta": outlet - inlet,
                          "clamped": np.asarray(raw_outlet < outlet)})
    return total_cpu, total_fan, return_sum / n_racks, per_class


def chiller_power(max_cooling_cap, load, ambient_temp):
    """Puissance compresseur (W), courbe EnergyPlus « electric chiller » du vendor."""
    load = np.asarray(load, dtype=float)
    ambient_temp = np.asarray(ambient_temp, dtype=float)
    cap_c = (0.94483600, -0.05700880, 0.00185486)
    pow_c = (2.333, -1.975, 0.6121)
    flf = (0.03303, 0.6852, 0.2818)
    min_plr, max_plr = 0.05, 1.0
    design_cond_temp, design_evp_out_temp, temp_rise_coef = 35.0, 6.67, 2.778

    delta_temp = (ambient_temp - design_cond_temp) / temp_rise_coef - (design_evp_out_temp - design_cond_temp)
    avail_rat = cap_c[0] + cap_c[1] * delta_temp + cap_c[2] * delta_temp**2
    available = np.where(avail_rat != 0, max_cooling_cap * avail_rat, 0.0)
    full_power_ratio = pow_c[0] + pow_c[1] * avail_rat + pow_c[2] * avail_rat**2
    positive = available > 0
    safe_avail = np.where(positive, available, 1.0)
    ratio = load / safe_avail
    plr = np.where(positive, np.maximum(min_plr, np.minimum(ratio, max_plr)), 0.0)
    frac_full = flf[0] + flf[1] * plr + flf[2] * plr**2
    oper = np.where(positive, np.where(ratio < min_plr, ratio, plr), 0.0)
    frac = np.where(oper < min_plr, np.minimum(1.0, oper / min_plr), 1.0)
    power = frac_full * full_power_ratio * available / VENDOR_RATED_COP * frac
    return np.where(oper > 0, power, 0.0)


def hvac_power(cfg: PhysicsConfig, setpoint: float, avg_return_temp, ambient_temp, ite_w,
               ct_rated_load: float, ctafr: float):
    """Charges CVC (W) : ventilateur CRAC, ventilateur de tour, charge CRAC, compresseur, pompes."""
    ambient_temp = np.asarray(ambient_temp, dtype=float)
    m_sys = cfg.rho_air * cfg.crac_supply_air_flow_rate_pu * ite_w
    crac_cooling = m_sys * cfg.c_air * np.maximum(0.0, avg_return_temp - setpoint)
    crac_fan = cfg.crac_fan_ref_p * (cfg.crac_supply_air_flow_rate_pu / cfg.crac_reference_air_flow_rate_pu) ** 3
    compressor = chiller_power(ct_rated_load, crac_cooling, ambient_temp)
    cw_pump = cfg.cw_pressure_drop * cfg.cw_water_flow_rate / cfg.cw_pump_efficiency
    ct_pump = cfg.ct_pressure_drop * cfg.ct_water_flow_rate / cfg.ct_pump_efficiency
    air_delta = np.maximum(50 - (ambient_temp - setpoint), 1)
    v_air = crac_cooling / (cfg.c_air * air_delta) / cfg.rho_air
    ct_fan = np.where(ambient_temp < 5, 0.0, ct_rated_load * np.minimum(v_air / ctafr, 1) ** 3)
    return {
        "crac_fan_w": np.full_like(crac_cooling, crac_fan),
        "ct_fan_w": ct_fan,
        "crac_cooling_w": crac_cooling,
        "compressor_w": compressor,
        "cw_pump_w": np.full_like(crac_cooling, cw_pump),
        "ct_pump_w": np.full_like(crac_cooling, ct_pump),
    }


def chiller_sizing(cfg: PhysicsConfig, racks: list[RackClass], full_load_w: float, idle_w: float,
                   max_ambient_temp: float, min_setpoint: float = SETPOINT_MIN,
                   max_setpoint: float = SETPOINT_MAX, min_rack_delta: float | None = None):
    """Dimensionnement tour/chiller au pire cas, comme make_dc_pyeplus_env."""
    cpu, fan, avg_return, _ = it_model(cfg, racks, full_load_w, idle_w, max_setpoint, 100.0, min_rack_delta)
    ite = float(cpu + fan)
    m_sys = cfg.rho_air * cfg.crac_supply_air_flow_rate_pu * ite
    crac_cooling = m_sys * cfg.c_air * max(0.0, float(avg_return) - min_setpoint)
    air_delta = max(50 - (max_ambient_temp - min_setpoint), 1)
    ctafr = crac_cooling / (cfg.c_air * air_delta) / cfg.rho_air
    return ctafr, crac_cooling


def vendor_water_usage_l_per_step(avg_return_temp, setpoint: float, wet_bulb):
    """Eau de tour du vendor (L par pas de 15 min) — indépendante de la charge."""
    range_temp = avg_return_temp - setpoint
    y_intercept = 0.3528 * range_temp + 0.101
    usage = np.clip(0.044 * np.asarray(wet_bulb, dtype=float) + y_intercept, 0, None)
    usage = usage + usage * 0.01
    return np.round(usage * 1000 / 4, 4)


def interpolate_hourly(values_8760) -> np.ndarray:
    """Passage horaire -> 15 min, identique aux managers SustainDC."""
    values = np.asarray(values_8760, dtype=float)
    x = np.arange(len(values))
    x_new = np.linspace(0, len(values), len(values) * 4)
    return np.interp(x_new, x, values)
