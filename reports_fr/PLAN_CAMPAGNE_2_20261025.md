# Exercices Nova — campagne 2 : améliorations et coût (25/10/2026)

Préparée sans GPU, avec l'accord de l'utilisateur (« oui prépare les améliorations »). Lancement seulement après son accord sur la taille et le coût.

## Ce qui change par rapport à l'essai de 600

| Leçon de l'essai | Amélioration |
|---|---|
| 204/600 créations perdues : la solution de GLM ratait ses propres tests | Une correction de la référence par GLM ; l'énoncé et les tests ne changent pas. L'exercice est gardé si la solution corrigée passe et si le départ échoue toujours. |
| Réparations trop faciles (environ 50 jetons de raisonnement) | Bogues **subtils** (un seul, visible seulement sur certains cas) ou **doubles** (deux endroits du code, contrôlé). |
| 60 thèmes : à 500 exercices par langage, les mêmes reviendraient sans cesse | **200 thèmes et 12 genres**, distribués à tour de rôle : chaque thème revient 2 ou 3 fois par langage. Les thèmes trop proches d'exercices d'Exercism sont écartés. |
| L'élève échoue surtout sur les exercices difficiles (37 % au premier essai) | **Moitié d'exercices difficiles**, au lieu de 40 %. |
| Ne pas abîmer l'essai | Dossiers à part. L'essai est seulement lu : ses exercices ne sont pas redemandés, et ses exercices gardés servent au filtre des doublons. |
| Créneaux perdus par des erreurs de code | Essai à blanc avant chaque chargement, sur le cluster et sur le PC (création comprise, dans les 6 langages). |

Contrôles faits :
- Tests : 115/115.
- Essais à blanc sur le PC avec les vraies données : campagne 2 complète, essai de 600, mesure de l'élève.
- Avec le nouveau code, l'essai de 600 reste reproduit : 600/600 spécifications identiques et 271/299 invites de bogue identiques. Les 28 autres sont les exercices C++ où l'en-tête de départ est maintenant montré (correction du 21/10).

## Coût prévu

`work/nova_122b/discoverer/estimer_exercices_v2.py` part des mesures de l'essai. Recalé sur l'essai, il prévoit 58 h GPU pour 61 h mesurées.

| Exercices demandés | Heures GPU | Exemples vérifiés (bas / central / haut) | Créneaux de 8 GPU |
|---|---|---|---|
| 1 500 (250 par langage) | ≈ 173 | 1 240 / 1 530 / 1 790 | ≈ 7 |
| **3 000 (500 par langage, préparé)** | **≈ 346** | 2 470 / 3 060 / 3 590 | ≈ 13 |
| 6 000 (1 000 par langage) | ≈ 692 | 4 950 / 6 120 / 7 170 | ≈ 25 |

Le coût dépend presque seulement du nombre d'exercices demandés. L'incertitude porte sur le nombre d'exemples obtenus, qui dépend de deux taux inconnus avant lancement : la part des références sauvées par la correction (supposée entre 30 % et 65 %) et la réussite des réparations de bogues plus durs.

**Budget :** 233 h GPU utilisées sur 5 000. Accès jusqu'au 05/01/2027.

## Déroulé proposé

1. **Premier lancement** de `Exercices_Nova_V2_Discoverer.bat` : 2 créneaux en chaîne, 62 h GPU au plus. Dans le Suivi, on lit les lignes `EXERCICES_NOVA_CORRECTION`, la validité des bogues subtils et doubles, et la durée des lots.
2. **Si les taux sont bons**, on relance le même fichier jusqu'à la fin de la campagne. Rien n'est refait. Le nombre de créneaux par lancement (`creneaux` dans `exercices_nova_v2.json`) peut être augmenté pour moins attendre la file.
3. **À la fin :** rapatrier, auditer un échantillon, et mesurer l'élève sur une partie des nouveaux exercices.
