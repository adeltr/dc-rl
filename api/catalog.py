"""Catalogue des paramètres éditables dans l'interface : libellé, unité, bornes réalistes,
pas, équipement qui les porte dans la scène 3D. Aucune de ces valeurs n'est dans le front."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from twin.datasources import site_catalog, workload_traces
from twin.physics import SETPOINT_MAX, SETPOINT_MIN

Equipment = Literal["substation", "hall", "cooling_plant", "battery", "site", "market"]


class Option(BaseModel):
    value: str | bool
    label: str


class ParameterSpec(BaseModel):
    path: str
    label: str
    unit: str
    equipment: Equipment
    kind: Literal["number", "integer", "select", "toggle", "percent"]
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[Option] | None = None
    help: str = ""
    sensitivity: bool = False  # proposé par défaut dans le tornado
    visible_when: dict | None = None  # {"path": ..., "in": [...]} : affiché seulement dans ce cas


def _p(path, label, unit, equipment, kind="number", lo=None, hi=None, step=None, options=None, help="",
       sensitivity=False, when=None):
    return ParameterSpec(path=path, label=label, unit=unit, equipment=equipment, kind=kind, min=lo, max=hi,
                         step=step, options=options, help=help, sensitivity=sensitivity,
                         visible_when={"path": when[0], "in": list(when[1])} if when else None)


def parameter_catalog() -> list[ParameterSpec]:
    sites = [Option(value=s["id"], label=s["label"]) for s in site_catalog().values()]
    traces = [Option(value=t, label=t.removesuffix(".csv").replace("_", " ")) for t in workload_traces()]
    return [
        # poste électrique
        _p("params.grid_capacity_mw", "Capacité de raccordement", "MW", "substation", lo=1, hi=500, step=0.5),
        _p("params.price.mode", "Tarif d'électricité", "", "substation", "select",
           options=[Option(value="flat", label="Tarif plat"), Option(value="tou", label="Plages horaires"),
                    Option(value="csv", label="Fichier 8 760 h")]),
        _p("params.price.flat_usd_per_mwh", "Prix de l'électricité", "$/MWh", "substation", lo=0, hi=500, step=1,
           sensitivity=True, when=("params.price.mode", ["flat"])),
        _p("params.price.tou_default_usd_per_mwh", "Prix hors plages", "$/MWh", "substation", lo=0, hi=500, step=1,
           when=("params.price.mode", ["tou"])),
        # hall
        _p("params.geometry.n_halls", "Nombre de halls", "", "hall", "integer", 1, 10, 1, sensitivity=True),
        _p("params.geometry.rows_per_hall", "Rangées par hall", "", "hall", "integer", 1, 60, 1),
        _p("params.geometry.racks_per_row", "Racks par rangée", "", "hall", "integer", 1, 60, 1),
        _p("params.geometry.kw_per_rack", "Densité", "kW/rack", "hall", lo=5, hi=100, step=0.5, sensitivity=True,
           help="Puissance IT de conception à 100 % de charge et 18 °C de consigne"),
        _p("params.load.mode", "Profil de charge", "", "hall", "select",
           options=[Option(value="constant", label="Utilisation constante"), Option(value="trace", label="Trace")]),
        _p("params.load.utilization", "Taux d'utilisation", "%", "hall", "percent", 0, 1, 0.01, sensitivity=True,
           when=("params.load.mode", ["constant"])),
        _p("params.load.trace", "Trace de charge", "", "hall", "select", options=traces, when=("params.load.mode", ["trace"])),
        # centrale de refroidissement
        _p("params.cooling.type", "Type de refroidissement", "", "cooling_plant", "select",
           options=[Option(value="air_chiller", label="Air + chiller"),
                    Option(value="air_free_cooling", label="Air + free cooling (approximation)"),
                    Option(value="liquid", label="Liquide (approximation)")]),
        _p("params.cooling.chiller_cop", "COP du chiller", "", "cooling_plant", lo=2, hi=10, step=0.1, sensitivity=True),
        _p("params.cooling.setpoint_c", "Consigne de soufflage", "°C", "cooling_plant", lo=SETPOINT_MIN,
           hi=SETPOINT_MAX, step=0.1, sensitivity=True),
        _p("params.cooling.liquid_fraction", "Part de chaleur en liquide", "%", "cooling_plant", "percent", 0, 1, 0.05,
           when=("params.cooling.type", ["liquid"])),
        # batterie
        _p("params.battery.power_mw", "Puissance batterie", "MW", "battery", lo=0, hi=200, step=0.5),
        _p("params.battery.energy_mwh", "Énergie batterie", "MWh", "battery", lo=0, hi=800, step=1),
        _p("params.battery.strategy", "Pilotage batterie", "", "battery", "select",
           options=[Option(value="price", label="Heures à bas prix"), Option(value="carbon", label="Heures bas carbone")]),
        _p("params.battery.round_trip_efficiency", "Rendement aller-retour", "%", "battery", "percent", 0.7, 0.98, 0.01),
        # site
        _p("params.site_id", "Site", "", "site", "select", options=sites),
        _p("params.data.carbon_intensity_g_per_kwh", "Intensité carbone (manuelle)", "gCO2/kWh", "site",
           lo=0, hi=1200, step=1, help="Vide = source publique"),
        # marché
        _p("market.rent_usd_per_kw_month", "Revenu", "$/kW/mois", "market", lo=100, hi=600, step=1, sensitivity=True),
        _p("market.rent_growth", "Indexation des loyers", "%/an", "market", "percent", 0, 0.06, 0.0025),
        _p("market.absorption_multiplier", "Rythme de montée en occupation", "×", "market", lo=0.25, hi=4, step=0.05,
           sensitivity=True),
        _p("market.carbon_price_usd_per_t", "Prix du carbone", "$/tCO2", "market", lo=0, hi=300, step=1),
        _p("market.water_price_usd_per_m3", "Prix de l'eau", "$/m³", "market", lo=0, hi=10, step=0.05),
        _p("market.idx_energy", "Indexation énergie", "%/an", "market", "percent", -0.02, 0.08, 0.0025),
        _p("market.idx_opex", "Indexation OPEX", "%/an", "market", "percent", -0.02, 0.08, 0.0025),
        _p("market.discount_rate", "Taux d'actualisation (VAN)", "%", "market", "percent", 0.03, 0.2, 0.0025),
        _p("market.perm_debt", "Dette permanente (refinancement)", "", "market", "toggle"),
        _p("market.dscr_covenant", "Covenant DSCR", "x", "market", lo=1.0, hi=2.0, step=0.05),
        _p("market.calibration", "Raccord au classeur", "", "market", "select",
           options=[Option(value="calibrated", label="Calibré sur le classeur"),
                    Option(value="absolute", label="Valeurs simulées brutes")]),
    ]


def catalog_by_path() -> dict[str, ParameterSpec]:
    return {spec.path: spec for spec in parameter_catalog()}
