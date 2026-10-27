"""Spécification du pont jumeau ↔ classeur (Data-Center-Development-Model v1.7).

``INPUTS`` : cellules d'hypothèses de l'onglet Underwriting recâblées vers une
plage nommée ``tw_*`` de la feuille Inputs_Twin. Dans la copie, la cellule
d'origine devient ``=tw_*`` ; dans le cas de base, la valeur ``tw_*`` est la
valeur originale de la cellule.

``OUTPUTS`` : formules ``out_*`` de la feuille Outputs, lues par le jumeau.
"""
from __future__ import annotations

from dataclasses import dataclass

UNDERWRITING = "Underwriting"
INPUT_SHEET = "Inputs_Twin"
OUTPUT_SHEET = "Outputs"
TENANT_ROWS = range(121, 131)  # 10 emplacements de locataires
YEARS = range(0, 12)           # mois 0 à 132 de la grille S:EU


@dataclass(frozen=True)
class InputSpec:
    name: str
    group: str
    unit: str
    description: str
    cell: str | None = None  # cellule Underwriting recâblée ; None = entrée propre au jumeau
    default: float | None = None  # pour les entrées sans cellule d'origine


def _tenant_inputs() -> list[InputSpec]:
    out = []
    for i, row in enumerate(TENANT_ROWS, start=1):
        out += [
            InputSpec(f"tw_whitespace_sf_{i}", "locataires", "SF", f"White space locataire {i}", f"D{row}"),
            InputSpec(f"tw_tenant_kw_{i}", "locataires", "kW", f"Charge IT louée, locataire {i}", f"E{row}"),
            InputSpec(f"tw_absorption_kw_month_{i}", "locataires", "kW/mois", f"Rythme d'absorption, locataire {i}", f"H{row}"),
            InputSpec(f"tw_rent_{i}", "marché", "$/kW/mois", f"Loyer, locataire {i}", f"I{row}"),
            InputSpec(f"tw_rent_growth_{i}", "marché", "%/an", f"Indexation du loyer, locataire {i}", f"J{row}"),
        ]
    return out


INPUTS: list[InputSpec] = [
    InputSpec("tw_gross_sf", "surfaces", "SF", "Surface brute du bâtiment", "K19"),
    *_tenant_inputs(),
    InputSpec("tw_pue", "énergie", "–", "PUE (multiplicateur des utilities)", "K23"),
    InputSpec("tw_utilities_rate", "énergie", "$/kW/mois", "Utilities : énergie + eau + carbone, par kW IT et par PUE", "H153"),
    InputSpec("tw_utilities_fixed", "énergie", "%", "Part fixe des utilities", "E153"),
    InputSpec("tw_idx_energy", "marché", "%/an", "Indexation des utilities", "G153"),
    InputSpec("tw_idx_maintenance", "marché", "%/an", "Indexation maintenance", "G154"),
    InputSpec("tw_idx_staffing", "marché", "%/an", "Indexation personnel et sûreté", "G155"),
    InputSpec("tw_idx_insurance", "marché", "%/an", "Indexation assurance", "G156"),
    InputSpec("tw_idx_property_tax", "marché", "%/an", "Indexation taxe foncière", "G159"),
    InputSpec("tw_capex_sitework", "capex", "$", "Voirie et réseaux", "K41"),
    InputSpec("tw_capex_concrete_structure", "capex", "$", "Béton et charpente", "K42"),
    InputSpec("tw_capex_envelope", "capex", "$", "Enveloppe", "K43"),
    InputSpec("tw_capex_raised_floor", "capex", "$", "Faux plancher", "K44"),
    InputSpec("tw_capex_mechanical", "capex", "$", "Mécanique (CVC, refroidissement)", "K45"),
    InputSpec("tw_capex_electrical", "capex", "$", "Électrique", "K46"),
    InputSpec("tw_capex_fire_protection", "capex", "$", "Protection incendie", "K47"),
    InputSpec("tw_capex_security", "capex", "$", "Sûreté", "K48"),
    InputSpec("tw_capex_interior_finishes", "capex", "$", "Aménagements", "K49"),
    InputSpec("tw_capex_grid", "capex", "$", "Raccordements réseaux", "K50"),
    InputSpec("tw_capex_battery", "capex", "$", "Batterie (ligne libre K51)", "K51"),
    InputSpec("tw_capex_battery_start", "capex", "mois", "Début de décaissement batterie", "D51"),
    InputSpec("tw_capex_battery_end", "capex", "mois", "Fin de décaissement batterie", "E51"),
    InputSpec("tw_capex_contingency", "capex", "$", "Aléas (coûts mous)", "K62"),
    InputSpec("tw_capex_dev_fee", "capex", "$", "Commission de développement", "K65"),
    InputSpec("tw_equity_total", "solveur", "$", "Equity totale, résolue pour LTC réel = LTC cible (remplace le goal seek VBA)", "K79"),
    InputSpec("tw_perm_debt", "financement", "0/1", "Dette permanente (refinancement) active", "A102"),
    InputSpec("tw_discount_rate", "marché", "%", "Taux d'actualisation de la VAN (pas de cellule d'origine)", default=0.08),
    InputSpec("tw_memo_energy_cost", "mémo", "$/an", "Coût d'énergie simulé (information)", default=0.0),
    InputSpec("tw_memo_water_cost", "mémo", "$/an", "Coût de l'eau (information)", default=0.0),
    InputSpec("tw_memo_carbon_cost", "mémo", "$/an", "Coût du carbone (information)", default=0.0),
]
INPUTS_BY_NAME = {spec.name: spec for spec in INPUTS}

