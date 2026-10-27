# Phase 0 — Découverte et mapping jumeau ↔ SustainDC ↔ Excel

Statut : **en attente de validation**. Aucun code applicatif n'a été écrit.

## 0. Point bloquant : le classeur Excel est absent

Le dépôt ne contient ni dossier `model/` ni fichier `.xlsx` (recherche `find . -name "*.xls*"` vide).
La partie Excel (§1) et la colonne « Cellule Excel cible » du mapping (§4) ne peuvent donc pas être remplies.
Il faut déposer le fichier dans `model/<NOM>.xlsx` (commit sur la branche, ou upload dans la session).
Dès réception, je complète le §1 et la colonne Excel, puis je reviens vers toi pour la validation.

Ce que je relèverai sur le classeur (méthode prévue, `openpyxl` + LibreOffice headless, sans le modifier) :

- feuilles, dimensions, plages nommées (`wb.defined_names`) et leur portée ;
- cellules d'hypothèses en dur (constantes numériques non-formule référencées par des formules) ;
- sorties clés : TRI projet / equity, VAN, DSCR min / moyen, LLCR, PLCR, CAPEX total, CFADS et service de la dette par année ;
- références circulaires (graphe de dépendances des formules) et réglage `calcPr` : `iterate`, `iterateCount`, `iterateDelta` ;
- macros (`.xlsm`, `vbaProject.bin`) et éventuels « copier-coller valeurs » de sculpting pilotés par macro ;
- base de valeurs mises en cache par Excel, qui sert de référence pour le test de non-régression à 1e-6.

## 1. Classeur Excel

À compléter dès réception du fichier.

## 2. SustainDC : ce que j'ai lu et mesuré

Source : `vendor/sustaindc`, cloné depuis `HewlettPackard/dc-rl`, commit `a92b475`. C'est le même commit que la racine de ce dépôt, qui est déjà un fork de dc-rl. `vendor/` est ignoré par git ; le commit sera épinglé dans le `Makefile`.

### 2.1 Architecture utile

| Élément | Fichier | Rôle |
|---|---|---|
| `DC_Config` | `utils/dc_config_reader.py` + `utils/dc_config.json` | géométrie (rangées, racks par rangée, serveurs par rack), courbes serveurs, paramètres CVC |
| `DataCenter_ITModel`, `Rack`, `CPU` | `envs/datacenter.py` | puissance CPU et ventilateurs IT par rack selon la charge et la température d'entrée ; température de sortie des racks |
| `calculate_HVAC_power` | `envs/datacenter.py` | charge CRAC, compresseur du chiller (courbe EnergyPlus « electric chiller »), ventilateur de la tour, pompes |
| `chiller_sizing` | `envs/datacenter.py` | dimensionnement de la tour et du chiller au pire cas (consigne mini, température extérieure maxi) |
| `calculate_cooling_tower_water_usage` | `envs/datacenter.py` | eau de la tour (L par pas de 15 min) |
| `dc_gymenv` | `envs/dc_gym.py` | env Gymnasium « data center » : action = delta de consigne {-1, 0, +1} °C, bornée à 15–21,6 °C |
| `Battery2` | `envs/battery_model.py` | batterie C/L/C : capacité en MWh, limites de charge et de décharge en C-rate, rendements |
| `Weather_Manager`, `Workload_Manager`, `CI_Manager` | `utils/managers.py` | EPW horaire interpolé en 15 min (température sèche et humide), trace d'utilisation CPU 0–1 sur 8760 h, intensité carbone horaire 2022 |
| `SustainDC` | `sustaindc_env.py` | orchestre les 3 env (load shifting, DC, batterie) pour le RL |

### 2.2 Comment simuler une année avec des actions fixes

L'enveloppe `SustainDC` n'est pas adaptée telle quelle à un calcul déterministe d'une année :

