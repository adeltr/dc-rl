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
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .spec import INPUT_SHEET, INPUTS_BY_NAME

ITERATION_COUNT = 250
EXCEL_ERRORS = {"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!", "#GETTING_DATA",
                "#SPILL!", "#CALC!", "#FIELD!", "#BLOCKED!", "#CONNECT!", "#BUSY!", "#UNKNOWN!", "#PYTHON!"}
ITERATION_EPSILON = 1e-5


class EngineUnavailable(RuntimeError):
    pass


class EngineError(RuntimeError):
    pass


class ExcelEngine(ABC):
    name: str
    # dossier où créer la copie de travail (None : dossier temporaire du système)
    workdir_root: Path | None = None

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


def _uno_env(soffice: str) -> dict[str, str]:
    """Variables pour importer ``uno`` hors du Python système : dossiers de uno.py / pyuno
    (``program`` sous Windows et Linux, ``Contents/Resources`` et ``Frameworks`` sous macOS)
    et fichier d'amorçage de l'URE."""
    program = Path(soffice).resolve().parent
    dirs = [d for d in (program, program.parent / "Resources", program.parent / "Frameworks")
            if (d / "uno.py").exists() or any(d.glob("pyuno*"))]
    env = {"TWIN_UNO_PATH": os.pathsep.join(str(d) for d in dirs)} if dirs else {}
    for d in dirs:
        for name in ("fundamentalrc", "fundamental.ini"):
            if (d / name).exists() and "URE_BOOTSTRAP" not in os.environ:
                env["URE_BOOTSTRAP"] = "vnd.sun.star.pathname:" + str(d / name)
    return env


def _find_uno_python(soffice: str) -> tuple[str | None, list[str]]:
    """Un Python capable d'``import uno`` : celui de LibreOffice, sinon le Python système.
    Renvoie aussi les candidats essayés, pour le message d'erreur."""
    candidates = [os.environ.get("TWIN_LO_PYTHON")]
    program = Path(soffice).resolve().parent
    contents = program.parent
    candidates += [str(program / "python.exe"), str(program / "python"), str(contents / "Resources" / "python")]
    # macOS récent : Python embarqué dans LibreOfficePython.framework
    framework = contents / "Frameworks" / "LibreOfficePython.framework" / "Versions"
    candidates += sorted(str(p) for p in framework.glob("*/Resources/Python.app/Contents/MacOS/LibreOfficePython"))
    candidates += sorted(str(p) for p in framework.glob("*/bin/python3*") if not p.name.endswith("-config"))
    candidates += [shutil.which("python3"), "/usr/bin/python3", sys.executable]
    env = {**os.environ, **_uno_env(soffice)}
    tried = []
    for candidate in candidates:
        if not candidate or not Path(candidate).exists() or candidate in tried:
            continue
        tried.append(candidate)
        probe = subprocess.run(
            [candidate, "-I", "-c",
             "import os, sys; sys.path[:0] = [p for p in os.environ.get('TWIN_UNO_PATH', '').split(os.pathsep) if p]; "
             "import uno"],
            capture_output=True, env=env)
        if probe.returncode == 0:
            return candidate, tried
    return None, tried


