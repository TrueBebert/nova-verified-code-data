"""Test « corriger de vrais programmes » de Nova 122B sur SWE-bench Verified (préparation : oui de l'utilisateur du
12/10/2026, 0 heure GPU) : 500 vrais bugs de 12 logiciels Python (GitHub), chacun avec son environnement (image de
conteneur) et les tests du projet. Sur Discoverer, les images tournent avec Apptainer (présent sur les nœuds de calcul,
RES-022), sans Docker ni droits particuliers. Le script d'évaluation et la lecture des résultats sont ceux de l'outil
officiel (paquet swebench, licence MIT) : seul le lancement du conteneur change.

  preparer --travail T       télécharge SWE-bench Verified (Hugging Face, version de l'outil 5 : script d'évaluation, image et
                             lecteur de résultats de chaque bug) dans T/donnees/swebench/verified_v5.jsonl.
  essai --travail T          sur un bug : image tirée par Apptainer (d'abord les images allégées d'Epoch AI sur GitHub,
                             sinon celles de SWE-bench sur Docker Hub), correction officielle puis aucune correction, dans
                             deux façons de lancer le conteneur ; le bug doit être résolu avec la correction officielle et
                             pas sans : la chaîne entière est alors prouvée (aucun modèle, 0 heure GPU).
  images --travail T         sous-ensemble de bugs (100 par défaut, tirés au hasard avec une graine fixe, au prorata de
                             chaque logiciel), leurs images, et les fichiers à corriger lus dans l'image (version du bug).
  generer --role R --config F --travail T
                             (GPU, après accord) le modèle voit le rapport de bug et les fichiers à corriger (réglage
                             « oracle » de SWE-bench, sans agent) et répond par des blocs SEARCH/REPLACE, transformés en
                             correction au format git ; puis correction par evaluer, dans la même tâche.
  evaluer --travail T --predictions P
                             chaque correction dans le conteneur de son bug, résultat lu par l'outil officiel (résolu ou
                             non), en parallèle ; reprend là où une tâche s'est arrêtée.
Licences : jeu de SWE-bench sous MIT, images d'Epoch AI sous MIT, logiciels testés sous leurs propres licences (BSD, MIT,
Apache) ; mesure interne seulement.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

JEU = 'SWE-bench/SWE-bench_Verified'  # 13/10 : l'outil 5.0.2 lit ce jeu (champs image, eval_script, log_parser)
FICHIER_JEU = 'verified_v5.jsonl'
SOUS_ENSEMBLE = 100
GRAINE = 20261012
LIMITE_INVITE = 160_000  # caractères (~40 000 jetons) : place pour 65 536 jetons de réponse dans 106 496
RESULTATS = Path('resultats') / 'swebench'
PREFERES = ['django__django-11099', 'astropy__astropy-12907', 'sympy__sympy-20590']  # essais courts
DELAI_S = 1800  # comme l'outil officiel
# 13/10 (essai 201035) : « simple » marche ; avec --fakeroot, l'écriture dans /testbed échoue (Invalid argument), les
# tests du bug ne s'installent pas et un bug non corrigé passe pour résolu : d'où la garde patch_de_test_applique
MODES = {'simple': ['--writable-tmpfs', '--containall'],
         'fakeroot': ['--fakeroot', '--writable-tmpfs', '--containall']}
APPLIQUER = ['git apply --verbose', 'git apply --verbose --reject', 'patch --batch --fuzz=5 -p1 -i']  # comme l'outil officiel


def fonction_test_spec():
    """make_test_spec de l'outil officiel : swebench.harness.utils depuis la version 5, test_spec avant."""
    for module in ('swebench.harness.utils', 'swebench.harness.test_spec.test_spec', 'swebench.harness.test_spec'):
        try:
            return getattr(__import__(module, fromlist=['make_test_spec']), 'make_test_spec')
        except (ImportError, AttributeError):
            continue
    raise ImportError('make_test_spec introuvable dans le paquet swebench')


def images(instance_id: str) -> list[str]:
    """Images candidates : allégées d'Epoch AI (GitHub, sans la limite anonyme de Docker Hub), puis officielles."""
    return [f'docker://ghcr.io/epoch-research/swe-bench.eval.x86_64.{instance_id}:latest',
            f"docker://swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_').lower()}:latest"]


