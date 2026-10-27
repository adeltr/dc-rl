# Phase 3 — API (FastAPI)

## Lancer

```bash
make api                              # http://127.0.0.1:8000 — documentation interactive : /docs
TWIN_BASE_SITE=us_ny_jfk make api     # site de base surchargé (météo du Panama encore bloquée, voir plus bas)
```

Au démarrage, en tâche de fond :

1. cas de base : physique, puis recalcul du classeur avec ses valeurs d'origine ;
2. précalcul du surrogate financier (17 recalculs du classeur, ≈ 30 s, priorité basse).

Une simulation demandée pendant ce précalcul n'attend au plus qu'un recalcul (≈ 1,5 s).

| Variable | Rôle | Défaut |
|---|---|---|
| `TWIN_BASE_SITE` | site du cas de base | `base_scenario.site_id` de `defaults.yaml` (Panama) |
| `TWIN_EXCEL_ENGINE` | `auto` / `xlwings` / `libreoffice` | `auto` |
| `TWIN_STORE_DIR` | résultats et scénarios sauvegardés | `store/` |
| `TWIN_SCENARIO_LOG` | journal JSONL de chaque simulation | `logs/scenarios.jsonl` |
| `TWIN_CORS` | origines autorisées | `http://localhost:5173` (Vite) |

## Routes

| Route | Rôle |
|---|---|
| `GET /health` | état : cas de base prêt, moteur, surrogate prêt, erreurs |
| `GET /meta` | **tout ce dont le front a besoin** : catalogue des paramètres éditables (libellé, unité, bornes réalistes, pas, équipement porteur, options), définitions des KPI (sens favorable, paramètres pilotes), sites, traces, valeurs par défaut avec leur source |
| `GET /scenario/base` | scénario de base, valeurs effectives (les `null` résolus), résultat de base |
| `POST /simulate` | `{scenario, client_id?}` → `{job_id, result_id}` (202). Les demandes en attente d'un même `client_id` sont annulées (debounce côté serveur) |
| `GET /simulate/{job_id}` | état de la tâche |
| `GET /simulate/{job_id}/events` | **SSE** : `en attente` → `simulation physique` → `recalcul Excel` → `terminé` (ou `erreur` / `annulé`). Reprise par `Last-Event-ID` |
| `POST /preview` | **aperçu immédiat** (20–100 ms) : physique exacte + finances estimées par le surrogate, `status: "provisional"` |
| `GET /results/{id}` | résultat complet : jumeau, classeur (entrées écrites, sorties, séries annuelles, flux mensuels), KPI (base / scénario / écart / favorable / paramètres pilotes), alertes |
| `GET /scenarios`, `POST /scenarios`, `PATCH /scenarios/{id}`, `DELETE /scenarios/{id}` | scénarios sauvegardés ; le cas de base est **verrouillé** (403) |
| `GET /compare?ids=a,b,c` | KPI côte à côte + séries (CFADS, service de la dette, DSCR, NOI, flux levered, PUE mensuel, énergie mensuelle) pour 1 à 5 résultats |
| `POST /sensitivity` | tornado ±X % sur N paramètres + grille 2D prix de l'électricité × taux d'utilisation ; `method: "exact"` (classeur à chaque point) ou `"surrogate"` (≈ 1 s) ; renvoie une tâche, même SSE |
| `GET /export/{id}.xlsx` | classeur recalculé du scénario (entrées et equity résolue réécrites ; onglet `Version` conservé) |
| `PUT /data/weather/{nom}.epw` | météo fournie à la main (EPW ou CSV) → chemin à mettre dans `params.data.weather_file` |

Exemple :

```bash
curl -s -X POST localhost:8000/simulate -H 'content-type: application/json' \
  -d '{"scenario":{"params":{"geometry":{"kw_per_rack":30}}},"client_id":"ui"}'
curl -N localhost:8000/simulate/<job_id>/events
curl -s localhost:8000/results/<result_id> | jq '.kpis[] | {label, base, value, delta, favorable}'
```

## KPI et alertes (`api/kpis.py`)

Cockpit : TRI equity, TRI projet, VAN, DSCR min et moyen, LLCR, CAPEX total, OPEX énergie année 1, PUE, coût effectif de l'énergie. Chaque KPI porte :

- sa valeur de base, sa valeur de scénario, l'écart absolu et relatif ;
- `favorable` (vert / rouge, selon `better`) ;
- la liste des paramètres du jumeau qui le pilotent, pour le survol.

Alertes, avec l'équipement visé pour la caméra :

| Alerte | Gravité | Cible |
|---|---|---|
| DSCR min sous le covenant (1,20x par défaut, réglable) | critique | `campus` |
| Appel réseau > capacité de raccordement | critique | `substation` |
| Entrée des racks hors plage ASHRAE recommandée 18–27 °C | avertissement | `hall` |
| Avertissements du jumeau (plancher ΔT, densité air, batterie inactive…) et données approximées | information | équipement concerné |

Avec les bornes de consigne de SustainDC (15–21,6 °C), l'entrée des racks reste entre 18,8 et 26,9 °C. L'alerte ASHRAE ne se déclenche donc pas avec le modèle actuel ; elle est testée sur un résultat modifié.

