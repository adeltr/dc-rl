# Phase 4 — Interface

## Lancer

```bash
make dev                              # API sur :8000 + interface sur http://localhost:5173 (proxy /api)
TWIN_BASE_SITE=us_ny_jfk make dev     # tant que la météo du Panama n'est pas accessible
```

Stack : React 19 + Vite 7 + TypeScript strict, React Three Fiber 9 + drei, Zustand, TanStack Query, Tailwind 4 + composants façon shadcn/ui (Radix), ECharts 6. Versions exactes dans `web/package.json` et `package-lock.json`.

## Disposition

| Zone | Contenu |
|---|---|
| En-tête | annuler / rétablir / revenir au cas de base ; scénarios sauvegardés (base verrouillée 🔒, renommer, supprimer, case « comparer ») ; sauvegarder ; copier le lien ; export Excel du résultat confirmé |
| Centre (≈ 60 %) | étape en cours (SSE) ; scène 3D du campus ; inspecteur de l'équipement sélectionné ; barre d'équipements accessible au clavier ; bascule carte thermique ; légende |
| Droite | cockpit financier (10 KPI) ; alertes ; panneau « Hypothèses marché » repliable |
| Bas | tiroir de graphiques repliable : CFADS et DSCR, heatmap 24 h × 365 j, PUE mensuel, tornado, grille prix × utilisation, comparaison |

## Scène 3D (`web/src/components/scene`)

- **Généré par les paramètres** : halls × rangées × racks (racks instanciés, jusqu'à 36 000). Ajouter une rangée fait apparaître une rangée ; changer le nombre de halls ajoute un bâtiment.
- **Équipements** : poste électrique (rouge si la pointe dépasse la capacité), centrale de refroidissement (chillers dont la vitesse de ventilateur suit le facteur de charge, tours), parc batterie (un conteneur par tranche d'énergie ; emplacement vide cliquable si pas de batterie).
- **Encodage** :
  - couleur des racks selon les kW/rack (échelle bornée par le catalogue de l'API) ;
  - flux d'énergie réseau → poste → halls / froid / batterie, avec une épaisseur proportionnelle aux MW moyens et des tirets animés dans le sens du flux ;
  - **carte thermique** : racks colorés par leur température de sortie, allées froides et chaudes au sol. L'échelle va du bas de la plage ASHRAE à la sortie la plus chaude.
- **Interaction** : clic sur un équipement ou bouton de la barre → inspecteur. Clic sur une alerte → la caméra se déplace vers l'équipement en cause et ouvre son inspecteur.

## Édition des paramètres

L'inspecteur et le panneau marché sont générés depuis `GET /meta`. Chaque paramètre a :

- un curseur, une saisie numérique (virgule décimale acceptée) et son unité ;
- des bornes réalistes, une aide le cas échéant ;
- un repère « modifié » et un bouton de retour à la valeur de base.

Équipements et paramètres portés :

| Équipement | Paramètres |
|---|---|
| Poste électrique | capacité de raccordement, mode de tarif, prix |
| Halls | halls, rangées, racks par rangée, densité, profil de charge |
| Centrale | type de refroidissement, COP, consigne, part liquide |
| Batterie | MW, MWh, pilotage prix ou carbone, rendement |
| Site | site (liste déroulante), intensité carbone manuelle |

**Aucune valeur métier n'est écrite dans le front** : libellés, unités, bornes, options, définitions des KPI, sens favorable, paramètres pilotes et valeurs effectives viennent de l'API.

## Boucle de retour

1. Chaque modification met à jour le brouillon (Zustand). L'historique fusionne les modifications rapides d'un même paramètre (Ctrl+Z / Ctrl+Maj+Z).
2. **400 ms** après la dernière modification :
   - `POST /preview` : valeurs **en ambre**, badge « provisoire » ;
   - `POST /simulate` avec un identifiant de client : le serveur annule les demandes en attente.
3. Les étapes SSE s'affichent : simulation physique → recalcul Excel → terminé. Les valeurs confirmées remplacent l'aperçu. Une réponse qui ne correspond plus au brouillon courant est ignorée ; l'interface n'est jamais bloquée.
4. Chaque KPI affiche la base, le scénario et l'écart (vert si favorable, rouge sinon, « = » si inchangé). Le survol ou le focus clavier liste les paramètres pilotes. DSCR et LLCR affichent « N/A » avec une explication tant que la dette permanente est désactivée.
5. **URL partageable** : seules les différences avec le cas de base sont encodées (`?s=…`), par exemple `?s=W1sicGFyYW1zLmdlb21ldHJ5Lmt3X3Blcl9yYWNrIiwzMF1d` pour 30 kW/rack.

## Graphiques (`web/src/components/charts`)

Règles de visualisation appliquées :

- palette catégorielle sombre bleu / orange / aqua dans un ordre fixe, validée sur la surface des panneaux (contrôle daltonisme ΔE ≥ 9,4 ; contraste ≥ 3:1) ;
- rampe séquentielle bleue pour la heatmap, divergente bleu ↔ rouge à milieu gris pour la grille 2D ;
- tooltips sur tous les graphiques, vue « Tableau » pour l'accessibilité ;
- base de comparaison en pointillé gris.

| Onglet | Contenu |
|---|---|
| CFADS et DSCR | CFADS et service de la dette par année (barres), CFADS de base en pointillé. **DSCR dans un second graphique aligné**, avec la ligne du covenant : pas de double axe |
| Heatmap 24 h × 365 j | consommation réseau (MW) ou prix ($/MWh) heure par heure |
| PUE mensuel | scénario et base |
| Tornado | ±X % réglable, KPI au choix, méthode rapide (surrogate, ≈ 1 s) ou exacte (classeur) |
| Grille prix × utilisation | KPI au choix, valeurs dans les cases |
| Comparaison | jusqu'à 3 scénarios cochés : tableau des KPI et CFADS superposés |

## Vérifications faites (Chromium headless + API réelle, LibreOffice)

- `tsc -b` strict et `vite build` sans erreur.
- **Parcours complet** :
  - densité 30 kW et raccordement 50 MW, sauvegarde ;
  - retour à la base ; refroidissement liquide + batterie 10 MW / 40 MWh + refinancement, sauvegarde ;
  - comparaison des 3 scénarios ; tornado par surrogate ; grille ; CFADS / DSCR avec covenant.
- **Prix +10 % (au clavier, flèches du curseur)** : OPEX énergie année 1 +10,0 %, coût effectif +10,0 %, TRI equity −16,3 pt, TRI projet −7,0 pt.
- **Clic sur l'alerte « Appel réseau 46,0 MW… »** : caméra sur le poste électrique, inspecteur ouvert.
- **Tabulation** : historique → scénarios → sauvegarde / lien / Excel → équipements → carte thermique → 10 KPI (libellé ARIA complet : valeur, base, écart) → hypothèses marché → graphiques. Curseurs pilotables aux flèches. Raccourcis Ctrl+Z / Ctrl+Maj+Z.

## Limites connues

- **Saisie batterie en deux temps.** Saisir la puissance avant l'énergie produit un état refusé par l'API (« puissance et énergie toutes deux nulles ou toutes deux > 0 »). Le message s'affiche dans l'indicateur d'étape et disparaît dès que l'énergie est saisie.
- **Thermique quasi uniforme.** Le modèle SustainDC ne distingue que deux classes de rangées (bord / intérieur), et la carte thermique ne peut pas être plus fine que ce modèle.
- **Tarif par plages horaires.** Il est accepté par l'API, mais l'édition des plages n'a pas encore de formulaire dédié dans l'inspecteur : il se règle par l'API ou par une URL partagée.