def preparer(travail: Path) -> list[dict]:
    from datasets import load_dataset
    dossier = travail / 'donnees' / 'swebench'
    dossier.mkdir(parents=True, exist_ok=True)
    jeu = load_dataset(JEU, split='test')
    lignes = [dict(r) for r in jeu]
    tmp = dossier / f'{FICHIER_JEU}.{os.getpid()}.partiel'
    tmp.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in lignes), encoding='utf-8')
    tmp.replace(dossier / FICHIER_JEU)
    depots = {}
    for r in lignes:
        depots[r['repo']] = depots.get(r['repo'], 0) + 1
    print(f"SWEBENCH_PREPARE : {len(lignes)} bugs ({' ; '.join(f'{d} {n}' for d, n in sorted(depots.items()))})", flush=True)
    return lignes


def charger(travail: Path) -> list[dict]:
    with open(travail / 'donnees' / 'swebench' / FICHIER_JEU, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def tirer(travail: Path, instance_id: str) -> tuple[Path | None, str, float]:
    """Image .sif dans T/swebench/images (gardée) ; renvoie (chemin ou None, source, secondes)."""
    sortie = travail / 'swebench' / 'images' / f'{instance_id}.sif'
    if sortie.exists():
        return sortie, 'déjà là', 0.0
    sortie.parent.mkdir(parents=True, exist_ok=True)
    for source in images(instance_id):
        t0 = time.time()
        tmp = sortie.with_name(f'{sortie.name}.{os.getpid()}.partiel')
        r = subprocess.run(['apptainer', 'pull', '--force', str(tmp), source], capture_output=True, text=True, timeout=3600)
        if r.returncode == 0 and tmp.exists():
            tmp.replace(sortie)
            return sortie, source, time.time() - t0
        print(f"SWEBENCH_TIRAGE_ECHEC {instance_id} : {source} : {(r.stderr or r.stdout).strip()[-300:]}", flush=True)
        with contextlib.suppress(OSError):
            tmp.unlink()
    return None, '', 0.0


def script_lancement(constantes) -> str:
    """Dans le conteneur : correction du modèle (s'il y en a une), avec les mêmes essais que l'outil officiel, puis son
    script d'évaluation. Les marqueurs écrits sont ceux que lit sa correction."""
    essais = ' || '.join(f'{c} /sweb_io/patch.diff' for c in APPLIQUER)
    return ('#!/bin/bash\ncd /testbed || exit 1\n'
            'if [ -s /sweb_io/patch.diff ]; then\n'
            f'  if {essais}; then echo "{constantes.APPLY_PATCH_PASS}"; else echo "{constantes.APPLY_PATCH_FAIL}"; exit 1; fi\n'
            'fi\n'
            '/bin/bash /sweb_io/eval.sh\n')


def executer(sif: Path, test_spec, patch: str, mode: list[str], dossier: Path, delai: float = DELAI_S) -> tuple[str, float]:
    """Une évaluation dans le conteneur (calque temporaire en mémoire : l'image n'est jamais modifiée)."""
    from swebench.harness import constants as K
    io_dir = Path(tempfile.mkdtemp(prefix='sweb_io_', dir=dossier))
    try:
        (io_dir / 'patch.diff').write_text(patch or '', encoding='utf-8')
        (io_dir / 'eval.sh').write_text(test_spec.eval_script, encoding='utf-8')
        (io_dir / 'lancer.sh').write_text(script_lancement(K), encoding='utf-8')
        cmd = ['apptainer', 'exec', *mode, '--pwd', '/testbed', '--env', 'PYTHONDONTWRITEBYTECODE=1',
               '--bind', f'{io_dir}:/sweb_io', str(sif), '/bin/bash', '/sweb_io/lancer.sh']
        t0 = time.time()
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        try:
            sortie, _ = p.communicate(timeout=delai)
            texte = sortie.decode('utf-8', 'replace')
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                os.killpg(p.pid, signal.SIGKILL)
            try:  # un processus échappé du groupe peut garder la sortie ouverte : on n'attend pas plus d'une minute
                sortie, _ = p.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                sortie = b''
                with contextlib.suppress(OSError):
                    p.stdout.close()
            texte = sortie.decode('utf-8', 'replace') + f'\n{K.TESTS_TIMEOUT}\n'
        return texte, time.time() - t0
    finally:
        shutil.rmtree(io_dir, ignore_errors=True)


def patch_de_test_applique(journal: str, test_patch: str) -> bool:
    """Le script d'évaluation installe les tests du bug (git apply -v, ou patch) : chaque fichier doit être annoncé comme
    appliqué ; sinon (écriture refusée dans le conteneur) le verdict ne vaut rien."""
    return all(f'Applied patch {f} cleanly' in journal or f'patching file {f}' in journal for f in chemins_patch(test_patch))


def verdict(rep: dict, garde: bool) -> bool | None:
    """Correction d'un modèle refusée par git et patch : non résolu, comme l'outil officiel (le script s'arrête avant
    d'installer les tests du bug : la garde ne dit alors rien) ; appliquée mais tests du bug pas installés : pas de
    verdict (None, environnement) ; sinon le verdict de l'outil officiel."""
    if not rep.get('patch_successfully_applied'):
        return False
    return bool(rep.get('resolved')) if garde else None


def rapport(test_spec, instance_id: str, patch: str, journal: str, dossier: Path) -> dict:
    from swebench.harness.grading import get_eval_report
    chemin = dossier / f'{instance_id}.{os.getpid()}.{time.time_ns()}.log'
    chemin.write_text(journal, encoding='utf-8')
    try:
        r = get_eval_report(test_spec, {'instance_id': instance_id, 'model_name_or_path': 'essai', 'model_patch': patch},
                            str(chemin), True)
        return r[instance_id]
    finally:
        chemin.unlink()


def essai(travail: Path) -> int:
    import swebench
    make_test_spec = fonction_test_spec()
    print(f"SWEBENCH_OUTILS : swebench {getattr(swebench, '__version__', '?')} ; "
          f"{subprocess.run(['apptainer', '--version'], capture_output=True, text=True).stdout.strip()}", flush=True)
    instances = {r['instance_id']: r for r in charger(travail)}
    choix = next((i for i in PREFERES if i in instances), sorted(instances)[0])
    inst = instances[choix]
    spec = make_test_spec(inst)
    print(f"SWEBENCH_ESSAI_BUG : {choix} ({inst['repo']}, version {inst['version']}) ; tests à faire passer : "
          f"{len(json.loads(inst['FAIL_TO_PASS']) if isinstance(inst['FAIL_TO_PASS'], str) else inst['FAIL_TO_PASS'])}",
          flush=True)
    sif, source, s = tirer(travail, choix)
    if sif is None:
        print('SWEBENCH_ESSAI_BILAN=ECHEC : image impossible à tirer', flush=True)
        return 1
    print(f'SWEBENCH_IMAGE : {source} en {s:.0f} s, {sif.stat().st_size / 1e9:.2f} Go', flush=True)
    dossier = travail / 'tmp' / 'swebench'
    dossier.mkdir(parents=True, exist_ok=True)
    bons = []
    for nom, mode in MODES.items():
        resultats = {}
        for cas, patch in (('correction officielle', inst['patch']), ('sans correction', '')):
            journal, duree = executer(sif, spec, patch, mode, dossier)
            r = rapport(spec, choix, patch, journal, dossier)
            resultats[cas] = r
            fin = ' | '.join(journal.strip().splitlines()[-4:])[:400]
            print(f"SWEBENCH_ESSAI {nom} / {cas} : résolu {r.get('resolved')} ; correction appliquée "
                  f"{r.get('patch_successfully_applied')} ; {duree:.0f} s ; fin : {fin}", flush=True)
        if resultats['correction officielle'].get('resolved') and not resultats['sans correction'].get('resolved'):
            bons.append(nom)
    print(f"SWEBENCH_ESSAI_BILAN={'OK' if bons else 'ECHEC'} : façons de lancer qui marchent : {', '.join(bons) or 'aucune'}",
          flush=True)
    return 0 if bons else 1


def chemins_patch(patch: str) -> list[str]:
    """Fichiers touchés par une correction (en-têtes « diff --git a/X b/X »), dans l'ordre."""
    return list(dict.fromkeys(re.findall(r'^diff --git a/(\S+) b/\S+', patch or '', re.M)))


def choisir(instances: list[dict], nombre: int = SOUS_ENSEMBLE, graine: int = GRAINE) -> list[str]:
    """Bugs tirés au hasard (graine fixe), au prorata de chaque logiciel, au moins un par logiciel."""
    par_depot = {}
    for r in sorted(instances, key=lambda r: r['instance_id']):
        par_depot.setdefault(r['repo'], []).append(r['instance_id'])
    quotas = {d: max(1, round(nombre * len(ids) / len(instances))) for d, ids in par_depot.items()}
    while sum(quotas.values()) > nombre:
        quotas[max(quotas, key=lambda d: (quotas[d], d))] -= 1
    while sum(quotas.values()) < nombre:
        quotas[max(quotas, key=lambda d: (len(par_depot[d]) - quotas[d], d))] += 1
    hasard = random.Random(graine)
    return sorted(i for d in sorted(par_depot) for i in hasard.sample(par_depot[d], min(quotas[d], len(par_depot[d]))))


def lire_fichiers(sif: Path, chemins: list[str]) -> dict[str, str | None]:
    """Contenu des fichiers à la version du bug, lus dans l'image (/testbed) ; None pour un fichier que la correction crée."""
    out = {}
    for c in chemins:
        r = subprocess.run(['apptainer', 'exec', '--containall', str(sif), 'cat', f'/testbed/{c}'], capture_output=True,
                           timeout=600)
        out[c] = r.stdout.decode('utf-8', 'replace') if r.returncode == 0 else None
    return out


def preparer_images(travail: Path, nombre: int) -> int:
    instances = {r['instance_id']: r for r in charger(travail)}
    ids = choisir(list(instances.values()), nombre)
    dossier = travail / 'donnees' / 'swebench'
    (dossier / f'sous_ensemble_{nombre}.json').write_text(json.dumps(ids, indent=1) + '\n', encoding='utf-8')
    oracle = dossier / 'oracle'
    oracle.mkdir(parents=True, exist_ok=True)
    make_test_spec = fonction_test_spec()
    controle = dossier / 'controle_images.jsonl'
    deja = lire_jsonl(controle)
    tmp_eval = travail / 'tmp' / 'swebench'
    tmp_eval.mkdir(parents=True, exist_ok=True)
    ok, rates, octets, t0 = [], [], 0, time.time()
    for k, i in enumerate(ids, 1):
        sif, source, s = tirer(travail, i)
        if sif is None:
            rates.append(i)
            continue
        octets += sif.stat().st_size
        f = oracle / f'{i}.json'
        if not f.exists():
            f.write_text(json.dumps(lire_fichiers(sif, chemins_patch(instances[i]['patch'])), ensure_ascii=False) + '\n',
                         encoding='utf-8')
        if i not in deja:  # la correction officielle doit résoudre le bug, tests du bug bien installés
            spec = make_test_spec(instances[i])
            journal, duree = executer(sif, spec, instances[i]['patch'], MODES['simple'], tmp_eval)
            rep = rapport(spec, i, instances[i]['patch'], journal, tmp_eval)
            garde = patch_de_test_applique(journal, instances[i]['test_patch'])
            deja[i] = {'instance_id': i, 'valide': bool(rep.get('resolved')) and garde, 'resolu': bool(rep.get('resolved')),
                       'garde': garde, 'secondes_eval': round(duree), 'secondes_image': round(s), 'source': source}
            ajouter(controle, [deja[i]])
        ok.append(i)
        print(f"SWEBENCH_IMAGES_BUG {k}/{len(ids)} {i} : image {s:.0f} s, contrôle {deja[i]['secondes_eval']} s, "
              f"résolu par la correction officielle {deja[i]['resolu']}, tests du bug installés {deja[i]['garde']}", flush=True)
        if k % 10 == 0:
            print(f'SWEBENCH_IMAGES_PROGRES : {k}/{len(ids)} ({len(rates)} ratées, {octets / 1e9:.1f} Go, '
                  f'{time.time() - t0:.0f} s)', flush=True)
    depots = {}
    for i in ok:
        depots[instances[i]['repo']] = depots.get(instances[i]['repo'], 0) + 1
    valides = sum(bool(deja.get(i, {}).get('valide')) for i in ok)
    print(f"SWEBENCH_IMAGES_BILAN : {len(ok)}/{len(ids)} images, {valides} bugs contrôlés (résolus par leur correction "
          f"officielle, tests installés) ({octets / 1e9:.1f} Go d'images) ; "
          f"{' ; '.join(f'{d} {n}' for d, n in sorted(depots.items()))}"
          f"{' ; ratées : ' + ' '.join(rates[:10]) if rates else ''}", flush=True)
    return 0 if ok else 1


FORMAT_EDITION = ('Fix the issue by editing the code. Answer with one or more edits, each in this exact format:\n\n'
                  'path/to/file.py\n<<<<<<< SEARCH\n(lines copied exactly from the current file, enough to be unique)\n'
                  '=======\n(the new lines)\n>>>>>>> REPLACE\n\n'
                  'To create a new file, leave the SEARCH part empty. Do not modify the tests.')


def invite(inst: dict, fichiers: dict[str, str | None]) -> str:
    code = ''.join(f'[start of {c}]\n{v}' + ('' if v.endswith('\n') else '\n') + f'[end of {c}]\n'
                   for c, v in fichiers.items() if v is not None)
    nouveaux = [c for c, v in fichiers.items() if v is None]
    return ('You will be given an issue from a real software project and the current content of the files that need to '
            f"change.\n\n<issue>\n{inst['problem_statement'].strip()}\n</issue>\n\n<code>\n{code}</code>\n\n"
            + (f"These files do not exist yet and may be created: {', '.join(nouveaux)}\n\n" if nouveaux else '')
            + FORMAT_EDITION)


EDITION = re.compile(r'^<{5,9} SEARCH[ \t]*\n(.*?)^={5,9}[ \t]*\n(.*?)^>{5,9} REPLACE[ \t]*$', re.S | re.M)


def trouver_chemin(ligne: str, chemins: list[str]) -> str | None:
    mots = re.sub(r'[`*#"\'<>()\[\]]', ' ', ligne).replace(':', ' ').split()
    for c in sorted(chemins, key=len, reverse=True):
        if any(m == c or m.endswith('/' + c) or c.endswith('/' + m) and '/' in m for m in mots):
            return c
    noms = [c for c in chemins if any(Path(m).name == Path(c).name for m in mots)]
    return noms[0] if len(noms) == 1 else None


def lire_editions(texte: str, chemins: list[str]) -> list[tuple[str, str, str]]:
    """(fichier, ancien, nouveau) dans l'ordre de la réponse. Le fichier est sur l'une des trois lignes qui précèdent le
    bloc (clôtures de code et décorations retirées) ; sinon celui du bloc précédent ; sinon, s'il n'y en a qu'un, ce
    fichier."""
    out = []
    texte = texte or ''
    courant = chemins[0] if len(chemins) == 1 else None
    for m in EDITION.finditer(texte):
        for ligne in reversed(texte[:m.start()].rstrip().splitlines()[-3:]):
            trouve = trouver_chemin(ligne, chemins)
            if trouve:
                courant = trouve
                break
        if courant:
            out.append((courant, m.group(1), m.group(2)))
    return out


def appliquer(contenu: str | None, ancien: str, nouveau: str) -> str | None:
    """Remplace la première occurrence de l'ancien bloc ; à défaut, la même suite de lignes aux espaces de fin près ;
    fichier nouveau si l'ancien bloc est vide. None si le bloc est introuvable."""
    if contenu is None:
        return nouveau if not ancien.strip() else None
    if not ancien.strip():
        return contenu + ('' if contenu.endswith('\n') or not contenu else '\n') + nouveau
    if ancien in contenu:
        return contenu.replace(ancien, nouveau, 1)
    lignes = contenu.splitlines(keepends=True)
    cherche = [l.rstrip() for l in ancien.splitlines()]
    while cherche and not cherche[-1]:
        cherche.pop()
    n = len(cherche)
    for i in range(len(lignes) - n + 1):
        if [l.rstrip() for l in lignes[i:i + n]] == cherche:
            remplace = nouveau if nouveau.endswith('\n') or not nouveau else nouveau + '\n'
            return ''.join(lignes[:i]) + remplace + ''.join(lignes[i + n:])
    return None


def faire_patch(fichiers: dict[str, str | None], editions: list[tuple[str, str, str]]) -> tuple[str, int]:
    """Correction au format de git (git diff --no-index, fin de fichier sans saut de ligne comprise) ; renvoie (correction,
    nombre d'éditions introuvables)."""
    nouveaux = dict(fichiers)
    ratees = 0
    for c, ancien, nouveau in editions:
        r = appliquer(nouveaux.get(c), ancien, nouveau)
        if r is None:
            ratees += 1
        else:
            nouveaux[c] = r
    morceaux = []
    with tempfile.TemporaryDirectory() as d:
        for c, avant in fichiers.items():
            apres = nouveaux.get(c)
            if apres is None or apres == avant:
                continue
            if avant is None:  # fichier créé
                lignes = apres.splitlines(keepends=True)
                if lignes and not lignes[-1].endswith('\n'):
                    lignes[-1] += '\n'
                morceaux.append(f'diff --git a/{c} b/{c}\nnew file mode 100644\n'
                                + ''.join(difflib.unified_diff([], lignes, fromfile='/dev/null', tofile=f'b/{c}')))
                continue
            for cote, texte in (('a', avant), ('b', apres)):
                f = Path(d) / cote / c
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(texte.encode('utf-8'))
            r = subprocess.run(['git', '-c', 'core.autocrlf=false', 'diff', '--no-index', '--no-prefix', '--no-color',
                                f'a/{c}', f'b/{c}'], cwd=d, capture_output=True)
            morceaux.append(r.stdout.decode('utf-8'))
    return ''.join(morceaux), ratees


def lire_jsonl(chemin: Path) -> dict[str, dict]:
    """Lignes déjà écrites, par bug. Une dernière ligne coupée par l'arrêt brutal d'une tâche (pas de saut de ligne final)
    est retirée du fichier, comme dans pilote.py : sinon chaque relance échouerait en le lisant."""
    if not chemin.exists():
        return {}
    brut = chemin.read_bytes()
    if brut and not brut.endswith(b'\n'):
        garde = brut[:brut.rfind(b'\n') + 1]
        chemin.write_bytes(garde)
        print(f'PILOTE_REPARATION {chemin.name} : dernière ligne incomplète retirée ({len(brut) - len(garde)} octets)',
              flush=True)
        brut = garde
    return {r['instance_id']: r for r in (json.loads(l) for l in brut.decode('utf-8').splitlines() if l.strip())}


def ajouter(chemin: Path, lignes: list[dict]) -> None:
    with chemin.open('a', encoding='utf-8', newline='\n') as f:
        f.write(''.join(json.dumps(l, ensure_ascii=False) + '\n' for l in lignes))
        f.flush()
        os.fsync(f.fileno())


def evaluer(travail: Path, predictions: Path, processus: int, mode: str = 'simple') -> int:
    """Chaque correction dans le conteneur de son bug (calque temporaire), résultat lu par l'outil officiel. Une
    correction vide n'est pas lancée (non résolue). Résultats ajoutés au fil de l'eau : une relance reprend."""
    make_test_spec = fonction_test_spec()
    instances = {r['instance_id']: r for r in charger(travail)}
    preds = lire_jsonl(predictions)
    sortie = predictions.with_name(predictions.name.replace('.predictions.jsonl', '') + '.evaluation.jsonl')
    faits = lire_jsonl(sortie)
    a_faire = [p for i, p in preds.items() if i not in faits]
    dossier = travail / 'tmp' / 'swebench'
    dossier.mkdir(parents=True, exist_ok=True)
    verrou = threading.Lock()
    t0 = time.time()

    def un(p):
        i = p['instance_id']
        sif = travail / 'swebench' / 'images' / f'{i}.sif'
        if not (p.get('model_patch') or '').strip():
            r = {'instance_id': i, 'resolved': False, 'patch_successfully_applied': False, 'secondes': 0, 'note': 'vide'}
        elif not sif.exists():
            r = {'instance_id': i, 'resolved': None, 'note': 'image absente'}
        else:
            spec = make_test_spec(instances[i])
            journal, duree = executer(sif, spec, p['model_patch'], MODES[mode], dossier)
            rep = rapport(spec, i, p['model_patch'], journal, dossier)
            garde = patch_de_test_applique(journal, instances[i]['test_patch'])
            r = {'instance_id': i, 'resolved': verdict(rep, garde), 'garde': garde,
                 'patch_successfully_applied': bool(rep.get('patch_successfully_applied')), 'secondes': round(duree)}
        with verrou:
            ajouter(sortie, [r])
        return r

    with ThreadPoolExecutor(processus) as pool:
        list(pool.map(un, a_faire))
    faits = lire_jsonl(sortie)
    depots = {}
    for i, r in faits.items():
        d = depots.setdefault(instances[i]['repo'], [0, 0])
        d[0] += bool(r.get('resolved'))
        d[1] += 1
    resolus = sum(bool(r.get('resolved')) for r in faits.values())
    print(f"SWEBENCH_EVAL {predictions.name.replace('.predictions.jsonl', '')} : {resolus}/{len(faits)} bugs résolus "
          f"({100 * resolus / max(len(faits), 1):.1f} %) ; corrections appliquées "
          f"{sum(bool(r.get('patch_successfully_applied')) for r in faits.values())} ; sans verdict (environnement) "
          f"{sum(r.get('resolved') is None for r in faits.values())} ; "
          f"{' ; '.join(f'{d} {a}/{b}' for d, (a, b) in sorted(depots.items()))} ({time.time() - t0:.0f} s)", flush=True)
    return 0


class MoteurOracle:
    """Faux moteur pour les essais sur le PC : renvoie la correction officielle sous forme de blocs SEARCH/REPLACE pour
    un bug sur deux, rien pour les autres."""

    def __init__(self, travail: Path, cas: list[tuple[dict, dict]], tp: int):
        self.tp = tp
        self.par_invite = {invite(inst, fichiers): (k, inst, fichiers) for k, (inst, fichiers) in enumerate(cas)}

    def ouvert(self, chat_kwargs: dict) -> bool:
        return bool(chat_kwargs.get('enable_thinking'))

    def generer(self, messages: list, phase: dict) -> list[list[dict]]:
        sorties = []
        for conv in messages:
            k, inst, fichiers = self.par_invite[conv[0]['content']]
            texte = 'No change needed.'
            if k % 2 == 0:
                texte = ''.join(f"{c}\n```python\n<<<<<<< SEARCH\n{a}=======\n{n}>>>>>>> REPLACE\n```\n"
                                for c, a, n in inst.get('_editions_essai', []))
            texte = ('Je lis le rapport.</think>' if self.ouvert(phase.get('chat_kwargs') or {}) else '') + texte
            sorties.append([{'texte': texte, 'jetons': len(texte.split()), 'fin': 'stop'}])
        return sorties


def generer(args, moteur=None, debut: float | None = None, phases: list[dict] | None = None, evaluer_ici: bool = True) -> int:
    """moteur, debut, phases : passés par code_reel.py (un seul chargement pour les deux bancs) ; evaluer_ici False :
    les corrections sont lancées ensuite par une tâche sur processeur (swebench_eval.sbatch), pas pendant que les GPU
    attendent."""
    import pilote as P
    travail = Path(args.travail)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    role = config['roles'][args.role]
    instances = {r['instance_id']: r for r in charger(travail)}
    ids = json.loads((travail / 'donnees' / 'swebench' / f"sous_ensemble_{config.get('sous_ensemble', SOUS_ENSEMBLE)}.json")
                     .read_text(encoding='utf-8'))
    oracle = travail / 'donnees' / 'swebench' / 'oracle'
    controle = lire_jsonl(travail / 'donnees' / 'swebench' / 'controle_images.jsonl')
    if controle:
        ids = [i for i in ids if controle.get(i, {}).get('valide')]
    cas = []
    for i in ids:
        f = oracle / f'{i}.json'
        if f.exists():
            fichiers = json.loads(f.read_text(encoding='utf-8'))
            if len(invite(instances[i], fichiers)) <= LIMITE_INVITE:
                cas.append((instances[i], fichiers))
    dossier = travail / RESULTATS
    dossier.mkdir(parents=True, exist_ok=True)
    if phases is None:
        phases = [p for p in role['phases'] if p.get('banc', 'swebench') == 'swebench']
    phases = [p for p in phases if not (dossier / f"{p['nom']}.fini").exists()
              and (evaluer_ici or not (dossier / f"{p['nom']}.genere").exists())]
    print(f"PILOTE_SWEBENCH_DEBUT {args.role} : {len(cas)} bugs (sur {len(ids)}, invites trop longues ou fichiers absents "
          f"écartés) ; phases restantes : {', '.join(p['nom'] for p in phases) or 'aucune'}", flush=True)
    if not phases:
        return 0
    for cle, valeur in (role.get('env') or {}).items():  # avant l'import de vLLM
        os.environ[cle] = str(valeur)
    debut = time.time() if debut is None else debut
    limite_s = 60 * (args.limite_minutes if args.limite_minutes is not None else role['limite_minutes'])
    tp = role['vllm'].get('tensor_parallel_size', 1)
    if moteur is not None:
        pass
    elif args.simulation:
        moteur = MoteurOracle(travail, cas, tp)
    else:
        chemin = str(travail / role['modele'])
        essais = [{}] + ([role['repli']] if role.get('repli') else [])
        moteur, _ = P.charger(lambda o: P.MoteurVllm(chemin, {**role['vllm'], **o}, config.get('graine', 0)), essais,
                              60 * role.get('limite_chargement_minutes', 70), P.arreter_processus_enfants)
        if moteur is None:
            print('PILOTE_SWEBENCH_BILAN=ECHEC : moteur jamais prêt', flush=True)
            return 4
    processus = max(1, (int(os.environ.get('SLURM_CPUS_PER_TASK') or os.cpu_count() or 2) - 4) // 4)
    for p in phases:
        fichier = dossier / f"{p['nom']}.predictions.jsonl"
        faits = lire_jsonl(fichier)
        a_faire = [(inst, fichiers) for inst, fichiers in cas if inst['instance_id'] not in faits]
        ouvert = moteur.ouvert(p.get('chat_kwargs') or {}) if a_faire else False
        # par lots, écrits dès qu'ils sont finis (15/10) : une tâche arrêtée par sa limite ne perd qu'un lot. Durée prévue
        # d'un lot complet : celle de la phase au prorata, au moins la moitié (la réponse la plus longue fixe la fin d'un
        # lot) ; ensuite celle du lot précédent (le 11/10, un lot a pris 1,8 fois la durée prévue)
        taille = max(1, p.get('lot') or len(a_faire))
        duree_lot = 60 * p.get('duree_minutes', 0) * min(1.0, max(taille / max(len(cas), 1), 0.5))
        nombre = -(-len(a_faire) // taille)
        for k in range(nombre):
            paquet = a_faire[k * taille:(k + 1) * taille]
            prevu = max(duree_lot * len(paquet) / taille, 0.5 * duree_lot)
            if time.time() - debut + 1.3 * prevu > limite_s:
                print(f"PILOTE_SWEBENCH_ARRET {p['nom']} : plus le temps dans cette tâche ({len(paquet)} bugs, "
                      f"{prevu / 60:.0f} min prévues)", flush=True)
                return 3
            t0 = time.time()
            sorties = moteur.generer([[{'role': 'user', 'content': invite(inst, fichiers)}] for inst, fichiers in paquet], p)
            duree = time.time() - t0
            duree_lot = duree * taille / len(paquet)
            lignes = []
            for (inst, fichiers), ech in zip(paquet, sorties):
                e = ech[0]
                _, reponse = P.separer(e['texte'], ouvert)
                editions = lire_editions(reponse, list(fichiers))
                patch, ratees = faire_patch(fichiers, editions)
                lignes.append({'instance_id': inst['instance_id'], 'model_name_or_path': p['nom'], 'model_patch': patch,
                               'jetons': e['jetons'], 'fin': e['fin'], 'editions': len(editions), 'editions_ratees': ratees,
                               'reponse': reponse})
            ajouter(fichier, lignes)
            longues = sum(l['fin'] == 'invite_trop_longue' for l in lignes)
            print(f"PILOTE_SWEBENCH_GENERATION {p['nom']} : {len(lignes)} réponses, {sum(l['jetons'] for l in lignes) / 1e6:.2f} M "
                  f"jetons en {duree / 60:.1f} min ; sans correction {sum(not l['model_patch'] for l in lignes)} ; coupées "
                  f"{sum(l['fin'] == 'length' for l in lignes)} ; éditions introuvables {sum(l['editions_ratees'] for l in lignes)}"
                  + (f' ; invites trop longues {longues}' if longues else '') + (f' (lot {k + 1}/{nombre})' if nombre > 1 else ''),
                  flush=True)
        if not evaluer_ici:  # réponses toutes écrites : la tâche suivante ne recharge pas le modèle pour rien
            (dossier / f"{p['nom']}.genere").write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
            print(f"PILOTE_SWEBENCH_EVAL {p['nom']} : plus tard, sur processeur (swebench_eval.sbatch)", flush=True)
            continue
        if args.simulation:  # sur le PC : ni conteneur ni outil officiel
            print(f"PILOTE_SWEBENCH_EVAL {p['nom']} : sautée (simulation)", flush=True)
            continue
        # correction dans la même tâche, avec l'outil officiel (environnement nova-swebench, Python à part)
        python = travail / 'envs' / 'nova-swebench' / 'bin' / 'python'
        r = subprocess.run([str(python) if python.exists() else sys.executable, '-B', str(Path(__file__).resolve()), 'evaluer',
                            '--travail', str(travail), '--predictions', str(fichier), '--processus', str(processus),
                            '--mode', config.get('mode', 'simple')])
        if r.returncode == 0:
            (dossier / f"{p['nom']}.fini").write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
    if evaluer_ici:
        print('PILOTE_SWEBENCH_BILAN=FINI', flush=True)
    return 0


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('commande', choices=('preparer', 'essai', 'images', 'generer', 'evaluer'))
    a.add_argument('--travail', required=True)
    a.add_argument('--nombre', type=int, default=SOUS_ENSEMBLE)
    a.add_argument('--predictions')
    a.add_argument('--processus', type=int, default=2)
    a.add_argument('--mode', choices=sorted(MODES), default='simple')
    a.add_argument('--role', choices=('professeur', 'eleve'))
    a.add_argument('--config')
    a.add_argument('--limite-minutes', type=float)
    a.add_argument('--simulation', action='store_true')
    args = a.parse_args()
    travail = Path(args.travail)
    if args.commande == 'preparer':
        preparer(travail)
        return 0
    if args.commande == 'essai':
        return essai(travail)
    if args.commande == 'images':
        return preparer_images(travail, args.nombre)
    if args.commande == 'evaluer':
        return evaluer(travail, Path(args.predictions), args.processus, args.mode)
    return generer(args)


if __name__ == '__main__':
    sys.exit(main())
