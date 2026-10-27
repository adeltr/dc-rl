"""Surrogate financier pour l'aperçu instantané (valeurs « provisoires »).

La physique est exacte et rapide (< 0,4 s). Le maillon lent est le classeur (≈ 1–2 s avec le
solveur d'equity). Le surrogate linéarise les sorties du classeur autour du cas de base, par
groupes d'entrées ``tw_*`` qui varient ensemble dans ``bridge/mapping.py`` : une simulation
complète du classeur par groupe, précalculée en tâche de fond de faible priorité.

Groupes « log » : dérivée par unité de ln(valeur / base) (produits IT × PUE × tarif exacts au
premier ordre). Groupes « abs » : dérivée par unité d'entrée (différence finie de pas ``step``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.optimize import brentq

from bridge.bridge import MONTHLY_NAMES, SCALAR_NAMES, SERIES_NAMES, WorkbookResults
from bridge.mapping import CAPEX_KEYS, OPEX_INDEX_NAMES
from bridge.spec import TENANT_ROWS

LOG_STEP = 0.05
TENANTS = range(1, len(TENANT_ROWS) + 1)
BUILDING_LINES = ["tw_capex_sitework", "tw_capex_concrete_structure", "tw_capex_envelope", "tw_capex_raised_floor",
                  "tw_capex_fire_protection", "tw_capex_security", "tw_capex_interior_finishes"]


@dataclass(frozen=True)
class Group:
    name: str
    inputs: tuple[str, ...]
    mode: str          # "log" ou "abs"
    step: float


GROUPS = [
    Group("tenant_kw", tuple(f"tw_tenant_kw_{i}" for i in TENANTS), "log", LOG_STEP),
    Group("absorption", tuple(f"tw_absorption_kw_month_{i}" for i in TENANTS), "log", LOG_STEP),
    Group("space", tuple(f"tw_whitespace_sf_{i}" for i in TENANTS) + ("tw_gross_sf",), "log", LOG_STEP),
    Group("rent", tuple(f"tw_rent_{i}" for i in TENANTS), "log", LOG_STEP),
    Group("rent_growth", tuple(f"tw_rent_growth_{i}" for i in TENANTS), "abs", 0.005),
    Group("pue", ("tw_pue",), "log", LOG_STEP),
    Group("utilities_rate", ("tw_utilities_rate",), "log", LOG_STEP),
    Group("idx_energy", ("tw_idx_energy",), "abs", 0.005),
    Group("idx_opex", OPEX_INDEX_NAMES, "abs", 0.005),
    Group("capex_building", tuple(BUILDING_LINES), "log", LOG_STEP),
    Group("capex_mechanical", ("tw_capex_mechanical",), "log", LOG_STEP),
    Group("capex_electrical", ("tw_capex_electrical",), "log", LOG_STEP),
    Group("capex_grid", ("tw_capex_grid",), "log", LOG_STEP),
    Group("capex_battery", ("tw_capex_battery",), "abs", 1e7),
    Group("capex_soft", ("tw_capex_contingency", "tw_capex_dev_fee"), "log", LOG_STEP),
    Group("discount_rate", ("tw_discount_rate",), "abs", 0.01),
    Group("perm_debt", ("tw_perm_debt",), "abs", 1.0),
]
assert set(CAPEX_KEYS.values()) <= {n for g in GROUPS for n in g.inputs}


def flatten(result: WorkbookResults) -> dict[str, float | None]:
    out = {name: result.outputs.get(name) for name in SCALAR_NAMES}
    for name in SERIES_NAMES:
        for i, value in enumerate(result.series[name]):
            out[f"{name}[{i}]"] = value
    for name in MONTHLY_NAMES:
        for i, value in enumerate(result.monthly[name]):
            out[f"{name}[{i}]"] = value
    return {k: (float(v) if isinstance(v, (int, float)) else None) for k, v in out.items()}


def _xnpv(rate: float, flows: list[float], dates: list[float]) -> float:
    return sum(cf / (1 + rate) ** ((d - dates[0]) / 365) for cf, d in zip(flows, dates))


def _xirr(flows: list[float], dates: list[float]) -> float | None:
    try:
        return brentq(lambda r: _xnpv(r, flows, dates), -0.99, 10.0, xtol=1e-12, maxiter=200)
    except ValueError:  # pas de changement de signe : TRI indéfini
        return None


def metrics_from_flows(values: dict[str, float | None], discount_rate: float) -> dict[str, float | None]:
    """TRI, VAN, multiples et profits recalculés comme J229/J230, I229/I230, K229/K230."""
    end = int(values["out_analysis_end_month"])
    start = 1 if values["out_month0_uses"] == 0 else 0
    months = range(start, end + 1)
    dates = [values[f"out_cfm_dates[{m}]"] for m in months]
    out = {}
    for kind, irr, em, profit, npv in (("unlevered", "out_irr_project", "out_em_unlevered", "out_profit_unlevered", "out_npv"),
                                       ("levered", "out_irr_equity", "out_em_levered", "out_profit_levered", "out_npv_equity")):
        row = [values.get(f"out_cfm_{kind}[{m}]") for m in range(133)]
        flows = [row[m] for m in months]
        if any(v is None for v in flows + dates):
            continue
        numbers = [v for v in row if v is not None]
        negatives = -sum(v for v in numbers if v < 0)
        out[irr] = _xirr(flows, dates)
        out[em] = sum(v for v in numbers if v > 0) / negatives if negatives else None
        out[profit] = sum(numbers)
        out[npv] = _xnpv(discount_rate, flows, dates)
    return out


class FinanceSurrogate:
    def __init__(self, base_inputs: dict[str, float], base: WorkbookResults, context: dict):
        self.base_inputs = dict(base_inputs)
        self.base = flatten(base)
        self.years = base.years
        self.context = context
        self.derivatives: dict[str, dict[str, float]] = {}
        self.anchors: dict[str, dict[str, float | None]] = {}  # sorties perturbées brutes

    @property
    def ready(self) -> bool:
        return len(self.derivatives) == len(GROUPS)

    @property
    def progress(self) -> float:
        return len(self.derivatives) / len(GROUPS)

    def perturbed_inputs(self, group: Group) -> dict[str, float]:
        inputs = dict(self.base_inputs)
        for name in group.inputs:
            if group.mode == "log":
                inputs[name] = self.base_inputs[name] * math.exp(group.step)
            else:
                inputs[name] = self.base_inputs[name] + group.step
        if group.name == "capex_battery":
            inputs["tw_capex_battery_start"] = self.context["D46"]
            inputs["tw_capex_battery_end"] = self.context["E46"]
        return inputs

    def add(self, group: Group, perturbed: WorkbookResults) -> None:
        values = flatten(perturbed)
        self.anchors[group.name] = values
        self.derivatives[group.name] = {
            k: (values[k] - self.base[k]) / group.step for k in self.base
            if values.get(k) is not None and self.base[k] is not None}

    def coordinates(self, inputs: dict[str, float]) -> dict[str, float]:
        coords = {}
        for group in GROUPS:
            terms = []
            for name in group.inputs:
                base, new = self.base_inputs[name], inputs.get(name, self.base_inputs[name])
                if group.mode == "log":
                    if base > 0 and new > 0:
                        terms.append(math.log(new / base))
                else:
                    terms.append(new - base)  # même unité que la dérivée (par unité d'entrée)
            coords[group.name] = sum(terms) / len(terms) if terms else 0.0
        return coords

    def estimate(self, inputs: dict[str, float]) -> tuple[dict[str, float | None], dict[str, list[float | None]]]:
        coords = self.coordinates(inputs)
        values: dict[str, float | None] = {}
        for key, base in self.base.items():
            if base is None:  # ex. DSCR sans dette permanente : valeur de l'ancre si le groupe est activé
                anchor = self.anchors.get("perm_debt", {}).get(key)
                values[key] = anchor if coords.get("perm_debt", 0) >= 0.5 else None
                continue
            values[key] = base + sum(t * self.derivatives[g].get(key, 0.0)
                                     for g, t in coords.items() if t and g in self.derivatives)
        scalars = {name: values[name] for name in SCALAR_NAMES}
        # TRI & co : recalculés sur les flux mensuels estimés (le TRI est trop non linéaire)
        scalars.update(metrics_from_flows(values, inputs.get("tw_discount_rate", self.base_inputs["tw_discount_rate"])))
        series = {name: [values.get(f"{name}[{i}]") for i in range(len(self.years))] for name in SERIES_NAMES}
        return scalars, series
