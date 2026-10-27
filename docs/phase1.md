# Phase 1 — Moteur du jumeau

## Lancer

```bash
make setup        # venv Python 3.11 + clone de SustainDC épinglé (a92b475) dans vendor/sustaindc
make test         # 31 tests : parité vendor, bilan énergétique, PUE, monotonie, cache, journal
make bench        # temps d'une simulation annuelle
```

```python
from twin.engine import run_year
from twin.params import TwinParams

r = run_year(TwinParams(site_id="us_ny_jfk", geometry={"kw_per_rack": 30}))
r.pue_annual, r.energy.facility_mwh, r.energy_cost_usd, r.capex.total_usd
```

## Organisation

| Fichier | Rôle |
|---|---|
| `twin/params.py` | `TwinParams` (pydantic) : géométrie (halls, rangées, racks, kW/rack → **capacité IT dérivée**), refroidissement, site, batterie, charge, capacité réseau, tarif, CAPEX manuel, données manuelles, corrections du vendor |
| `twin/engine.py` | `run_year(params) -> TwinResults` : cache par hash, journal JSONL ; `simulate()` sans cache |
| `twin/physics.py` | port vectorisé des équations SustainDC (parité ≤ 1e-9 avec `dc_gymenv`) |
| `twin/datasources.py` | catalogue de sites, météo, intensité carbone, traces de charge, avec provenance |
| `twin/pricing.py` | tarif plat, plages horaires (heures × jours ouvrés / week-end × mois), CSV 8 760 h |
| `twin/battery.py` | règle déterministe : charge aux pas les moins chers (ou les moins carbonés) du jour, décharge aux plus chers ; écrêtage au-delà de la capacité réseau |
| `twin/capex.py` | CAPEX par composant, ventilé sur les lignes de coûts durs du classeur (K41–K51) |
| `twin/config/defaults.yaml` | toutes les valeurs par défaut, éditables, chacune avec sa source |
| `twin/config/sites.yaml` | sites de la liste déroulante |

## Temps de calcul

`make bench` (5 répétitions, sans cache de résultats) :

| Cas | Médiane | Max |
|---|---|---|
| base (NY, 20 MW, charge 100 %) | 0,012 s | 0,012 s |
| trace Alibaba | 0,014 s | 0,014 s |
| batterie + tarif horaire | 0,032 s | 0,033 s |
| campus 200 MW (10 halls) | 0,012 s | 0,337 s* |

\* premier chargement d'un site : lecture de l'EPW et calcul de la température humide, puis mise en cache mémoire.

La boucle SustainDC d'origine prend 19 s par an pour 20 racks, soit environ 16 min pour les 1 000 racks du cas de base. Le port vectorisé met moins de 0,4 s dans le pire cas, sous le seuil de 3 s : **pas de surrogate pour la physique**. Le maillon lent sera le recalcul Excel (≈ 0,5 s par recalcul LibreOffice, plusieurs itérations pour le goal seek de l'equity). Un aperçu instantané des KPI financiers relève donc de la phase 2 ou 3, à discuter.

## Résultats (géométrie de base : 2 halls × 20 rangées × 25 racks × 20 kW = 20 MW)

| Scénario | IT MWh | Refroid. MWh | Pertes MWh | PUE | Pointe MW | Eau m³ | tCO2 | Coût énergie M$ | $/MWh eff. | Cycles |
|---|---|---|---|---|---|---|---|---|---|---|
| New York JFK, charge 100 % | 175 340 | 52 114 | 10 881 | 1,359 | 27,9 | 261 163 | 65 046 | 35,75 | 150,0 | 0 |
| Idem, trace de charge Alibaba | 136 685 | 22 168 | 8 201 | 1,222 | 22,2 | 131 818 | 45 600 | 25,06 | 150,0 | 0 |
| Phoenix | 175 340 | 43 791 | 10 754 | 1,311 | 27,3 | 251 286 | 132 209 | 34,48 | 150,0 | 0 |
| Seattle + free cooling | 175 340 | 17 028 | 10 347 | 1,156 | 28,4 | 199 656 | 11 078 | 30,41 | 150,0 | 0 |
| Refroidissement liquide | 175 340 | 14 642 | 10 310 | 1,142 | 23,0 | 52 233 | 54 641 | 30,04 | 150,0 | 0 |
| COP 6 | 175 340 | 29 969 | 10 544 | 1,231 | 25,7 | 220 161 | 58 943 | 32,38 | 150,0 | 0 |
| Tarif HP/HC sans batterie | 175 340 | 52 114 | 10 881 | 1,359 | 27,9 | 261 163 | 65 046 | 25,13 | 105,4 | 0 |
| Tarif HP/HC + batterie 10 MW / 40 MWh | 175 340 | 52 114 | 10 881 | 1,359 | 30,0 | 261 163 | 65 158 | 24,82 | 104,0 | 66 |
| SustainDC brut (corrections désactivées) | 175 340 | 51 021 | 10 864 | 1,353 | 27,6 | 29 199 | 64 730 | 35,58 | 150,0 | 0 |