## Aperçu provisoire : le surrogate financier (`api/surrogate.py`)

La physique est exacte en moins de 0,4 s. Le maillon lent est le classeur : 0,7 s sans solveur, 1,5 à 2 s avec la résolution de l'equity. Pour l'aperçu, le classeur est linéarisé autour du cas de base, par 17 groupes d'entrées qui varient ensemble dans le pont :

- dérivée en log pour les grandeurs multiplicatives (kW, PUE, tarif, CAPEX) ;
- dérivée par unité d'entrée pour les indexations, le taux d'actualisation, la batterie et la dette permanente.

Les TRI, VAN, multiples et profits ne sont pas linéarisés : ils sont recalculés sur les **flux mensuels estimés**, avec les mêmes fenêtres que les XIRR du classeur (contrôle : sur les flux de base, écart ≤ 1e-13 avec le classeur).

Précision mesurée (aperçu / exact) :

| Scénario | TRI equity | TRI projet | CAPEX total | OPEX énergie an 1 |
|---|---|---|---|---|
| Prix +10 % | −3,5 % / −4,0 % | 4,0 % / 3,8 % | 219,5 / 219,7 M$ | 43,3 / 43,4 M$ |
| Loyer 300 $/kW/mois | 20,42 % / 20,42 % | 15,37 % / 15,37 % | 211,2 / 211,2 M$ | identique |
| Dette permanente | 13,54 % / 13,54 % | identique | identique | identique |
| Refroidissement liquide | 27,8 % / 26,3 % | 19,9 % / 18,9 % | 208,7 / 211,4 M$ | 32,4 / 33,1 M$ |
| 30 kW/rack | 9,8 % / 7,7 % | 9,6 % / 8,6 % | 290,4 / 306,3 M$ | 58,4 / 63,0 M$ |
| HP/HC + batterie 10 MW / 40 MWh | 39,0 % / 35,0 % | 27,5 % / 24,7 % | 204,5 / 210,9 M$ | 24,7 / 27,4 M$ |

L'aperçu est fiable pour les changements modérés. Les grands écarts (densité +50 %, énergie −35 %) montrent la non-linéarité du classeur, en particulier la réserve de déficit d'exploitation qui sature à zéro. C'est pourquoi l'aperçu est marqué « provisoire » et que la valeur confirmée arrive 1,5 à 2 s plus tard.

## Sensibilités

- **Tornado** : ±X % (10 % par défaut) sur les paramètres marqués `sensitivity` du catalogue, ou sur une liste donnée. Valeurs entières arrondies, bornes du catalogue respectées. Les 15 KPI sont fournis pour chaque extrémité, et le tornado est trié par amplitude du TRI equity.
- **Grille** : prix plat de l'électricité (défaut : base × 0,8 à 1,2) × utilisation constante (défaut : 50 à 100 %), les 15 KPI par case.
- Coût : `exact` ≈ 1,5 s par point (48 points par défaut ≈ 70 s) ; `surrogate` ≈ 1 s au total.

Exemple de tornado sur le TRI equity (base 12,3 %, ±10 %, surrogate) : revenu −25 % / +26 % ; prix de l'électricité +23 % / −3 % ; consigne de soufflage +16 % / +7 % ; utilisation +20 % / = (bornée à 100 %) ; COP +10 % / +14 % ; montée en occupation +12 % / +13 %.

## Robustesse

- **Une seule file d'exécution pour le classeur**, à priorités : utilisateur > sensibilités > précalcul du surrogate.
- **Copie de travail privée** du classeur pour chaque moteur : pas de conflit de verrou LibreOffice entre processus.
- **Erreurs explicites, résultat partiel conservé.** Exemple : sans météo pour le Panama, la tâche échoue avec `Météo indisponible… autoriser archive-api.open-meteo.com… ou fournir un fichier EPW/CSV`, et le résultat garde ce qui a pu être calculé.
- **Capacité IT jamais saisie** : `n_racks` et `it_capacity_mw` renvoyés par l'API sont ignorés s'ils reviennent en entrée (aller-retour JSON), et toujours recalculés depuis la géométrie.
- **Journal** `logs/scenarios.jsonl` : une ligne `physics` et une ligne `workbook` par simulation (paramètres, marché, moteur, durée, itérations du solveur, sorties).

## Tests

`tests/test_api.py` (11 tests, ≈ 60 s avec LibreOffice et le précalcul du surrogate) :

- ordre des étapes SSE ;
- prix +10 % : OPEX énergie +10 % à 1e-9 et TRI projet / equity en baisse, de bout en bout par l'API ;
- aller-retour JSON, CRUD des scénarios et verrou du cas de base ;
- comparaison de 3 résultats, export relu avec openpyxl, debounce ;
- validation, absence de météo, météo manuelle ;
- alertes (réseau, covenant, ASHRAE) ;
- aperçu < 1 s et proche de l'exact pour un petit écart ;
- tornado trié ; point exact du tornado et de la grille = simulation directe.
