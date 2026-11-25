# Travail en agent : préparation et marche à suivre — 01/11/2026

**But (DEC-019).** Mesurer GLM-5.3 contre l'élève quand ils corrigent de vrais bugs dans un terminal, avant de décider une génération de trajectoires à grande échelle. La mesure du 17/10 donnait les bons fichiers d'un coup : elle ne mesurait pas ce travail.

**État.** Prêt sur le PC, rien lancé sur le cluster, aucune heure GPU utilisée. Le vrai conteneur n'a encore jamais tourné : c'est ce que vérifie l'étape 1.

## Marche à suivre

| Étape | Lanceur | Coût | Ce qu'on regarde |
|---|---|---|---|
| 1. Essai sans modèle | `Essai_Agent_Discoverer.bat` | 0 h GPU | Conteneur isolé ; départ sur les 12 logiciels ; la correction officielle passée par le terminal résout le bug, l'absence de correction non, reprise sans perte |
| 2. Pilote (après accord) | `Pilote_Agent_Discoverer.bat` | 2,7 h GPU au plus | L'élève sur 8 bugs : moteur continu, durée d'un tour, place en mémoire |
| 3. Mesure (après accord sur le coût) | `Mesurer_Agent_Discoverer.bat` | 106 h GPU au plus | L'élève et GLM-5.3 sur les 99 bugs contrôlés, verdicts de l'outil officiel |

Le coût attendu de l'étape 3 était estimé à 20 à 40 h GPU le 17/10. Ce n'est pas une mesure : il sera recalé avec le pilote.

## Choix retenus

- **Une commande par réponse, dans un bloc de texte.** Le protocole est le même pour les deux modèles et ne dépend d'aucun format d'outil propre à un modèle. Limite : les chiffres publiés utilisent les outils natifs, donc les nôtres ne leur sont pas comparables.
- **Pas de serveur.** Les demandes s'ajoutent au moteur vLLM déjà employé, pendant que les autres tournent. Repli automatique sur l'appel par lots s'il manque l'interface.
- **Conteneur :** un par bug, sans réseau, sans le dossier du projet ni le dossier personnel. La sonde le vérifie avant chaque chargement du modèle : si l'isolation manque, le modèle n'est pas chargé.
- **Chaque tour est écrit**, avec l'état des fichiers. Un créneau arrêté reprend au suivant, dans un conteneur neuf.
- **Verdict :** même outil officiel et même conteneur neuf que la mesure du 17/10.
- **SWE-bench reste réservé à la mesure.** Les trajectoires portent la mention « mesure seulement ». Une génération pour l'entraînement devra utiliser d'autres tâches.

## Contrôles faits sur le PC

- `test_agent_code.py` : logique complète avec faux moteur et faux terminal, puis la vraie boucle du terminal lancée par bash, avec des commandes écrites par nous. Le code des modèles ne tourne jamais sur le PC.
- `test_discoverer.py` : lanceurs avec faux SLURM. Pilote et mesure sont refusés tant que l'essai n'a pas réussi ; la mesure soumet 6 tâches, Discoverer en accepte 8.
- **Défaut trouvé et corrigé :** après une reprise, un changement de même taille pouvait disparaître de la correction sauvegardée. Sur 8 reprises, l'ancienne version l'a perdu 3 puis 4 fois ; la version retenue, jamais (ERR-146).

## Ce qui n'est pas vérifié

- Apptainer sans réseau et sans le dossier du projet sur les nœuds de Discoverer : étape 1.
- L'ajout de demandes à vLLM avec un vrai modèle : testé avec un faux seulement ; étape 2.
- La durée réelle et le coût : étape 2.
- Le raisonnement n'est pas renvoyé au modèle d'un tour à l'autre : choix simple et identique pour les deux, pas forcément leur meilleur réglage.

## Point de calendrier

- Il reste 65 jours d'accès et 4 421 h GPU. Au rythme de la campagne 2 (73 h GPU par jour), on pourrait consommer environ 4 700 h d'ici le 05/01, à condition que des tâches tournent sans interruption à partir de maintenant.
- La génération générale du professeur n'a pas commencé, alors que le brouillon de plan la prévoyait du 15/10 au 30/11, avec l'entraînement final en décembre.
- La mesure en agent pèse peu (106 h au plus). Une génération de trajectoires à grande échelle (300 à 800 h estimées le 17/10) se fera au détriment d'autre chose : ce sera à décider après la mesure.

## Mise à jour du 03/11

- **Essai du 01/11 réussi (tâche 206813, 0 h GPU) :**
  - conteneur sans réseau (le témoin avec réseau se connecte, ce qui prouve que le contrôle mesure quelque chose), sans le dossier du projet ni les clés ;
  - départ correct sur les 12 logiciels ;
  - correction officielle résolue, absence de correction non résolue, reprise sans perte.
- **Deux défauts vus dans les chiffres, corrigés (ERR-147) :**
  - 64 Mo d'écriture par conteneur, dont 24 à 83 % déjà pris au départ par ma sauvegarde ;
  - 257 s de départ pour django.

  La sauvegarde n'écrit plus rien dans le dépôt ; tests 81/81.
- **Nouvel essai à lancer (0 h GPU).** Il mesure aussi la place pendant les tests de chaque logiciel, et sonde deux façons de mettre `/tmp` (et le calque) sur disque.
- **Verrou :** le pilote et la mesure refusent de partir tant qu'un essai n'a pas réussi avec la version actuelle du programme.
