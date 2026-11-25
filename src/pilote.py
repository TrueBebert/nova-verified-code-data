"""Pilote de Nova 122B sur Discoverer+ : réponses du professeur (GLM-5.3) ou de l'élève (Qwen3.5-122B-A10B-FP8) sur le jeu
du pilote, phase par phase, selon pilote_v1.json. À lancer DANS une tâche SLURM (pilote_professeur.sbatch, pilote_eleve.sbatch).

- Chaque phase écrit <résultats>/<phase>.jsonl au fil de l'eau, un lot à la fois. Une relance saute les identifiants déjà
  faits ; <phase>.fini marque une phase terminée.
- Arrêt propre avant la limite de la tâche : on ne commence pas un lot qui risque de ne pas finir (durée du lot précédent).
- Lignes PILOTE_* dans le journal, lues par le suivi : débit en jetons par seconde, heures GPU par million de jetons, part
  des réponses coupées par la limite de jetons.
- Réglages lus au démarrage de la tâche : ils peuvent encore changer jusque-là (renvoyés par Pilote_Discoverer.bat), y compris
  les variables d'environnement de vLLM (clé « env » du rôle), posées avant son import.
- Garde-fou de chargement (test 199800 du 08/10 : coupé à 1 h 15 avant la fin du démarrage de vLLM) : si le moteur n'est pas
  prêt après « limite_chargement_minutes », ses processus sont arrêtés et on réessaie avec les options de « repli » (par
  exemple sans graphes CUDA), dans la même tâche ; sans repli possible, la tâche s'arrête et libère le nœud.
- --simulation : faux moteur, pour tester toute la logique sur le PC, sans GPU.
- Code (11/10) : quand toutes les phases sont finies et que des phases code_* le sont, leurs réponses sont corrigées tout de
  suite sur les processeurs de la tâche (pilote_code.py evaluer, quelques minutes, GPU inoccupés), jusqu'à 3 min avant la
  fin de la tâche : pas de seconde attente dans la file pour la correction. Ce qui reste est repris par Evaluer_Code.

Codes de sortie : 0 phases terminées (une phase de remplissage peut s'arrêter avant la fin) ; 3 arrêt avant la limite de
temps pendant une phase du pilote (relancer pour continuer) ; 4 moteur jamais prêt ; 1 erreur.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def invite(q: dict) -> list[dict]:
    """Comme comparaison/generer.py et distillation/generer_professeur.py : consigne, puis contexte."""
    return [{'role': 'user', 'content': q['consigne'] + ('\n\n' + q['contexte'] if q.get('contexte') else '')}]


def raisonnement_ouvert(tokenizer, chat_kwargs: dict) -> bool:
    """Copie de distillation/generer_professeur.py (test_discoverer vérifie qu'elles s'accordent) : vrai si l'invite de
    génération ouvre déjà <think> (GLM-5.3 toujours ; Qwen3.5 avec enable_thinking)."""
    rendu = tokenizer.apply_chat_template([{'role': 'user', 'content': 'x'}], add_generation_prompt=True, tokenize=False,
                                          **chat_kwargs)
    return rendu.rstrip().endswith('<think>')


def separer(texte: str, ouvert: bool) -> tuple[str | None, str]:
    """Copie de distillation/generer_professeur.py : (raisonnement, réponse). Raisonnement coupé avant </think> : pas de
    réponse. Sans raisonnement : tout est réponse."""
    if '</think>' in texte:
        avant, apres = texte.split('</think>', 1)
        return avant.replace('<think>', '').strip(), apres.strip()
    if ouvert or texte.lstrip().startswith('<think>'):
        return texte.replace('<think>', '').strip(), ''
    return None, texte.strip()


def recomposer(texte: str, ids, id_fin: int | None, decoder) -> tuple[str, bool]:
    """vLLM retire les jetons spéciaux du texte. Si </think> en est un, il manque au texte alors qu'il est dans les jetons :
    toute la sortie passerait pour du raisonnement, sans réponse. On recompose alors raisonnement + </think> + réponse à
    partir des jetons. Renvoie (texte, recomposé ou non)."""
    if id_fin is None or '</think>' in texte:
        return texte, False
    ids = list(ids)
    if id_fin not in ids:
        return texte, False
    i = ids.index(id_fin)
    return decoder(ids[:i]) + '</think>' + decoder(ids[i + 1:]), True


MARGE_JETONS = 64  # écart possible entre notre compte de l'invite et celui de vLLM
REPONSE_MIN = 4096  # place de réponse en dessous de laquelle une invite n'est pas envoyée


class MoteurVllm:
    """vLLM hors ligne. Les noyaux de DeepGEMM (CUDA_HOME, libstdc++) sont réglés par le script de la tâche."""

    def __init__(self, chemin: str, reglages: dict, graine: int):
        from vllm import LLM  # seulement sur le nœud GPU
        self.llm = LLM(model=chemin, seed=graine, **reglages)
        self.max_len = reglages.get('max_model_len')
        self.tp = reglages.get('tensor_parallel_size', 1)
        tok = self.llm.get_tokenizer()
        i = tok.convert_tokens_to_ids('</think>')
        self.id_fin = i if isinstance(i, int) and i != getattr(tok, 'unk_token_id', None) else None
        self.decoder = lambda ids: tok.decode(ids, skip_special_tokens=True)
        self.recomposes = 0
        print(f"PILOTE_FIN_DE_RAISONNEMENT jeton {self.id_fin} ; jeton spécial, retiré du texte par vLLM : "
              f"{'</think>' in getattr(tok, 'all_special_tokens', [])}", flush=True)

    def ouvert(self, chat_kwargs: dict) -> bool:
        return raisonnement_ouvert(self.llm.get_tokenizer(), chat_kwargs)

    def budgets(self, messages: list, max_tokens: int, chat_kwargs: dict) -> list[int]:
        """Jetons de réponse permis pour chaque invite (15/10) : max_tokens, ou moins quand invite + réponse dépasseraient
        max_model_len (vrais bugs de SWE-bench : fichiers entiers dans l'invite ; second essai des exercices : première
        réponse et sortie des tests) ; 0 quand l'invite ne laisse pas de place pour répondre (elle n'est pas envoyée :
        une seule invite trop longue ferait échouer tout le lot)."""
        if not self.max_len:
            return [max_tokens] * len(messages)
        tok = self.llm.get_tokenizer()
        out = []
        for conv in messages:
            try:
                texte = tok.apply_chat_template(conv, tokenize=False, add_generation_prompt=True, **chat_kwargs)
                n = len(tok.encode(texte, add_special_tokens=False))
            except Exception:  # compte impossible : réglage d'origine
                out.append(max_tokens)
                continue
            place = self.max_len - n - MARGE_JETONS
            out.append(min(max_tokens, place) if place >= min(max_tokens, REPONSE_MIN) else 0)
        return out

    def generer(self, messages: list, phase: dict) -> list[list[dict]]:
        from vllm import SamplingParams
        options = {k: phase[k] for k in ('top_p', 'top_k', 'min_p', 'repetition_penalty') if k in phase}
        chat_kwargs = phase.get('chat_kwargs') or {}
        n = phase.get('n', 1)
        budgets = self.budgets(messages, phase['max_tokens'], chat_kwargs)
        garder = [k for k, b in enumerate(budgets) if b > 0]

        def params(max_tokens):
            return SamplingParams(n=n, temperature=phase.get('temperature', 0.0), max_tokens=max_tokens, **options)
        # un seul jeu de réglages quand aucune invite n'est longue (comme avant le 15/10), sinon un par invite
        if all(budgets[k] == phase['max_tokens'] for k in garder):
            reglages = params(phase['max_tokens'])
        else:
            reglages = [params(budgets[k]) for k in garder]
        sorties = (self.llm.chat([messages[k] for k in garder], reglages, chat_template_kwargs=chat_kwargs, use_tqdm=False)
                   if garder else [])
        resultats = [[{'texte': '', 'jetons': 0, 'fin': 'invite_trop_longue'} for _ in range(n)] for _ in messages]
        for k, s in zip(garder, sorties):
            ech = []
            for o in s.outputs:
                texte, recompose = recomposer(o.text, o.token_ids, self.id_fin, self.decoder)
                self.recomposes += recompose
                ech.append({'texte': texte, 'jetons': len(o.token_ids), 'fin': o.finish_reason})
            resultats[k] = ech
        return resultats


def arreter_processus_enfants():
    """Arrête les processus lancés par vLLM (moteur et travailleurs) : le constructeur en attente échoue alors, et les GPU
    sont libérés pour un nouvel essai."""
    import psutil  # dépendance de vLLM
    enfants = psutil.Process().children(recursive=True)
    for p in enfants:
        try:
            p.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(enfants, timeout=60)
    return len(enfants)


class Garde:
    """Minuteur de chargement : à l'échéance, appelle arreter() ; si le chargement ne rend pas la main dans les 3 minutes
    qui suivent, quitte (code 4) pour libérer le nœud plutôt que d'attendre la limite de la tâche."""

    def __init__(self, limite_s: float, arreter, sortie_forcee=None):
        self.fini = threading.Event()
        self.declenche = False
        self.arreter = arreter
        self.sortie_forcee = sortie_forcee or (lambda: os._exit(4))
        self.minuteur = threading.Timer(limite_s, self._echeance)
        self.minuteur.daemon = True
        self.secours = None

    def _echeance(self):
        if self.fini.is_set():
            return
        self.declenche = True
        print('PILOTE_GARDE : moteur pas prêt à temps, arrêt de ses processus', flush=True)
        try:
            n = self.arreter()
            print(f'PILOTE_GARDE : {n} processus arrêtés', flush=True)
        finally:
            self.secours = threading.Timer(180, self._abandon)
            self.secours.daemon = True
            self.secours.start()

    def _abandon(self):
        if not self.fini.is_set():
            print('PILOTE_BILAN=ECHEC : le chargement ne rend pas la main après l\'arrêt de ses processus', flush=True)
            self.sortie_forcee()

    def __enter__(self):
        self.minuteur.start()
        return self

    def __exit__(self, *exc):
        self.fini.set()
        self.minuteur.cancel()
        if self.secours:
            self.secours.cancel()
        return False


