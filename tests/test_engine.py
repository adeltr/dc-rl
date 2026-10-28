"""Tests du moteur du jumeau (twin/engine.py)."""
import json

import numpy as np
import pytest

from twin import engine
from twin.datasources import DataUnavailable
from twin.params import TwinParams

SITE = "us_ny_jfk"
TOU = {"mode": "tou", "tou_default_usd_per_mwh": 90,
       "tou_periods": [{"price_usd_per_mwh": 220, "start_hour": 17, "end_hour": 21, "days": "weekday"}]}

CONFIGS = {
    "base": {},
    "trace": {"load": {"mode": "trace"}},
    "battery_tou": {"price": TOU, "battery": {"power_mw": 10, "energy_mwh": 40}},
    "battery_carbon": {"battery": {"power_mw": 5, "energy_mwh": 10, "strategy": "carbon"}},
    "liquid": {"cooling": {"type": "liquid"}},
    "free_cooling_seattle": {"cooling": {"type": "air_free_cooling"}, "site_id": "us_wa_seattle"},
    "phoenix_cop5": {"site_id": "us_az_phoenix", "cooling": {"chiller_cop": 5, "setpoint_c": 21}},
    "vendor_raw": {"patches": {"cop_correction": False, "include_auxiliaries": False, "water_heat_based": False,
                               "sizing_from_weather_p996": False, "rack_delta_floor": False}},
}


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engine, "LOG_PATH", tmp_path / "scenarios.jsonl")
    engine._memory_cache.clear()


def params(**overrides) -> TwinParams:
    return TwinParams.model_validate({"site_id": SITE, **overrides})


@pytest.fixture(scope="module")
def results():
    return {name: engine.simulate(params(**cfg)) for name, cfg in CONFIGS.items()}


@pytest.mark.parametrize("name", CONFIGS)
def test_energy_balance(results, name):
    r = results[name]
    e = r.energy
    assert e.facility_mwh == pytest.approx(e.it_mwh + e.cooling_mwh + e.losses_mwh, rel=1e-12)
    assert e.cooling_mwh == pytest.approx(e.compressor_mwh + e.cooling_tower_fan_mwh + e.crac_fan_mwh
                                          + e.pumps_mwh + e.liquid_overhead_mwh, rel=1e-12)
    assert e.grid_mwh == pytest.approx(e.facility_mwh + e.battery_charge_mwh - e.battery_discharge_mwh, rel=1e-12)
    assert e.battery_losses_mwh >= -1e-9
    assert e.battery_charge_mwh >= e.battery_discharge_mwh - 1e-9
    assert sum(r.monthly_facility_mwh) == pytest.approx(e.facility_mwh, rel=1e-12)
    assert sum(r.monthly_energy_cost_usd) == pytest.approx(r.energy_cost_usd, rel=1e-12)
    assert np.mean(r.hourly_grid_mw) * 8760 == pytest.approx(e.grid_mwh, rel=1e-8)  # série arrondie à 1e-6 MW


@pytest.mark.parametrize("name", CONFIGS)
def test_pue_at_least_one(results, name):
    r = results[name]
    assert r.pue_annual >= 1
    assert all(p >= 1 for p in r.pue_monthly)


@pytest.mark.parametrize("field, values", [
    ("n_halls", [1, 2, 3]),
    ("rows_per_hall", [4, 10, 20]),
    ("racks_per_row", [5, 25, 40]),
    ("kw_per_rack", [10, 20, 40]),
])
def test_more_it_gives_more_energy(field, values):
    runs = [engine.simulate(params(geometry={field: v})) for v in values]
    for small, big in zip(runs, runs[1:]):
        assert big.it_capacity_mw > small.it_capacity_mw
        assert big.energy.it_mwh > small.energy.it_mwh
        assert big.energy.facility_mwh > small.energy.facility_mwh
        assert big.capex.total_usd > small.capex.total_usd


def test_it_capacity_is_derived():
    p = params(geometry={"n_halls": 2, "rows_per_hall": 20, "racks_per_row": 25, "kw_per_rack": 20})
    assert p.geometry.it_capacity_mw == pytest.approx(20.0)
    sent = TwinParams.model_validate({"geometry": {"it_capacity_mw": 50, "n_racks": 7}})
    assert sent.geometry.it_capacity_mw == pytest.approx(20.0) and sent.geometry.n_racks == 1000


def test_price_plus_ten_percent_gives_cost_plus_ten_percent():
    base = engine.simulate(params(price={"flat_usd_per_mwh": 150}))
    high = engine.simulate(params(price={"flat_usd_per_mwh": 165}))
    assert high.energy_cost_usd / base.energy_cost_usd == pytest.approx(1.10, rel=1e-12)
    assert high.energy.grid_mwh == pytest.approx(base.energy.grid_mwh, rel=1e-12)


