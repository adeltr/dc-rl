"""API FastAPI : routes, SSE, scénarios, comparaison, sensibilités, export, alertes."""
import json
import time

import openpyxl
import pytest
from fastapi.testclient import TestClient

from api import app as app_module
from api import service as service_module
from api.kpis import compute_alerts
from api.service import TwinService
from api.store import Store
from bridge import bridge as bridge_module
from twin import engine as engine_module

pytestmark = pytest.mark.skipif(not bridge_module.SOURCE_WORKBOOK.exists(), reason="classeur absent")
SITE = "us_ny_jfk"
STAGES = ["en attente", "simulation physique", "recalcul Excel", "terminé"]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    mp = pytest.MonkeyPatch()
    mp.setenv("TWIN_BASE_SITE", SITE)
    mp.setattr(engine_module, "LOG_PATH", tmp / "scenarios.jsonl")
    mp.setattr(engine_module, "CACHE_DIR", tmp / "cache")
    mp.setattr(bridge_module, "LOG_PATH", tmp / "scenarios.jsonl")
    mp.setattr(service_module, "EXPORT_DIR", tmp / "exports")
    app_module.app.state.service = TwinService(store=Store(tmp / "store"))
    with TestClient(app_module.app) as c:
        c.tmp = tmp
        yield c
    app_module.app.state.service = None
    mp.undo()


def scenario(**params):
    return {"params": {"site_id": SITE, **params}}


