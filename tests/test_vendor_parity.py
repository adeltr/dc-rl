"""Le port vectorisé (twin/physics.py) reproduit l'environnement Gymnasium SustainDC."""
import numpy as np
import pytest

from twin import physics as P
from twin.vendor import ensure_vendor_path, vendor_dc_config
from twin.vendor_ref import run_vendor_reference

ROWS, RACKS_PER_ROW, SERVERS = 4, 2, 200
SUPPLY = [5.3] * 2 + [5.0] * 4 + [5.3] * 2
RETURN = [-3.7] * 2 + [-2.5] * 4 + [-3.7] * 2


@pytest.fixture(scope="module")
def two_weeks():
    ensure_vendor_path()
    from utils.managers import Weather_Manager, Workload_Manager

    weather = Weather_Manager(init_day=0, location="USA_NY_New.York-Kennedy.epw")
    workload = Workload_Manager(init_day=0, workload_filename="Alibaba_CPU_Data_Hourly_1.csv")
    window = slice(4000, 4000 + 14 * 96)
    return (weather.original_temp_data[window], weather.original_wb_data[window],
            np.clip(workload.original_data[window], 0, 1))


@pytest.mark.parametrize("setpoint", [15.0, 18.0, 21.6])
def test_port_matches_vendor_gym_env(two_weeks, setpoint):
    ambient, wet_bulb, load = two_weeks
    ref = run_vendor_reference(ROWS, RACKS_PER_ROW, SERVERS, SUPPLY, RETURN, 130, 10, setpoint,
                               ambient, wet_bulb, load)

    cfg = P.PhysicsConfig.from_vendor_json(vendor_dc_config())
    racks = [P.RackClass(4, SERVERS, 5.3, -3.7), P.RackClass(4, SERVERS, 5.0, -2.5)]
    ctafr, ct_rated = P.chiller_sizing(cfg, racks, 130, 10, P.VENDOR_SIZING_AMBIENT["NY"])
    cpu, fan, avg_return, _ = P.it_model(cfg, racks, 130, 10, setpoint, load * 100)
    hvac = P.hvac_power(cfg, setpoint, avg_return, ambient, cpu + fan, ct_rated, ctafr)
    water = P.vendor_water_usage_l_per_step(avg_return, setpoint, wet_bulb)

    assert ct_rated == pytest.approx(ref["ct_rated_load_w"], rel=1e-12)
    assert ctafr == pytest.approx(ref["ctafr"], rel=1e-12)
    np.testing.assert_allclose((cpu + fan) / 1e3, ref["dc_ITE_total_power_kW"], rtol=1e-9)
    np.testing.assert_allclose(hvac["ct_fan_w"] / 1e3, ref["dc_CT_total_power_kW"], rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(hvac["compressor_w"] / 1e3, ref["dc_Compressor_total_power_kW"], rtol=1e-9)
    np.testing.assert_allclose(water, ref["dc_water_usage"], rtol=1e-9)
    np.testing.assert_allclose(hvac["cw_pump_w"], ref["dc_CW_pump_power_kW"], rtol=1e-12)
