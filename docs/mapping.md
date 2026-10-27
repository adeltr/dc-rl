# Phase 0 — Découverte et mapping jumeau ↔ SustainDC ↔ Excel

Statut : **validé** (Q1–Q8, avec les recommandations retenues). Deux décisions complémentaires :

- toute donnée absente du classeur et de SustainDC est tirée d'une API publique, avec sa provenance affichée, et reste modifiable à la main ;
- le pont Excel garde les deux moteurs. LibreOffice est disponible ici ; xlwings (Excel installé) est sélectionnable plus tard, sans rien bloquer.

> Dépôt public. Le classeur contient le nom du projet, une adresse et une société. Ces informations ne sont pas reproduites ici, et le `.xlsm` n'est pas versionné (`model/` est ignoré par git) tant que tu n'as pas donné ton accord (Q8).

## 1. Le classeur Excel

Fichier : `Data-Center-Development-Model-v1.7.xlsm` (A.CRE, Adventures in CRE).
Le skill fourni (`data-center-development-model-v16.skill`) décrit la **v1.6**. En v1.7, **toutes les lignes à partir de la 97 sont décalées de +3** : par exemple `IT_Load` est en E131 et non en E128, `Mgmt_Fee_Pct` en I158 et non en I155. Le mapping ci-dessous utilise les cellules **v1.7**, relevées dans le fichier.

### 1.1 Nature du modèle — écart important avec le cahier des charges

C'est un modèle de **promotion immobilière** (développement puis revente), pas un modèle de project finance à dette sculptée :

