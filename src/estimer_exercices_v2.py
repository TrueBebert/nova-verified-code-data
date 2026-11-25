"""Coût et rendement prévus de la campagne 2 des exercices Nova (25/10/2026), à partir des mesures de l'essai de 600
(journaux des tâches 202543, 202544, 202885, 203303 ; bilan de l'élève 203664). Les hypothèses nouvelles (correction des
références, bogues plus durs) sont données en fourchette basse / centrale / haute."""
import json
import sys

# mesures de l'essai (8 GPU)
CREATION_MIN = 75.4 + 77.2 + 73.3 + 82.0     # 4 lots de 150 créations
CREATION_TACHES = 600
VALIDES, GARDES, EXEMPLES = 348, 306, 541
REJET_REFERENCE = 204                       # la solution rate ses propres tests
AVAL_MIN = 19.7 + 14.9 + 3.4 + 6.4 + 3.9 + 6.5 + 2.3  # résolution (2 essais), bogues, réparations, pour 306 gardés
GPU = 8
# chargements (10 à 28 min par créneau), essai à blanc, fins de créneau : recalé sur l'essai (48,7 h GPU de génération,
# 58,7 h mesurées hors plantage du 21/10)
SURCOUT = 1.20

HYPOTHESES = {  # (part des références sauvées, part gardée, exemples par exercice gardé, surcoût des réparations)
    'basse': (0.30, 0.84, 1.45, 2.0),
    'centrale': (0.50, 0.87, 1.58, 1.5),
    'haute': (0.65, 0.89, 1.70, 1.2),
}


def estimer(taches: int, hyp: str) -> dict:
    sauve, garde, par_garde, rep = HYPOTHESES[hyp]
    gpu_h_creation = CREATION_MIN / 60 * GPU / CREATION_TACHES                    # par tâche
    gpu_h_correction = gpu_h_creation * 0.45 * REJET_REFERENCE / CREATION_TACHES  # réponse plus courte : 45 % des jetons
    valides = VALIDES / CREATION_TACHES + sauve * REJET_REFERENCE / CREATION_TACHES * 0.95
    gardes = valides * garde
    gpu_h_aval = AVAL_MIN / 60 * GPU / GARDES * (1 + (rep - 1) * (6.5 + 2.3) / AVAL_MIN)  # réparations plus longues
    total = taches * (gpu_h_creation + gpu_h_correction + gardes * gpu_h_aval) * SURCOUT
    exemples = taches * gardes * par_garde
    return {'taches': taches, 'hypothese': hyp, 'heures_gpu': round(total), 'exemples': round(exemples),
            'heures_par_exemple': round(total / exemples, 3), 'creneaux_de_31h': round(total / 28 + 0.5)}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    lignes = [estimer(t, h) for t in (1500, 3000, 6000) for h in HYPOTHESES]
    for l in lignes:
        print(json.dumps(l, ensure_ascii=False))
    essai = (CREATION_MIN / 60 * GPU + AVAL_MIN / 60 * GPU) * SURCOUT
    print(f"contrôle sur l'essai : {essai:.0f} h GPU de génération et chargements prévues pour 600 tâches "
          f"(mesuré : 61 h au total, dont environ 1 h perdue) ; {EXEMPLES} exemples")
    return 0


if __name__ == '__main__':
    sys.exit(main())
