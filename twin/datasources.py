"""Données d'entrée du jumeau : catalogue de sites, météo, intensité carbone, charge.

Règle : toute donnée absente du classeur et de SustainDC est tirée d'une source
publique, mise en cache localement, et peut toujours être remplacée à la main.
Chaque valeur renvoyée porte sa provenance (``Provenance``) pour l'interface.
Aucune donnée n'est inventée : si une source est injoignable et qu'il n'y a ni
cache ni saisie manuelle, une ``DataUnavailable`` explicite est levée.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel

from .physics import interpolate_hourly
from .vendor import REPO_ROOT, ensure_vendor_path, vendor_data_dir

CONFIG_DIR = Path(__file__).resolve().parent / "config"
DATA_DIR = REPO_ROOT / "data"
WEATHER_CACHE = DATA_DIR / "weather"
CARBON_CACHE = DATA_DIR / "carbon"
HTTP_TIMEOUT_S = 60

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
OWID_ENERGY_URL = "https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv"


class DataUnavailable(RuntimeError):
    """Source injoignable, pas de cache, pas de valeur manuelle."""


class Provenance(BaseModel):
    status: Literal["vendor", "api", "cache", "manual", "default", "workbook"]
    source: str
    detail: str = ""
    url: str | None = None
    retrieved_at: str | None = None


@dataclass
class Series:
    values: np.ndarray  # 35 040 pas de 15 min
    provenance: Provenance


# --------------------------------------------------------------------------- sites

@lru_cache(maxsize=1)
def site_catalog() -> dict[str, dict]:
    with open(CONFIG_DIR / "sites.yaml") as f:
        sites = yaml.safe_load(f)["sites"]
    catalog = {}
    for site in sites:
        site = dict(site)
        if site["weather"]["source"] == "sustaindc_epw":
            site.update(_epw_location(vendor_data_dir() / "Weather" / site["weather"]["file"]))
        catalog[site["id"]] = site
    return catalog


def get_site(site_id: str) -> dict:
    try:
        return site_catalog()[site_id]
    except KeyError:
        raise ValueError(f"Site inconnu : {site_id}. Sites disponibles : {sorted(site_catalog())}") from None


def _epw_location(path: Path) -> dict:
    with open(path, encoding="latin-1") as f:
        fields = f.readline().strip().split(",")
    return {"latitude": float(fields[6]), "longitude": float(fields[7]), "utc_offset_h": float(fields[8])}


# --------------------------------------------------------------------------- HTTP

def _http_get(url: str, params: dict | None = None) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "dc-twin/0.1"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        return response.read()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- météo

@dataclass
class Weather:
    dry_bulb: np.ndarray  # °C, 35 040 pas
    wet_bulb: np.ndarray  # °C
    dry_bulb_hourly: np.ndarray  # °C, 8 760 h (dimensionnement p99,6)
    provenance: Provenance


def wet_bulb_from_rh(temp_c, rh_pct, pressure_pa) -> np.ndarray:
    """Température humide, même méthode que utils/managers.Weather_Manager (psychrolib)."""
    ensure_vendor_path()
    import psychrolib as psy

    psy.SetUnitSystem(psy.SI)
    return np.array([psy.GetTWetBulbFromRelHum(t, min(max(rh, 0.0), 100.0) / 100, p)
                     for t, rh, p in zip(temp_c, rh_pct, pressure_pa)])


def load_weather(site_id: str, manual_file: str | None = None) -> Weather:
    if manual_file:
        return _weather_from_file(Path(manual_file))
    site = get_site(site_id)
    if site["weather"]["source"] == "sustaindc_epw":
        return _weather_from_vendor_epw(site["weather"]["file"])
    return _weather_from_public_api(site)


@lru_cache(maxsize=32)
def _weather_from_vendor_epw(filename: str) -> Weather:
    ensure_vendor_path()
    from utils.managers import Weather_Manager

    # Weather_Manager lit l'EPW via son paramètre « location » (nom de fichier) ;
    # original_* = séries non bruitées, avant le bruit aléatoire ajouté par reset().
    manager = Weather_Manager(init_day=0, location=filename)
    hourly = np.loadtxt(vendor_data_dir() / "Weather" / filename, delimiter=",", skiprows=8,
                        usecols=6, encoding="latin-1")
    arrays = [manager.original_temp_data.copy(), manager.original_wb_data.copy(), hourly]
    for a in arrays:
        a.flags.writeable = False  # partagé entre appels via le cache
    return Weather(*arrays,
                   Provenance(status="vendor", source="SustainDC EPW", detail=filename))


def _weather_from_file(path: Path) -> Weather:
    """EPW ou CSV (colonnes temp_c, rh_pct, pressure_pa ; 8 760 lignes) fourni à la main."""
    if path.suffix.lower() == ".epw":
        rows = np.genfromtxt(path, delimiter=",", skip_header=8, usecols=(6, 8, 9), encoding="latin-1")
        temp, rh, pressure = rows[:, 0], rows[:, 1], rows[:, 2]
    else:
        temp, rh, pressure = _read_weather_csv(path)
    return _weather_from_hourly(temp, rh, pressure,
                                Provenance(status="manual", source="fichier météo fourni", detail=str(path)))


def _read_weather_csv(path: Path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return (np.array([float(r["temp_c"]) for r in rows]), np.array([float(r["rh_pct"]) for r in rows]),
            np.array([float(r["pressure_pa"]) for r in rows]))


def _weather_from_hourly(temp, rh, pressure, provenance: Provenance) -> Weather:
    temp, rh, pressure = (np.asarray(a, dtype=float)[:8760] for a in (temp, rh, pressure))
    if len(temp) != 8760:
        raise ValueError(f"Série météo de {len(temp)} heures ; 8 760 attendues.")
    wet = wet_bulb_from_rh(temp, rh, pressure)
    return Weather(interpolate_hourly(temp), interpolate_hourly(wet), temp, provenance)


def _weather_from_public_api(site: dict) -> Weather:
    year = int(site["weather"].get("year", 2023))
    cache = WEATHER_CACHE / f"{site['id']}_{year}.csv"
    if cache.exists():
        meta = json.loads(cache.with_suffix(".json").read_text())
        temp, rh, pressure = _read_weather_csv(cache)
        return _weather_from_hourly(temp, rh, pressure, Provenance(status="cache", **meta))
    errors = []
    for fetch in (_fetch_open_meteo, _fetch_nasa_power):
        try:
            temp, rh, pressure, meta = fetch(site["latitude"], site["longitude"], year)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            errors.append(f"{fetch.__name__}: {exc}")
            continue
        WEATHER_CACHE.mkdir(parents=True, exist_ok=True)
        with open(cache, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["temp_c", "rh_pct", "pressure_pa"])
            writer.writerows(zip(temp, rh, pressure))
        cache.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return _weather_from_hourly(temp, rh, pressure, Provenance(status="api", **meta))
    raise DataUnavailable(
        f"Météo indisponible pour {site['label']} : " + " ; ".join(errors)
        + ". Autoriser archive-api.open-meteo.com ou power.larc.nasa.gov dans la politique réseau, "
        "ou fournir un fichier EPW/CSV (weather_file)."
    )


def _drop_leap_day(times: list[str], *series):
    keep = [i for i, t in enumerate(times) if not t.startswith(tuple(f"{y}-02-29" for y in range(1900, 2100)))]
    return [np.asarray(s, dtype=float)[keep] for s in series]


def _fetch_open_meteo(lat: float, lon: float, year: int):
    params = {"latitude": lat, "longitude": lon, "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
              "hourly": "temperature_2m,relative_humidity_2m,surface_pressure", "timezone": "auto"}
    data = json.loads(_http_get(OPEN_METEO_URL, params))
    hourly = data["hourly"]
    temp, rh, pressure_hpa = _drop_leap_day(hourly["time"], hourly["temperature_2m"],
                                            hourly["relative_humidity_2m"], hourly["surface_pressure"])
    meta = {"source": "Open-Meteo Archive (ERA5)", "detail": f"{lat}, {lon}, {year}, heure locale",
            "url": OPEN_METEO_URL, "retrieved_at": _now()}
    return temp, rh, pressure_hpa * 100, meta


def _fetch_nasa_power(lat: float, lon: float, year: int):
    params = {"parameters": "T2M,RH2M,PS", "community": "RE", "latitude": lat, "longitude": lon,
              "start": f"{year}0101", "end": f"{year}1231", "format": "JSON", "time-standard": "LST"}
    data = json.loads(_http_get(NASA_POWER_URL, params))["properties"]["parameter"]
    keys = sorted(data["T2M"])
    times = [f"{k[:4]}-{k[4:6]}-{k[6:8]}" for k in keys]
    temp, rh, pressure_kpa = _drop_leap_day(times, [data["T2M"][k] for k in keys],
                                            [data["RH2M"][k] for k in keys], [data["PS"][k] for k in keys])
    meta = {"source": "NASA POWER (MERRA-2)", "detail": f"{lat}, {lon}, {year}, heure solaire locale",
            "url": NASA_POWER_URL, "retrieved_at": _now()}
    return temp, rh, pressure_kpa * 1000, meta


# --------------------------------------------------------------------------- carbone

def load_carbon_intensity(site_id: str, manual_g_per_kwh: float | None = None) -> Series:
    """Intensité carbone du réseau (gCO2/kWh) sur 35 040 pas."""
    if manual_g_per_kwh is not None:
        return Series(np.full(35040, float(manual_g_per_kwh)),
                      Provenance(status="manual", source="saisie manuelle",
                                 detail=f"{manual_g_per_kwh:,.0f} gCO2/kWh".replace(",", "\u202f")))
    site = get_site(site_id)
    if site["carbon"]["source"] == "sustaindc_ci":
        region = site["carbon"]["region"]
        return Series(_vendor_carbon(region),
                      Provenance(status="vendor", source="SustainDC carbon intensity (horaire 2022)",
                                 detail=f"{region}_NG_&_avgCI.csv"))
    value, provenance = owid_carbon_intensity(site["country"])
    return Series(np.full(35040, value), provenance)


@lru_cache(maxsize=32)
def _vendor_carbon(region: str) -> np.ndarray:
    ensure_vendor_path()
    from utils.managers import CI_Manager

    values = CI_Manager(init_day=0, location=region).original_data.copy()
    values.flags.writeable = False
    return values


def owid_carbon_intensity(iso_code: str) -> tuple[float, Provenance]:
    cache = CARBON_CACHE / "owid_carbon_intensity_elec.json"
    status = "cache"
    if not cache.exists():
        try:
            raw = _http_get(OWID_ENERGY_URL)
        except (urllib.error.URLError, OSError) as exc:
            raise DataUnavailable(
                f"Intensité carbone indisponible ({exc}). Autoriser raw.githubusercontent.com "
                "ou saisir carbon_intensity_g_per_kwh."
            ) from exc
        latest: dict[str, dict] = {}
        for row in csv.DictReader(io.StringIO(raw.decode())):
            iso, value = row.get("iso_code"), row.get("carbon_intensity_elec")
            if iso and value:
                year = int(row["year"])
                if iso not in latest or year > latest[iso]["year"]:
                    latest[iso] = {"year": year, "value": float(value)}
        CARBON_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"url": OWID_ENERGY_URL, "retrieved_at": _now(), "countries": latest}, indent=1))
        status = "api"
    payload = json.loads(cache.read_text())
    if iso_code not in payload["countries"]:
        raise DataUnavailable(f"Pas d'intensité carbone OWID pour {iso_code} ; saisir carbon_intensity_g_per_kwh.")
    entry = payload["countries"][iso_code]
    return entry["value"], Provenance(
        status=status, source="Our World in Data – energy-data (carbon_intensity_elec)",
        detail=f"{iso_code} {entry['year']}, facteur annuel constant (approximation)",
        url=payload["url"], retrieved_at=payload["retrieved_at"])


# --------------------------------------------------------------------------- charge

def workload_traces() -> list[str]:
    return sorted(p.name for p in (vendor_data_dir() / "Workload").glob("*.csv"))


def load_workload(trace: str | None, manual_file: str | None = None) -> Series:
    """Taux d'utilisation CPU (0–1) sur 35 040 pas."""
    if manual_file:
        values = np.loadtxt(manual_file, delimiter=",", skiprows=1, usecols=-1)[:8760]
        if len(values) != 8760:
            raise ValueError("La trace de charge doit contenir 8 760 valeurs horaires.")
        return Series(np.clip(interpolate_hourly(values), 0, 1),
                      Provenance(status="manual", source="trace fournie", detail=manual_file))
    ensure_vendor_path()
    from utils.managers import Workload_Manager

    manager = Workload_Manager(init_day=0, workload_filename=trace)
    return Series(np.clip(manager.original_data, 0, 1),
                  Provenance(status="vendor", source="SustainDC workload", detail=trace))
