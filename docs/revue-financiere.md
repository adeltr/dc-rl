# Revue financière du cas de base

> Deux revues successives. La première est décrite d'abord, la seconde dans la section « Deuxième revue ». Les tableaux de résultats à jour sont dans [phase5.md](phase5.md).

Cette note fait suite à une relecture externe des résultats du cockpit. Elle reprend chaque point, ce qui a été vérifié dans le classeur, puis la correction appliquée. Les choix retenus sont les options « les plus proches de la réalité ».

## Constats

| # | Point soulevé | Vérification | Verdict |
|---|---|---|---|
| 1 | OPEX énergie (39,4 M$) supérieure de 10 % à 20 MW × PUE 1,36 × 8 760 h × 150 $/MWh (35,7 M$). Indexation sur 4 ans ? | Le cas de base reprenait l'hypothèse du classeur : 109,5 $/kW/mois × 20 000 kW × **PUE 1,5** × 12 = 39,42 M$ (soit 150 $/MWh). L'écart vaut 1,5 / 1,359. L'indexation ne commence qu'en 2e année d'exploitation. | **Incohérence réelle** : le cockpit affichait le PUE simulé, le classeur utilisait 1,5. |
| 2 | TRI equity > TRI projet mais DSCR et LLCR N/A et aucune barre de dette | Un prêt de construction de 138,5 M$ (LTC 65 %, 9 %) court jusqu'à la vente (mois 72) faute de dette permanente. Ses intérêts (≈ 12,5 M$/an) pèsent sur l'exploitation. Le graphique et le DSCR ne lisaient que la dette permanente (ligne 170). | **Défaut d'affichage** : l'effet de levier est réel, le service de la dette était invisible. |
| 3 | CFADS ≈ −31 M$ en A3 | Le classeur facture 100 % de l'énergie à pleine puissance dès la mise en service (E153 = 100 % fixe), alors que l'EGR est à 12,1 M$ en A3 contre 68 M$ stabilisé. | **Confirmé** : l'énergie ne suivait pas l'occupation. |
| 4 | TRI de 10,9 % pour un rendement d'environ 8 % : valeur terminale ? | Horizon de 72 mois. La vente se fait au mois 72 sur un NOI capitalisé à 6,75 %, pour 265,6 M$ nets. Le TRI vient surtout de la cession. | **Confirmé**, la cession n'était pas visible. |
| 5 | Racks en rouge à 28–29 °C, « aucune alerte » | 28,5 °C est la **sortie** d'air. L'entrée est à 23,0–23,3 °C, dans la plage ASHRAE 18–27 °C, et l'alerte porte bien sur l'entrée. L'échelle s'arrêtait juste au-dessus de la sortie. | **Légende ambiguë**, pas d'erreur de calcul. |

## Corrections

### Calculs (changent les résultats)

- **Le classeur reçoit le PUE et le coût d'énergie simulés** : `market.calibration = "absolute"` par défaut. Le mode « valeurs du classeur, variations simulées » reste disponible.
- **Part fixe de l'énergie** (`market.utilities_fixed_share`, E153), 15 % à la première revue, puis déduite des pertes fixes simulées (voir plus bas) :
  - le reste suit la charge IT louée (ligne 114 du classeur) ;
  - les 15 % couvrent la base consommée sans locataire : éclairage, contrôle, pertes à vide des onduleurs et du froid ;
  - le paramètre est réglable dans les hypothèses marché.
- **Service de la dette total** (`out_debt_service_total`) :
  - dette permanente + intérêts du prêt de construction pendant les années d'exploitation ;
  - le DSCR est calculé dessus ;
  - le LLCR reste propre à la dette permanente.
- **Classeur d'origine** : avec le mode calé et une part fixe de 100 %, on retrouve exactement le classeur (test `test_original_market_gives_original_values`).

### Affichage et alertes

- « Coût effectif de l'énergie » devient **« Prix moyen de l'électricité »** (année simulée, avant indexation).
- « CAPEX total » devient **« Coût total du projet »** : coût avant financement plus portage. Chaque KPI a désormais une définition au survol, fournie par l'API.
- **Nouvelles alertes** :
  - CFADS négatif en exploitation ;
  - intérêts du prêt de construction non couverts (DSCR < 1).
- **Covenant** : l'alerte ne porte que sur les années de dette permanente.
- **Graphique CFADS** : il montre le service de la dette total et indique la cession (montant net, taux de sortie, mois).
- **Carte thermique** :
  - la légende devient « Sortie d'air des racks » et affiche l'entrée et la plage ASHRAE ;
  - l'échelle va de 18 à 45 °C (`thermal.hot_aisle_display_max_c`).

## Effet sur le cas de base (New York JFK, 20 MW)

