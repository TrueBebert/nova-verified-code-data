# Audit des données des exercices Nova — 23/10/2026

**Périmètre.** Les 541 exemples de `resultats/exercices_nova/donnees.jsonl` (essai de 600, terminé le 23/10). Calcul sur le PC avec `work/nova_122b/discoverer/audit_donnees_exercices.py`. Aucun code de modèle n'est exécuté. Détail dans `audit_donnees_20261023.json` ; échantillon relu dans `echantillon_donnees_20261023.txt`.

## Contrôles sur les 541 exemples

| Contrôle | Résultat |
|---|---|
| Forme (tours, une seule réponse apprise, en dernier) | 541/541 conformes |
| Traces de l'essai à blanc | 0 |
| Nom d'un modèle (GLM, Qwen, Claude, OpenAI…) dans le raisonnement ou la réponse | 0 |
| Caractères chinois ou japonais | 0 |
| Exercism ou polyglot cités | 0 |
| Compte, projet ou chemins du cluster (CLUSTER_USER, cluster_fs, ehpc, scratch) | 0 |
| Réponse vide / sans fichier reconnu | 0 / 0 |
| Description du bogue (écrite par l'auteur) visible dans l'invite de réparation | 0 |
| Raisonnement vide | 1 (`cpp/sales-report-engine#ecrire`) |
| Repères `=== … ===` dans la réponse | 2, faux positifs : texte du format de rapport que l'exercice Rust doit produire |
| Chemin `../envs/nova-polyglot/…` dans une sortie de tests montrée | 4 invites de relance Python (pas dans les réponses apprises) |

## Chiffres

- **Types :** écrire 250, réparer après les tests 49, réparer un bogue d'après un rapport 132, d'après la sortie des tests 110.
- **Langages :** cpp 89, go 88, java 89, javascript 84, python 110, rust 81.
- **Réparations :** 1 ligne modifiée en médiane (2 lignes de diff), 10 au 90e centile, 68 au plus. 140/242 rendent exactement la solution d'origine de GLM ; les autres passent les tests autrement.
- **Longueur du raisonnement, en médiane :**
  - environ 5 800 caractères pour écrire un programme (90e centile 34 600, maximum 175 000) ;
  - environ 180 à 250 caractères pour les réparations.
- **Réussite de GLM au premier essai :** « moyen » 165/199 (83 %), « difficile » 85/107 (79 %).
- **Formulations de demande :** les 4 sont employées de façon équilibrée (71 à 82 fois chacune).

## Relecture de 8 exemples (2 par type, langages variés)

- **Énoncés :** précis et complets (API exacte, règles, cas limites, exemples).
- **Solutions :** complètes et idiomatiques.
- **Raisonnement pour écrire :** réel. GLM refait les exemples de l'énoncé et vérifie les cas limites.
- **Bogues injectés :** réalistes (`>=` au lieu de `>`, arrondi par excès, mauvaise fonction d'échappement d'URL, décalage d'une colonne).
- **Rapports d'utilisateur :** crédibles. Ils donnent une entrée concrète et le mauvais résultat, sans la cause.
- **Corrections :** minimales, avec une courte explication de la cause avant le fichier complet.

Particularités notées :
- Quelques réponses Java mettent le chemin du fichier dans son propre bloc de code. La lecture des fichiers marche quand même.
- Une relance Python montre que GLM avait laissé une clôture de bloc de code dans son fichier. Sa première réponse n'est pas apprise.

## Limites et points à décider

1. **Les réparations ont un raisonnement très court**, environ 50 jetons en médiane, malgré l'effort « élevé » : GLM voit le bogue tout de suite. Ces exemples apprennent la correction rapide, pas le débogage en profondeur. Ils vont mieux avec les niveaux Rapide ou Moyen, sauf si l'on injecte des bogues plus subtils ou plusieurs bogues.
2. **Les exercices sont faciles pour GLM** (82 % du premier coup), et la mention « difficile » change peu. Il faut mesurer l'élève sur les mêmes exercices avant de passer à grande échelle.
3. **Coût :** 61 h GPU pour 541 exemples, soit environ 0,11 h par exemple, dont 74 % pour la création. Le passage à grande échelle demande une création moins chère (réparer les solutions de référence qui ratent leurs tests, 204/600 rejets).
4. **Nettoyage avant l'entraînement :**
   - écarter l'exemple sans raisonnement ;
   - normaliser les chemins `envs/nova-polyglot` des sorties de tests (facultatif).
5. **Limite de cette relecture :** elle est faite par moi, sur 8 exemples. Ce n'est pas une revue indépendante.
