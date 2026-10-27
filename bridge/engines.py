"""Moteurs de calcul du classeur : interface ``ExcelEngine`` et deux implémentations.

- ``XlwingsEngine`` : Excel installé (Windows / macOS), recalcul fidèle ;
- ``LibreOfficeEngine`` : LibreOffice headless, itération activée pour les circularités.

``select_engine()`` choisit automatiquement (``TWIN_EXCEL_ENGINE`` = auto | xlwings | libreoffice).

Règle commune : seules les plages ``tw_*`` de la feuille Inputs_Twin peuvent être
écrites, et jamais une cellule contenant une formule.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .spec import INPUT_SHEET, INPUTS_BY_NAME

ITERATION_COUNT = 250
ITERATION_EPSILON = 1e-5


class EngineUnavailable(RuntimeError):
    pass


class EngineError(RuntimeError):
    pass


class ExcelEngine(ABC):
    name: str

    @abstractmethod
    def open(self, path: Path) -> None: ...

    def write_inputs(self, values: dict[str, float]) -> None:
        unknown = [n for n in values if n not in INPUTS_BY_NAME]
        if unknown:
            raise PermissionError(f"Écriture refusée hors Inputs_Twin : {unknown}")
        self._write(values)

    @abstractmethod
    def _write(self, values: dict[str, float]) -> None: ...

    @abstractmethod
    def recalculate(self, full: bool = False) -> None: ...

    @abstractmethod
    def read(self, names: list[str]) -> dict[str, Any]: ...

    @abstractmethod
    def read_cells(self, sheet: str, refs: list[str]) -> dict[str, Any]: ...

    @abstractmethod
    def save_as(self, path: Path) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


# --------------------------------------------------------------------------- LibreOffice

def _find_soffice() -> str | None:
    for candidate in (os.environ.get("TWIN_SOFFICE"), shutil.which("soffice"), shutil.which("libreoffice"),
                      r"C:\Program Files\LibreOffice\program\soffice.exe",
                      "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _find_uno_python(soffice: str) -> str | None:
    """Un Python capable d'``import uno`` : celui de LibreOffice, sinon le Python système."""
    candidates = [os.environ.get("TWIN_LO_PYTHON")]
    program = Path(soffice).resolve().parent
    candidates += [str(program / "python.exe"), str(program / "python"),
                   str(program.parent / "Resources" / "python")]
    candidates += [shutil.which("python3"), "/usr/bin/python3", sys.executable]
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        probe = subprocess.run([candidate, "-c", "import uno"], capture_output=True)
        if probe.returncode == 0:
            return candidate
    return None


