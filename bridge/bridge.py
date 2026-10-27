"""Pont jumeau ↔ classeur : écrit Inputs_Twin, recalcule, résout l'equity, lit Outputs."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from twin.results import TwinResults
from twin.vendor import REPO_ROOT

from .build import build_bridge_workbook
from .engines import ExcelEngine, select_engine
from .mapping import MarketAssumptions, workbook_inputs
from .spec import MONTHLY_OUTPUTS, SCALAR_OUTPUTS, SERIES_OUTPUTS

SOURCE_WORKBOOK = Path(os.environ.get("TWIN_WORKBOOK", REPO_ROOT / "model" / "Data-Center-Development-Model-v1.7.xlsm"))
BRIDGE_WORKBOOK = Path(os.environ.get("TWIN_BRIDGE_WORKBOOK", REPO_ROOT / "build" / "twin_model.xlsm"))
EXPORT_DIR = Path(os.environ.get("TWIN_EXPORT_DIR", REPO_ROOT / "exports"))
LOG_PATH = Path(os.environ.get("TWIN_SCENARIO_LOG", REPO_ROOT / "logs" / "scenarios.jsonl"))

LTC_ACCEPT = 1e-6     # écart LTC accepté sans relancer le solveur (goal seek du classeur : 1,1e-7)
LTC_TOLERANCE = 1e-9  # précision visée quand le solveur tourne
MAX_SOLVER_ITERATIONS = 30
SCALAR_NAMES = [name for name, *_ in SCALAR_OUTPUTS] + ["out_dscr_min", "out_dscr_avg"]
SERIES_NAMES = [name for name, *_ in SERIES_OUTPUTS] + ["out_dscr"]
MONTHLY_NAMES = [name for name, _ in MONTHLY_OUTPUTS]


class WorkbookResults(BaseModel):
    engine: str
    duration_s: float
    solver_iterations: int
    ltc_error: float
    recalc_ok: bool
    inputs: dict[str, float]
    outputs: dict[str, Any]          # scalaires ; None si vide ou en erreur
    years: list[int]                 # années d'analyse jusqu'à la vente
    series: dict[str, list[float | None]]
    monthly: dict[str, list[float | None]] = {}  # flux mensuels (mois 0 à 132) ; None hors analyse
    errors: dict[str, Any]
    export_path: str | None = None


def ensure_bridge_workbook(source: Path = SOURCE_WORKBOOK, target: Path = BRIDGE_WORKBOOK) -> dict:
    """Construit la copie pont si elle est absente ou plus ancienne que le classeur source."""
    manifest_path = target.with_suffix(".manifest.json")
    if not source.exists():
        raise FileNotFoundError(
            f"Classeur introuvable : {source}. Copiez le .xlsm à cet emplacement "
            f"(sous ce nom exact) ou indiquez son chemin avec TWIN_WORKBOOK, puis relancez l'API.")
    if (not target.exists() or not manifest_path.exists()
            or target.stat().st_mtime < source.stat().st_mtime
            or target.stat().st_mtime < Path(__file__).with_name("spec.py").stat().st_mtime):
        return build_bridge_workbook(source, target)
    return json.loads(manifest_path.read_text())


def _clean(value):
    if isinstance(value, dict) or value == "":
        return None
    return value


class ExcelBridge:
    def __init__(self, engine: ExcelEngine | None = None, workbook: Path = BRIDGE_WORKBOOK,
                 source: Path = SOURCE_WORKBOOK):
        self.manifest = ensure_bridge_workbook(source, workbook)
        self.workbook = workbook
        # copie privée : plusieurs processus peuvent travailler sans conflit de verrou
        self._workdir = Path(tempfile.mkdtemp(prefix="dctwin_wb_"))
        self.working_copy = self._workdir / workbook.name
        shutil.copy2(workbook, self.working_copy)
        self.engine = engine or select_engine()
        self.engine.open(self.working_copy)
        self._lock = threading.Lock()

    @property
    def base_inputs(self) -> dict[str, float]:
        return {name: spec["value"] for name, spec in self.manifest["inputs"].items()}

    def close(self) -> None:
        self.engine.close()
        shutil.rmtree(self._workdir, ignore_errors=True)

    # ------------------------------------------------------------------ calcul
    def run_inputs(self, inputs: dict[str, float], export_path: Path | None = None) -> WorkbookResults:
        """Écrit un jeu complet d'entrées (base + surcharges), recalcule et lit les sorties."""
        with self._lock:
            t0 = time.perf_counter()
            full = {**self.base_inputs, **inputs}
            self.engine.write_inputs(full)
            self.engine.recalculate()
            iterations, ltc_error = self._solve_equity(full)
            values = self.engine.read(SCALAR_NAMES + SERIES_NAMES + MONTHLY_NAMES + ["out_years"])
            if export_path is not None:
                self.engine.save_as(export_path)
            duration = time.perf_counter() - t0

        errors = {k: v for k, v in values.items() if isinstance(v, dict)}
        outputs = {name: _clean(values[name]) for name in SCALAR_NAMES}
        end_year = int(-(-outputs["out_analysis_end_month"] // 12))
        years = [int(y) for y in values["out_years"][0] if y <= end_year]
        series = {}
        for name in SERIES_NAMES:
            row = values[name][0]
            series[name] = [_clean(v) for v in row[:len(years)]]
            errors.update({f"{name}[{i}]": v for i, v in enumerate(row[:len(years)]) if isinstance(v, dict)})
        monthly = {name: [v if isinstance(v, (int, float)) else None for v in values[name][0]] for name in MONTHLY_NAMES}
        return WorkbookResults(
            engine=self.engine.name, monthly=monthly, duration_s=duration, solver_iterations=iterations, ltc_error=ltc_error,
            recalc_ok=bool(outputs["out_recalc_ok"]), inputs=full, outputs=outputs, years=years, series=series,
            errors=errors, export_path=str(export_path) if export_path else None)

    def run(self, twin: TwinResults, twin_base: TwinResults, market: MarketAssumptions | None = None,
            export_path: Path | None = None, scenario_id: str | None = None) -> WorkbookResults:
        market = market or MarketAssumptions()
        inputs = workbook_inputs(twin, twin_base, market, self.manifest)
        result = self.run_inputs(inputs, export_path)
        log_workbook_run(scenario_id or twin.params_hash, twin.params_hash, market, result)
        return result

    def _solve_equity(self, inputs: dict[str, float]) -> tuple[int, float]:
        """Equity telle que LTC réel = LTC cible ; remplace le goal seek de Recalculate_Const.

        LTC réel = 1 − E / coût(E) : on cherche le zéro de h(E) = E − (1 − cible) × coût(E).
        Premier pas par point fixe, puis sécante (le coût dépend faiblement de E via les intérêts).
        """
        def evaluate(equity: float | None) -> tuple[float, float]:
            if equity is not None:
                self.engine.write_inputs({"tw_equity_total": equity})
                self.engine.recalculate()
            r = self.engine.read(["out_ltc_actual", "out_ltc_target", "out_capex_total", "out_equity"])
            return r["out_ltc_actual"] - r["out_ltc_target"], r["out_equity"] - (1 - r["out_ltc_target"]) * r["out_capex_total"]

        ltc_error, h0 = evaluate(None)
        if abs(ltc_error) <= LTC_ACCEPT:
            return 0, ltc_error
        e0 = inputs["tw_equity_total"]
        e1 = e0 - h0  # point fixe : E = (1 − cible) × coût(E)
        for iteration in range(1, MAX_SOLVER_ITERATIONS + 1):
            ltc_error, h1 = evaluate(e1)
            if abs(ltc_error) <= LTC_TOLERANCE:
                inputs["tw_equity_total"] = e1
                return iteration, ltc_error
            slope = (h1 - h0) / (e1 - e0) if e1 != e0 else 1.0
            e0, h0, e1 = e1, h1, e1 - h1 / slope
        raise RuntimeError(f"Solveur d'equity non convergé (écart LTC {ltc_error:.2e}).")


def log_workbook_run(scenario_id: str, params_hash: str, market: MarketAssumptions, result: WorkbookResults) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    keys = ("out_irr_project", "out_irr_equity", "out_npv", "out_capex_total", "out_opex_energy_y1",
            "out_dscr_min", "out_llcr", "out_equity")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "workbook",
        "scenario_id": scenario_id,
        "params_hash": params_hash,
        "engine": result.engine,
        "duration_s": round(result.duration_s, 4),
        "solver_iterations": result.solver_iterations,
        "market": market.model_dump(),
        "outputs": {k: result.outputs.get(k) for k in keys},
        "recalc_ok": result.recalc_ok,
        "export_path": result.export_path,
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