# Mêmes plages que les XIRR de J229 / J230 (S76 = 0 : le flux démarre au mois 1)
_SPAN = "IF($S$76=0,{fn}({rate}OFFSET(Underwriting!$T${row},0,0,1,Timing_Analysis_End_Month),OFFSET(Underwriting!$T$213,0,0,1,Timing_Analysis_End_Month)),{fn}({rate}OFFSET(Underwriting!$S${row},0,0,1,Timing_Analysis_End_Month+1),OFFSET(Underwriting!$S$213,0,0,1,Timing_Analysis_End_Month+1)))"
_MONTHS = "Underwriting!$S$29:$EU$29"


def _llcr() -> str:
    """LLCR de la dette permanente sur la détention : VAN, au taux du prêt, des CFADS du mois
    suivant le financement jusqu'à la vente, plus le produit net de cession (ligne 223), rapportée
    au montant prêté. Le prêt est remboursé in fine à la vente, d'où l'inclusion de la cession."""
    discount = f"1/(1+Underwriting!$C$105/12)^({_MONTHS}-PermDebt_Fund)"
    window = f"({_MONTHS}>PermDebt_Fund)*({_MONTHS}<=Timing_Analysis_End_Month)"
    return (f'IF(Perm_Debt_Flag=0,"",(SUMPRODUCT({window},Underwriting!$S$169:$EU$169,{discount})'
            f"+SUMPRODUCT({window},Underwriting!$S$223:$EU$223,{discount}))/Underwriting!$K$103)")