def charger(creer, essais: list[dict], limite_s: float, arreter) -> tuple[object | None, int]:
    """Essaie chaque jeu d'options (d'abord les réglages normaux, puis les replis) sous un garde-fou. Renvoie (moteur ou
    None, numéro de l'essai réussi)."""
    for i, options in enumerate(essais, 1):
        t0 = time.time()
        print(f'PILOTE_CHARGEMENT_ESSAI {i}/{len(essais)} : options {json.dumps(options, ensure_ascii=False)} ; '
              f'garde-fou {limite_s / 60:.0f} min', flush=True)
        try:
            with Garde(limite_s, arreter) as garde:
                moteur = creer(options)
            print(f'PILOTE_CHARGEMENT=OK (essai {i}, {time.time() - t0:.0f} s)', flush=True)
            return moteur, i
        except Exception as e:  # moteur arrêté par le garde-fou, ou erreur de démarrage
            raison = 'garde-fou' if garde.declenche else f'{type(e).__name__}: {str(e)[:300]}'
            print(f'PILOTE_CHARGEMENT_ECHEC essai {i} ({time.time() - t0:.0f} s) : {raison}', flush=True)
            try:
                arreter()
            except Exception:
                pass
    return None, 0


class MoteurSimule:
    """Faux moteur pour le PC : le professeur raisonne toujours, l'élève seulement avec enable_thinking ; une pause par lot
    (--simulation-pause) pour essayer l'arrêt avant la limite de temps ; un blocage au chargement pour essayer le garde-fou
    (options {"simulation_blocage": true} : le constructeur attend qu'on l'arrête, puis échoue)."""

    ARRET = threading.Event()

    def __init__(self, role: str, tp: int, pause: float, options: dict | None = None):
        self.role, self.tp, self.pause = role, tp, pause
        if (options or {}).get('simulation_blocage'):
            MoteurSimule.ARRET.wait(600)
            MoteurSimule.ARRET.clear()
            raise RuntimeError('moteur simulé arrêté pendant son chargement')

    def ouvert(self, chat_kwargs: dict) -> bool:
        return self.role == 'professeur' or bool(chat_kwargs.get('enable_thinking'))

    def generer(self, messages: list, phase: dict) -> list[list[dict]]:
        time.sleep(self.pause)
        raisonne = self.ouvert(phase.get('chat_kwargs') or {})
        sorties = []
        for m in messages:
            h = int(hashlib.sha256(m[0]['content'].encode('utf-8')).hexdigest(), 16)
            ech = []
            for j in range(phase.get('n', 1)):
                coupe = (h + j) % 10 == 0
                texte = (f'Je compare les données ({j}).' + ('' if coupe else '</think>') if raisonne else '') + \
                    ('' if coupe and raisonne else f'Réponse simulée {(h + j) % 7}.')
                ech.append({'texte': texte, 'jetons': len(texte.split()), 'fin': 'length' if coupe else 'stop'})
            sorties.append(ech)
        return sorties


