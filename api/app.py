"""API du jumeau numérique (FastAPI).

Lancement : ``uvicorn api.app:app --port 8000`` (ou ``make api``).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from twin import defaults as D
from twin.datasources import DATA_DIR, DataUnavailable, _weather_from_file, site_catalog, workload_traces
from twin.params import Price
from twin.pricing import hourly_prices

from .catalog import parameter_catalog
from .kpis import KPIS
from .scenario import ScenarioInput, effective_values
from .service import ServiceError, TwinService
from .store import BASE_ID, SavedScenario

logging.basicConfig(level=os.environ.get("TWIN_LOG_LEVEL", "INFO"))
UPLOAD_DIR = DATA_DIR / "uploads"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "service", None) is None:
        app.state.service = TwinService()
    yield
    app.state.service.shutdown()


app = FastAPI(title="Jumeau numérique de data center", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("TWIN_CORS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])


def service(request: Request) -> TwinService:
    return request.app.state.service


@app.exception_handler(ServiceError)
async def service_error(_request: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.exception_handler(DataUnavailable)
async def data_unavailable(_request: Request, exc: DataUnavailable):
    return JSONResponse(status_code=424, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def invalid_value(_request: Request, exc: ValueError):
    """Paramètre incohérent détecté pendant le calcul (ex. tarif CSV sans fichier) : 422, jamais 500."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimulateRequest(_Body):
    scenario: ScenarioInput = Field(default_factory=ScenarioInput)
    client_id: str | None = Field(None, description="les demandes en attente du même client sont annulées")


class PreviewRequest(_Body):
    scenario: ScenarioInput = Field(default_factory=ScenarioInput)


class SaveScenarioRequest(_Body):
    name: str = Field(min_length=1, max_length=120)
    scenario: ScenarioInput
    result_id: str | None = None


class PatchScenarioRequest(_Body):
    name: str | None = Field(None, min_length=1, max_length=120)
    scenario: ScenarioInput | None = None
    result_id: str | None = None


class SensitivityRequest(_Body):
    scenario: ScenarioInput | None = None
    pct: float = Field(0.10, gt=0, le=0.9, description="variation ± du tornado (0,10 = ±10 %)")
    parameters: list[str] | None = Field(None, description="chemins du catalogue ; défaut : paramètres marqués sensitivity")
    prices: list[float] | None = Field(None, description="prix de l'électricité de la grille ($/MWh)")
    utilizations: list[float] | None = Field(None, description="taux d'utilisation de la grille (0–1)")
    tornado: bool = True
    grid: bool = True
    method: str = Field("exact", pattern="^(exact|surrogate)$")
    client_id: str | None = None


# ---------------------------------------------------------------------- méta

@app.get("/health")
def health(request: Request):
    svc = service(request)
    return {"base_ready": svc.base_ready.is_set(), "engine": svc.bridge.engine.name if svc.bridge else None,
            "bridge_error": svc.bridge_error, "base_twin_error": svc.base_twin_error,
            "surrogate_ready": svc.surrogate is not None}