def test_battery_respects_limits(results):
    r = results["battery_tou"]
    assert r.battery_cycles > 0
    assert r.flows_mw.peak["battery_charge"] <= 10 + 1e-9
    assert r.flows_mw.peak["battery_discharge"] <= 10 + 1e-9
    assert r.energy_cost_usd < engine.simulate(params(price=TOU)).energy_cost_usd


def test_fixed_losses_make_pue_rise_at_low_load():
    """Les pertes fixes dégradent le PUE à faible charge (comportement observé en exploitation)."""
    nominal, idle = engine.simulate(params(load={"utilization": 0.4})), engine.simulate(params(load={"utilization": 0.0}))
    assert idle.pue_annual > nominal.pue_annual
    assert idle.fixed_energy_share > nominal.fixed_energy_share > 0
    share = engine.D.value("electrical", "fixed_losses_share")
    assert nominal.energy.fixed_losses_mwh == pytest.approx(share * nominal.it_capacity_mw * 8760, rel=1e-9)
    none = engine.simulate(params(load={"utilization": 0.4}, electrical={"fixed_losses_share": 0.0}))
    assert none.fixed_energy_share == 0 and none.pue_annual < nominal.pue_annual


def test_default_load_is_realistic_share_of_contract():
    r = engine.simulate(TwinParams(site_id=SITE))
    assert 0.6 <= r.it_load_factor <= 0.8
    assert r.thermal.rack_delta_floor_share == 0  # dans le domaine thermique de SustainDC


def test_grid_sized_on_design_peak():
    """Le raccordement suit la pointe de conception (serveurs à 100 %), pas la charge moyenne."""
    dense = engine.simulate(params(geometry={"kw_per_rack": 30}))
    assert dense.peak_grid_mw < dense.grid_capacity_contract_mw < dense.peak_design_mw
    assert dense.grid_capacity_mw >= dense.peak_design_mw and dense.grid_upgrade_mw > 0
    grid = next(line for line in dense.capex.lines if line.key == "grid")
    assert grid.amount_usd == pytest.approx(grid.unit_cost * dense.grid_capacity_mw)
    fixed = engine.simulate(params(geometry={"kw_per_rack": 30}, grid_auto_upgrade=False))
    assert fixed.grid_capacity_mw == 30 and fixed.grid_upgrade_mw == 0
    assert fixed.capex.total_usd < dense.capex.total_usd


def test_battery_savings_and_payback(results):
    r = results["battery_tou"]
    without = engine.simulate(params(price=TOU))
    assert r.battery_savings_usd == pytest.approx(without.energy_cost_usd - r.energy_cost_usd, rel=1e-9)
    assert r.battery_payback_years == pytest.approx(r.capex.by_component["battery"] / r.battery_savings_usd)
    assert results["base"].battery_payback_years is None


def test_capex_base_matches_workbook_hard_costs():
    r = engine.simulate(TwinParams(site_id=SITE))
    assert r.capex.total_usd == pytest.approx(127_500_000, rel=1e-12)  # Underwriting!K52


def test_cache_and_log():
    p = params()
    first = engine.run_year(p)
    second = engine.run_year(p)
    assert not first.from_cache and second.from_cache
    assert second.params_hash == first.params_hash
    assert params(cooling={"setpoint_c": 19}).cache_key(engine.ENGINE_VERSION) != first.params_hash
    engine._memory_cache.clear()
    assert engine.run_year(p).from_cache  # cache disque
    lines = engine.LOG_PATH.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["params_hash"] == first.params_hash and record["duration_s"] > 0
    assert record["outputs"]["pue_annual"] == pytest.approx(first.pue_annual)


def test_annual_run_is_fast():
    r = engine.simulate(params(load={"mode": "trace"}))
    assert r.duration_s < 3.0


def test_manual_overrides_win():
    r = engine.simulate(params(data={"carbon_intensity_g_per_kwh": 100.0}))
    assert r.provenance["carbon_intensity"].status == "manual"
    assert r.co2_t == pytest.approx(r.energy.grid_mwh * 100 / 1000, rel=1e-12)


def test_missing_public_data_is_never_invented(monkeypatch, tmp_path):
    from twin import datasources

    monkeypatch.setattr(datasources, "WEATHER_CACHE", tmp_path)

    def offline(*args, **kwargs):
        raise OSError("hors ligne")

    monkeypatch.setattr(datasources, "_http_get", offline)
    with pytest.raises(DataUnavailable):
        engine.simulate(TwinParams(site_id="pa_panama_tocumen"))
