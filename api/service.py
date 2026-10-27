"""Orchestration : cas de base, simulation (physique puis classeur), aperçu, sensibilités, export.

Le classeur n'est manipulé que depuis le thread du ``JobManager``.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from bridge.bridge import EXPORT_DIR, ExcelBridge, WorkbookResults
from bridge.mapping import workbook_inputs
from twin.datasources import DataUnavailable
from twin.engine import run_year
from twin.results import TwinResults

from .catalog import catalog_by_path
from .jobs import STAGE_EXCEL, STAGE_PHYSICS, JobContext, JobFailed, JobManager
from .kpis import KPIS, KPIS_BY_ID, compute_alerts, compute_kpis, kpi_raw
from .scenario import ScenarioInput, base_scenario, effective_values, get_path, set_path
from .store import BASE_ID, SavedScenario, ScenarioResult, SensitivityResult, Store
from .surrogate import GROUPS, FinanceSurrogate

log = logging.getLogger(__name__)
PRIORITY_USER, PRIORITY_SENSITIVITY, PRIORITY_SURROGATE = 0, 1, 9


class ServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class TwinService:
    def __init__(self, store: Store | None = None, bridge_factory=ExcelBridge, build_surrogate: bool = True):
        self.store = store or Store()
        self.jobs = JobManager()
        self.base = base_scenario()
        self.base_twin: TwinResults | None = None
        self.base_twin_error: str | None = None
        self.base_workbook: WorkbookResults | None = None
        self.bridge: ExcelBridge | None = None
        self.bridge_error: str | None = None
        self.surrogate: FinanceSurrogate | None = None
        self.base_ready = threading.Event()
        self._build_surrogate = build_surrogate
        self.init_job = self.jobs.submit("init", lambda ctx: self._init(ctx, bridge_factory), PRIORITY_USER)

    # ------------------------------------------------------------------ cas de base
    def _init(self, ctx: JobContext, bridge_factory) -> str:
        try:
            ctx.stage(STAGE_PHYSICS, 0.1, "cas de base")
            try:
                self.base_twin = run_year(self.base.params)
            except (DataUnavailable, ValueError) as exc:
                self.base_twin_error = str(exc)
                log.warning("physique du cas de base indisponible : %s", exc)
            ctx.stage(STAGE_EXCEL, 0.5, "cas de base")
            try:
                self.bridge = bridge_factory()
                self.base_workbook = self.bridge.run_inputs({})
            except Exception as exc:  # moteur absent, classeur absent…
                self.bridge_error = f"{type(exc).__name__}: {exc}"
                log.error("classeur indisponible : %s", self.bridge_error)
            result = ScenarioResult(
                id=BASE_ID, status="confirmed" if self.base_workbook else "error", scenario=self.base,
                twin=self.base_twin, workbook=self.base_workbook,
                kpis=compute_kpis(self.base_twin, self.base_workbook, self.base_twin, self.base_workbook),
                alerts=compute_alerts(self.base_twin, self.base_workbook, self.base.market.dscr_covenant),
                error="; ".join(e for e in (self.base_twin_error, self.bridge_error) if e) or None)
            self.store.put_result(result)
            self.store.upsert_scenario(SavedScenario(id=BASE_ID, name="Cas de base", locked=True,
                                                     scenario=self.base, result_id=BASE_ID))
        finally:
            self.base_ready.set()
        if self._build_surrogate and self.base_twin is not None and self.base_workbook is not None:
            self._schedule_surrogate()
        return BASE_ID

    def _schedule_surrogate(self) -> None:
        surrogate = FinanceSurrogate(self.bridge.base_inputs, self.base_workbook, self.bridge.manifest["context"])
        for group in GROUPS:
            def task(_ctx, group=group):
                surrogate.add(group, self.bridge.run_inputs(surrogate.perturbed_inputs(group)))
                if surrogate.ready:
                    self.surrogate = surrogate
                    log.info("surrogate financier prêt (%d groupes)", len(GROUPS))
            self.jobs.submit("surrogate", task, PRIORITY_SURROGATE, internal=True)

    def require_base(self, timeout: float = 120) -> None:
        if not self.base_ready.wait(timeout):
            raise ServiceError("Cas de base en cours de calcul", 503)
        if self.base_workbook is None:
            raise ServiceError(f"Classeur indisponible : {self.bridge_error}", 503)
        if self.base_twin is None:
            raise ServiceError(f"Physique du cas de base indisponible : {self.base_twin_error}", 424)

    @property
    def manifest(self) -> dict:
        if self.bridge is None:
            raise ServiceError(f"Classeur indisponible : {self.bridge_error}", 503)
        return self.bridge.manifest

    # ------------------------------------------------------------------ simulation complète
    def simulate(self, scenario: ScenarioInput, client_id: str | None = None):
        result_id = self.store.new_id()

        def task(ctx: JobContext) -> str:
            t0 = time.perf_counter()
            ctx.stage(STAGE_PHYSICS, 0.1)
            try:
                twin = run_year(scenario.params)
            except (DataUnavailable, ValueError) as exc:
                self._store_error(result_id, scenario, None, str(exc))
                raise JobFailed(str(exc), result_id) from exc
            durations = {"physics": time.perf_counter() - t0}
            ctx.stage(STAGE_EXCEL, 0.5)
            try:
                self.require_base(timeout=0)
                t1 = time.perf_counter()
                workbook = self.bridge.run(twin, self.base_twin, scenario.market, scenario_id=result_id)
                durations["workbook"] = time.perf_counter() - t1
            except Exception as exc:
                self._store_error(result_id, scenario, twin, str(exc))
                raise JobFailed(str(exc), result_id) from exc
            self.store.put_result(self._result(result_id, scenario, twin, workbook, "confirmed", durations))
            return result_id

        return self.jobs.submit("simulate", task, PRIORITY_USER, client_id=client_id), result_id

    def _result(self, result_id, scenario, twin, workbook, status, durations, estimate=None) -> ScenarioResult:
        outputs = workbook if workbook is not None else estimate
        return ScenarioResult(
            id=result_id, status=status, scenario=scenario, twin=twin, workbook=workbook,
            estimated_outputs=estimate,
            kpis=compute_kpis(twin, outputs, self.base_twin, self.base_workbook),
            alerts=compute_alerts(twin, outputs, scenario.market.dscr_covenant), durations_s=durations)

    def _store_error(self, result_id, scenario, twin, message) -> None:
        self.store.put_result(ScenarioResult(
            id=result_id, status="error", scenario=scenario, twin=twin, error=message,
            kpis=compute_kpis(twin, None, self.base_twin, self.base_workbook) if twin else [],
            alerts=compute_alerts(twin, None, scenario.market.dscr_covenant) if twin else []))

    # ------------------------------------------------------------------ aperçu
    def preview(self, scenario: ScenarioInput) -> ScenarioResult:
        """Physique exacte + finances estimées par le surrogate. Ne passe pas par le classeur."""
        t0 = time.perf_counter()
        twin = run_year(scenario.params)
        estimate, series = None, None
        if self.surrogate is not None and self.base_twin is not None:
            inputs = workbook_inputs(twin, self.base_twin, scenario.market, self.manifest)
            estimate, series = self.surrogate.estimate(inputs)
        result = self._result("preview", scenario, twin, None, "provisional",
                              {"preview": time.perf_counter() - t0}, estimate)
        result.estimated_series = series
        result.estimated_years = self.surrogate.years if self.surrogate else None
        return result

    # ------------------------------------------------------------------ sensibilités
    def sensitivity(self, scenario: ScenarioInput, pct: float, parameters: list[str] | None,
                    grid_prices: list[float] | None, grid_utilizations: list[float] | None,
                    method: str, include_tornado: bool, include_grid: bool, client_id: str | None = None):
        self.require_base(timeout=60)
        if method == "surrogate" and self.surrogate is None:
            raise ServiceError("Surrogate en cours de construction ; utiliser method=exact ou réessayer", 409)
        catalog = catalog_by_path()
        effective = effective_values(scenario, self.manifest)
        parameters = parameters or [p.path for p in catalog.values() if p.sensitivity]
        unknown = [p for p in parameters if p not in catalog]
        if unknown:
            raise ServiceError(f"Paramètres inconnus : {unknown}", 422)
        runs: list[tuple[str, dict]] = []
        tornado_plan = []
        if include_tornado:
            for path in parameters:
                spec, value = catalog[path], get_path(effective, path)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ServiceError(f"{path} n'est pas numérique : pas de tornado", 422)
                low, high = value * (1 - pct), value * (1 + pct)
                if spec.kind == "integer":
                    low, high = min(round(low), value - 1), max(round(high), value + 1)
                low, high = max(low, spec.min), min(high, spec.max)
                tornado_plan.append({"path": path, "label": spec.label, "unit": spec.unit, "base": value,
                                     "low": low, "high": high})
                runs += [(f"t:{path}:low", set_path(effective, path, low)),
                         (f"t:{path}:high", set_path(effective, path, high))]
        grid_plan = None
        if include_grid:
            price0 = get_path(effective, "params.price.flat_usd_per_mwh")
            prices = grid_prices or [round(price0 * f, 6) for f in (0.8, 0.9, 1.0, 1.1, 1.2)]
            utils = grid_utilizations or [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
            grid_plan = {"prices": prices, "utilizations": utils}
            for i, price in enumerate(prices):
                for j, util in enumerate(utils):
                    data = set_path(effective, "params.price.mode", "flat")
                    data = set_path(data, "params.price.flat_usd_per_mwh", price)
                    data = set_path(data, "params.load.mode", "constant")
                    runs.append((f"g:{i}:{j}", set_path(data, "params.load.utilization", util)))
        result_id = self.store.new_id()

        def task(ctx: JobContext) -> str:
            values: dict[str, dict[str, float | None]] = {}
            errors = []
            for n, (key, data) in enumerate(runs):
                ctx.stage(f"{STAGE_PHYSICS} / {STAGE_EXCEL}", n / max(len(runs), 1), f"{n + 1}/{len(runs)}")
                try:
                    values[key] = self._kpi_values(ScenarioInput.model_validate(data), method)
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
                    values[key] = {}
            base_values = self._kpi_values(scenario, method)
            tornado = None
            if tornado_plan:
                tornado = []
                for item in tornado_plan:
                    low, high = values[f"t:{item['path']}:low"], values[f"t:{item['path']}:high"]
                    tornado.append({**item, "kpis": {k.id: {"base": base_values.get(k.id), "low": low.get(k.id),
                                                            "high": high.get(k.id)} for k in KPIS}})
                key_kpi = "irr_equity"
                tornado.sort(key=lambda t: -abs((t["kpis"][key_kpi]["high"] or 0) - (t["kpis"][key_kpi]["low"] or 0)))
            grid = None
            if grid_plan:
                grid = {**grid_plan, "x": "params.price.flat_usd_per_mwh", "y": "params.load.utilization",
                        "kpis": {k.id: [[values[f"g:{i}:{j}"].get(k.id) for j in range(len(grid_plan["utilizations"]))]
                                        for i in range(len(grid_plan["prices"]))] for k in KPIS}}
            self.store.put_result(SensitivityResult(id=result_id, method=method, scenario=scenario, tornado=tornado,
                                                    grid=grid, errors=errors))
            return result_id

        return self.jobs.submit("sensitivity", task, PRIORITY_SENSITIVITY, client_id=client_id), result_id

    def _kpi_values(self, scenario: ScenarioInput, method: str) -> dict[str, float | None]:
        twin = run_year(scenario.params)
        if method == "surrogate":
            outputs, _ = self.surrogate.estimate(workbook_inputs(twin, self.base_twin, scenario.market, self.manifest))
        else:
            outputs = self.bridge.run(twin, self.base_twin, scenario.market).outputs
        return {k.id: kpi_raw(k, twin, outputs) for k in KPIS}

    # ------------------------------------------------------------------ export / comparaison
    def export(self, result_id: str) -> Path:
        result = self.store.get_result(result_id)
        if result is None or result.kind != "scenario":
            raise ServiceError("Résultat inconnu", 404)
        if result.workbook is None:
            raise ServiceError("Ce résultat n'a pas de classeur recalculé (aperçu ou erreur)", 409)
        path = EXPORT_DIR / f"{result_id}.xlsx"
        if not path.exists():
            self.jobs.run_sync("export", lambda: self.bridge.run_inputs(result.workbook.inputs, export_path=path))
        return path

    def compare(self, ids: list[str]) -> dict[str, Any]:
        items = []
        for result_id in ids:
            result = self.store.get_result(result_id)
            if result is None or result.kind != "scenario":
                raise ServiceError(f"Résultat inconnu : {result_id}", 404)
            items.append(result)
        names = {s.result_id: s.name for s in self.store.list_scenarios() if s.result_id}
        series_keys = ["out_cfads", "out_debt_service", "out_dscr", "out_noi", "out_cf_levered"]
        return {
            "kpis": [k.model_dump() for k in KPIS],
            "scenarios": [{
                "id": r.id, "name": names.get(r.id, r.id), "status": r.status,
                "kpis": {k.id: k.value for k in r.kpis},
                "years": r.workbook.years if r.workbook else None,
                "series": {k: r.workbook.series[k] for k in series_keys} if r.workbook else None,
                "pue_monthly": r.twin.pue_monthly if r.twin else None,
                "monthly_grid_mwh": r.twin.monthly_grid_mwh if r.twin else None,
            } for r in items],
        }

    def shutdown(self) -> None:
        self.jobs.stop()
        if self.bridge is not None:
            self.bridge.close()


def env_flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")