| Attendu (cahier des charges) | Présent dans le classeur |
|---|---|
| CAPEX | oui : terrain (lignes 33–37), coûts durs (41–51), coûts mous (55–65), portage (71–73) |
| OPEX | oui : lignes 153–159, avec les utilities = $/kW/mois × IT × PUE |
| CFADS | **non** en tant que tel ; l'équivalent le plus proche est le « Cash Flow from Operations » (ligne 169, mensuel) |
| Debt sculpting | **non** : prêt de construction dimensionné sur un LTC cible ; dette permanente optionnelle à annuités constantes (`Perm_Debt_Flag`, désactivée dans le cas de base) |
| DSRA, intérêts intercalaires | intérêts de construction capitalisés et réserve de déficit d'exploitation (lignes 71–73, 92–93) ; pas de DSRA |
| DSCR / LLCR / PLCR | **non natifs**. Seul un DSCR ponctuel existe en F104, et seulement si la dette permanente est activée |
| TRI projet / equity | oui : TRI « unlevered » J229 et « levered » J230 (XIRR mensuel) |
| VAN | **non** (pas de taux d'actualisation dans le classeur) |
| Sortie | revente au mois 72 par capitalisation du NOI (taux de sortie 6,75 %) |

### 1.2 Feuilles

| Feuille | Taille | Rôle |
|---|---|---|
| `Version` | A1:Q46 | changelog. La licence A.CRE impose de **la conserver intacte** dans toute copie |
| `Underwriting` | A1:KF290 | toutes les hypothèses (colonnes A–K), grille mensuelle (S:EU = mois 0 à 132), moteur de calcul (FA:KE) |
| `Annual CF` | B2:Q43 | agrégation annuelle (rapport) |
| `S-Curve Reference` | B2:AL25 | courbes de décaissement en S |

### 1.3 Plages nommées (v1.7)

Entrées : `Investment_Name` E17, `Start_Date` E26, `Unit_Type` K17, `Gross` K19, `PUE` K23, `Debt_LTC_Target` C80, `Interest_Const_Loan` E84, `Interest_Mezz_Loan` E85, `Fixed_Variable` A83, `Perm_Debt?` A102, `PermDebt_Fund` C104, `Timing_Operation_Begin_Month` D113, `Mgmt_Fee_Pct` I158, `Timing_Reversion_Month` D178.

Calculées : `IT_Load` E131, `Project_Cost_Total` K76, `Equity_Total` K79, `Debt_Total` K80, `Debt_LTC_Actual` F80, `Stabilization_1st_Month` D114, `Timing_Construction_End` E76, `Timing_Analysis_End_Month` K25, `Valuation_Untrended` / `Trended` / `Reversion` I207 / J207 / K207, `Rel_EGR_ProForma` K148, `REL_Mgmt_Fee_Proforma` K158, `Mgmt_Fee_0` S158, `Rel_Mgmt_Fee_All` S158:EU158, `Recalc_Const` EX282, `Recalc_Mgmt` EX283, `Recalc?` EX284. Plus des plages de section et `Rel_*` (dette permanente, budget).

### 1.4 Circularités, itération et macros

- Réglage du fichier : `calcPr iterateCount=250 iterateDelta=1e-5`, mais **itération désactivée** (`iterate` absent).
- Aucune formule n'est circulaire en l'état. Les deux boucles sont « cassées » par des **valeurs en dur posées par des macros VBA** (bouton jaune *Recalculate*, `Run_Recalculate`) :
  1. **`Recalculate_Const`** : *goal seek* de `Equity_Total` (K79, **valeur en dur** 74 578 152,26) jusqu'à `Debt_LTC_Actual` (F80) = `Debt_LTC_Target` (C80). Il résout la boucle intérêts de construction ↔ montant du prêt ↔ coût total.
  2. **`Recalculate_Mgmt_Fee`** : active l'itération, écrit `=Mgmt_Fee_Pct × EGR` sur la ligne 158 (S:EU et K158), puis **colle les valeurs** : 133 nombres en dur sur la ligne 158. La boucle passe par les refacturations (recovery = % × total OPEX, qui inclut les honoraires). Elle n'est active que si un % de refacturation est > 0 ; il vaut 0 dans le cas de base.
- Indicateurs de cohérence : `Recalc_Const` (LTC atteint à 3 décimales), `Recalc_Mgmt` (honoraires moyens = % cible), `Recalc?` = ET des deux. Tous valent **VRAI** dans le fichier livré.
- Autres macros : activation et désactivation de la dette permanente, taux fixe ou variable, ajout et suppression de lignes de budget. Le pont n'en utilisera aucune.

### 1.5 Vérification LibreOffice headless (faite)

- Tel quel, LibreOffice 24.2 calcule **faux** : les noms `Perm_Debt?` et `Recalc?` contiennent un `?`, illégal pour LibreOffice (Err:509). L'erreur se propage à 4 273 cellules, dont les TRI.
- **Correctif de compatibilité**, appliqué à la copie seulement : renommer en `Perm_Debt_Flag` et `Recalc_Flag`, soit 174 occurrences dans les formules. Résultat sur les **25 433 cellules numériques**, comparées aux valeurs mises en cache par Excel :
  - `Underwriting` : écart relatif max **2,4e-8** (tolérance demandée : 1e-6). TRI unlevered 10,8630294 % contre 10,8630294 % ; TRI levered 12,3272847 % contre 12,3272842 %.
  - `Annual CF` colonnes H–M : `#VALUE!`. LibreOffice n'accepte pas `OFFSET(..., -largeur)`. **Correctif** : réécrire en `OFFSET(réf, 0, début−n+1, 1, n)`, ce qui est équivalent dans Excel.
- Recalcul complet : **0,5 s** (UNO, processus LibreOffice gardé ouvert).

### 1.6 Hypothèses du cas de base (cellules en dur, police bleue)

| Bloc | Cellules | Valeur |
|---|---|---|
| Surface | K19 brute, D121:D130 white space (somme D131) | 150 000 SF, 90 000 SF |
| Puissance IT | E121:E130 kW par locataire (somme `IT_Load` E131) ; K22 = MW (formule) | 6 locataires : 6 000 / 4 000 / 3 000 / 2 500 / 2 000 / 2 500 kW = **20 MW** |
| PUE | K23 | **1,5**, puissance totale K24 = 30 MW |
| Terrain | K33, K34 | 10,9 M$ + 0,4 M$ |
| Coûts durs | K41 voirie et VRD 10,21 M ; K42 béton et charpente 19,1 M ; K43 enveloppe 12,75 M ; K44 faux plancher 6,38 M ; **K45 mécanique (HVAC) 22,95 M** ; **K46 électrique 31,88 M** ; K47 incendie 5,1 M ; K48 sûreté 3,83 M ; K49 aménagements 7,65 M ; **K50 raccordements réseaux 7,65 M** ; K51 ligne libre « [Item] » = 0 | total 127,5 M$ (6 375 $/kW) |
| Coûts mous | K55–K65 | 19,12 M$ |
| Calendrier | D/E 41–65 (mois), E26 date de début | début 07/2025, construction 24 mois, exploitation au mois 25 |
| Locataires | F (début de bail), G (début de montée), **H absorption 417 kW/mois**, **I loyer 285 $/kW/mois**, **J indexation 2 %** | stabilisation au mois 46 |
| Vacance | I147 | 5 % |
| **Utilities** | **E153 = 100 % fixe, G153 indexation 2,5 %, H153 = 109,5 $/kW/mois** ; K153 = H153 × IT × PUE × 12 | 39,42 M$/an, soit **150 $/MWh** à facteur de charge 100 % |
| Autres OPEX | maintenance H154 10 $/kW/mois (25 % fixe) ; personnel H155 5 ; assurance H156 0,5 ; G&A H157 0,75 ; honoraires I158 3 % de l'EGR ; taxe foncière K159 1,1 M$ | |
| Capex récurrent | H165 1 $/kW/mois | |
| Dette | C80 LTC cible 65 % ; C84 construction 65 % à E84 9 % ; mezzanine 0 % (E85 12 %) ; dette permanente **off** (A102 = 0 ; C105 6 %, C107 30 ans, G100 LTV 60 %) | |
| Sortie | K175 cap rate actuel 6 % ; K176 cap rate de sortie 6,75 % ; K177 frais de vente 2 % ; D178 mois de vente 72 | |

### 1.7 Sorties clés (valeurs Excel en cache = référence de non-régression)

| Sortie | Cellule | Base |
|---|---|---|
| TRI unlevered (« projet ») | J229 | 10,863 % |
| TRI levered (« equity ») | J230 | 12,327 % |
| Multiple unlevered / levered | I229 / I230 | 1,605x / 1,870x |
| Profit net unlevered / levered | K229 / K230 | 116,49 M$ / 64,91 M$ |
| Coût total (avec portage) / avant financement | K76 / K68 | 213,08 M$ / 157,92 M$ |
| Equity / dette | K79 / K80 | 74,58 M$ / 138,50 M$ |
| Rendement sur coût (non indexé, indexé, à la vente) | I233 / J233 / K233 | 8,73 % / 8,45 % / 8,58 % |
| Marge de développement | I235 | 273 bp |
| Valeurs (non indexée, indexée, vente) | I207 / J207 / K207 | 310,2 / 277,9 / 271,0 M$ |
| NOI stabilisé | I195 | 18,61 M$ |
| Séries mensuelles | 153 utilities, 162 NOI, 169 CFO, 215 intérêts, 221 service de la dette permanente, 229 / 230 flux unlevered / levered | — |

## 2. SustainDC : ce que j'ai lu et mesuré

Source : `vendor/sustaindc`, cloné depuis `HewlettPackard/dc-rl` au commit `a92b475` (identique à la racine de ce fork). `vendor/` est ignoré par git ; le commit sera épinglé dans le `Makefile`.

### 2.1 Architecture utile

| Élément | Fichier | Rôle |
|---|---|---|
| `DC_Config` | `utils/dc_config_reader.py` + `utils/dc_config.json` | géométrie, courbes serveurs, CVC |
| `DataCenter_ITModel`, `Rack`, `CPU` | `envs/datacenter.py` | puissance CPU et ventilateurs IT par rack (charge, T entrée) ; T sortie des racks |
| `calculate_HVAC_power` | `envs/datacenter.py` | charge CRAC, compresseur (courbe EnergyPlus), ventilateur de tour, pompes |
| `chiller_sizing` | `envs/datacenter.py` | dimensionnement au pire cas |
| `calculate_cooling_tower_water_usage` | `envs/datacenter.py` | eau de la tour |
| `dc_gymenv` | `envs/dc_gym.py` | action = delta de consigne {-1, 0, +1}, bornée à 15–21,6 °C |
| `Battery2` | `envs/battery_model.py` | batterie C/L/C (MWh, C-rate, rendements) |
| `Weather_Manager`, `Workload_Manager`, `CI_Manager` | `utils/managers.py` | EPW interpolé en 15 min, utilisation CPU sur 8760 h, intensité carbone 2022 |

### 2.2 Simuler une année avec des actions fixes

`SustainDC.reset()` est aléatoire : jour de départ tiré au sort, bruit sur la météo, décalage de 0 à 13 jours. Il importe aussi `torch` et `harl`. Le wrapper construira donc `dc_gymenv` via `make_dc_pyeplus_env` avec un `dc_config.json` généré, lira les séries brutes (`original_*`) et bouclera sur 35 040 pas de 15 min avec l'action `1` (consigne fixe). La batterie sera pilotée hors env avec `Battery2`.

Mesure (20 racks, New York, trace Alibaba, 18 °C) : **18,9 s par an** ; 9 258 MWh IT ; 3 927 MWh de refroidissement ; PUE (IT + CVC) 1,424 ; pointe 1,83 MW ; 43 740 m³ d'eau.

Utilisation CPU moyenne des traces fournies : Alibaba 1 = 49,5 %, Alibaba 2 = 31,5 %, Google = 67,9 %.

### 2.3 Constats sur le modèle vendor

1. `datacenter_capacity_mw` ne pilote pas la puissance : les résultats sont identiques à 1 et à 5 MW. C'est `CPUS_PER_RACK` qui la fixe, et le wrapper le calcule à partir des kW par rack.
2. La courbe serveur donne environ 68 kW par rack à 100 % de charge, et encore **56 %** de cette puissance à 0 % de charge. kW par rack = puissance de conception à 100 % de charge et à 18 °C (Q2).
3. Le COP saisi n'est pas utilisé : `rated_cop = 3.0` est en dur. Le wrapper applique compresseur × 3 / COP.
4. Le total CVC exclut les ventilateurs CRAC et les pompes. Je les ajoute.
5. Aucune perte électrique. J'ajoute des rendements UPS et transformateur (YAML).
6. L'eau ne dépend pas de la charge. Je la recalcule à partir de la chaleur rejetée (évaporation, purge à 5 cycles, entraînement 1 %) ; c'est une approximation.
7. La consigne est bornée à 15–21,6 °C ; la température d'entrée de rack = consigne + 3,8 à 5,3 °C.
8. Dimensionnement du chiller par site : seuls NY, AZ et WA sont prévus. Je le remplace par le percentile 99,6 % de l'EPW.
9. Sites : 11 EPW américains et l'intensité carbone des régions US 2022 uniquement. **Il n'y a ni EPW ni intensité carbone pour le Panama**, site du classeur. Les sites hors catalogue SustainDC passeront par Open-Meteo (Q6).
10. Le temps de calcul est proportionnel au nombre de racks (environ 1 s par rack et par an). Le cas de base du classeur (environ 1 000 racks) prendrait environ 16 min. Comme les racks d'une même classe (bord ou intérieur) sont identiques, je simulerai **une rangée de chaque classe** et je pondérerai, ce qui est **exact** ; avec un port vectorisé validé contre le vendor à 1e-9, l'objectif est moins d'une seconde par an. Surrogate seulement au-delà de 3 s.

## 3. Ce qui manque et traitement proposé

| Manque | Où | Traitement proposé | Statut |
|---|---|---|---|
| Refroidissement liquide | SustainDC | fraction `f_liquide` de la chaleur par boucle liquide (pompes et CDU ≈ 2–3 % de l'IT, dry-cooler sans compresseur) ; le reste par le modèle air | **approximation** |
| Free cooling / économiseur | SustainDC | compresseur à 0 quand T humide + approche ≤ T eau glacée | **approximation** (sans effet au Panama) |
| Chiller à air vs à eau | SustainDC | via le COP saisi | approximation |
| Prix de l'électricité | les deux | Python : plat, plages, CSV 8760 ; coût = Σ prix_h × énergie réseau_h | exact |
| Batterie MW ≠ MWh | SustainDC | `Battery2` avec C-rate = MW/MWh, rendement aller-retour, règle prix ou carbone | adaptation |
| Batterie au CAPEX | Excel | ligne libre **K51** des coûts durs (« [Item] » renommée « BESS ») | ajout dans la copie |
| Pertes électriques | SustainDC | rendements UPS et transformateur | Python |
| Eau, prix de l'eau | les deux | eau recalculée (2.3 point 6) ; aucune ligne eau dans le classeur → intégrée au taux utilities (§4.4) | Python |
| CO2, prix du carbone | les deux | Σ intensité × énergie ; aucune ligne carbone dans le classeur → intégrée au taux utilities | Python |
| Raccordement réseau | SustainDC | alerte pointe > capacité ; capacité de base = K24 (30 MW) | Python |
| Taux d'utilisation | Excel | le classeur suppose des utilities **100 % fixes à pleine puissance** (E153 = 1) ; le jumeau calcule l'énergie réelle au profil de charge choisi | voir Q1 |
| VAN | Excel | `XNPV` sur le flux unlevered (ligne 229) au taux `tw_discount_rate`, sur la feuille `Outputs` | **nouvel input**, pas de source dans le classeur |
| DSCR, LLCR, PLCR, CFADS | Excel | calculés sur `Outputs` : CFADS ≈ CFO (169) ; DSCR = CFO / service de la dette permanente (221) ; LLCR = VAN(CFADS sur la durée du prêt, au taux du prêt) / encours. **N/A tant que la dette permanente est désactivée** (cas de base) | voir Q3 |
| Covenant DSCR | Excel | alerte UI uniquement (1,20x) | — |

## 4. Mapping paramètre du jumeau → calcul → cellule Excel

Principe du pont (Q1) : une copie du classeur reçoit une feuille `Inputs_Twin` (constantes `tw_*`) et une feuille `Outputs` (formules `out_*`). Chaque cellule d'hypothèse ci-dessous est remplacée par `=tw_…`. **Dans le cas de base, chaque `tw_*` contient la valeur originale de la cellule.** Python n'écrit que dans `Inputs_Twin`.

### 4.1 Géométrie et puissance

| Paramètre du jumeau | SustainDC / Python | Cellule Excel (v1.7) → `tw_*` | Unité | Base |
|---|---|---|---|---|
| Nombre de halls | PY : multiplicateur | — | – | **2** (« 2 phases de 10 MW ») |
| Rangées par hall | SDC `NUM_ROWS` | — | – | **20** |
| Racks par rangée | SDC `NUM_RACKS_PER_ROW` | — | – | **25** |
| kW par rack | SDC `CPUS_PER_RACK` calibré | — | kW | **20** |
| **Capacité IT (dérivée)** | halls × rangées × racks × kW / 1000 | E121:E130 → `tw_tenant_kw_1..10` (base_i × IT / 20 000, répartition au prorata) | kW | 2 × 20 × 25 × 20 = **20 000** |
| Absorption (rythme de commercialisation) | prorata de la capacité (durée de montée conservée) | H121:H130 → `tw_absorption_1..10` | kW/mois | 417 |
| White space | 90 SF/rack (base 90 000 / 1 000) | D121:D130 → `tw_whitespace_1..10` | SF | 90 000 |
| Surface brute | white space / 0,6 (ratio de base) | K19 → `tw_gross_sf` | SF | 150 000 |
| Capacité réseau | PY : alerte | (CAPEX K50, §4.3) | MW | 30 (= K24) |

### 4.2 Physique et énergie

| Paramètre du jumeau | SustainDC / Python | Cellule Excel → `tw_*` | Unité | Base |
|---|---|---|---|---|
| Type de refroidissement | PY : `air_chiller` / `air_free_cooling` / `liquide` | K45 (§4.3) | énum | air_chiller |
| COP chiller | compresseur × 3 / COP | — | – | 3,0 |
| Consigne de soufflage | `dc_env.raw_curr_stpt` | — | °C | 18 |
| Site (liste déroulante) | `twin/sites.yaml` → EPW SustainDC ou série Open-Meteo en cache ; intensité carbone (CSV horaire US ou facteur constant) ; sizing p99,6 | — | – | Panama (Open-Meteo, Q6) |
| Profil de charge | trace ou utilisation constante | — (Q1) | % | à valider (Q1) |
| Batterie | `Battery2` | K51 (§4.3) | MW / MWh | 0 / 0 |
| **PUE annuel simulé** | total / IT | **K23 → `tw_pue`** | – | 1,5 |
| **Coût énergie annuel** | Σ prix_h × énergie_h | **H153 → `tw_utilities_rate`** = (énergie + eau + carbone) / (IT_kW × PUE × 12) | $/kW/mois | 109,5 |
| Tarif électricité | plat / plages / CSV | via H153 | $/MWh | **150** (= 109,5 × 12 / 8,76) |
| Part fixe des utilities | — | E153 → `tw_utilities_fixed` | % | 100 % |

### 4.3 CAPEX paramétrique (YAML, défauts calés sur le classeur)

| Poste | Formule | Cellule → `tw_*` | Défaut |
|---|---|---|---|
| Bâtiment | $/kW IT × IT, réparti au prorata des lignes de base | K41, K42, K43, K44, K47, K48, K49 → `tw_capex_<ligne>` | **3 251 $/kW** (65,02 M$) |
| Mécanique | $/kW IT selon le type de refroidissement | K45 → `tw_capex_mechanical` | **1 147,5 $/kW** (air_chiller) ; autres types : défauts proposés, à confirmer |
| Électrique | $/kW IT | K46 → `tw_capex_electrical` | **1 594 $/kW** |
| Raccordement réseau | $/MW de capacité réseau | K50 → `tw_capex_grid` | **255 000 $/MW** (7,65 M$ / 30 MW) |
| Batterie | $/MWh + $/MW (PCS) | K51 → `tw_capex_battery` | 0 en base ; prix unitaires proposés, à confirmer |
| Terrain, coûts mous | inchangés | K33–K37, K55–K65 | tels quels (Q4) |

### 4.4 Hypothèses marché (panneau global)

| Paramètre | Cellule → `tw_*` | Unité | Base |
|---|---|---|---|
| Loyer | I121:I130 → `tw_rent_1..10` (une valeur commune) | $/kW/mois | 285 |
| Indexation loyers | J121:J130 → `tw_rent_growth` | %/an | 2 % |
| Montée en occupation | H (absorption), F/G (calendrier) | kW/mois, mois | 417 ; mois 26 / 38 |
| Prix carbone | ajouté à H153 | $/tCO2 | 0 (aucune source dans le classeur) |
| Prix de l'eau | ajouté à H153 | $/m³ | 0 (aucune source dans le classeur) |
| Indexation énergie | G153 → `tw_idx_energy` | %/an | 2,5 % |
| Indexation OPEX | G154:G159 → `tw_idx_opex` | %/an | 2,5 % |
| Taux d'actualisation VAN | `tw_discount_rate` (nouveau) | % | à fournir (Q3) |
| Covenant DSCR | UI | x | 1,20 |

### 4.5 Circularités dans la copie

| Boucle | Original | Copie (pont) |
|---|---|---|
| Equity / LTC | K79 en dur, goal seek VBA | K79 → `tw_equity_total` ; Python résout F80 = C80 par sécante (≈ 5–8 recalculs) dans les deux moteurs ; vérifie `Recalc_Const` |
| Honoraires de gestion | ligne 158 en dur (valeurs collées) | ligne 158 et K158 en formules `=Mgmt_Fee_Pct × EGR` + **itération activée** (250 ; 1e-5) ; vérifie `Recalc_Mgmt` |
| Noms avec `?` | `Perm_Debt?`, `Recalc?` | renommés `Perm_Debt_Flag`, `Recalc_Flag` |
| `OFFSET` à largeur négative | Annual CF H:M | forme équivalente à largeur positive |

### 4.6 Sorties lues par le jumeau (`Outputs`)

`out_irr_project` = J229 · `out_irr_equity` = J230 · `out_em_unlev` / `out_em_lev` = I229 / I230 · `out_profit_unlev` / `out_profit_lev` = K229 / K230 · `out_capex_total` = K76 · `out_capex_before_fin` = K68 · `out_equity` = K79 · `out_debt` = K80 · `out_ltc` = F80 · `out_yoc` = I233 · `out_dev_spread` = I235 · `out_value_sale` = K207 · `out_noi_stab` = I195 · `out_opex_energy_y1` = Σ ligne 153 sur les 12 premiers mois d'exploitation · `out_npv` = XNPV(ligne 229) · séries annuelles `out_cfads[]` (169), `out_debt_service[]` (221, plus les intérêts de construction 215 pour information), `out_dscr[]`, `out_dscr_min`, `out_dscr_avg`, `out_llcr` (N/A si la dette permanente est désactivée) · `out_recalc_ok` = EX284.

## 5. Questions à valider

- **Q1 — Raccord physique ↔ classeur.** Le classeur calcule les utilities à **pleine puissance et 100 % fixes** : 20 MW × 1,5 × 8 760 h × 150 $/MWh = 39,4 M$/an. Le jumeau calcule une consommation réelle au profil de charge (environ 50 % d'utilisation CPU avec la trace Alibaba ; puissance IT environ 78 % de la conception). Pour que le cas de base reproduise le classeur, je propose :
  - **cas de base** = valeurs originales (`tw_pue` = 1,5, `tw_utilities_rate` = 109,5), ce qui garantit la non-régression à 1e-6 ;
  - **scénarios, mode calibré par défaut** : `tw_pue` = 1,5 × PUE_sim / PUE_sim_base et `tw_utilities_rate` = 109,5 × (coût_sim / coût_sim_base) × (IT_base × PUE_base) / (IT × PUE). Ainsi « +10 % sur le prix » donne exactement « +10 % d'OPEX énergie » ;
  - **mode absolu** disponible (valeurs simulées brutes), avec l'écart base simulée / base classeur affiché.
  
  Profil de charge de base pour la simulation : **utilisation constante à 100 %** (cohérent avec l'hypothèse du classeur), ou trace ? Je recommande 100 % constant en base.
- **Q2 — Géométrie de base** : 2 halls × 20 rangées × 25 racks × 20 kW = 20 MW, en air avec chiller. Et kW par rack = puissance de conception à 100 % de charge et 18 °C. D'accord ?
- **Q3 — Indicateurs de project finance absents.** DSCR, LLCR et VAN n'existent pas nativement, et la dette est un prêt de construction remboursé à la vente (pas de service de la dette en exploitation). Options :
  - (a) calculer DSCR / LLCR sur `Outputs` uniquement si la dette permanente est activée (N/A dans le cas de base, mais le panneau la permet) ;
  - (b) activer la dette permanente dans tous les scénarios ; dans ce cas, le cas de base du jumeau diffère du classeur original, ce qui est contradictoire avec la non-régression.
  
  Je recommande (a). Il me faut aussi un **taux d'actualisation** pour la VAN.
- **Q4 — CAPEX** : les coûts mous et le terrain restent fixes, ou bien sont-ils proportionnels aux coûts durs ou à la surface ? Je propose fixes, sauf « Contingency » et « Development Fee » (lignes 62 et 65), qui garderaient leur ratio de base aux coûts durs (1,5 % et 3 %).
- **Q5 — Corrections du vendor** (COP, auxiliaires, eau, sizing) et **approximations** (liquide, free cooling), désactivables et documentées dans `docs/vendor_patches.md`. D'accord ?
- **Q6 — Site : décidé.** Le site est une simple liste déroulante, sans saisie libre. Le catalogue est décrit dans `twin/sites.yaml` ; chaque entrée a un identifiant, un libellé, des coordonnées, une source météo et une source carbone.
  - **Météo disponible tout de suite** : les 11 EPW de SustainDC (Phoenix, Tucson, San José, Atlanta, Chicago, New York JFK et LaGuardia, Dallas, Leesburg VA, Port Angeles, Seattle).
  - **Sinon, API publique** : Open-Meteo Archive (réanalyse ERA5, gratuite, sans clé). On en tire la température sèche, l'humidité relative et la pression horaires d'une année ; la température humide est calculée avec `psychrolib`, comme dans SustainDC. Repli : NASA POWER (horaire, sans clé). La série est mise en cache dans `data/weather/<site>.csv` et réutilisée hors ligne.
  - **Carbone** : fichiers CI horaires de SustainDC pour les sites US. Pour les autres, un facteur annuel constant dans le YAML, sourcé et marqué « approximation » : il n'existe pas d'API horaire publique sans clé.
  - **Panama** : entrée du catalogue alimentée par Open-Meteo, en attente de l'ouverture réseau (voir ci-dessous).
  - **Blocage actuel** : la politique réseau de la session refuse `archive-api.open-meteo.com`, `power.larc.nasa.gov`, `re.jrc.ec.europa.eu` et `climate.onebuilding.org` (403). Tant que ces domaines ne sont pas autorisés, seuls les 11 sites US sont utilisables, et le Panama ne sera pas simulé avec une météo inventée.
- **Q7 — Excel.** Seul LibreOffice est disponible ici. L'implémentation xlwings sera écrite mais testable uniquement chez toi (Windows / macOS avec Excel).
- **Q8 — Confidentialité.** Le dépôt `adeltr/dc-rl` est **public**. Le `.xlsm` contient le nom du projet, une adresse et une société. Je propose de **ne pas le versionner** (`model/` ignoré par git ; chemin configurable) et de publier seulement des cellules et des valeurs numériques, comme dans ce document. Faut-il plutôt passer le dépôt en privé et versionner le fichier ?
