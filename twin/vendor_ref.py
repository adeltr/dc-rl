"""Simulation de référence avec l'environnement Gymnasium SustainDC d'origine.

Sert uniquement à valider le port vectorisé (tests/test_vendor_parity.py) : boucle
pas à pas sur ``dc_gymenv`` avec une consigne fixe (action 1 = delta 0).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from .vendor import ensure_vendor_path, vendor_dc_config


def write_vendor_config(rows: int, racks_per_row: int, servers_per_rack: int,
                        supply_approach: list[float], return_approach: list[float],
                        full_load_w: float, idle_w: float, directory: Path) -> Path:
    cfg = json.loads(json.dumps(vendor_dc_config()))
    n = rows * racks_per_row
    dc = cfg["data_center_configuration"]
    dc["NUM_ROWS"], dc["NUM_RACKS_PER_ROW"], dc["CPUS_PER_RACK"] = rows, racks_per_row, servers_per_rack
    dc["RACK_SUPPLY_APPROACH_TEMP_LIST"] = supply_approach
    dc["RACK_RETURN_APPROACH_TEMP_LIST"] = return_approach
    cfg["server_characteristics"]["DEFAULT_SERVER_POWER_CHARACTERISTICS"] = [[full_load_w, idle_w]] * n
    path = directory / "dc_config_twin_ref.json"
    path.write_text(json.dumps(cfg))
    return path


def run_vendor_reference(rows: int, racks_per_row: int, servers_per_rack: int,
                         supply_approach: list[float], return_approach: list[float],
                         full_load_w: float, idle_w: float, setpoint: float,
                         ambient: np.ndarray, wet_bulb: np.ndarray, load_frac: np.ndarray,
                         location: str = "NY") -> dict[str, np.ndarray]:
    ensure_vendor_path()
    from utils.make_envs_pyenv import make_dc_pyeplus_env

    with tempfile.TemporaryDirectory() as tmp:
        path = write_vendor_config(rows, racks_per_row, servers_per_rack, supply_approach,
                                   return_approach, full_load_w, idle_w, Path(tmp))
        # Capacité assez haute pour que MAX_W_PER_RACK ne retire aucun serveur
        capacity_mw = rows * racks_per_row * servers_per_rack * full_load_w * 4 / 1e6
        env, _ = make_dc_pyeplus_env(month=1, location=location, datacenter_capacity_mw=capacity_mw,
                                     dc_config_file=str(path), add_cpu_usage=False, use_ls_cpu_load=True)
    env.reset()
    env.raw_curr_stpt = setpoint
    keys = ["dc_ITE_total_power_kW", "dc_CT_total_power_kW", "dc_Compressor_total_power_kW",
            "dc_HVAC_total_power_kW", "dc_total_power_kW", "dc_int_temperature", "dc_water_usage",
            "dc_CW_pump_power_kW", "dc_CT_pump_power_kW"]
    out = {k: np.empty(len(ambient)) for k in keys}
    for k in range(len(ambient)):
        env.set_ambient_temp(ambient[k], wet_bulb[k])
        env.set_shifted_wklds(float(load_frac[k]))
        _, _, _, _, info = env.step(1)
        for key in keys:
            out[key][k] = info[key]
    out["ct_rated_load_w"] = env.DC_Config.CT_FAN_REF_P
    out["ctafr"] = env.DC_Config.CT_REFRENCE_AIR_FLOW_RATE
    return out
