"""Persistance des résultats et des scénarios sauvegardés (fichiers JSON sous ``store/``)."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from bridge.bridge import WorkbookResults
from twin.results import TwinResults
from twin.vendor import REPO_ROOT

from .kpis import Alert, KpiValue
from .scenario import ScenarioInput

STORE_DIR = Path(os.environ.get("TWIN_STORE_DIR", REPO_ROOT / "store"))
BASE_ID = "base"


class ScenarioResult(BaseModel):
    id: str
    kind: Literal["scenario"] = "scenario"
    status: Literal["provisional", "confirmed", "error"]
    created_at: float = Field(default_factory=time.time)
    scenario: ScenarioInput
    twin: TwinResults | None = None
    workbook: WorkbookResults | None = None
    # aperçu : sorties du classeur estimées par le surrogate (valeurs provisoires)
    estimated_outputs: dict[str, float | None] | None = None
    estimated_series: dict[str, list[float | None]] | None = None
    estimated_years: list[int] | None = None
    kpis: list[KpiValue] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    error: str | None = None
    durations_s: dict[str, float] = Field(default_factory=dict)


class SensitivityResult(BaseModel):
    id: str
    kind: Literal["sensitivity"] = "sensitivity"
    created_at: float = Field(default_factory=time.time)
    method: str
    scenario: ScenarioInput
    tornado: list[dict[str, Any]] | None = None
    grid: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


class SavedScenario(BaseModel):
    id: str
    name: str
    locked: bool = False
    scenario: ScenarioInput
    result_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class Store:
    def __init__(self, root: Path = STORE_DIR):
        self.root = root
        (root / "results").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._results: dict[str, ScenarioResult | SensitivityResult] = {}
        self._scenarios_path = root / "scenarios.json"
        self._scenarios: dict[str, SavedScenario] = {}
        if self._scenarios_path.exists():
            for item in json.loads(self._scenarios_path.read_text()):
                saved = SavedScenario.model_validate(item)
                self._scenarios[saved.id] = saved

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------ résultats
    def put_result(self, result: ScenarioResult | SensitivityResult) -> None:
        with self._lock:
            self._results[result.id] = result
            path = self.root / "results" / f"{result.id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(result.model_dump_json())
            tmp.replace(path)

    def get_result(self, result_id: str) -> ScenarioResult | SensitivityResult | None:
        with self._lock:
            if result_id in self._results:
                return self._results[result_id]
        path = self.root / "results" / f"{result_id}.json"
        if not path.exists() or not result_id.replace("_", "").isalnum():
            return None
        data = json.loads(path.read_text())
        model = SensitivityResult if data.get("kind") == "sensitivity" else ScenarioResult
        result = model.model_validate(data)
        with self._lock:
            self._results[result_id] = result
        return result

    # ------------------------------------------------------------------ scénarios sauvegardés
    def _save_scenarios(self) -> None:
        tmp = self._scenarios_path.with_suffix(".tmp")
        tmp.write_text(json.dumps([s.model_dump(mode="json") for s in self._scenarios.values()], ensure_ascii=False))
        tmp.replace(self._scenarios_path)

    def list_scenarios(self) -> list[SavedScenario]:
        return sorted(self._scenarios.values(), key=lambda s: (not s.locked, s.created_at))

    def get_scenario(self, scenario_id: str) -> SavedScenario | None:
        return self._scenarios.get(scenario_id)

    def upsert_scenario(self, saved: SavedScenario) -> SavedScenario:
        with self._lock:
            saved.updated_at = time.time()
            self._scenarios[saved.id] = saved
            self._save_scenarios()
        return saved

    def delete_scenario(self, scenario_id: str) -> None:
        with self._lock:
            self._scenarios.pop(scenario_id, None)
            self._save_scenarios()
