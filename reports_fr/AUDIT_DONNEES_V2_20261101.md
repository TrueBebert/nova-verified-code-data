# Audit des données de la campagne 2 des exercices Nova — 01/11/2026

**Périmètre.** Les 2 909 exemples de `resultats/exercices_nova_v2/donnees.jsonl`, rapatriés le 01/11. Calcul sur le PC, sans exécuter de code de modèle, avec `work/nova_122b/discoverer/audit_campagne2.py`, `audit_campagne2_coherence.py` et `audit_campagne2_exclusions.py`. Détail dans `audit_donnees_v2_20261101.json`, `audit_coherence_v2_20261101.json` et `exclusions_v2_20261101.json`.

**Verdict.** Données utilisables après exclusion : **2 533 exemples sur 2 909**, soit 0,137 h GPU par exemple. Rien n'est effacé : `exclusions_v2_20261101.json` donne la raison de chaque exclusion, à appliquer quand on construira les données d'entraînement.

## Défaut principal : la correction des références

Quand une solution ratait ses tests, la consigne disait que l'énoncé et les tests étaient définitifs. Si les tests étaient faux, GLM-5.3 devait donc tordre la solution. Exemple relu : un cas spécial pour le nom `"<seat>-pick"`, seulement pour passer un test écrit par erreur (`go/card-draft-index`).

Preuve indépendante : au premier essai, GLM ne voit pas les tests.

| Exercices gardés | GLM réussit au premier essai |
|---|---|
| Non corrigés | 1 221/1 477 (83 %) |
| Corrigés, sans contradiction évoquée pendant la correction | 71/97 (73 %) |
| Corrigés, avec contradiction évoquée | 31/271 (11 %) |

Conséquences :
- **Environ 270 des 1 845 exercices gardés ont probablement un énoncé et des tests en désaccord.**
- **Coût de la correction :** 46,4 h GPU, pour 430 exercices sauvés sur 874. Il en reste 162 exemples après exclusion.
- **Lecture du premier essai :** la baisse de 82 % à 72 % ne vient pas d'exercices plus durs. Sur les exercices non corrigés, GLM fait 83 %, contre 82 % dans l'essai de 600.
- **Mention « difficile » :** elle change peu pour GLM (moyen 680/807, soit 84 % ; difficile 541/670, soit 81 %).

## Exclusions (raisons cumulables, 376 exemples au total)

| Raison | Exemples |
|---|---|
| Exercice corrigé que GLM ne réussit pas du premier coup (tous ses exemples) | 196 |
| Le raisonnement ou la réponse parle du test lui-même (« grader », « harness », « injected bug », « puzzle »…) | 90 |
| Bogue double dont un des deux bogues reste dans le code réparé, invisible pour les tests | 66 |
| Au deuxième essai, GLM évoque une contradiction entre énoncé et tests (exercice non corrigé) | 55 |
| Premier essai raté à cause de l'extraction des fichiers (voir plus bas) | 24 |
| Raisonnement vide | 7 |
| Caractères chinois | 1 |
| Exercism cité | 1 |

**Il reste :** écrire 1 286, réparer après les tests 153, réparer un bogue 1 094 (tests 534, rapport 560). Par langage : cpp 399, go 439, java 442, javascript 434, python 442, rust 377. Moyen 1 333, difficile 1 200. 1 485 exercices différents.

## Contrôles sur les 2 909 exemples

