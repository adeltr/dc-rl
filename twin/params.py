"""Paramètres d'entrée du jumeau (pydantic). La capacité IT est toujours dérivée."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from . import defaults as D
from .physics import SETPOINT_MAX, SETPOINT_MIN

CoolingType = Literal["air_chiller", "air_free_cooling", "liquid"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Geometry(_Model):
    n_halls: int = Field(default_factory=lambda: D.value("base_scenario", "n_halls"), ge=1, le=20)
    rows_per_hall: int = Field(default_factory=lambda: D.value("base_scenario", "rows_per_hall"), ge=1, le=100)
    racks_per_row: int = Field(default_factory=lambda: D.value("base_scenario", "racks_per_row"), ge=1, le=100)
    kw_per_rack: float = Field(default_factory=lambda: D.value("base_scenario", "kw_per_rack"), ge=2, le=150)

    @computed_field
    @property
    def n_racks(self) -> int:
        return self.n_halls * self.rows_per_hall * self.racks_per_row

    @computed_field
    @property
    def it_capacity_mw(self) -> float:
        return self.n_racks * self.kw_per_rack / 1000


class Cooling(_Model):
    type: CoolingType = "air_chiller"
    chiller_cop: float = Field(3.0, ge=1.5, le=12.0)
    setpoint_c: float = Field(18.0, ge=SETPOINT_MIN, le=SETPOINT_MAX)
    liquid_fraction: float | None = Field(None, ge=0, le=1)


class Battery(_Model):
    power_mw: float = Field(0.0, ge=0, le=500)
    energy_mwh: float = Field(0.0, ge=0, le=4000)
    strategy: Literal["price", "carbon"] = "price"
    round_trip_efficiency: float | None = Field(None, gt=0.5, le=1.0)

    @model_validator(mode="after")
    def _both_or_none(self):
        if (self.power_mw > 0) != (self.energy_mwh > 0):
            raise ValueError("Batterie : puissance et énergie doivent être toutes deux nulles ou toutes deux > 0.")
        return self


class Load(_Model):
    mode: Literal["constant", "trace"] = "constant"
    utilization: float = Field(1.0, ge=0, le=1)
    trace: str = "Alibaba_CPU_Data_Hourly_1.csv"
    trace_file: str | None = None


class TouPeriod(_Model):
    price_usd_per_mwh: float = Field(ge=-1000, le=10000)
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24, description="exclu")
    days: Literal["all", "weekday", "weekend"] = "all"
    months: list[int] | None = Field(None, description="1–12 ; None = toute l'année")


class Price(_Model):
    mode: Literal["flat", "tou", "csv"] = "flat"
    flat_usd_per_mwh: float | None = Field(None, ge=-1000, le=10000)
    tou_periods: list[TouPeriod] = Field(default_factory=list)
    tou_default_usd_per_mwh: float | None = None
    csv_file: str | None = None


class Patches(_Model):
    cop_correction: bool = Field(default_factory=lambda: D.value("patches", "cop_correction"))
    include_auxiliaries: bool = Field(default_factory=lambda: D.value("patches", "include_auxiliaries"))
    water_heat_based: bool = Field(default_factory=lambda: D.value("patches", "water_heat_based"))
    sizing_from_weather_p996: bool = Field(default_factory=lambda: D.value("patches", "sizing_from_weather_p996"))
    rack_delta_floor: bool = Field(default_factory=lambda: D.value("patches", "rack_delta_floor"))


class CapexOverrides(_Model):
    """Coûts unitaires saisis à la main ; None = valeur de defaults.yaml."""

    building_usd_per_kw_it: float | None = Field(None, ge=0)
    mechanical_usd_per_kw_it: float | None = Field(None, ge=0)
    electrical_usd_per_kw_it: float | None = Field(None, ge=0)
    grid_usd_per_mw: float | None = Field(None, ge=0)
    battery_usd_per_kwh: float | None = Field(None, ge=0)
    battery_usd_per_kw: float | None = Field(None, ge=0)


class DataOverrides(_Model):
    """Remplacement manuel des données tirées des sources publiques."""

    weather_file: str | None = None
    carbon_intensity_g_per_kwh: float | None = Field(None, ge=0, le=2000)


class TwinParams(_Model):
    geometry: Geometry = Field(default_factory=Geometry)
    cooling: Cooling = Field(default_factory=Cooling)
    site_id: str = Field(default_factory=lambda: D.value("base_scenario", "site_id"))
    battery: Battery = Field(default_factory=Battery)
    load: Load = Field(default_factory=Load)
    grid_capacity_mw: float = Field(default_factory=lambda: D.value("base_scenario", "grid_capacity_mw"), gt=0, le=5000)
    price: Price = Field(default_factory=Price)
    capex: CapexOverrides = Field(default_factory=CapexOverrides)
    data: DataOverrides = Field(default_factory=DataOverrides)
    patches: Patches = Field(default_factory=Patches)

    def cache_key(self, engine_version: str) -> str:
        """Hash des paramètres, de la version du moteur et des fichiers référencés."""
        payload = {"engine": engine_version, "params": self.model_dump(mode="json"),
                   "defaults": D.raw_defaults(), "files": {}}
        for path in (self.load.trace_file, self.price.csv_file, self.data.weather_file):
            if path:
                payload["files"][path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:20]
