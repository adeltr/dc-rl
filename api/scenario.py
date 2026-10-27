"""Scénario = paramètres du jumeau + hypothèses marché ; accès par chemins pointés."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bridge.mapping import MarketAssumptions
from twin import defaults as D
from twin.params import TwinParams


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: TwinParams = Field(default_factory=TwinParams)
    market: MarketAssumptions = Field(default_factory=MarketAssumptions)

    def key(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def base_scenario() -> ScenarioInput:
    """Cas de base : défauts de defaults.yaml ; site surchargeable par TWIN_BASE_SITE."""
    params = TwinParams()
    site = os.environ.get("TWIN_BASE_SITE")
    if site:
        params = params.model_copy(update={"site_id": site})
    return ScenarioInput(params=params)


def get_path(obj: dict, path: str) -> Any:
    node: Any = obj
    for key in path.split("."):
        node = node[key]
    return node


def set_path(obj: dict, path: str, value: Any) -> dict:
    """Copie de ``obj`` avec ``path`` remplacé."""
    out = json.loads(json.dumps(obj))
    node = out
    keys = path.split(".")
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return out


def effective_values(scenario: ScenarioInput, manifest: dict) -> dict:
    """Scénario où chaque None est remplacé par la valeur réellement utilisée (classeur ou défaut)."""
    data = scenario.model_dump(mode="json")
    wb = {name: spec["value"] for name, spec in manifest["inputs"].items()}
    resolved = {
        "params.price.flat_usd_per_mwh": D.value("price", "flat_usd_per_mwh"),
        "params.cooling.liquid_fraction": D.value("liquid_cooling", "liquid_fraction"),
        "params.battery.round_trip_efficiency": D.value("battery", "round_trip_efficiency"),
        "market.rent_usd_per_kw_month": wb["tw_rent_1"],
        "market.rent_growth": wb["tw_rent_growth_1"],
        "market.idx_energy": wb["tw_idx_energy"],
        "market.idx_opex": wb["tw_idx_maintenance"],
        "market.discount_rate": wb["tw_discount_rate"],
        "market.perm_debt": bool(wb["tw_perm_debt"]),
    }
    for path, value in resolved.items():
        if get_path(data, path) is None:
            data = set_path(data, path, value)
    return data