- `reset()` tire un jour et une heure de départ au hasard, et `Weather_Manager.reset()` ajoute un bruit cohérent puis décale la météo de 0 à 13 jours au hasard ;
- `sustaindc_env.py` importe `torch` et `harl.envs.sustaindc.dashboard_v2` (dépendances RL lourdes) ;
- la durée d'épisode est exprimée en jours à partir d'un mois de départ.

Approche retenue pour le wrapper, sans toucher à `vendor/` :

1. construire `dc_gymenv` via `utils.make_envs_pyenv.make_dc_pyeplus_env(...)` avec un `dc_config.json` **généré** dans un dossier temporaire à partir des paramètres du jumeau ;
2. lire directement les séries brutes non bruitées des managers (`original_temp_data`, `original_wb_data`, `original_data`) ;
3. boucler sur les 35 040 pas de 15 min avec l'action `1` (delta 0, consigne fixe), après avoir fixé `env.raw_curr_stpt` ;
4. piloter la batterie hors env, avec `Battery2` et une règle simple : prix bas ou carbone bas → charge, haut → décharge.

C'est vérifié par un script de mesure jetable (hors dépôt) sur la config par défaut (20 racks, New York JFK, trace Alibaba, consigne 18 °C) :

| Mesure | Valeur |
|---|---|
| Construction de l'env | 0,3 s |
| **Une année (35 040 pas)** | **18,9 s** |
| MWh IT | 9 258 |
| MWh refroidissement (tour + compresseur) | 3 927, dont compresseur 3 572 |
| PUE annuel (IT + CVC) / IT | 1,424 |
| Pointe | 1,83 MW |
| Eau | 43 740 m³ |

### 2.3 Constats importants sur le modèle (à connaître avant le mapping)

1. **`datacenter_capacity_mw` ne pilote pas la puissance.** Il ne fixe qu'un plafond par rack (`MAX_W_PER_RACK`). La puissance réelle vient de `CPUS_PER_RACK` (200) × la courbe serveur. À 1 MW ou à 5 MW, j'obtiens exactement les mêmes résultats. Le wrapper doit donc générer `CPUS_PER_RACK` à partir des kW par rack.
2. **La courbe serveur donne beaucoup plus que la puissance nominale.** Avec des serveurs « 110–170 W », un rack consomme environ 68 kW à 100 % de charge et 18 °C de consigne. À 0 % de charge, il consomme encore 56 % de la pleine charge. Proposition : calibrer le nombre de serveurs pour que « kW par rack » = **puissance IT de conception à 100 % de charge et à une température d'entrée de référence** (consigne 18 °C, soit environ 23 °C en entrée de rack).
3. **Le COP du chiller saisi n'est pas utilisé.** `CHILLER_COP_BASE` est lu mais `calculate_chiller_power` code en dur `rated_cop = 3.0`. Proposition : wrapper `P_compresseur × 3,0 / COP_saisi` (post-traitement documenté, aucun patch du vendor).
4. **Le total CVC exclut les auxiliaires.** `dc_HVAC_total_power_kW` = ventilateur de tour + compresseur. Les ventilateurs CRAC et les pompes CW/CT sont calculés mais non sommés. Ce sont des valeurs fixes et petites (environ 0,03 kW et 0,38 kW). Je les ajoute dans le poste « refroidissement » du jumeau.
5. **Aucune perte électrique** (UPS, transformateurs, distribution). Pour le bilan « total = IT + refroidissement + pertes », j'ajoute un calcul Python : rendement UPS et transformateur paramétrables, valeurs par défaut dans le YAML.
6. **L'eau ne dépend pas de la charge.** La formule donne un débit en m³/h ne dépendant que des températures, pour une tour de débit fixe : 43 740 m³ quelle que soit la taille. Proposition : recalculer l'eau en Python à partir de la chaleur rejetée. Évaporation ≈ chaleur / chaleur latente ≈ 1,47 L/kWh rejeté, × (1 + 1/(cycles de concentration − 1)) pour la purge, + 1 % d'entraînement. Les cycles de concentration (5) viennent de SustainDC. C'est signalé comme approximation.
7. **Consigne bornée à 15–21,6 °C** (`min_temp` et `max_temp` en dur dans `make_dc_pyeplus_env`). La température d'entrée de rack = consigne + approche (3,8 à 5,3 °C). La plage ASHRAE recommandée (18–27 °C) est donc atteinte jusqu'à environ 21,6 °C de consigne. Les bornes du slider suivront ces valeurs.
8. **Dimensionnement du chiller par site** : `max_amb_temperature` vaut 30 °C (NY), 50 °C (AZ), 20 °C (WA), sinon 50 °C par défaut avec un warning. Le wrapper le remplacera par le percentile 99,6 % de la température sèche de l'EPW (pratique ASHRAE de dimensionnement).
9. **Sites disponibles** : 11 EPW américains. Intensité carbone : régions US 2022. Correspondance site → EPW → fichier CI via `obtain_paths`, mais seuls 8 États sont gérés. Le jumeau aura sa propre table de sites. Un site hors US exige d'ajouter un EPW et un CSV d'intensité carbone 8760 h.
10. **Performance** : le coût est proportionnel au nombre de racks (boucle Python par rack). 20 racks = 19 s, donc un hall de 400 racks ≈ 6 min. Or, à charge uniforme, tous les racks d'une même « classe » (même approche de soufflage et de reprise, mêmes serveurs) donnent des résultats identiques. Le modèle a 2 classes : rangées de bord (5,3 / −3,7 °C) et rangées intérieures (5,0 / −2,5 °C). Proposition : simuler une rangée de bord et une rangée intérieure, puis pondérer par le nombre de rangées et de halls. C'est **exact** dans le modèle SustainDC, pas une approximation. Je propose aussi un port vectorisé (numpy sur les 35 040 pas) des mêmes équations, validé contre la boucle du vendor à 1e-9 près par un test. Objectif : moins d'une seconde par année. Si on dépasse 3 s, le surrogate (grille interpolée) sera construit comme prévu.

