"""Batterie pilotée par une règle déterministe (pas de RL).

Chaque jour, la batterie se charge sur les pas de 15 min où le signal (prix ou
intensité carbone) est le plus bas et se décharge sur ceux où il est le plus haut.
Elle écrête aussi la pointe au-delà de la capacité de raccordement.

On n'utilise pas envs/battery_model.Battery2 : sa décharge multiplie par
l'efficacité au lieu de diviser (convention qui crée de l'énergie quand eff_d < 1).
Voir docs/vendor_patches.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

STEP_H = 0.25
STEPS_PER_DAY = 96


@dataclass
class BatteryResult:
    charge_mw: np.ndarray      # puissance soutirée au réseau pour charger
    discharge_mw: np.ndarray   # puissance fournie au site
    soc_mwh: np.ndarray
    cycles: float
    losses_mwh: float


def dispatch(facility_mw: np.ndarray, signal: np.ndarray, power_mw: float, energy_mwh: float,
             round_trip_efficiency: float, soc_min: float, soc_max: float,
             grid_capacity_mw: float) -> BatteryResult:
    n = len(facility_mw)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    soc = np.zeros(n)
    if power_mw <= 0 or energy_mwh <= 0:
        return BatteryResult(charge, discharge, soc, 0.0, 0.0)

    eta = math.sqrt(round_trip_efficiency)
    e_min, e_max = soc_min * energy_mwh, soc_max * energy_mwh
    usable = e_max - e_min
    n_charge = min(STEPS_PER_DAY // 2, math.ceil(usable / (power_mw * eta) / STEP_H))
    n_discharge = min(STEPS_PER_DAY // 2, math.ceil(usable * eta / power_mw / STEP_H))

    plan = np.zeros(n, dtype=np.int8)  # +1 charge, -1 décharge
    for start in range(0, n, STEPS_PER_DAY):
        day = signal[start:start + STEPS_PER_DAY]
        if np.ptp(day) <= 1e-9:
            continue
        order = np.argsort(day, kind="stable")
        plan[start + order[:n_charge]] = 1
        plan[start + order[::-1][:n_discharge]] = -1

    stored = e_min
    delivered = 0.0
    for k in range(n):
        load = facility_mw[k]
        overload = load - grid_capacity_mw
        if overload > 0 or plan[k] == -1:
            want = power_mw if plan[k] == -1 else 0.0
            want = min(max(want, overload), power_mw, load)
            p = min(want, max(stored - e_min, 0.0) * eta / STEP_H)
            discharge[k] = p
            stored -= p * STEP_H / eta
            delivered += p * STEP_H
        elif plan[k] == 1:
            headroom = max(grid_capacity_mw - load, 0.0)
            p = min(power_mw, headroom, max(e_max - stored, 0.0) / (eta * STEP_H))
            charge[k] = p
            stored += p * eta * STEP_H
        soc[k] = stored
    losses = charge.sum() * STEP_H - delivered - (stored - e_min)
    return BatteryResult(charge, discharge, soc, delivered / energy_mwh, losses)