| KPI | Avant | Après |
|---|---|---|
| PUE utilisé par le classeur | 1,5 | 1,359 |
| OPEX énergie, 12 premiers mois | 39,4 M$ | 11,0 M$ |
| CFADS A3 | −31,5 M$ | −3,1 M$ |
| Coût total du projet | 213,1 M$ (dont 34,7 M$ de déficit d'exploitation) | 177,3 M$ |
| Coût avant financement | 157,9 M$ | 157,9 M$ |
| DSCR min / moyen | N/A | −0,31x / 1,33x |
| TRI projet | 10,86 % | 19,86 % |
| TRI equity | 12,33 % | 28,10 % |

## Points qui restent à arbitrer

Ces points relèvent des hypothèses du classeur, que le jumeau ne modifie pas.

- **Loyer de 285 $/kW/mois, énergie comprise.** Le classeur ne refacture pas l'énergie (F134:F143 = 0 %). Ce loyer est cohérent avec un bail tout compris. Avec une refacturation de l'énergie, il faudrait le ramener vers 120 à 180 $/kW/mois. Garder les deux à la fois compterait l'énergie deux fois.
- **Taux de sortie de 6,75 % contre un rendement sur coût d'environ 12 %** : c'est cet écart qui porte la majeure partie du TRI. Il faut le valider avec des comparables de transactions.
- **Prix de l'électricité de 150 $/MWh** : c'est le prix implicite du classeur (projet au Panama). New York ne sert qu'à fournir la météo, en attendant celle du Panama.
- **PUE à charge partielle.** Le PUE simulé correspond à une pleine occupation. En montée en charge, il est plus élevé ; la part fixe ne le couvre qu'en partie.

## Deuxième revue : hypothèses qui suivent les autres paramètres

| # | Incohérence | Correction | Paramètre modifiable |
|---|---|---|---|
| 1 | Serveurs à 100 % toute l'année : énergie surestimée dans un bail tout compris | Utilisation CPU par défaut de 40 %, soit **74 % de la puissance contractuelle** (fourchette usuelle de 60 à 80 %), dans le domaine thermique de SustainDC. Indicateur « Charge IT moyenne » | `params.load.utilization` (halls) ; `load.utilization` dans `defaults.yaml` |
| 2 | PUE meilleur à faible charge, faute de consommations fixes | **Pertes fixes** de 5 % de la puissance IT de conception : onduleurs et transformateurs à vide, ventilation et pompage minimaux, éclairage. Le PUE suit une courbe en U (minimum vers 70 à 75 % de charge) et remonte à faible charge. La part fixe du classeur (E153) est **déduite** de ces pertes et suit donc la taille, la charge et le refroidissement | `params.electrical.fixed_losses_share` (poste électrique) ; `market.utilities_fixed_share` pour forcer une valeur |
| 3 | Le scénario de démonstration attribuait à la technique le gain d'un tarif moins cher | Tarif HP/HC de même prix moyen que le tarif plat dans le scénario 3. **Économie annuelle et temps de retour de la batterie**, avec une alerte si elle n'est pas rentable sur sa durée de vie (15 ans) | `battery.life_years` (`defaults.yaml`) ; coûts unitaires de la batterie |
| 4 | Scénario physiquement impossible mais « rentable » | Le raccordement est dimensionné sur la **pointe de conception** (serveurs à 100 %, simulation interne au même site). Il est renforcé automatiquement et le surcoût est ajouté au CAPEX réseau, avec une alerte de délai et d'accord du gestionnaire. Sans renforcement, une alerte critique signale le scénario « non faisable » | `params.grid_auto_upgrade` (poste électrique) |
| 5 | Taxe foncière fixe à 1,1 M$ quel que soit l'investissement | `tw_property_tax` (K159, recâblée) = taux × coûts durs ; par défaut, le taux implicite du classeur (0,86 % des coûts durs) | `market.property_tax_rate` |
| 6 | DSCR minimum tiré par l'année de montée en occupation | DSCR mesuré **à partir de la première année stabilisée** (convention prêteur) ; la montée en occupation est suivie par l'alerte « CFADS négatif » | — |
| — | TRI après impôt ? | Les définitions précisent « **avant impôt** » : le classeur ne modélise ni impôt ni amortissement | — |

Chacune de ces valeurs garde sa source dans `twin/config/defaults.yaml`. Le mode « valeurs du classeur » avec une part fixe de 100 % reproduit toujours exactement le classeur d'origine (`original_market`).

### Ce que montrent maintenant les résultats

- **Cas de base.** Il devient très rentable (TRI projet 32 %, equity 46 %). L'énergie réellement consommée (24,6 M$/an) est bien inférieure à l'hypothèse pleine puissance du classeur (39,4 M$), alors que le loyer de 285 $/kW/mois, énergie comprise, ne change pas. Ce niveau de TRI n'est crédible que si ce loyer et le taux de sortie de 6,75 % le sont : **ce sont les deux hypothèses à valider en priorité**.
- **Refroidissement liquide et batterie.** À prix moyen égal, ils ne relèvent pas le TRI : leur CAPEX (+22,7 M$) dépasse l'économie d'énergie. La batterie se rembourse en 14,4 ans.
- **Densité à 30 kW/rack.** Elle impose un renforcement du raccordement à 48 MW (+4,6 M$).
