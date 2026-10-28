"""Construit la copie « pont » du classeur, par édition directe du XML (styles, graphique,
boutons et VBA conservés tels quels ; openpyxl les perdrait).

Modifications, toutes dans la copie :

1. feuille ``Inputs_Twin`` : une ligne par entrée ``tw_*`` (valeur = valeur originale) ;
2. chaque cellule d'hypothèse recâblée devient ``=tw_*`` (sa valeur en cache est conservée) ;
3. feuille ``Outputs`` : formules ``out_*`` et séries annuelles ;
4. honoraires de gestion (ligne 158 et K158) : valeurs collées par la macro remplacées
   par la formule que la macro écrit, ``Mgmt_Fee_Pct × EGR`` ; itération activée ;
5. compatibilité LibreOffice : noms ``Perm_Debt?`` / ``Recalc?`` doublés par
   ``Perm_Debt_Flag`` / ``Recalc_Flag`` (le VBA garde les noms d'origine) ; OFFSET à
   largeur négative de « Annual CF » réécrit à largeur positive (même résultat dans Excel).

Usage : ``python -m bridge.build model/Data-Center-Development-Model-v1.7.xlsm build/twin_model.xlsm``
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .spec import (INPUT_SHEET, INPUTS, MONTHLY_OUTPUTS, OUTPUT_SHEET, SCALAR_OUTPUTS, SERIES_OUTPUTS,
                   UNDERWRITING, YEARS)

BRIDGE_VERSION = "4"  # 2 : lignes cohérentes (Excel) ; 3 : dette totale, cession ; 4 : taxe foncière, DSCR stabilisé
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SHEET_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
SHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
MONTH_COLUMNS = None  # calculé : S..EU


def col_letter(index: int) -> str:
    s = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


MONTH_COLUMNS = [col_letter(i) for i in range(col_index("S"), col_index("EU") + 1)]


class BuildError(RuntimeError):
    pass


# --------------------------------------------------------------------------- XML cellules

def _cell_pattern(ref: str) -> re.Pattern:
    return re.compile(rf'<c r="{ref}"(?P<attrs>(?:\s+[a-z]+="[^"]*")*)\s*(?:/>|>(?P<body>.*?)</c>)', re.S)


def read_constant(sheet_xml: str, ref: str, shared_strings: list[str]) -> float | str | None:
    m = _cell_pattern(ref).search(sheet_xml)
    if not m or not m.group("body"):
        return None
    body = m.group("body")
    if "<f" in body:
        raise BuildError(f"{ref} contient déjà une formule : ce n'est pas une hypothèse en dur.")
    v = re.search(r"<v>(.*?)</v>", body, re.S)
    if v is None:
        return None
    if 't="s"' in m.group("attrs"):
        return shared_strings[int(v.group(1))]
    return float(v.group(1))


def set_formula(sheet_xml: str, ref: str, formula: str, cached: float | None, allow_formula=False) -> str:
    pattern = _cell_pattern(ref)
    m = pattern.search(sheet_xml)
    if not m:
        raise BuildError(f"Cellule {ref} introuvable.")
    body = m.group("body") or ""
    if "<f" in body and not allow_formula:
        raise BuildError(f"{ref} contient déjà une formule.")
    attrs = re.sub(r'\s+t="[^"]*"', "", m.group("attrs"))
    value = f"<v>{_num(cached)}</v>" if cached is not None else ""
    new = f'<c r="{ref}"{attrs}><f>{escape(formula)}</f>{value}</c>'
    return sheet_xml[:m.start()] + new + sheet_xml[m.end():]


def _num(value: float) -> str:
    return repr(float(value)) if not float(value).is_integer() else str(int(value))


# --------------------------------------------------------------------------- nouvelles feuilles

def _inline(ref: str, text: str, style: int = 0) -> str:
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _number(ref: str, value: float, style: int = 0) -> str:
    return f'<c r="{ref}" s="{style}"><v>{_num(value)}</v></c>'


def _formula(ref: str, formula: str, style: int = 0) -> str:
    return f'<c r="{ref}" s="{style}"><f>{escape(formula)}</f></c>'


_ROW_OF_CELL = re.compile(r'<c r="[A-Z]+(\d+)"')


def _sheet(rows: list[list[str]], widths: list[float]) -> str:
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    # numéro de ligne lu sur la première cellule : Excel refuse une cellule hors de sa ligne
    # (LibreOffice la tolère), et les feuilles sautent des lignes
    body = "".join(f'<row r="{_ROW_OF_CELL.match(cells[0]).group(1)}">{"".join(cells)}</row>'
                   for cells in rows if cells)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_REL}"><sheetPr><tabColor rgb="FF1F4E79"/></sheetPr>'
            f'<sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/>'
            f"<cols>{cols}</cols><sheetData>{body}</sheetData></worksheet>")


def build_input_sheet(values: dict[str, float]) -> tuple[str, dict[str, str]]:
    rows = [[_inline("A1", "Entrées du jumeau numérique — seule feuille écrite par Python")],
            [_inline("A2", "Les cellules d'hypothèses d'Underwriting pointent vers ces valeurs. Cas de base = valeurs originales du classeur.")],
            [],
            [_inline("A4", "Nom"), _inline("B4", "Valeur"), _inline("C4", "Unité"), _inline("D4", "Cellule d'origine"),
             _inline("E4", "Groupe"), _inline("F4", "Description")]]
    names = {}
    for i, spec in enumerate(INPUTS):
        r = 5 + i
        rows.append([_inline(f"A{r}", spec.name), _number(f"B{r}", values[spec.name]), _inline(f"C{r}", spec.unit),
                     _inline(f"D{r}", f"{UNDERWRITING}!{spec.cell}" if spec.cell else "—"),
                     _inline(f"E{r}", spec.group), _inline(f"F{r}", spec.description)])
        names[spec.name] = f"{INPUT_SHEET}!$B${r}"
    return _sheet(rows, [34, 18, 12, 22, 14, 70]), names


def build_output_sheet() -> tuple[str, dict[str, str]]:
    rows = [[_inline("A1", "Sorties lues par le jumeau numérique (formules, ne pas saisir)")], [],
            [_inline("A3", "Nom"), _inline("B3", "Valeur"), _inline("C3", "Unité"), _inline("D3", "Description")]]
    names = {}
    r = 4
    for name, description, unit, formula in SCALAR_OUTPUTS:
        rows.append([_inline(f"A{r}", name), _formula(f"B{r}", formula), _inline(f"C{r}", unit),
                     _inline(f"D{r}", description)])
        names[name] = f"{OUTPUT_SHEET}!$B${r}"
        r += 1
    r += 1
    first, last = col_letter(1), col_letter(len(YEARS))
    header = [_inline(f"A{r}", "out_years")] + [_number(f"{col_letter(1 + i)}{r}", y) for i, y in enumerate(YEARS)]
    rows.append(header)
    names["out_years"] = f"{OUTPUT_SHEET}!${first}${r}:${last}${r}"
    year_row = r
    r += 1
    series_rows = {}
    for name, _description, src_row in SERIES_OUTPUTS:
        cells = [_inline(f"A{r}", name)]
        for i in range(len(YEARS)):
            col = col_letter(1 + i)
            cells.append(_formula(f"{col}{r}", f"SUMIF({UNDERWRITING}!$S$28:$EU$28,{col}${year_row},"
                                                 f"{UNDERWRITING}!$S${src_row}:$EU${src_row})"))
        rows.append(cells)
        names[name] = f"{OUTPUT_SHEET}!${first}${r}:${last}${r}"
        series_rows[name] = r
        r += 1
    cfads, ds = series_rows["out_cfads"], series_rows["out_debt_service"]
    egr, ci = series_rows["out_egr"], series_rows["out_construction_interest_y"]
    # service de la dette en exploitation : dette permanente + intérêts du prêt de construction
    # (sans dette permanente, ce prêt court jusqu'à la vente et ses intérêts pèsent sur le CFADS)
    cells = [_inline(f"A{r}", "out_debt_service_total")]
    for i in range(len(YEARS)):
        col = col_letter(1 + i)
        cells.append(_formula(f"{col}{r}", f"{col}{ds}+IF({col}{egr}>0,{col}{ci},0)"))
    rows.append(cells)
    names["out_debt_service_total"] = f"{OUTPUT_SHEET}!${first}${r}:${last}${r}"
    total = r
    r += 1
    cells = [_inline(f"A{r}", "out_dscr")]
    for i in range(len(YEARS)):
        col = col_letter(1 + i)
        # DSCR testé à partir de la première année entièrement stabilisée (convention prêteur :
        # la montée en occupation est couverte par le prêt de construction / la réserve d'intérêts)
        cells.append(_formula(f"{col}{r}", f'IF(AND(12*({col}${year_row}-1)+1>=Stabilization_1st_Month,'
                                             f'{col}{egr}>0,{col}{total}>0),{col}{cfads}/{col}{total},"")'))
    rows.append(cells)
    names["out_dscr"] = f"{OUTPUT_SHEET}!${first}${r}:${last}${r}"
    dscr_range = f"{first}{r}:{last}{r}"
    r += 2
    for name, fn, label in (("out_dscr_min", "MIN", "DSCR minimum"), ("out_dscr_avg", "AVERAGE", "DSCR moyen")):
        rows.append([_inline(f"A{r}", name), _formula(f"B{r}", f'IF(COUNT({dscr_range})=0,"",{fn}({dscr_range}))'),
                     _inline(f"C{r}", "x"), _inline(f"D{r}", f"{label} (années stabilisées avec service de la dette)")])
        names[name] = f"{OUTPUT_SHEET}!$B${r}"
        r += 1
    return _sheet(rows, [30] + [16] * len(YEARS)), names


# --------------------------------------------------------------------------- assemblage

def _sheet_paths(files: dict[str, bytes]) -> dict[str, str]:
    workbook = files["xl/workbook.xml"].decode()
    rels = files["xl/_rels/workbook.xml.rels"].decode()
    targets = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', rels))
    return {name: "xl/" + targets[rid] for name, rid in re.findall(r'<sheet name="([^"]+)" sheetId="\d+" r:id="(rId\d+)"', workbook)}


def _shared_strings(files: dict[str, bytes]) -> list[str]:
    xml = files.get("xl/sharedStrings.xml", b"").decode()
    return [re.sub(r"<[^>]+>", "", si) for si in re.findall(r"<si>(.*?)</si>", xml, re.S)]


def build_bridge_workbook(src: Path, dst: Path) -> dict:
    with zipfile.ZipFile(src) as z:
        files = {info.filename: z.read(info.filename) for info in z.infolist()}
    paths = _sheet_paths(files)
    strings = _shared_strings(files)
    uw_path = paths[UNDERWRITING]
    uw = files[uw_path].decode()

    # 1-2. valeurs originales puis recâblage
    original: dict[str, float] = {}
    for spec in INPUTS:
        if spec.cell is None:
            original[spec.name] = float(spec.default)
            continue
        value = read_constant(uw, spec.cell, strings)
        if not isinstance(value, float):
            raise BuildError(f"{spec.cell} ({spec.name}) n'est pas une constante numérique : {value!r}")
        original[spec.name] = value
        uw = set_formula(uw, spec.cell, spec.name, value)

    # contexte lu dans le classeur (non recâblé) : calendrier de la ligne électrique, pour la batterie
    context = {ref: read_constant(uw, ref, strings) for ref in ("D46", "E46")}

    # 4. honoraires de gestion : formule de Recalculate_Mgmt_Fee à la place des valeurs collées
    for col in MONTH_COLUMNS:
        cached = read_constant(uw, f"{col}158", strings)
        uw = set_formula(uw, f"{col}158", f"Mgmt_Fee_Pct*{col}148", cached if isinstance(cached, float) else 0.0)
    cached = read_constant(uw, "K158", strings)
    uw = set_formula(uw, "K158", "Mgmt_Fee_Pct*Rel_EGR_ProForma", cached)

    # 5a. noms avec « ? » dans les formules (le VBA conserve les noms d'origine)
    def rename(xml: str) -> str:
        return re.sub(r"(?i)perm_debt\?", "Perm_Debt_Flag", re.sub(r"(?i)recalc\?", "Recalc_Flag", xml))

    files[uw_path] = rename(uw).encode()
    for name, path in paths.items():
        if name != UNDERWRITING:
            files[path] = rename(files[path].decode()).encode()

    # 5b. OFFSET à largeur négative (Annual CF)
    annual = files[paths["Annual CF"]].decode()
    annual, n_offset = re.subn(r"OFFSET\((Underwriting!\$S\d+),0,(SUM\(\$H\$6:([A-Z]+)\$6\)),1,-\3\$6\)",
                               r"OFFSET(\1,0,\2-\3$6+1,1,\3$6)", annual)
    if n_offset == 0:
        raise BuildError("Aucune formule OFFSET à largeur négative trouvée dans Annual CF.")
    files[paths["Annual CF"]] = annual.encode()

    # 3. nouvelles feuilles
    input_xml, input_names = build_input_sheet(original)
    output_xml, output_names = build_output_sheet()
    files["xl/worksheets/sheet_twin_inputs.xml"] = input_xml.encode()
    files["xl/worksheets/sheet_twin_outputs.xml"] = output_xml.encode()

    rels = files["xl/_rels/workbook.xml.rels"].decode()
    rels = rels.replace("</Relationships>",
                        f'<Relationship Id="rIdTwinIn" Type="{SHEET_REL}" Target="worksheets/sheet_twin_inputs.xml"/>'
                        f'<Relationship Id="rIdTwinOut" Type="{SHEET_REL}" Target="worksheets/sheet_twin_outputs.xml"/>'
                        "</Relationships>")
    rels = re.sub(r'<Relationship [^>]*Target="calcChain.xml"/>', "", rels)
    files["xl/_rels/workbook.xml.rels"] = rels.encode()
    files.pop("xl/calcChain.xml", None)

    ct = files["[Content_Types].xml"].decode()
    ct = re.sub(r'<Override PartName="/xl/calcChain.xml"[^>]*/>', "", ct)
    ct = ct.replace("</Types>",
                    f'<Override PartName="/xl/worksheets/sheet_twin_inputs.xml" ContentType="{SHEET_CT}"/>'
                    f'<Override PartName="/xl/worksheets/sheet_twin_outputs.xml" ContentType="{SHEET_CT}"/></Types>')
    files["[Content_Types].xml"] = ct.encode()

    wb = files["xl/workbook.xml"].decode()
    max_id = max(int(i) for i in re.findall(r'sheetId="(\d+)"', wb))
    wb = wb.replace("</sheets>",
                    f'<sheet name="{INPUT_SHEET}" sheetId="{max_id + 1}" r:id="rIdTwinIn"/>'
                    f'<sheet name="{OUTPUT_SHEET}" sheetId="{max_id + 2}" r:id="rIdTwinOut"/></sheets>')
    aliases = {"Perm_Debt_Flag": re.search(r'<definedName name="Perm_Debt\?">([^<]+)<', wb).group(1),
               "Recalc_Flag": re.search(r'<definedName name="Recalc\?">([^<]+)<', wb).group(1)}
    output_names.update(dict(MONTHLY_OUTPUTS))
    new_names = {**aliases, **input_names, **output_names}
    defined = "".join(f'<definedName name="{n}">{escape(ref)}</definedName>' for n, ref in sorted(new_names.items()))
    wb = wb.replace("</definedNames>", defined + "</definedNames>")
    calc = re.search(r"<calcPr[^>]*/>", wb).group(0)
    new_calc = re.sub(r'\s(iterate|iterateCount|iterateDelta|fullCalcOnLoad)="[^"]*"', "", calc)
    new_calc = new_calc.replace("<calcPr", '<calcPr iterate="1" iterateCount="250" iterateDelta="0.00001" fullCalcOnLoad="1"')
    files["xl/workbook.xml"] = wb.replace(calc, new_calc).encode()

    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        order = [i.filename for i in zin.infolist() if i.filename in files]
        order += [name for name in files if name not in order]
        for name in order:
            zout.writestr(name, files[name])

    manifest = {
        "bridge_version": BRIDGE_VERSION,
        "source": src.name,
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "inputs": {spec.name: {"cell": spec.cell, "value": original[spec.name], "unit": spec.unit,
                               "group": spec.group, "ref": input_names[spec.name]} for spec in INPUTS},
        "outputs": output_names,
        "context": context,
        "offset_rewrites": n_offset,
    }
    dst.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    m = build_bridge_workbook(src, dst)
    print(f"{dst} : {len(m['inputs'])} entrées tw_*, {len(m['outputs'])} sorties out_*, "
          f"{m['offset_rewrites']} OFFSET réécrits")