@app.get("/meta")
def meta(request: Request):
    svc = service(request)
    return {
        "parameters": [p.model_dump() for p in parameter_catalog()],
        "kpis": [k.model_dump() for k in KPIS],
        "sites": list(site_catalog().values()),
        "workload_traces": workload_traces(),
        "defaults": D.raw_defaults(),
        "tou_period": {  # éditeur des plages horaires du tarif
            "price": {"min": 0, "max": 1000, "step": 1, "unit": "$/MWh"},
            "hours": {"min": 0, "max": 24},
            "days": [{"value": "all", "label": "Tous les jours"}, {"value": "weekday", "label": "Jours ouvrés"},
                     {"value": "weekend", "label": "Week-end"}],
            "months": [{"value": m, "label": l} for m, l in enumerate(
                ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."], 1)],
        },
        "engine": svc.bridge.engine.name if svc.bridge else None,
        "surrogate_ready": svc.surrogate is not None,
    }


@app.get("/scenario/base")
def scenario_base(request: Request):
    svc = service(request)
    svc.base_ready.wait(120)
    result = svc.store.get_result(BASE_ID)
    return {
        "scenario": svc.base.model_dump(mode="json"),
        "effective": effective_values(svc.base, svc.manifest, svc.base_twin) if svc.bridge else None,
        "result": result.model_dump(mode="json") if result else None,
        "base_twin_error": svc.base_twin_error,
        "bridge_error": svc.bridge_error,
    }


# ---------------------------------------------------------------------- simulation

@app.post("/simulate", status_code=202)
def simulate(body: SimulateRequest, request: Request):
    job, result_id = service(request).simulate(body.scenario, body.client_id)
    return {"job_id": job.id, "result_id": result_id, "events": f"/simulate/{job.id}/events"}


@app.get("/simulate/{job_id}")
def job_status(job_id: str, request: Request):
    job = service(request).jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Tâche inconnue")
    return job.model_dump(exclude={"events"})


@app.get("/simulate/{job_id}/events")
async def job_events(job_id: str, request: Request):
    """Progression en Server-Sent Events : en attente → simulation physique → recalcul Excel → terminé."""
    svc = service(request)
    if svc.jobs.get(job_id) is None:
        raise HTTPException(404, "Tâche inconnue")
    last = request.headers.get("last-event-id")
    start = int(last) if last and last.isdigit() else 0

    async def stream():
        seq = start
        yield "retry: 2000\n\n"
        while True:
            events = await asyncio.to_thread(svc.jobs.events_since, job_id, seq, 10.0)
            for event in events:
                seq = event.seq
                yield f"id: {event.seq}\nevent: {event.status}\ndata: {event.model_dump_json()}\n\n"
            job = svc.jobs.get(job_id)
            if job.finished and not [e for e in job.events if e.seq > seq]:
                return
            if not events:
                yield ": keep-alive\n\n"
            if await request.is_disconnected():
                return

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/preview")
def preview(body: PreviewRequest, request: Request):
    """Aperçu immédiat : physique exacte, finances estimées par le surrogate (status = provisional)."""
    return service(request).preview(body.scenario).model_dump(mode="json")


@app.get("/results/{result_id}")
def get_result(result_id: str, request: Request):
    result = service(request).store.get_result(result_id)
    if result is None:
        raise HTTPException(404, "Résultat inconnu (calcul en cours ou identifiant erroné)")
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------- scénarios

@app.get("/scenarios")
def list_scenarios(request: Request):
    return [s.model_dump(mode="json") for s in service(request).store.list_scenarios()]


@app.post("/scenarios", status_code=201)
def save_scenario(body: SaveScenarioRequest, request: Request):
    store = service(request).store
    saved = SavedScenario(id=store.new_id(), name=body.name, scenario=body.scenario, result_id=body.result_id)
    return store.upsert_scenario(saved).model_dump(mode="json")


@app.patch("/scenarios/{scenario_id}")
def patch_scenario(scenario_id: str, body: PatchScenarioRequest, request: Request):
    store = service(request).store
    saved = store.get_scenario(scenario_id)
    if saved is None:
        raise HTTPException(404, "Scénario inconnu")
    if saved.locked:
        raise HTTPException(403, "Le cas de base est verrouillé")
    update = body.model_dump(exclude_unset=True)
    if "scenario" in update:
        update["scenario"] = body.scenario
    return store.upsert_scenario(saved.model_copy(update=update)).model_dump(mode="json")


@app.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str, request: Request):
    store = service(request).store
    saved = store.get_scenario(scenario_id)
    if saved is None:
        raise HTTPException(404, "Scénario inconnu")
    if saved.locked:
        raise HTTPException(403, "Le cas de base est verrouillé")
    store.delete_scenario(scenario_id)


@app.get("/compare")
def compare(request: Request, ids: str = Query(..., description="identifiants de résultats séparés par des virgules")):
    id_list = [i for i in ids.split(",") if i]
    if not 1 <= len(id_list) <= 5:
        raise HTTPException(422, "1 à 5 identifiants")
    return service(request).compare(id_list)


# ---------------------------------------------------------------------- sensibilités, export, données

@app.post("/sensitivity", status_code=202)
def sensitivity(body: SensitivityRequest, request: Request):
    svc = service(request)
    job, result_id = svc.sensitivity(body.scenario or svc.base, body.pct, body.parameters, body.prices,
                                     body.utilizations, body.method, body.tornado, body.grid, body.client_id)
    return {"job_id": job.id, "result_id": result_id, "events": f"/simulate/{job.id}/events"}


@app.get("/export/{result_id}.xlsx")
def export(result_id: str, request: Request):
    if not re.fullmatch(r"[A-Za-z0-9_]+", result_id):
        raise HTTPException(404, "Résultat inconnu")
    path = service(request).export(result_id)
    return FileResponse(path, filename=f"scenario_{result_id}.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.put("/data/weather/{filename}", status_code=201)
async def upload_weather(filename: str, request: Request):
    """Météo fournie à la main (EPW ou CSV temp_c, rh_pct, pressure_pa) : renvoie le chemin à
    placer dans ``params.data.weather_file``."""
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.(epw|csv)", filename, flags=re.I):
        raise HTTPException(422, "Nom de fichier attendu : lettres, chiffres, . _ - ; extension .epw ou .csv")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / filename
    path.write_bytes(await request.body())
    try:
        _weather_from_file(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Fichier météo invalide : {exc}") from exc
    return {"weather_file": str(Path(path).resolve())}


@app.put("/data/price/{filename}", status_code=201)
async def upload_price(filename: str, request: Request):
    """Tarif horaire fourni à la main (CSV : une ligne d'en-tête, 8 760 prix en $/MWh dans la dernière
    colonne) : renvoie le chemin à placer dans ``params.price.csv_file``."""
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.csv", filename, flags=re.I):
        raise HTTPException(422, "Nom de fichier attendu : lettres, chiffres, . _ - ; extension .csv")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / filename
    path.write_bytes(await request.body())
    try:
        prices, _ = hourly_prices(Price(mode="csv", csv_file=str(path)))
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Tarif invalide : {exc}") from exc
    return {"csv_file": str(Path(path).resolve()), "hours": len(prices),
            "min": float(prices.min()), "max": float(prices.max()), "mean": float(prices.mean())}
