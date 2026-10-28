"""Traduction résultats du jumeau + hypothèses marché -> valeurs ``tw_*`` du classeur.

Mode ``absolute`` (par défaut) : le PUE et le coût d'énergie simulés sont écrits tels quels,
si bien que le cockpit et le classeur parlent du même PUE. Mode ``calibrated`` : le classeur
garde ses valeurs (PUE 1,5, 109,5 $/kW/mois) et varie du même rapport que la simulation.

Part fixe de l'énergie (E153) : par défaut, part de l'énergie simulée indépendante de la charge
(pertes fixes). Le classeur d'origine facture 100 % de l'énergie dès la mise en service, même
pour des salles non louées ; le reste suit ici la charge IT louée (ligne 114).

Taxe foncière (K159) : au prorata des coûts durs, au taux implicite du classeur par défaut.

``original_market(manifest)`` avec les paramètres de base du jumeau renvoie exactement les
valeurs du classeur d'origine : c'est la référence de non-régression.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from twin.results import TwinResults

from .spec import TENANT_ROWS

N_TENANTS = len(TENANT_ROWS)
CAPEX_KEYS = {
    "sitework": "tw_capex_sitework", "concrete_structure": "tw_capex_concrete_structure",
    "envelope": "tw_capex_envelope", "raised_floor": "tw_capex_raised_floor",
    "mechanical": "tw_capex_mechanical", "electrical": "tw_capex_electrical",
    "fire_protection": "tw_capex_fire_protection", "security": "tw_capex_security",
    "interior_finishes": "tw_capex_interior_finishes", "grid": "tw_capex_grid", "battery": "tw_capex_battery",
}
OPEX_INDEX_NAMES = ("tw_idx_maintenance", "tw_idx_staffing", "tw_idx_insurance", "tw_idx_property_tax")


class MarketAssumptions(BaseModel):
    """Panneau « Hypothèses marché ». None = valeur du classeur (ou défaut documenté)."""

    model_config = ConfigDict(extra="forbid")

    rent_usd_per_kw_month: float | None = Field(None, ge=0, le=2000)
    rent_growth: float | None = Field(None, ge=-0.1, le=0.2)
    absorption_multiplier: float = Field(1.0, gt=0, le=10, description="montée en occupation : × rythme d'absorption")
    carbon_price_usd_per_t: float = Field(0.0, ge=0, le=1000)
    water_price_usd_per_m3: float = Field(0.0, ge=0, le=50)
    idx_energy: float | None = Field(None, ge=-0.1, le=0.3)
    idx_opex: float | None = Field(None, ge=-0.1, le=0.3)
    discount_rate: float | None = Field(None, gt=0, le=0.5)
    perm_debt: bool | None = None
    dscr_covenant: float = Field(1.20, gt=0, le=5, description="alerte de l'interface uniquement")
    calibration: Literal["calibrated", "absolute"] = "absolute"
    utilities_fixed_share: float | None = Field(
        None, ge=0, le=1, description="part de l'énergie due même sans locataire ; None = part simulée")
    property_tax_rate: float | None = Field(
        None, ge=0, le=0.1, description="taxe foncière annuelle / coûts durs ; None = taux implicite du classeur")

    def is_original(self, manifest: dict) -> bool:
        """Hypothèses du classeur d'origine (au covenant d'affichage près)."""
        exclude = {"dscr_covenant"}
        return self.model_dump(exclude=exclude) == original_market(manifest).model_dump(exclude=exclude)


def original_market(manifest: dict) -> MarketAssumptions:
    """Hypothèses qui reproduisent le classeur d'origine : valeurs du classeur et part fixe d'origine."""
    return MarketAssumptions(calibration="calibrated",
                             utilities_fixed_share=manifest["inputs"]["tw_utilities_fixed"]["value"])


def implicit_property_tax_rate(manifest: dict) -> float:
    """Taxe foncière du classeur rapportée à ses coûts durs."""
    base = {name: spec["value"] for name, spec in manifest["inputs"].items()}
    return base["tw_property_tax"] / sum(base[name] for name in CAPEX_KEYS.values())


def workbook_inputs(twin: TwinResults, twin_base: TwinResults, market: MarketAssumptions,
                    manifest: dict) -> dict[str, float]:
    base = {name: spec["value"] for name, spec in manifest["inputs"].items()}
    inputs = dict(base)
    inputs["tw_memo_energy_cost"] = twin.energy_cost_usd
    water_cost = twin.water_m3 * market.water_price_usd_per_m3
    carbon_cost = twin.co2_t * market.carbon_price_usd_per_t
    inputs["tw_memo_water_cost"] = water_cost
    inputs["tw_memo_carbon_cost"] = carbon_cost
    if twin.params_hash == twin_base.params_hash and market.is_original(manifest):
        return inputs
    inputs["tw_utilities_fixed"] = (market.utilities_fixed_share if market.utilities_fixed_share is not None
                                    else twin.fixed_energy_share)

    # --- dimensionnement : charge IT et surfaces au prorata
    base_it_kw = sum(base[f"tw_tenant_kw_{i}"] for i in range(1, N_TENANTS + 1))
    it_kw = twin.it_capacity_mw * 1000
    scale_it = it_kw / base_it_kw
    scale_space = twin.n_racks / twin_base.n_racks
    for i in range(1, N_TENANTS + 1):
        inputs[f"tw_tenant_kw_{i}"] = base[f"tw_tenant_kw_{i}"] * scale_it
        inputs[f"tw_absorption_kw_month_{i}"] = base[f"tw_absorption_kw_month_{i}"] * scale_it * market.absorption_multiplier
        inputs[f"tw_whitespace_sf_{i}"] = base[f"tw_whitespace_sf_{i}"] * scale_space
        if market.rent_usd_per_kw_month is not None and base[f"tw_tenant_kw_{i}"] > 0:
            inputs[f"tw_rent_{i}"] = market.rent_usd_per_kw_month
        if market.rent_growth is not None and base[f"tw_tenant_kw_{i}"] > 0:
            inputs[f"tw_rent_growth_{i}"] = market.rent_growth
    inputs["tw_gross_sf"] = base["tw_gross_sf"] * scale_space

    # --- énergie : utilities = H153 × IT × PUE × 12
    base_pue = base["tw_pue"]
    base_utilities = base["tw_utilities_rate"] * base_it_kw * base_pue * 12
    if market.calibration == "calibrated":
        pue = base_pue * twin.pue_annual / twin_base.pue_annual
        energy = base_utilities * twin.energy_cost_usd / twin_base.energy_cost_usd
    else:
        pue = twin.pue_annual
        energy = twin.energy_cost_usd
    inputs["tw_pue"] = pue
    inputs["tw_utilities_rate"] = (energy + water_cost + carbon_cost) / (it_kw * pue * 12)
    if market.idx_energy is not None:
        inputs["tw_idx_energy"] = market.idx_energy
    if market.idx_opex is not None:
        for name in OPEX_INDEX_NAMES:
            inputs[name] = market.idx_opex

    # --- CAPEX : coûts unitaires du YAML (calés sur le classeur) × quantités du jumeau
    for line in twin.capex.lines:
        inputs[CAPEX_KEYS[line.key]] = line.amount_usd
    if inputs["tw_capex_battery"] > 0:
        inputs["tw_capex_battery_start"] = manifest["context"]["D46"]
        inputs["tw_capex_battery_end"] = manifest["context"]["E46"]
    hard_base = sum(base[name] for name in CAPEX_KEYS.values())
    hard_new = sum(inputs[name] for name in CAPEX_KEYS.values())
    inputs["tw_capex_contingency"] = base["tw_capex_contingency"] * hard_new / hard_base
    inputs["tw_capex_dev_fee"] = base["tw_capex_dev_fee"] * hard_new / hard_base
    # taxe foncière : suit la valeur des installations
    rate = market.property_tax_rate if market.property_tax_rate is not None else implicit_property_tax_rate(manifest)
    inputs["tw_property_tax"] = rate * hard_new

    # --- financement
    if market.perm_debt is not None:
        inputs["tw_perm_debt"] = 1.0 if market.perm_debt else 0.0
    if market.discount_rate is not None:
        inputs["tw_discount_rate"] = market.discount_rate
    return inputs
