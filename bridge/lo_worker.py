"""Worker LibreOffice headless, exécuté par un Python qui dispose du module ``uno``
(Python système sous Linux, ``program/python`` de LibreOffice sous Windows / macOS).

Protocole : une commande JSON par ligne sur stdin, une réponse JSON par ligne sur stdout.
Ce fichier n'importe rien du projet : il doit tourner avec n'importe quel Python 3.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.table.CellContentType import FORMULA

FORMULA_ERROR = 4  # com.sun.star.sheet.FormulaResult.ERROR
CELL_FLAG_FORMULA = 16  # com.sun.star.sheet.CellFlags.FORMULA
FILTERS = {".xlsx": "Calc MS Excel 2007 XML", ".xlsm": "Calc MS Excel 2007 VBA XML", ".ods": "calc8"}


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


class Worker:
    def __init__(self, soffice):
        self.pipe = f"dctwin_{uuid.uuid4().hex[:12]}"
        self.profile = tempfile.mkdtemp(prefix="dctwin_lo_")
        self.proc = subprocess.Popen(
            [soffice, "--headless", "--invisible", "--nologo", "--norestore", "--nodefault",
             f"-env:UserInstallation={uno.systemPathToFileUrl(self.profile)}",
             f"--accept=pipe,name={self.pipe};urp;StarOffice.ComponentContext"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        deadline = time.time() + 60
        while True:
            try:
                ctx = resolver.resolve(f"uno:pipe,name={self.pipe};urp;StarOffice.ComponentContext")
                break
            except Exception:
                if time.time() > deadline or self.proc.poll() is not None:
                    raise RuntimeError("LibreOffice n'a pas démarré")
                time.sleep(0.25)
        self.desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        self.doc = None

    # -- commandes
    def open(self, path, iteration_count=250, iteration_epsilon=1e-5):
        self.close()
        self._addresses = {}
        url = uno.systemPathToFileUrl(os.path.abspath(path))
        self.doc = self.desktop.loadComponentFromURL(url, "_blank", 0, (prop("Hidden", True), prop("ReadOnly", False)))
        if self.doc is None:
            raise RuntimeError(f"Ouverture impossible : {path}")
        self.doc.IsIterationEnabled = True
        self.doc.IterationCount = int(iteration_count)
        self.doc.IterationEpsilon = float(iteration_epsilon)
        self.doc.enableAutomaticCalculation(False)  # recalcul explicite via « calc »
        self.doc.calculateAll()
        return {"names": sorted(self.doc.NamedRanges.ElementNames)}

    def _range(self, name):
        if not self.doc.NamedRanges.hasByName(name):
            raise KeyError(f"plage nommée inconnue : {name}")
        cells = self.doc.NamedRanges.getByName(name).getReferredCells()
        if cells is None:
            raise KeyError(f"{name} ne désigne pas une plage de cellules")
        return cells

    def _address(self, name):
        """(feuille, ligne, colonne) de la première cellule d'une plage nommée, mis en cache."""
        if name not in self._addresses:
            cells = self._range(name)
            a = cells.RangeAddress
            self._addresses[name] = (cells.Spreadsheet.Name, a.Sheet, a.StartRow, a.StartColumn,
                                     a.EndRow - a.StartRow + 1, a.EndColumn - a.StartColumn + 1)
        return self._addresses[name]

    def _block(self, addresses):
        """Plus petit bloc contenant toutes les cellules (même feuille)."""
        sheet_index = addresses[0][1]
        rows = [a[2] for a in addresses] + [a[2] + a[4] - 1 for a in addresses]
        cols = [a[3] for a in addresses] + [a[3] + a[5] - 1 for a in addresses]
        ws = self.doc.Sheets.getByIndex(sheet_index)
        return ws.getCellRangeByPosition(min(cols), min(rows), max(cols), max(rows)), min(rows), min(cols)

    def set(self, values, sheet):
        if not values:
            return {"written": 0}
        addresses = {name: self._address(name) for name in values}
        for name, a in addresses.items():
            if a[0] != sheet:
                raise PermissionError(f"{name} n'est pas sur la feuille {sheet}")
            if a[4] != 1 or a[5] != 1:
                raise PermissionError(f"{name} n'est pas une cellule unique")
        block, row0, col0 = self._block(list(addresses.values()))
        formulas = block.queryContentCells(CELL_FLAG_FORMULA)
        formula_cells = set()
        for i in range(formulas.Count):
            f = formulas.getByIndex(i).RangeAddress
            formula_cells |= {(r, c) for r in range(f.StartRow, f.EndRow + 1) for c in range(f.StartColumn, f.EndColumn + 1)}
        refused = [n for n, a in addresses.items() if (a[2], a[3]) in formula_cells]
        if refused:
            raise PermissionError(f"{refused} contiennent une formule : écriture refusée")
        if formula_cells:
            # le bloc contient des formules hors cibles : écriture cellule par cellule
            for name, a in addresses.items():
                block.getCellByPosition(a[3] - col0, a[2] - row0).setValue(float(values[name]))
            return {"written": len(values)}
        data = [list(row) for row in block.getDataArray()]
        for name, a in addresses.items():
            data[a[2] - row0][a[3] - col0] = float(values[name])
        block.setDataArray(tuple(tuple(row) for row in data))
        return {"written": len(values)}

    def calc(self, full=False):
        t0 = time.perf_counter()
        if full:
            self.doc.calculateAll()
        else:
            self.doc.calculate()
        return {"seconds": time.perf_counter() - t0}

    @staticmethod
    def _cell_value(cell):
        if cell.getError():
            return {"error": cell.getError()}
        if cell.getType() == FORMULA and cell.FormulaResultType2 == 2:  # texte
            return cell.getString()
        if cell.getType().value == "TEXT":
            return cell.getString()
        if cell.getType().value == "EMPTY":
            return None
        return cell.getValue()

    def _read_block(self, addresses):
        """Valeurs (et erreurs) du plus petit bloc couvrant ``addresses``."""
        block, row0, col0 = self._block(addresses)
        data = [list(row) for row in block.getDataArray()]
        errors = block.queryFormulaCells(FORMULA_ERROR)
        for i in range(errors.Count):
            e = errors.getByIndex(i).RangeAddress
            for r in range(e.StartRow, e.EndRow + 1):
                for c in range(e.StartColumn, e.EndColumn + 1):
                    cell = block.getCellByPosition(c - col0, r - row0)
                    data[r - row0][c - col0] = {"error": cell.getError()}
        return data, row0, col0

    def get(self, names):
        out = {}
        singles = {}
        for name in names:
            a = self._address(name)
            if a[4] == 1 and a[5] == 1:
                singles.setdefault(a[1], {})[name] = a
            else:
                data, row0, col0 = self._read_block([a])
                out[name] = data
        for group in singles.values():
            data, row0, col0 = self._read_block(list(group.values()))
            for name, a in group.items():
                out[name] = data[a[2] - row0][a[3] - col0]
        return out

    def get_cells(self, sheet, refs):
        ws = self.doc.Sheets.getByName(sheet)
        return {ref: self._cell_value(ws.getCellRangeByName(ref)) for ref in refs}

    def save(self, path):
        ext = os.path.splitext(path)[1].lower()
        self.doc.storeToURL(uno.systemPathToFileUrl(os.path.abspath(path)), (prop("FilterName", FILTERS[ext]),))
        return {"path": path}

    def close(self):
        if self.doc is not None:
            try:
                self.doc.close(True)
            except Exception:
                pass
            self.doc = None
        return {}

    def quit(self):
        self.close()
        try:
            self.desktop.terminate()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)
        return {}


def main():
    worker = Worker(sys.argv[1] if len(sys.argv) > 1 else "soffice")
    print(json.dumps({"ok": True, "ready": True}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        cmd = request.pop("cmd")
        try:
            result = getattr(worker, cmd)(**request)
            print(json.dumps({"ok": True, "result": result}), flush=True)
        except Exception as exc:  # renvoyé au client, le worker reste vivant
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), flush=True)
        if cmd == "quit":
            break


if __name__ == "__main__":
    main()