def wait(client, job, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/simulate/{job['job_id']}").json()
        if status["status"] in ("done", "error", "cancelled"):
            return status
        time.sleep(0.1)
    raise TimeoutError(job)


def simulate(client, body):
    job = client.post("/simulate", json=body).json()
    status = wait(client, job)
    return status, client.get(f"/results/{job['result_id']}").json()


def kpi(result, kpi_id):
    return next(k for k in result["kpis"] if k["id"] == kpi_id)


def test_meta_and_base(client):
    meta = client.get("/meta").json()
    paths = {p["path"]: p for p in meta["parameters"]}
    assert paths["params.geometry.kw_per_rack"]["equipment"] == "hall"
    assert paths["params.price.flat_usd_per_mwh"]["equipment"] == "substation"
    assert paths["params.cooling.chiller_cop"]["equipment"] == "cooling_plant"
    assert paths["params.battery.energy_mwh"]["equipment"] == "battery"
    assert all(p["min"] is None or p["min"] < p["max"] for p in meta["parameters"])
    assert {k["id"] for k in meta["kpis"] if k["cockpit"]} == {
        "irr_equity", "irr_project", "npv", "dscr_min", "dscr_avg", "llcr", "capex_total", "opex_energy_y1", "pue",
        "energy_cost_effective"}
    base = client.get("/scenario/base").json()
    assert base["result"]["status"] == "confirmed"
    assert base["effective"]["params"]["price"]["flat_usd_per_mwh"] == 150.0
    irr = kpi(base["result"], "irr_equity")
    assert irr["value"] == irr["base"] and irr["delta"] == 0 and irr["favorable"] is None
    assert irr["drivers"]
    # le cockpit et le classeur utilisent le même PUE (le PUE simulé)
    assert base["result"]["workbook"]["outputs"]["out_pue"] == pytest.approx(kpi(base["result"], "pue")["value"])
    assert kpi(base["result"], "dscr_min")["note"] and kpi(base["result"], "llcr")["value"] is None
    alerts = {a["id"] for a in base["result"]["alerts"]}
    assert {"cfads_negative", "dscr_construction"} <= alerts  # montée en occupation en A3


def test_simulate_streams_stages_in_order(client):
    job = client.post("/simulate", json={"scenario": scenario(geometry={"kw_per_rack": 22})}).json()
    stages = []
    with client.stream("GET", f"/simulate/{job['job_id']}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                stages.append(json.loads(line[6:])["stage"])
    assert [s for s in STAGES if s in stages] == STAGES
    assert stages[-1] == "terminé"
    result = client.get(f"/results/{job['result_id']}").json()
    assert result["status"] == "confirmed" and result["workbook"]["recalc_ok"]


def test_price_plus_ten_percent_end_to_end(client):
    _, high = simulate(client, {"scenario": scenario(price={"flat_usd_per_mwh": 165})})
    opex = kpi(high, "opex_energy_y1")
    assert opex["delta_pct"] == pytest.approx(0.10, abs=1e-9) and opex["favorable"] is False
    assert kpi(high, "irr_equity")["delta"] < 0 and kpi(high, "irr_project")["delta"] < 0
    assert kpi(high, "irr_equity")["favorable"] is False
    assert kpi(high, "energy_cost_effective")["delta_pct"] == pytest.approx(0.10, abs=1e-9)


def test_round_trip_and_saved_scenarios(client):
    base = client.get("/scenario/base").json()
    status, result = simulate(client, {"scenario": base["result"]["scenario"]})  # JSON renvoyé tel quel
    assert status["status"] == "done"
    saved = client.post("/scenarios", json={"name": "Copie", "scenario": result["scenario"],
                                            "result_id": result["id"]}).json()
    renamed = client.patch(f"/scenarios/{saved['id']}", json={"name": "Copie renommée"}).json()
    assert renamed["name"] == "Copie renommée"
    assert client.patch("/scenarios/base", json={"name": "x"}).status_code == 403
    assert client.delete("/scenarios/base").status_code == 403
    names = [s["name"] for s in client.get("/scenarios").json()]
    assert names[0] == "Cas de base" and "Copie renommée" in names
    assert client.delete(f"/scenarios/{saved['id']}").status_code == 204


def test_compare_three(client):
    _, a = simulate(client, {"scenario": scenario(cooling={"type": "liquid"})})
    _, b = simulate(client, {"scenario": {**scenario(), "market": {"perm_debt": True}}})
    out = client.get(f"/compare?ids=base,{a['id']},{b['id']}").json()
    assert [s["id"] for s in out["scenarios"]] == ["base", a["id"], b["id"]]
    # le DSCR couvre aussi les intérêts du prêt de construction : défini même sans dette permanente
    assert all(isinstance(s["kpis"]["dscr_min"], float) for s in out["scenarios"])
    assert out["scenarios"][0]["kpis"]["llcr"] is None and out["scenarios"][2]["kpis"]["llcr"] > 0
    assert len(out["scenarios"][1]["series"]["out_cfads"]) == len(out["scenarios"][1]["years"])
    assert len(out["scenarios"][1]["pue_monthly"]) == 12
    assert client.get("/compare?ids=nope").status_code == 404


def test_export(client):
    _, result = simulate(client, {"scenario": scenario(geometry={"kw_per_rack": 25})})
    response = client.get(f"/export/{result['id']}.xlsx")
    assert response.status_code == 200
    path = client.tmp / "export.xlsx"
    path.write_bytes(response.content)
    wb = openpyxl.load_workbook(path, data_only=True)
    assert wb["Underwriting"]["E131"].value == pytest.approx(25_000)
    assert wb["Outputs"] is not None and "Version" in wb.sheetnames
    assert client.get("/export/inconnu.xlsx").status_code == 404


def test_debounce_cancels_pending_requests(client):
    jobs = [client.post("/simulate", json={"scenario": scenario(geometry={"kw_per_rack": k}), "client_id": "ui"}).json()
            for k in (26, 27, 28, 29)]
    statuses = [wait(client, j)["status"] for j in jobs]
    assert statuses[-1] == "done" and "cancelled" in statuses


def test_validation_and_missing_data(client):
    ignored = client.post("/preview", json={"scenario": scenario(geometry={"it_capacity_mw": 50})}).json()
    assert ignored["twin"]["it_capacity_mw"] == pytest.approx(20.0)  # dérivée, jamais saisie
    half = client.post("/preview", json={"scenario": scenario(battery={"power_mw": 5})}).json()
    assert half["twin"]["battery_cycles"] == 0 and half["twin"]["capex"]["by_component"]["battery"] == 0
    assert any("Batterie incomplète" in a["message"] and a["target"] == "battery" for a in half["alerts"])
    assert client.post("/simulate", json={"scenario": scenario(geometry={"kw_per_rack": 500})}).status_code == 422
    no_csv = client.post("/preview", json={"scenario": scenario(price={"mode": "csv"})})
    assert no_csv.status_code == 422 and "aucun fichier" in no_csv.json()["detail"]
    empty_tou = client.post("/preview", json={"scenario": scenario(price={"mode": "tou", "tou_default_usd_per_mwh": 120})}).json()
    assert empty_tou["twin"]["effective_price_usd_per_mwh"] == pytest.approx(120)
    status, result = simulate(client, {"scenario": {"params": {"site_id": "pa_panama_tocumen"}}})
    if status["status"] == "error":  # sans accès réseau ni cache : aucune météo inventée
        assert "Météo indisponible" in status["error"] and result["status"] == "error"


def test_manual_weather_upload(client):
    epw = (engine_module.REPO_ROOT / "vendor/sustaindc/data/Weather/USA_TX_Dallas-Fort.Worth.epw").read_bytes()
    uploaded = client.put("/data/weather/test_upload.epw", content=epw).json()
    status, result = simulate(client, {"scenario": {"params": {"site_id": "pa_panama_tocumen",
                                                               "data": {"weather_file": uploaded["weather_file"]}}}})
    assert status["status"] == "done" and result["twin"]["provenance"]["weather"]["status"] == "manual"
    assert client.put("/data/weather/bad.epw", content=b"pas un epw").status_code == 422
    (engine_module.REPO_ROOT / "data/uploads/test_upload.epw").unlink(missing_ok=True)


def test_alerts(client):
    _, result = simulate(client, {"scenario": scenario(geometry={"kw_per_rack": 30})})
    alerts = {a["id"]: a for a in result["alerts"]}
    assert alerts["grid_capacity"]["target"] == "substation" and alerts["grid_capacity"]["severity"] == "critical"
    _, debt = simulate(client, {"scenario": {**scenario(), "market": {"perm_debt": True, "dscr_covenant": 1.9}}})
    assert any(a["id"] == "dscr_covenant" and a["target"] == "campus" for a in debt["alerts"])
    svc = app_module.app.state.service
    hot = svc.base_twin.model_copy(deep=True)
    hot.thermal.rack_inlet_c = {"edge": 28.5, "inner": 23.0}
    assert any(a.id == "ashrae_edge" and a.target == "hall" for a in compute_alerts(hot, None, 1.2))


def test_preview_and_sensitivity(client):
    svc = app_module.app.state.service
    deadline = time.time() + 300
    while svc.surrogate is None and time.time() < deadline:
        time.sleep(1)
    assert svc.surrogate is not None
    body = {"scenario": scenario(price={"flat_usd_per_mwh": 153})}
    t0 = time.perf_counter()
    preview = client.post("/preview", json=body).json()
    assert time.perf_counter() - t0 < 1.0
    assert preview["status"] == "provisional" and preview["estimated_outputs"]
    _, exact = simulate(client, body)
    for kpi_id, tolerance in (("irr_equity", 0.005), ("irr_project", 0.002), ("opex_energy_y1", 0.01)):
        p, e = kpi(preview, kpi_id)["value"], kpi(exact, kpi_id)["value"]
        assert abs(p - e) <= tolerance * max(1, abs(e)), (kpi_id, p, e)

    fast = client.post("/sensitivity", json={"method": "surrogate"}).json()
    assert wait(client, fast)["status"] == "done"
    s = client.get(f"/results/{fast['result_id']}").json()
    assert not s["errors"]
    spreads = [abs(t["kpis"]["irr_equity"]["high"] - t["kpis"]["irr_equity"]["low"]) for t in s["tornado"]]
    assert spreads == sorted(spreads, reverse=True)
    assert len(s["grid"]["kpis"]["irr_equity"]) == len(s["grid"]["prices"])
    assert len(s["grid"]["kpis"]["irr_equity"][0]) == len(s["grid"]["utilizations"])

    exact_job = client.post("/sensitivity", json={"method": "exact", "parameters": ["params.price.flat_usd_per_mwh"],
                                                  "prices": [165.0], "utilizations": [1.0]}).json()
    assert wait(client, exact_job)["status"] == "done"
    sx = client.get(f"/results/{exact_job['result_id']}").json()
    _, high = simulate(client, {"scenario": scenario(price={"flat_usd_per_mwh": 165})})
    assert sx["tornado"][0]["kpis"]["irr_equity"]["high"] == pytest.approx(kpi(high, "irr_equity")["value"], rel=1e-9)
    assert sx["grid"]["kpis"]["irr_equity"][0][0] == pytest.approx(kpi(high, "irr_equity")["value"], rel=1e-9)
