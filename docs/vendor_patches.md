# Écarts au code SustainDC (vendor/sustaindc)

Le code de `vendor/sustaindc` (HewlettPackard/dc-rl, commit `a92b475`) **n'est jamais modifié**. Le jumeau :

1. importe ses modules tels quels (`twin/vendor.py`) : managers de données, `dc_config.json` ;
2. réimplémente ses équations à l'identique dans `twin/physics.py`, en version vectorisée. La parité est vérifiée par `tests/test_vendor_parity.py` contre l'environnement Gymnasium `dc_gymenv` d'origine : écart relatif ≤ 1e-9 sur la puissance IT, le compresseur, le ventilateur de tour, les pompes et l'eau, pour les consignes 15, 18 et 21,6 °C ;
3. applique des corrections **dans le wrapper** (`twin/engine.py`). Chacune est désactivable via `params.patches`, avec ses valeurs par défaut dans `twin/config/defaults.yaml`.

Avec tous les `patches` à `false`, le moteur donne le calcul SustainDC brut.

## Corrections (désactivables)

| `patches.*` | Constat dans le vendor | Correction | Statut |
|---|---|---|---|
| `cop_correction` | `calculate_chiller_power` code `rated_cop = 3.0` en dur ; `CHILLER_COP_BASE` du JSON n'est jamais lu | compresseur × 3,0 / COP saisi | correction |
| `include_auxiliaries` | `dc_HVAC_total_power_kW` = ventilateur de tour + compresseur ; le ventilateur CRAC et les pompes CW/CT sont calculés mais non sommés | ajoutés au refroidissement (valeurs vendor × nombre de halls) | correction |
| `water_heat_based` | l'eau de tour ne dépend que des températures, pas de la charge (43 740 m³/an quelle que soit la taille) | eau = chaleur rejetée / chaleur latente (2 450 kJ/kg) × (1 + 1/(cycles − 1) + entraînement), avec cycles = 5 et entraînement = 1 % (valeurs vendor). La formule vendor reste exposée (`water_m3_vendor_formula`) | **approximation** |
| `sizing_from_weather_p996` | `make_dc_pyeplus_env` dimensionne le chiller avec 30 °C (NY), 50 °C (AZ), 20 °C (WA), sinon 50 °C | température sèche au percentile 99,6 % de l'année météo du site | correction |
| `rack_delta_floor` | le modèle empirique de sortie de rack est calé sur 200 serveurs par rack (≈ 68 kW). Sous ≈ 30 kW/rack à faible charge, il donne un ΔT sortie − entrée < 2 °C, voire négatif, et `compute_datacenter_IT_load_outlet_temp` lève une exception | plancher ΔT = 2 °C (le seuil du vendor). La part des pas concernés est publiée (`thermal.rack_delta_floor_share`) avec un avertissement | **approximation** |

## Hors vendor (ajouts du jumeau)

| Élément | Traitement | Statut |
|---|---|---|
| Simulation annuelle déterministe | `SustainDC.reset()` tire un jour de départ au hasard, ajoute un bruit météo et un décalage de 0 à 13 jours. Le jumeau lit les séries brutes `original_*` des managers sur 365 jours, avec une consigne fixe | méthode |
| Géométrie | rangées de bord (approches 5,3 / −3,7 °C) et intérieures (5,0 / −2,5 °C) de `dc_config.json`, deux rangées de bord par hall. Un serveur type (130 W / 10 W, valeur majoritaire du vendor), en nombre continu par rack | méthode |
| kW par rack | puissance IT de conception à 100 % de charge et 18 °C de consigne | convention validée (Q2) |
| Batterie | `Battery2` n'est pas utilisée : sa décharge retire `énergie × eff_d` au lieu de `énergie / eff_d`, ce qui crée de l'énergie dès que `eff_d < 1`. Modèle propre : rendement aller-retour, bornes de SoC, puissance limitée, règle journalière prix bas / prix haut (ou carbone), écrêtage au-delà de la capacité réseau | remplacement |
| Free cooling (`air_free_cooling`) | compresseur × (1 − part libre) ; part libre = (consigne − (T humide + 4 °C)) / 3 °C, bornée à [0, 1] | **approximation** |
| Refroidissement liquide (`liquid`) | 80 % de la chaleur IT par boucle liquide (pompes, CDU, dry-cooler = 3 % de l'IT, sans eau) ; le reste par le modèle air SustainDC | **approximation** |
| Pertes électriques | UPS 96 % sur l'IT, transformateur 98,5 % sur l'IT après UPS + refroidissement | hypothèse à confirmer |
| Prix, coût, CO2 | coût = Σ prix horaire × énergie réseau au pas de 15 min ; CO2 = Σ intensité × énergie réseau | calcul |
| Données hors SustainDC | météo : Open-Meteo Archive, repli NASA POWER. Intensité carbone hors US : Our World in Data (facteur annuel). Tout est en cache dans `data/`, remplaçable à la main (`params.data`), et rien n'est inventé si la source est injoignable | sources publiques |
