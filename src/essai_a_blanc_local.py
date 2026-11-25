"""Essai à blanc des exercices Nova sur le PC (21/10/2026), sur les résultats rapatriés du cluster : les phases qui
restent, puis l'export, passent sur une copie avec le faux moteur et les faux tests d'exercices_nova (rien n'est
exécuté, le code des modèles ne tourne jamais sur le PC). Même contrôle que celui que la tâche fait avant de charger
le modèle, mais avant de relancer : une erreur de code se corrige sans attendre la file de Discoverer.

  python essai_a_blanc_local.py            professeur (résultats dans pilote/resultats_cluster, Rapatrier_Pilote)
  python essai_a_blanc_local.py --eleve    mesure de l'élève (23/10) : mêmes exercices, bilan comparé à GLM-5.3
  python essai_a_blanc_local.py --v2       campagne 2 (25/10) : toutes les phases, création comprise ; les gabarits du
                                           banc polyglot n'étant pas sur le PC, ceux de chaque langage sont pris parmi
                                           les exercices rapatriés de l'essai (même structure)
"""
import json
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import exercices_nova as EN  # noqa: E402


def gabarits_locaux(travail: Path) -> dict[str, dict]:
    """Un exercice gardé de l'essai par langage, pris pour gabarit (dossier rapatrié, fichiers techniques compris)."""
    creation = EN.lire_jsonl(travail / EN.RESULTATS / 'creation.jsonl')
    gardes = json.loads((travail / EN.RESULTATS / 'taches_finales.json').read_text(encoding='utf-8'))['gardes']
    out = {}
    for i in gardes:
        e = creation[i]['entree']
        if e['langue'] not in out and (travail / e['dossier'] / '.meta' / 'config.json').exists():
            out[e['langue']] = e
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    eleve, v2 = '--eleve' in sys.argv[1:], '--v2' in sys.argv[1:]
    travail = ICI / 'pilote' / 'resultats_cluster'
    nom = 'exercices_nova_eleve_v1.json' if eleve else 'exercices_nova_v2.json' if v2 else 'exercices_nova_v1.json'
    config = json.loads((ICI / nom).read_text(encoding='utf-8'))
    dossier = travail / config.get('resultats', EN.RESULTATS_ELEVE if eleve else EN.RESULTATS)
    etapes = ('resolution',) if eleve else ('creation', 'resolution', 'injection', 'reparation')
    restantes = [e for e in etapes if not (dossier / f'{e}.fini').exists()]
    if not (travail / EN.DONNEES).exists():
        print('ESSAI_A_BLANC_LOCAL : exercices absents (donnees/exercices_nova) ; lancer Rapatrier_Pilote_Discoverer.bat')
        return 2
    if v2:
        EN.gabarits = gabarits_locaux
    print(f"ESSAI_A_BLANC_LOCAL ({'élève' if eleve else 'campagne 2' if v2 else 'professeur'}) : phases restantes : "
          f"{', '.join(restantes) or 'aucune'}")
    erreur, sortie = EN.essai_a_blanc(travail, config, restantes, EN.PipelineEleve if eleve else EN.Pipeline)
    try:  # dossier vide créé par l'essai pour une campagne pas encore commencée
        dossier.rmdir()
    except OSError:
        pass
    print('\n'.join('  ' + l for l in sortie.strip().splitlines()[-30:]))
    if erreur:
        print('ESSAI_A_BLANC_LOCAL=ECHEC')
        print(erreur)
        return 1
    print('ESSAI_A_BLANC_LOCAL=OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