class LibreOfficeEngine(ExcelEngine):
    name = "libreoffice"

    def __init__(self):
        soffice = _find_soffice()
        if soffice is None:
            raise EngineUnavailable("LibreOffice introuvable (soffice).")
        python = _find_uno_python(soffice)
        if python is None:
            raise EngineUnavailable("Aucun Python avec le module uno (définir TWIN_LO_PYTHON).")
        worker = Path(__file__).with_name("lo_worker.py")
        self._proc = subprocess.Popen([python, "-I", str(worker), soffice], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True, bufsize=1)
        self._lock = threading.Lock()
        ready = json.loads(self._proc.stdout.readline() or "{}")
        if not ready.get("ready"):
            raise EngineUnavailable("Le worker LibreOffice n'a pas démarré.")

    def _call(self, cmd: str, **kwargs):
        with self._lock:
            if self._proc.poll() is not None:
                raise EngineError("Le worker LibreOffice s'est arrêté.")
            self._proc.stdin.write(json.dumps({"cmd": cmd, **kwargs}) + "\n")
            self._proc.stdin.flush()
            reply = json.loads(self._proc.stdout.readline())
        if not reply["ok"]:
            error = reply["error"]
            raise (PermissionError if error.startswith("PermissionError") else EngineError)(error)
        return reply["result"]

    def open(self, path: Path) -> None:
        self._call("open", path=str(path), iteration_count=ITERATION_COUNT, iteration_epsilon=ITERATION_EPSILON)

    def _write(self, values):
        self._call("set", values=values, sheet=INPUT_SHEET)

    def recalculate(self, full: bool = False) -> None:
        self._call("calc", full=full)

    def read(self, names):
        return self._call("get", names=list(names))

    def read_cells(self, sheet, refs):
        return self._call("get_cells", sheet=sheet, refs=list(refs))

    def save_as(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._call("save", path=str(path))

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self._call("quit")
            except EngineError:
                pass
            self._proc.wait(timeout=30)


# --------------------------------------------------------------------------- xlwings

class XlwingsEngine(ExcelEngine):
    """Excel piloté par xlwings. Non testable sous Linux ; vérifié par tests/test_bridge.py
    lorsque Excel est présent (TWIN_EXCEL_ENGINE=xlwings)."""

    name = "xlwings"

    def __init__(self):
        if platform.system() not in ("Windows", "Darwin"):
            raise EngineUnavailable("xlwings nécessite Excel (Windows ou macOS).")
        try:
            import xlwings as xw
        except ImportError as exc:
            raise EngineUnavailable("xlwings n'est pas installé (pip install xlwings).") from exc
        self._xw = xw
        self._app = xw.App(visible=False, add_book=False)
        self._app.display_alerts = False
        self._app.screen_updating = False
        self._book = None
        self._windows = platform.system() == "Windows"

    def open(self, path: Path) -> None:
        self.close_book()
        self._book = self._app.books.open(str(path), update_links=False)
        if self._windows:
            self._app.api.Iteration = True
            self._app.api.MaxIterations = ITERATION_COUNT
            self._app.api.MaxChange = ITERATION_EPSILON
        else:  # macOS (appscript)
            self._app.api.iteration.set(True)
            self._app.api.max_iterations.set(ITERATION_COUNT)
            self._app.api.max_change.set(ITERATION_EPSILON)
        self.recalculate(full=True)

    def _range(self, name):
        return self._book.names[name].refers_to_range

    def _write(self, values):
        for name, value in values.items():
            rng = self._range(name)
            if rng.sheet.name != INPUT_SHEET:
                raise PermissionError(f"{name} n'est pas sur la feuille {INPUT_SHEET}")
            if str(rng.formula).startswith("="):
                raise PermissionError(f"{name} contient une formule : écriture refusée")
            rng.value = float(value)

    def recalculate(self, full: bool = False) -> None:
        if full and self._windows:
            self._app.api.CalculateFull()
        else:
            self._app.calculate()

    @staticmethod
    def _clean(value):
        if isinstance(value, str) and value.startswith("#"):
            return {"error": value}
        return value

    def read(self, names):
        out = {}
        for name in names:
            rng = self._range(name)
            value = rng.value
            if rng.count > 1:
                rows = value if isinstance(value[0], list) else [value]
                out[name] = [[self._clean(v) for v in row] for row in rows]
            else:
                out[name] = self._clean(value)
        return out

    def read_cells(self, sheet, refs):
        ws = self._book.sheets[sheet]
        return {ref: self._clean(ws.range(ref).value) for ref in refs}

    def save_as(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if self._windows:
            self._book.api.SaveCopyAs(str(Path(path).resolve()))
        else:
            self._book.save(str(Path(path).resolve()))

    def close_book(self) -> None:
        if self._book is not None:
            self._book.close()
            self._book = None

    def close(self) -> None:
        self.close_book()
        self._app.quit()


# --------------------------------------------------------------------------- sélection

def select_engine(preference: str | None = None) -> ExcelEngine:
    preference = (preference or os.environ.get("TWIN_EXCEL_ENGINE", "auto")).lower()
    order = {"auto": [XlwingsEngine, LibreOfficeEngine], "xlwings": [XlwingsEngine],
             "libreoffice": [LibreOfficeEngine]}.get(preference)
    if order is None:
        raise ValueError(f"TWIN_EXCEL_ENGINE inconnu : {preference}")
    reasons = []
    for cls in order:
        try:
            return cls()
        except EngineUnavailable as exc:
            reasons.append(f"{cls.name}: {exc}")
    raise EngineUnavailable("Aucun moteur de calcul disponible — " + " ; ".join(reasons))
