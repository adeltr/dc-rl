"""Prix de l'électricité heure par heure ($/MWh) : tarif plat, plages horaires ou CSV 8 760 h."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from . import defaults as D
from .datasources import Provenance
from .params import Price


def _fr(value: float) -> str:
    return f"{value:,.1f}".replace(",", "\u202f").replace(".", ",")


def calendar(year: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mois (1–12), jour de semaine (0 = lundi) et heure pour les 8 760 heures (365 jours)."""
    days = [date(year, 1, 1) + timedelta(days=d) for d in range(365)]
    month = np.repeat([d.month for d in days], 24)
    weekday = np.repeat([d.weekday() for d in days], 24)
    hour = np.tile(np.arange(24), 365)
    return month, weekday, hour


def hourly_prices(price: Price) -> tuple[np.ndarray, Provenance]:
    flat_default = D.value("price", "flat_usd_per_mwh")
    if price.mode == "flat":
        if price.flat_usd_per_mwh is None:
            entry = D.entry("price", "flat_usd_per_mwh")
            return np.full(8760, float(flat_default)), Provenance(
                status="workbook", source="classeur", detail=entry.get("note", ""))
        return np.full(8760, price.flat_usd_per_mwh), Provenance(
            status="manual", source="tarif plat saisi", detail=f"{_fr(price.flat_usd_per_mwh)} $/MWh")
    if price.mode == "csv":
        if not price.csv_file:
            raise ValueError("Tarif CSV : aucun fichier de prix fourni (téléverser un CSV de 8 760 prix).")
        values = np.loadtxt(price.csv_file, delimiter=",", skiprows=1, usecols=-1)
        if len(values) < 8760:
            raise ValueError(f"Tarif CSV : {len(values)} valeurs, 8 760 attendues.")
        return values[:8760].astype(float), Provenance(status="manual", source="tarif CSV 8760 h",
                                                       detail=price.csv_file)
    month, weekday, hour = calendar(D.value("price", "calendar_year"))
    base = price.tou_default_usd_per_mwh if price.tou_default_usd_per_mwh is not None else flat_default
    out = np.full(8760, float(base))
    assigned = np.zeros(8760, dtype=bool)
    for period in price.tou_periods:  # la première plage qui correspond l'emporte
        mask = (hour >= period.start_hour) & (hour < period.end_hour)
        if period.days == "weekday":
            mask &= weekday < 5
        elif period.days == "weekend":
            mask &= weekday >= 5
        if period.months:
            mask &= np.isin(month, period.months)
        mask &= ~assigned
        out[mask] = period.price_usd_per_mwh
        assigned |= mask
    return out, Provenance(status="manual", source="tarif par plages horaires",
                           detail=f"{len(price.tou_periods)} plage(s), hors plages {_fr(base)} $/MWh")
