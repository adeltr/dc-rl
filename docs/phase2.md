# Phase 2 — Pont Excel

## Lancer

```bash
make bridge   # construit build/twin_model.xlsm depuis model/Data-Center-Development-Model-v1.7.xlsm
make test     # tests du moteur et du pont, dont la non-régression (LibreOffice)
```

```python
from bridge.bridge import ExcelBridge
from bridge.mapping import MarketAssumptions
from twin.engine import run_year
from twin.params import TwinParams

base = run_year(TwinParams(site_id="us_ny_jfk"))
scenario = run_year(TwinParams(site_id="us_ny_jfk", geometry={"kw_per_rack": 30}))
bridge = ExcelBridge()                      # moteur choisi automatiquement
result = bridge.run(scenario, base, MarketAssumptions(perm_debt=True), export_path="exports/s1.xlsx")
result.outputs["out_irr_equity"], result.series["out_dscr"]
```

Le classeur source et la copie pont ne sont **pas versionnés** (dépôt public) : `model/`, `build/` et `exports/` sont ignorés par git. Leurs chemins sont configurables (`TWIN_WORKBOOK`, `TWIN_BRIDGE_WORKBOOK`, `TWIN_EXPORT_DIR`).

## La copie pont (`bridge/build.py`)

Elle est construite par **édition directe du XML** du `.xlsm`. Les styles, le graphique, les boutons, le VBA et l'onglet `Version` (exigé par la licence A.CRE) restent intacts ; openpyxl les aurait perdus. La copie est reconstruite automatiquement si le classeur source ou `bridge/spec.py` change.

| Modification | Détail |
|---|---|
| Feuille `Inputs_Twin` | 80 entrées `tw_*` (constantes, valeur de base = valeur originale), avec unité, cellule d'origine, groupe et description |
| Recâblage | 76 cellules d'hypothèses d'`Underwriting` deviennent `=tw_*` (liste dans `bridge/spec.py`) : surfaces, locataires (kW, absorption, loyer, indexation), PUE, utilities, indexations, 11 lignes de coûts durs + calendrier batterie, aléas, commission de développement, equity, dette permanente |
| Feuille `Outputs` | 37 sorties scalaires `out_*` + 10 séries annuelles (années 0 à 11, par `SUMIF` sur la ligne 28) + DSCR min / moyen |
| Equity (K79) | `=tw_equity_total`, résolue par le solveur Python. Remplace le goal seek VBA `Recalculate_Const`, qui exige une constante en K79 |
| Honoraires de gestion | les 133 valeurs collées de la ligne 158 et K158 redeviennent la formule écrite par `Recalculate_Mgmt_Fee` (`Mgmt_Fee_Pct × EGR`) ; itération activée (`iterate="1"`, 250 itérations, 1e-5) |
| Compatibilité LibreOffice | `Perm_Debt?` et `Recalc?` (le `?` est illégal pour LibreOffice) doublés par `Perm_Debt_Flag` / `Recalc_Flag` dans les formules ; les noms d'origine restent pour le VBA. 160 `OFFSET(…, -n)` d'`Annual CF` réécrits en `OFFSET(…, c−n+1, …, n)`, identique dans Excel |

Dans Excel, les macros restent utilisables, avec deux réserves. Le bouton *Recalculate* ne peut plus faire son goal seek sur K79, qui est une formule : c'est le solveur du pont qui s'en charge. Les boutons de dette permanente écrivent dans A102 et remplacent son lien vers `tw_perm_debt`.

## Moteurs (`bridge/engines.py`)

| Moteur | Quand | Détail |
|---|---|---|
| `XlwingsEngine` | Excel installé (Windows / macOS) | itération Excel activée, `CalculateFull`, export par `SaveCopyAs`. **Non testé ici** (Linux) ; sélection `TWIN_EXCEL_ENGINE=xlwings` |
| `LibreOfficeEngine` | sinon | LibreOffice headless piloté par un worker UNO (`bridge/lo_worker.py`, lancé avec le Python qui fournit `uno`) ; itération activée ; calcul automatique coupé, recalcul explicite |

`select_engine()` (`TWIN_EXCEL_ENGINE` = `auto` | `xlwings` | `libreoffice`) : `auto` essaie xlwings, puis LibreOffice.

**Écriture** : seules les plages `tw_*` de la feuille `Inputs_Twin` sont acceptées. Deux contrôles :

1. côté Python, le nom doit figurer dans la spécification ;
2. côté moteur, la cellule doit être sur `Inputs_Twin` et ne pas contenir de formule.

Le cas contraire lève `PermissionError`.

## Traduction jumeau → classeur (`bridge/mapping.py`)

> Mis à jour après la revue financière (voir [revue-financiere.md](revue-financiere.md)) : le mode absolu et une part fixe de l'énergie de 15 % sont désormais les défauts.

- **Classeur d'origine** (jumeau = base, mode calibré, part fixe du classeur) : valeurs originales exactes.
- **Charge IT** : kW des locataires × (IT du scénario / 20 000 kW) ; absorption idem × multiplicateur de montée en occupation. **Surfaces** : × (racks du scénario / racks de base).
- **Énergie, mode absolu** (défaut) : PUE et coût d'énergie simulés écrits tels quels ; le cockpit et le classeur utilisent le même PUE.
- **Énergie, mode calibré** :
  - `tw_pue` = 1,5 × PUE simulé / PUE simulé de base ;
  - utilities annuelles = 39,42 M$ × coût simulé / coût simulé de base + eau + carbone ;
  - `tw_utilities_rate` = utilities / (IT × PUE × 12).