Tarif HP/HC : 220 $/MWh de 17 h à 21 h les jours ouvrés, 90 $/MWh sinon. Le CAPEX de base calculé (127,5 M$) est égal aux coûts durs du classeur (`Underwriting!K52`).

Points de lecture :

- **PUE de 1,36 contre 1,5 dans le classeur.** C'est attendu : SustainDC est un modèle simplifié. Le pont Excel travaillera en mode calibré (Q1) : base du classeur × rapport scénario / base simulée.
- **Batterie et pointe.** La batterie se recharge jusqu'à la capacité réseau (30 MW), ce qui fait monter la pointe à 30 MW sans la dépasser.
- **Racks de 10 kW avec la trace de charge.** Le plancher de ΔT joue sur 100 % des pas, ce qui est signalé dans `warnings`. Le modèle thermique SustainDC est hors domaine pour ces densités.

## Sorties (`TwinResults`)

- Énergies : IT, refroidissement (compresseur, ventilateur de tour, CRAC, pompes, liquide), pertes, site, batterie, réseau.
- Indicateurs : PUE annuel et mensuel, pointes site et réseau, heures de dépassement de la capacité réseau, eau (méthode jumeau et formule vendor), tCO2, coût d'énergie au pas de 15 min, $/MWh effectif, cycles batterie.
- Séries : mensuelles (IT, site, réseau, coût) et horaires sur 8 760 h (appel réseau, prix), pour la heatmap 24 × 365.
- Thermique : température d'entrée par classe de rangée, sortie moyenne et max, conformité ASHRAE, part de plancher ΔT, taille du chiller et facteur de charge (annuel et mensuel), température de dimensionnement.
- Flux moyens et de pointe (réseau, IT, refroidissement, pertes, batterie, compresseur) pour la scène 3D.
- CAPEX par ligne : montant, coût unitaire, cellule Excel, source.
- `provenance` de chaque donnée (vendor / api / cache / manual / workbook / default) et `warnings`.

Chaque simulation est journalisée dans `logs/scenarios.jsonl` (paramètres, durée, sorties principales) et mise en cache dans `.cache/twin/<hash>.json`.

## Données publiques

| Donnée | Source automatique | Remplacement manuel |
|---|---|---|
| Météo, sites US | EPW SustainDC (11 sites) | `data.weather_file` (EPW ou CSV `temp_c, rh_pct, pressure_pa`) |
| Météo, autres sites | Open-Meteo Archive (ERA5), repli NASA POWER, cache `data/weather/` | idem |
| Intensité carbone, US | série horaire SustainDC 2022 | `data.carbon_intensity_g_per_kwh` |
| Intensité carbone, autres pays | Our World in Data `carbon_intensity_elec`, dernière année. Panama : 221,15 g/kWh (2024), en cache dans `data/carbon/` | idem |
| Prix de l'électricité | classeur : 150 $/MWh (H153) | `price.*` |

**Panama (site du classeur) : bloqué pour l'instant.** La politique réseau de la session refuse `archive-api.open-meteo.com` et `power.larc.nasa.gov`. Le moteur lève `DataUnavailable` au lieu d'inventer une météo. Une fois l'un de ces domaines autorisé, la série est téléchargée et mise en cache au premier appel. On peut aussi fournir un EPW ou un CSV à la main.