# (nom, description, unité, formule) — formules sans « = »
SCALAR_OUTPUTS: list[tuple[str, str, str, str]] = [
    ("out_irr_project", "TRI projet (unlevered)", "%", "Underwriting!$J$229"),
    ("out_irr_equity", "TRI equity (levered)", "%", "Underwriting!$J$230"),
    ("out_em_unlevered", "Multiple unlevered", "x", "Underwriting!$I$229"),
    ("out_em_levered", "Multiple levered", "x", "Underwriting!$I$230"),
    ("out_profit_unlevered", "Profit net unlevered", "$", "Underwriting!$K$229"),
    ("out_profit_levered", "Profit net levered", "$", "Underwriting!$K$230"),
    ("out_npv", "VAN du flux unlevered au taux tw_discount_rate", "$",
     _SPAN.format(fn="XNPV", rate="tw_discount_rate,", row=229)),
    ("out_npv_equity", "VAN du flux levered au taux tw_discount_rate", "$",
     _SPAN.format(fn="XNPV", rate="tw_discount_rate,", row=230)),
    ("out_capex_total", "Coût total du projet (avec portage)", "$", "Project_Cost_Total"),
    ("out_capex_before_financing", "Coût avant financement", "$", "Underwriting!$K$68"),
    ("out_hard_costs", "Coûts durs", "$", "Underwriting!$K$52"),
    ("out_equity", "Equity", "$", "Equity_Total"),
    ("out_debt", "Dette de construction", "$", "Debt_Total"),
    ("out_ltc_actual", "LTC réel", "%", "Debt_LTC_Actual"),
    ("out_ltc_target", "LTC cible", "%", "Debt_LTC_Target"),
    ("out_construction_interest", "Intérêts de construction capitalisés", "$", "Underwriting!$K$71"),
    ("out_yoc_untrended", "Rendement sur coût non indexé", "%", "Underwriting!$I$233"),
    ("out_yoc_trended", "Rendement sur coût indexé", "%", "Underwriting!$J$233"),
    ("out_dev_spread_bps", "Marge de développement", "bp", "Underwriting!$I$235"),
    ("out_value_untrended", "Valeur stabilisée non indexée", "$", "Valuation_Untrended"),
    ("out_value_sale", "Valeur de revente", "$", "Valuation_Reversion"),
    ("out_noi_stabilized", "NOI stabilisé (pro forma)", "$", "Underwriting!$I$195"),
    ("out_utilities_proforma", "Utilities pro forma (année pleine)", "$", "Underwriting!$K$153"),
    ("out_opex_energy_y1", "OPEX énergie, 12 premiers mois d'exploitation", "$",
     "SUM(OFFSET(Underwriting!$S$153,0,Timing_Operation_Begin_Month,1,12))"),
    ("out_it_load_kw", "Charge IT (kW)", "kW", "IT_Load"),
    ("out_pue", "PUE", "–", "PUE"),
    ("out_operation_begin_month", "Mois de début d'exploitation", "mois", "Timing_Operation_Begin_Month"),
    ("out_stabilization_month", "Mois de stabilisation", "mois", "Stabilization_1st_Month"),
    ("out_analysis_end_month", "Mois de vente", "mois", "Timing_Analysis_End_Month"),
    ("out_perm_debt_active", "Dette permanente active", "0/1", "Perm_Debt_Flag"),
    ("out_perm_loan_amount", "Montant de la dette permanente", "$", "IF(Perm_Debt_Flag=0,0,Underwriting!$K$103)"),
    ("out_llcr", "LLCR dette permanente (détention + cession)", "x", _llcr()),
    ("out_recalc_const_ok", "Indicateur Recalc_Const", "bool", "IF(Recalc_Const,1,0)"),
    ("out_recalc_mgmt_ok", "Indicateur Recalc_Mgmt", "bool", "IF(Recalc_Mgmt,1,0)"),
    ("out_recalc_ok", "Indicateur Recalc? (les deux)", "bool", "IF(Recalc_Flag,1,0)"),
]

# Séries annuelles : SUMIF par année d'analysis (ligne 28) sur la grille mensuelle
SERIES_OUTPUTS: list[tuple[str, str, int]] = [
    ("out_egr", "Revenus effectifs (EGR)", 148),
    ("out_utilities", "Utilities", 153),
    ("out_opex", "OPEX total", 160),
    ("out_noi", "NOI", 162),
    ("out_cfads", "CFADS (cash-flow d'exploitation)", 169),
    ("out_debt_service", "Service de la dette permanente", 170),
    ("out_construction_interest_y", "Intérêts de construction", 215),
    ("out_cf_unlevered", "Flux unlevered", 229),
    ("out_cf_levered", "Flux levered", 230),
]