class LibreOfficeEngine(ExcelEngine):
    name = "libreoffice"

    def __init__(self):
        soffice = _find_soffice()
        if soffice is None:
            raise EngineUnavailable("LibreOffice introuvable (soffice).")
        python, tried = _find_uno_python(soffice)
        if python is None:
            raise EngineUnavailable(f"Aucun Python avec le module uno parmi {tried or 'aucun candidat'} "
                                    f"(LibreOffice : {soffice} ; définir TWIN_LO_PYTHON).")
        worker = Path(__file__).with_name("lo_worker.py")
        self._proc = subprocess.Popen([python, "-I", str(worker), soffice], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True, bufsize=1,
                                      env={**os.environ, **_uno_env(soffice)})
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
        self._windows = platform.system() == "Windows"
        if self._windows:
            self._app = xw.App(visible=False, add_book=False)
        else:
            self._app = self._mac_app()
        self._app.display_alerts = False
        self._app.screen_updating = False
        self._book = None
        if not self._windows:
            # Excel pour Mac est sandboxé : il n'ouvre sans demande que les fichiers de son conteneur
            self.workdir_root = Path.home() / "Library" / "Containers" / "com.microsoft.Excel" / "Data" / "dctwin"
            self.workdir_root.mkdir(parents=True, exist_ok=True)

    def open(self, path: Path) -> None:
        self.close_book()
        if self._windows:
            self._book = self._app.books.open(str(path), update_links=False)
        else:
            self._book = self._open_mac(path)
        if self._windows:
            self._app.api.Iteration = True
            self._app.api.MaxIterations = ITERATION_COUNT
            self._app.api.MaxChange = ITERATION_EPSILON
        else:  # macOS (appscript)
            self._app.api.iteration.set(True)
            self._app.api.max_iterations.set(ITERATION_COUNT)
            self._app.api.max_change.set(ITERATION_EPSILON)
        # calcul manuel : sinon Excel recalcule tout le classeur (circulaire) à chaque cellule écrite
        self._app.calculation = "manual"
        self._ranges = {}
        self._input_block = None
        self.recalculate(full=True)

    def _mac_app(self):
        """Excel pour Mac gère mal une instance lancée en arrière-plan par xlwings : on lance Excel
        normalement s'il n'est pas ouvert, puis on pilote cette instance."""
        if not self._xw.apps:
            subprocess.run(["open", "-g", "-a", "Microsoft Excel"], check=False)
            for _ in range(60):
                if self._xw.apps:
                    break
                time.sleep(1)
            else:
                raise EngineUnavailable("Excel n'a pas démarré (open -a 'Microsoft Excel').")
        return self._xw.apps.active

    def _open_mac(self, path: Path):
        """``open_workbook`` d'AppleScript échoue parfois (« Parameter error », -50) ; la commande
        ``open`` avec une référence de fichier transmet en plus le droit d'accès au bac à sable."""
        try:
            return self._app.books.open(str(path))
        except Exception as first:
            try:
                import mactypes
                self._app.api.open(mactypes.Alias(str(path)))
                for _ in range(60):  # la commande open rend la main avant la fin du chargement
                    if path.name in [b.name for b in self._app.books]:
                        return self._app.books[path.name]
                    time.sleep(1)
                raise EngineError("classeur toujours absent après 60 s (fenêtre de dialogue dans Excel ?)")
            except Exception as second:
                raise EngineError(f"Excel n'a pas pu ouvrir {path} : {first} ; puis : {second}") from second

    def _range(self, name):
        """(feuille, 1re ligne, 1re colonne, nb lignes, nb colonnes) d'un nom, résolu une seule fois :
        chaque accès à Excel est un aller-retour AppleScript / COM coûteux."""
        if name not in self._ranges:
            rng = self._book.names[name].refers_to_range
            rows, cols = rng.shape
            self._ranges[name] = (rng.sheet.name, rng.row, rng.column, rows, cols)
        return self._ranges[name]

    def _block(self, sheet, r0, c0, r1, c1):
        return self._book.sheets[sheet].range((r0, c0), (r1, c1)).options(ndim=2)

    def _values(self, block):
        """Valeurs 2D, cellules en erreur rendues par leur texte (#DIV/0!…). ``err_to_str`` n'est pas
        utilisable sous macOS : xlwings y renvoie None pour une plage de plusieurs lignes."""
        if self._windows:
            return block.options(ndim=2, err_to_str=True).value
        values = block.value
        texts = block.api.string_value.get()
        if not isinstance(texts, list):
            texts = [[texts]]
        elif texts and not isinstance(texts[0], list):
            texts = [texts] if len(values) == 1 else [[t] for t in texts]
        for i, row in enumerate(texts):
            for j, text in enumerate(row):
                if isinstance(text, str) and text in EXCEL_ERRORS:
                    values[i][j] = text
        return values

    def _inputs(self):
        """Bloc contigu de la colonne Valeur d'Inputs_Twin, vérifié une fois (aucune formule),
        écrit ensuite d'un seul coup."""
        if self._input_block is None:
            rows = {}
            for name in INPUTS_BY_NAME:
                sheet, row, col, n_rows, n_cols = self._range(name)
                if sheet != INPUT_SHEET or (n_rows, n_cols) != (1, 1):
                    raise PermissionError(f"{name} n'est pas une cellule de la feuille {INPUT_SHEET}")
                rows[name] = (row, col)
            cols = {c for _, c in rows.values()}
            if len(cols) != 1:
                raise PermissionError(f"Les entrées de {INPUT_SHEET} ne sont pas dans une seule colonne")
            col = cols.pop()
            r0, r1 = min(r for r, _ in rows.values()), max(r for r, _ in rows.values())
            block = self._block(INPUT_SHEET, r0, col, r1, col)
            formulas = block.formula  # selon la plateforme : liste de lignes ou liste plate
            formulas = [f[0] if isinstance(f, (list, tuple)) else f
                        for f in (formulas if isinstance(formulas, (list, tuple)) else [formulas])]
            for name, (row, _) in rows.items():
                if str(formulas[row - r0]).startswith("="):
                    raise PermissionError(f"{name} contient une formule : écriture refusée")
            values = [row[0] for row in block.value]
            self._input_block = (r0, col, r1, rows, values)
        return self._input_block

    def _write(self, values):
        r0, col, r1, rows, current = self._inputs()
        for name, value in values.items():
            if name not in rows:
                raise PermissionError(f"{name} n'est pas sur la feuille {INPUT_SHEET}")
            current[rows[name][0] - r0] = float(value)
        # cellules hors entrées éventuelles (lignes intermédiaires) : valeurs relues inchangées
        self._block(INPUT_SHEET, r0, col, r1, col).value = [[v] for v in current]

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
        """Lit tous les noms demandés avec un seul accès par feuille (rectangle englobant)."""
        located = {name: self._range(name) for name in names}
        blocks = {}
        for sheet in {loc[0] for loc in located.values()}:
            locs = [loc for loc in located.values() if loc[0] == sheet]
            r0, c0 = min(l[1] for l in locs), min(l[2] for l in locs)
            r1, c1 = max(l[1] + l[3] - 1 for l in locs), max(l[2] + l[4] - 1 for l in locs)
            blocks[sheet] = (r0, c0, self._values(self._block(sheet, r0, c0, r1, c1)))
        out = {}
        for name, (sheet, row, col, n_rows, n_cols) in located.items():
            r0, c0, data = blocks[sheet]
            cells = [[self._clean(v) for v in line[col - c0:col - c0 + n_cols]]
                     for line in data[row - r0:row - r0 + n_rows]]
            out[name] = cells if n_rows * n_cols > 1 else cells[0][0]
        return out

    def read_cells(self, sheet, refs):
        ws = self._book.sheets[sheet]
        return {ref: self._clean(ws.range(ref).value) for ref in refs}

    def save_as(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if self._windows:
            self._book.api.SaveCopyAs(str(Path(path).resolve()))
        else:  # macOS : pas de SaveCopyAs ; enregistrer sur place (dans le conteneur) puis copier
            self._book.save()
            shutil.copy2(self._book.fullname, Path(path).resolve())

    def close_book(self) -> None:
        if self._book is not None:
            self._book.close()
            self._book = None
            self._app.calculation = "automatic"  # instance éventuellement partagée avec l'utilisateur

    def close(self) -> None:
        self.close_book()
        if self._windows:  # sous macOS, l'instance d'Excel est partagée avec l'utilisateur
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