## 3. Ce qui n'existe pas dans SustainDC et traitement proposé

| Manque | Traitement proposé | Statut |
|---|---|---|
| Refroidissement liquide (DLC, immersion) | mode simplifié : fraction `f_liquide` de la chaleur IT évacuée par boucle liquide à PUE partiel fixe (pompes et CDU ≈ 2–3 % de l'IT), plus dry-cooler ou tour sans compresseur ; le reste (1 − f) passe par le modèle air SustainDC | **approximation**, signalée dans l'UI |
| Free cooling / économiseur | heures où T humide + approche < T eau glacée requise : compresseur à 0, ventilateurs de tour seuls | **approximation** |
| Chiller à air vs à eau | courbe EnergyPlus du vendor = chiller à air ; « chiller à eau + tour » via COP saisi (point 3) | approximation via COP |
| Prix de l'électricité | Python : plat, plages horaires (HP/HC, saisons), CSV 8760 h ; coût = Σ prix_h × énergie_h soutirée au réseau (après batterie) | calcul Python exact |
| Batterie : puissance MW distincte des MWh | `Battery2` avec `c_lim = d_lim = MW / MWh`, rendement aller-retour paramétrable (le vendor a 100 %), règle déterministe prix ou carbone | adaptation du modèle vendor |
| Comptage des cycles batterie | Python : Σ énergie déchargée / capacité utile | calcul Python |
| Capacité de raccordement réseau | Python : alerte si pointe > capacité ; option d'écrêtage par la batterie | calcul Python |
| Pertes électriques (UPS, transfo) | Python : rendements dans le YAML | calcul Python |
| Plusieurs halls | multiplicateur (halls identiques) | exact dans le modèle |
| Densité > environ 30 kW par rack en air | autorisée mais alerte « hors domaine air » si refroidissement = air et kW par rack > seuil (YAML, 30 kW par défaut) | garde-fou |
| CAPEX | Python paramétrique, YAML éditable : $/MW IT pour bâtiment, électrique, mécanique (par type de refroidissement), $/MWh et $/MW batterie, raccordement | calcul Python |
| Eau proportionnelle à la charge | voir 2.3 point 6 | approximation |
| tCO2 | Σ intensité_h × énergie réseau_h (CSV CI du site, gCO2/kWh) | calcul Python |

## 4. Mapping paramètre du jumeau → calcul → Excel

Légende : **SDC** = variable SustainDC alimentée par le wrapper ; **PY** = calcul Python du jumeau ; « ? » = cellule à identifier dans le classeur.
Les valeurs du cas de base dans ce tableau sont celles de SustainDC par défaut. Elles seront **remplacées par les hypothèses du classeur** dès sa lecture (voir la question Q1).

### 4.1 Entrées physiques (jumeau → simulation)

| Paramètre du jumeau | SustainDC / calcul Python | Cellule Excel cible | Unité | Base (provisoire) |
|---|---|---|---|---|
| Nombre de halls | PY : multiplicateur des résultats | ? (via capacité IT) | – | 1 |
| Rangées par hall | SDC `data_center_configuration.NUM_ROWS` ; listes d'approche générées (bord / intérieur) | – | – | 4 |
| Racks par rangée | SDC `NUM_RACKS_PER_ROW` | – | – | 5 |
| kW par rack | SDC `CPUS_PER_RACK` calibré (2.3 point 2), `MAX_W_PER_RACK` relevé | – | kW | 67,8 (équivalent défaut) |
| **Capacité IT (dérivée, non saisie)** | PY : halls × rangées × racks × kW / 1000 | ? capacité IT installée (MW) | MW | 1,36 |
| Type de refroidissement | PY : `air_chiller` (SDC pur), `air_free_cooling`, `liquide` (§3) | ? (choix CAPEX mécanique) | énum | air_chiller |
| COP chiller | PY : compresseur × 3,0 / COP (2.3 point 3) | – | – | 3,0 |
| Consigne de soufflage | SDC `dc_env.raw_curr_stpt`, action fixe `1` | – | °C | 18 |
| Site | SDC EPW (`Weather_Manager`), CSV CI (`CI_Manager`) ; PY sizing p99,6 | ? (libellé de site) | – | New York JFK / NYIS |
| Batterie puissance | PY `Battery2.c_lim = d_lim = MW / MWh` | ? | MW | 0 |
| Batterie énergie | PY `Battery2.capacity` | ? | MWh | 0 |
| Stratégie batterie | PY : charge aux heures à bas prix ou à bas carbone | – | énum | prix |
| Profil de charge | SDC `Workload_Manager.original_data` (trace) ou utilisation constante | ? (taux d'occupation, si présent) | % | trace Alibaba 1 (moyenne à calculer) |
| Capacité de raccordement réseau | PY : alerte / écrêtage | ? | MW | à définir |
| Rendement UPS / transformateur | PY (YAML) | – | % | 96 / 99 (proposé) |
| Tarif électricité | PY : plat, plages ou CSV 8760 | ? prix de l'énergie | $/MWh | à lire dans le classeur |

### 4.2 Sorties du jumeau → hypothèses du classeur

| Sortie du jumeau | Calcul | Cellule Excel cible (tw_*) | Unité |
|---|---|---|---|
| Énergie IT annuelle | Σ SDC `dc_ITE_total_power_kW` × 0,25 h | `tw_it_mwh` → ? | MWh/an |
| Énergie refroidissement | Σ (tour + compresseur × 3/COP + CRAC + pompes) | `tw_cooling_mwh` → ? | MWh/an |
| Pertes électriques | PY | `tw_losses_mwh` → ? | MWh/an |
| Énergie totale soutirée | IT + refroidissement + pertes ± batterie | `tw_total_mwh` → ? | MWh/an |
| PUE annuel | total / IT | `tw_pue` → ? (si l'OPEX énergie est calculé par PUE × IT) | – |
| PUE mensuel | idem par mois | (graphique seulement) | – |
| Pointe | max des pas de 15 min | `tw_peak_mw` → ? (abonnement / puissance souscrite si présent) | MW |
| Eau | PY (2.3 point 6) | `tw_water_m3` → ? | m³/an |
| Émissions | PY | `tw_tco2` → ? (coût carbone) | tCO2/an |
| Coût d'énergie | Σ prix_h × énergie_h | `tw_energy_cost` → ? OPEX énergie année 1 | $/an |
| Coût effectif de l'énergie | coût / total | `tw_energy_price_eff` | $/MWh |
| Cycles batterie | PY | `tw_bat_cycles` → ? (dégradation, si présente) | cycles/an |

### 4.3 CAPEX paramétrique (PY, YAML) → classeur

| Poste | Formule | Cellule Excel cible | Unité | Défaut proposé (éditable) |
|---|---|---|---|---|
| Bâtiment / génie civil | $/MW IT × MW IT | `tw_capex_building` → ? | $ | à caler sur le classeur |
| Électrique (HT/BT, UPS, groupes) | $/MW IT × MW IT | `tw_capex_electrical` → ? | $ | idem |
| Mécanique | $/MW IT selon le type de refroidissement | `tw_capex_mechanical` → ? | $ | idem |
| Batterie | $/MWh × MWh (+ $/MW × MW pour le PCS) | `tw_capex_battery` → ? | $ | idem |
| Raccordement réseau | $/MW × capacité | `tw_capex_grid` → ? | $ | idem |

### 4.4 Hypothèses marché (panneau global) → classeur

| Paramètre | Cellule Excel cible | Unité |
|---|---|---|
| Revenu colocation | `tw_rev_kw_month` → ? | $/kW/mois |
| Montée en occupation (courbe par année) | `tw_occupancy_ramp` → ? | % par an |
| Prix carbone | `tw_carbon_price` → ? | $/tCO2 |
| Prix de l'eau | `tw_water_price` → ? | $/m³ |
| Indexations (revenus, énergie, OPEX) | `tw_idx_*` → ? | %/an |
| Covenant DSCR (alerte UI, pas Excel) | – | x (1,20 par défaut) |

### 4.5 Sorties du classeur (out_*) lues par le jumeau

`out_equity_irr`, `out_project_irr`, `out_npv`, `out_dscr_min`, `out_dscr_avg`, `out_llcr`, `out_plcr`, `out_capex_total`, `out_opex_energy_y1`, `out_cfads[]`, `out_debt_service[]`, `out_dscr[]` (séries annuelles). Cellules sources à identifier.

## 5. Questions à valider

- **Q1 — Cas de base et non-régression.** Le test exige que le cas de base reproduise le classeur original à 1e-6. Or la simulation ne retrouvera jamais exactement les MWh ou le PUE saisis en dur dans le classeur. Je propose :
  - en **cas de base**, `Inputs_Twin` contient les **valeurs originales** du classeur (le test valide le recâblage) ;
  - pour un scénario, deux modes :
    - (a) **absolu** : les valeurs simulées sont écrites telles quelles ;
    - (b) **calibré** : valeur classeur × (simulation scénario / simulation base), pour que « base simulée = base classeur ».
  
  Je recommande **(b) par défaut**, avec (a) disponible et l'écart base simulée / base classeur affiché. D'accord ?
- **Q2 — Définition des kW par rack** : puissance de conception à 100 % de charge à 18 °C de consigne (2.3 point 2). D'accord ?
- **Q3 — Corrections du modèle vendor** faites dans le wrapper : COP effectif, auxiliaires ajoutés, eau proportionnelle à la chaleur, sizing p99,6. Chaque correction sera désactivable et documentée dans `docs/vendor_patches.md`. D'accord ?
- **Q4 — Refroidissement liquide et free cooling** en mode simplifié (§3), signalés « approximation ». D'accord ?
- **Q5 — Performance** : rangées-classes + port vectorisé validé contre le vendor, surrogate seulement si plus de 3 s. D'accord ?
- **Q6 — Classeur** : merci de déposer `model/<NOM>.xlsx`. Indique aussi si Excel (xlwings) sera disponible chez toi. Ici, seul LibreOffice headless est installé.