def lire_questions(chemin: Path) -> list[dict]:
    ouvrir = gzip.open if chemin.suffix == '.gz' else open
    with ouvrir(chemin, 'rt', encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def ids_faits(chemin: Path) -> set[str]:
    """Identifiants déjà écrits. Une ligne coupée par l'arrêt brutal d'une tâche (fin de fichier sans saut de ligne) est
    retirée, pour que le fichier reste lisible ligne à ligne."""
    if not chemin.exists():
        return set()
    brut = chemin.read_bytes()
    if brut and not brut.endswith(b'\n'):
        garde = brut[:brut.rfind(b'\n') + 1]
        chemin.write_bytes(garde)
        print(f'PILOTE_REPARATION {chemin.name} : dernière ligne incomplète retirée ({len(brut) - len(garde)} octets)',
              flush=True)
        brut = garde
    return {json.loads(l)['id'] for l in brut.decode('utf-8').splitlines() if l.strip()}


def millions(n: int) -> str:
    return f'{n / 1e6:.2f} M'


def executer_phase(moteur, role: str, nom_modele: str, phase: dict, dossier: Path, entree: Path, lot: int,
                   debut: float, limite_s: float) -> str:
    """Renvoie 'finie' ou 'arretee' (limite de temps proche)."""
    nom = phase['nom']
    sortie, fini = dossier / f'{nom}.jsonl', dossier / f'{nom}.fini'
    questions = lire_questions(entree)
    if phase.get('categories'):  # une partie seulement du fichier (par exemple les maths et les sciences du jeu « max »)
        questions = [q for q in questions if q.get('categorie') in phase['categories']]
    faits = ids_faits(sortie)
    a_faire = [q for q in questions if q['id'] not in faits]
    print(f'PILOTE_PHASE_DEBUT {nom} : {len(questions)} demandes, {len(faits)} déjà faites, {len(a_faire)} à faire ; '
          f"n={phase.get('n', 1)} température={phase.get('temperature', 0.0)} max_tokens={phase['max_tokens']} "
          f"chat_kwargs={json.dumps(phase.get('chat_kwargs') or {}, ensure_ascii=False)}", flush=True)
    chat_kwargs = phase.get('chat_kwargs') or {}
    ouvert = moteur.ouvert(chat_kwargs)
    jetons = echantillons = coupes = vides = 0
    secondes = 0.0
    # durée prévue du premier lot (longues réponses, 11/10) : sans elle, le premier lot d'une phase partirait même à
    # quelques minutes de la fin de la tâche et serait perdu ; ensuite, la durée du lot précédent
    duree_lot = 60.0 * phase.get('duree_lot_minutes', 0)
    etat = 'finie'
    for i in range(0, len(a_faire), lot):
        ecoule = time.time() - debut
        if ecoule + 1.3 * duree_lot > limite_s:
            print(f'PILOTE_ARRET {nom} : {ecoule / 60:.0f} min écoulées, le lot suivant risquerait de dépasser la limite '
                  f'({limite_s / 60:.0f} min) ; relancer pour continuer', flush=True)
            etat = 'arretee'
            break
        paquet = a_faire[i:i + lot]
        t0 = time.time()
        resultats = moteur.generer([invite(q) for q in paquet], phase)
        duree_lot = time.time() - t0
        lignes = []
        for q, ech in zip(paquet, resultats):
            sortis = []
            for e in ech:
                raisonnement, reponse = separer(e['texte'], ouvert)
                sortis.append({'texte': reponse, 'raisonnement': raisonnement, 'fin': e['fin'], 'jetons': e['jetons']})
                jetons += e['jetons']
                echantillons += 1
                coupes += e['fin'] == 'length'
                vides += not reponse
            lignes.append(json.dumps({'id': q['id'], 'phase': nom, 'modele': nom_modele, 'chat_kwargs': chat_kwargs,
                                      'n': phase.get('n', 1), 'temperature': phase.get('temperature', 0.0),
                                      'max_tokens': phase['max_tokens'], 'echantillons': sortis}, ensure_ascii=False))
        with sortie.open('a', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lignes) + '\n')
            f.flush()
            os.fsync(f.fileno())
        secondes += duree_lot
        faits_total = len(faits) + min(i + lot, len(a_faire))
        lot_jetons = sum(e['jetons'] for ech in resultats for e in ech)
        print(f'PILOTE_LOT {nom} : {faits_total}/{len(questions)} demandes ; {millions(lot_jetons)} jetons en '
              f'{duree_lot:.0f} s ({lot_jetons / max(duree_lot, 1e-9):.0f} jetons/s)', flush=True)
    if etat == 'finie':
        fini.write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
    if echantillons:
        par_s = jetons / max(secondes, 1e-9)
        h_gpu = moteur.tp * secondes / 3600
        print(f'PILOTE_PHASE {nom}={"FINIE" if etat == "finie" else "A_REPRENDRE"} : {echantillons} échantillons, '
              f'{millions(jetons)} jetons en {secondes / 60:.1f} min, {par_s:.0f} jetons/s, {h_gpu:.2f} h GPU, '
              f'{moteur.tp * 1e6 / par_s / 3600:.2f} h GPU par million de jetons ; coupés par la limite de jetons : '
              f'{100 * coupes / echantillons:.1f} % ; sans réponse après le raisonnement : {100 * vides / echantillons:.1f} % ; '
              f'fin de raisonnement recomposée par les jetons (depuis le début) : {getattr(moteur, "recomposes", 0)}',
              flush=True)
    elif etat == 'finie':
        print(f'PILOTE_PHASE {nom}=FINIE : rien à faire', flush=True)
    return etat


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--role', required=True, choices=('professeur', 'eleve'))
    a.add_argument('--config', required=True)
    a.add_argument('--travail', required=True, help='dossier de travail du projet sur le cluster')
    a.add_argument('--limite-minutes', type=float, help='remplace la limite de la configuration')
    a.add_argument('--simulation', action='store_true')
    a.add_argument('--simulation-pause', type=float, default=0.0)
    a.add_argument('--limite-chargement-minutes', type=float, help='remplace le garde-fou de chargement de la configuration')
    args = a.parse_args()
    debut = time.time()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    role = config['roles'][args.role]
    travail = Path(args.travail)
    dossier = travail / config['dossier_resultats']
    dossier.mkdir(parents=True, exist_ok=True)
    limite_s = 60 * (args.limite_minutes if args.limite_minutes is not None else role['limite_minutes'])
    code_dir = Path(args.config).resolve().parent
    phases = [p for p in role['phases'] if not (dossier / f"{p['nom']}.fini").exists()]
    print(f"PILOTE_DEBUT {args.role} : modèle {role['modele']} ; phases restantes : "
          f"{', '.join(p['nom'] for p in phases) or 'aucune'}", flush=True)
    if not phases:
        print('PILOTE_BILAN=FINI', flush=True)
        return 0
    # Une tâche précédente n'a jamais eu de moteur prêt : la suite en file s'arrête aussitôt (quelques secondes de GPU) au
    # lieu de rejouer le même échec. Pilote_Discoverer.bat met ce témoin de côté quand il renvoie de nouveaux réglages.
    temoin = dossier / f'{args.role}.moteur_jamais_pret'
    if temoin.exists():
        print(f'PILOTE_BILAN=ECHEC : la tâche précédente n\'a jamais eu de moteur prêt ({temoin.read_text(encoding="utf-8").strip()}) ; '
              'nouveaux réglages à envoyer par Pilote_Discoverer.bat', flush=True)
        return 4
    for p in list(phases):
        if (code_dir / p['entree']).exists():
            continue
        if p.get('preparer') == 'code':  # problèmes LiveCodeBench téléchargés au début de la tâche (pilote_code.py)
            try:
                sys.path.insert(0, str(code_dir))
                import pilote_code
                pilote_code.preparer(travail, code_dir / p['entree'])
                continue
            except Exception as e:
                print(f"PILOTE_PHASE_SAUTEE {p['nom']} : préparation impossible ({type(e).__name__}: {e})", flush=True)
        else:
            print(f"PILOTE_PHASE_SAUTEE {p['nom']} : fichier d'entrée absent {p['entree']}", flush=True)
        phases.remove(p)
    if not phases:
        print('PILOTE_BILAN=ECHEC : aucune phase possible', flush=True)
        return 1
    for cle, valeur in (role.get('env') or {}).items():  # avant l'import de vLLM
        os.environ[cle] = str(valeur)
        print(f'PILOTE_ENV {cle}={valeur}', flush=True)
    tp = role['vllm'].get('tensor_parallel_size', 1)
    essais = [role.get('options_simulation', {}) if args.simulation else {}] + ([role['repli']] if role.get('repli') else [])
    limite_chargement = 60 * (args.limite_chargement_minutes if args.limite_chargement_minutes is not None
                              else role.get('limite_chargement_minutes', 70))
    if args.simulation:
        moteur, essai = charger(lambda o: MoteurSimule(args.role, tp, args.simulation_pause, o), essais, limite_chargement,
                                lambda: (MoteurSimule.ARRET.set(), 0)[1])
    else:
        chemin = str(travail / role['modele'])
        moteur, essai = charger(lambda o: MoteurVllm(chemin, {**role['vllm'], **o}, config.get('graine', 0)), essais,
                                limite_chargement, arreter_processus_enfants)
    if moteur is None:
        temoin.write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + f" tâche {os.environ.get('SLURM_JOB_ID', '?')}\n",
                          encoding='utf-8')
        print('PILOTE_BILAN=ECHEC : moteur jamais prêt, voir PILOTE_CHARGEMENT_ECHEC', flush=True)
        return 4
    for p in phases:
        etat = executer_phase(moteur, args.role, role['modele'], p, dossier, code_dir / p['entree'],
                              p.get('lot', config.get('lot', 512)), debut, limite_s)
        if etat == 'arretee':
            if p.get('remplissage'):
                print('PILOTE_BILAN=FINI (remplissage arrêté par la limite de temps, à reprendre plus tard)', flush=True)
                corriger_code(role, dossier, code_dir, travail)
                return 0
            print('PILOTE_BILAN=A_REPRENDRE', flush=True)
            corriger_code(role, dossier, code_dir, travail)  # les phases de code déjà finies, s'il reste du temps
            return 3
    if all((dossier / f"{p['nom']}.fini").exists() for p in role['phases']):  # une phase sautée laisse le rôle ouvert
        (dossier / f'{args.role}.fini').write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
    print('PILOTE_BILAN=FINI', flush=True)
    corriger_code(role, dossier, code_dir, travail)
    return 0


def corriger_code(role: dict, dossier: Path, code_dir: Path, travail: Path) -> None:
    """Phases code_* terminées : correction par pilote_code.py dans un processus à part, sur les processeurs de la tâche
    (il s'arrête seul 3 min avant la fin de la tâche SLURM). Une erreur de correction ne change pas le bilan du pilote."""
    if not any(p['nom'].startswith('code_') and (dossier / f"{p['nom']}.fini").exists() for p in role['phases']):
        return
    processus = max(2, int(os.environ.get('SLURM_CPUS_PER_TASK') or os.cpu_count() or 2) - 4)
    print(f'PILOTE_CODE_EVAL_DEBUT : correction des phases de code terminées, {processus} processus', flush=True)
    r = subprocess.run([sys.executable, '-B', str(code_dir / 'pilote_code.py'), 'evaluer', '--travail', str(travail),
                        '--processus', str(processus)])
    if r.returncode:
        print(f'PILOTE_CODE_EVAL_ECHEC : code {r.returncode} (à reprendre par Evaluer_Code)', flush=True)


if __name__ == '__main__':
    sys.exit(main())