- **Part fixe de l'énergie** (E153) : 15 % par défaut ; le reste suit la charge IT louée (ligne 114). Classeur d'origine : 100 %.
- **CAPEX** : montants du jumeau par ligne (K41–K51) ; aléas et commission de développement au prorata des coûts durs.
- **Marché** : loyer, indexations, montée en occupation, prix de l'eau et du carbone, taux d'actualisation, dette permanente, covenant DSCR (alerte de l'interface uniquement).

## Indicateurs ajoutés (feuille `Outputs`)

| Sortie | Définition |
|---|---|
| `out_npv`, `out_npv_equity` | XNPV des flux unlevered / levered (mêmes plages que les XIRR de J229 / J230, choisies par `Underwriting!S76`) au taux `tw_discount_rate`. Contrôle : VAN au taux du TRI = 0. **8 % par défaut, sans source publique trouvée : à confirmer** |
| `out_opex_energy_y1` | utilities des 12 premiers mois d'exploitation |
| `out_cfads[]` | cash-flow d'exploitation (ligne 169), par année |
| `out_debt_service[]` | service de la dette permanente (ligne 170) |
| `out_dscr[]`, `out_dscr_min`, `out_dscr_avg` | CFADS / service de la dette, années où la dette permanente est servie. **N/A si elle est désactivée** (cas de base : prêt de construction remboursé à la vente) |
| `out_llcr` | VAN au taux du prêt (CFADS du mois suivant le financement jusqu'à la vente + produit net de cession) / montant prêté. Le prêt est remboursé in fine à la vente, d'où l'inclusion de la cession. N/A sans dette permanente |

## Non-régression

`tests/test_bridge.py` recalcule la copie avec les valeurs de base (LibreOffice). Il compare ensuite **chaque cellule numérique des 4 feuilles d'origine** (plus de 25 000) aux valeurs calculées par Excel et enregistrées dans le fichier original : tolérance relative 1e-6, aucun écart. Les sorties nouvelles (VAN, OPEX énergie an 1, séries annuelles) sont recalculées en Python à partir des valeurs en cache du classeur original et concordent aussi à 1e-6. Écart max observé sur l'onglet Underwriting : 2,4e-8 (TRI levered : 12,3272847 % contre 12,3272842 % dans Excel).

## Temps et résultats (LibreOffice, météo New York)

Démarrage de LibreOffice et ouverture : 2,8 s, une seule fois (processus conservé). Par scénario : écriture 0,05 s, recalcul ≈ 0,5 s, lecture 0,09 s ; le solveur d'equity ajoute 2 à 3 recalculs.

| Scénario | Durée totale | Itérations solveur | TRI projet | TRI equity | VAN 8 % | CAPEX total | OPEX énergie an 1 | PUE classeur | DSCR min | LLCR |
|---|---|---|---|---|---|---|---|---|---|---|
| Cas de base (NY) | 0,73 s | 0 | 10,86 % | 12,33 % | 22,4 M$ | 213,1 M$ | 39,42 M$ | 1,500 | N/A | N/A |
| Prix +10 % | 1,43 s | 2 | 3,85 % | −4,00 % | −29,4 M$ | 219,7 M$ | 43,36 M$ | 1,500 | N/A | N/A |
| 30 kW/rack | 2,06 s | 3 | 8,58 % | 7,69 % | 6,2 M$ | 306,3 M$ | 62,96 M$ | 1,597 | N/A | N/A |
| Refroidissement liquide | 2,06 s | 3 | 18,91 % | 26,26 % | 98,5 M$ | 211,4 M$ | 33,13 M$ | 1,261 | N/A | N/A |
| HP/HC + batterie 10 MW / 40 MWh | 1,58 s | 2 | 24,67 % | 34,99 % | 167,8 M$ | 210,9 M$ | 27,37 M$ | 1,500 | N/A | N/A |
| Dette permanente activée | 0,73 s | 0 | 10,86 % | 13,54 % | 22,4 M$ | 213,1 M$ | 39,42 M$ | 1,500 | 1,77x | 1,93x |
| Loyer 300 $/kW/mois | 2,14 s | 3 | 15,37 % | 20,42 % | 61,9 M$ | 211,2 M$ | 39,42 M$ | 1,500 | N/A | N/A |
| Mode absolu | 1,95 s | 3 | 16,36 % | 22,10 % | 70,5 M$ | 207,3 M$ | 35,75 M$ | 1,359 | N/A | N/A |

**Sensibilité extrême à l'énergie, propre au classeur.** Les utilities (39,4 M$/an) représentent 61 % de l'EGR et ne sont pas refacturées aux locataires (taux de refacturation F134:F143 = 0 %). Elles sont aussi 100 % fixes à pleine puissance (E153). Un prix +10 % retire 3,9 M$ de NOI, soit environ 58 M$ de valeur de sortie au taux de 6,75 %, et fait passer le TRI equity de 12,3 % à −4,0 %. Le pont reproduit fidèlement ce comportement. Pour l'atténuer, il faudrait modifier les hypothèses du classeur (refacturation de l'énergie, part variable).

Chaque passage dans le classeur est journalisé dans `logs/scenarios.jsonl` (`stage: "workbook"` : marché, moteur, durée, itérations, sorties). La simulation physique est journalisée avec `stage: "physics"`.