| Contrôle | Résultat |
|---|---|
| Forme, identifiants uniques, exercices tous gardés par le filtre | conformes |
| Encodage abîmé | 0 |
| Traces de l'essai à blanc | 0 |
| Nom de modèle dans le raisonnement ou la réponse | 0 |
| Chemin ou compte du cluster dans une réponse | 0 |
| Chemin du cluster dans une sortie de tests montrée à GLM | 19 invites, à normaliser à la construction |
| Réponse vide, sans fichier reconnu ou coupée | 0 |
| Description du bogue par son auteur visible dans l'invite | 0 |
| Énoncés identiques (dans la campagne ou avec l'essai) | 0 |
| Thèmes | les 200 sont employés, 9 exercices gardés par thème en médiane |

## Bogues

| | Subtils | Doubles |
|---|---|---|
| Valides | 532/850 | 762/821 |
| Rejetés car les tests ne voient pas le bogue | 285 | 41 |
| Réparés | 510 | 728 |
| Part des tests ratés, en médiane (Go non lu) | 7 % | 12 à 13 % |
| Raisonnement de réparation, en médiane | 205 caractères | 439 caractères |

- **Objectif atteint en partie seulement.** Les bogues sont discrets pour les tests, mais GLM les voit vite : le raisonnement des bogues subtils reste celui de l'essai de 600 (180 à 250 caractères), celui des doubles est environ deux fois plus long. Ces exemples servent surtout aux modes Rapide et Moyen.
- **Les tests ne prouvent pas tout.** Ils ratent un bogue subtil sur trois (285/850). « Vérifié par les tests » n'est donc pas une preuve que le programme est juste.

## Défaut d'extraction des fichiers

Si GLM écrit `` ```python ``, puis le chemin, puis de nouveau `` ```python ``, le fichier extrait garde ces lignes et l'essai échoue. Cela fait 39 premiers essais ratés à tort sur 1 845. Le deuxième essai parle alors d'un fichier « pollué » ; ces exemples sont exclus.

Effet sur la mesure de l'élève du 25/10 : 11 échecs de GLM et 1 échec de l'élève viennent de ce défaut. L'écart réel entre les deux est donc un peu plus grand qu'annoncé ; la conclusion ne change pas.

## Relecture

Relus : 18 exemples tirés au hasard, 6 références corrigées au hasard, 10 références suspectes, et les cas de bogue restant.
- **Énoncés, solutions et rapports d'utilisateur :** précis et crédibles.
- **Réparations :** claires, avec la cause, puis le fichier complet.
- **Détecteur de bogue restant :** une première version se trompait presque toujours (1 vrai cas sur 14) et a été abandonnée. La version retenue est juste sur environ 15 cas relus sur 16. Elle en manque sans doute d'autres.

## Limites

- Relecture faite par moi : ce n'est pas une revue indépendante.
- Le mot-clé de contradiction fait aussi des fausses alertes (par exemple « conflict » dans un exercice de planning). Il n'est utilisé que sur les corrections et les deuxièmes essais.
- Les exercices corrigés et réussis du premier coup sont gardés (162 exemples restants), mais certains peuvent garder un test douteux.
- Un exercice non corrigé peut aussi avoir un énoncé et des tests en désaccord. Seuls ceux que GLM signale au deuxième essai sont exclus.

## Application de la liste (01/11, accord de l'utilisateur : « oui applique la liste »)

- **Fichier :** `donnees_v2_propres_20261101.jsonl`, 2 533 exemples, 71,5 Mo, sha256 `adc01daa32e967ae43eeb82959d7258f01702a91575e8b39b4ae1a3931a86de4` (manifeste : `donnees_v2_propres_20261101.manifeste.json`). Écrit par `work/nova_122b/discoverer/appliquer_exclusions_v2.py`, qui refuse d'écraser un résultat différent.
- **Source inchangée :** `resultats/exercices_nova_v2/donnees.jsonl` (2 909 exemples, sha256 `6820b295…`), seulement lue. La liste d'exclusion n'a pas changé non plus.
- **Seule retouche :** 6 chemins du cluster remplacés dans les sorties de tests de 2 exemples gardés (`go/price-history-engine`, `python/test-sharding-migrator`). Les 17 autres invites concernées par l'audit étaient dans des exemples exclus. Les réponses apprises ne changent pas.
- **Contrôles :** 2 533 + 376 = 2 909, sans recoupement ; comptes par type, langage et difficulté conformes ; les 2 531 autres lignes sont identiques à la source, octet pour octet ; aucun compte ni chemin du cluster ; empreinte recoupée avec un second outil ; recomptage à part, sans le code qui a écrit le fichier.
- **Essai de 600 :** mêmes règles appliquées le 01/11 par `trier_essai600.py` : 514 exemples gardés sur 541 (`donnees_v1_propres_20261101.jsonl`, sha256 `0ee4cbc6…`, liste `exclusions_v1_20261101.json`). Total des deux fichiers propres : 3 047 exemples, aucun en commun.
- **Pas encore fait :** le format d'`assembler.py` (champs `categorie`, `source` et `verifie`) et le passage du raisonnement au format d'entraînement.

## À faire avant une prochaine campagne (pas de GPU à ce stade)

1. **Correction des références :** autoriser GLM à répondre que l'énoncé et les tests se contredisent, et rejeter alors l'exercice. Ne garder un exercice corrigé que si GLM le réussit au premier essai.
2. **Extraction :** accepter la double clôture. Le code est partagé avec les mesures déjà faites, donc la correction doit être faite à part et les anciens scores rester tels quels.
3. **Réparations :** pour obtenir un vrai raisonnement de débogage, prévoir autre chose que des bogues injectés (par exemple les échecs réels de l'élève).
