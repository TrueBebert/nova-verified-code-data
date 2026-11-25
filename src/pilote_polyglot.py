"""Test « corriger du vrai code » de Nova 122B (préparation : oui de l'utilisateur du 12/10/2026, 0 heure GPU ; la
génération sur GPU attend un nouvel accord). Exercices d'Exercism en 6 langages (C++, Go, Java, JavaScript, Python, Rust),
ceux du banc « polyglot » d'Aider (Aider-AI/polyglot-benchmark, commit 7e0611e7, 225 exercices) : le modèle reçoit la
consigne et les fichiers à modifier, et rend les fichiers entiers ; les tests de l'exercice tranchent ; en cas d'échec, un
second essai avec la sortie des tests (deux essais, comme Aider). Le code écrit par un modèle ne tourne que sur le cluster,
jamais sur le PC de l'utilisateur. Sans conteneur (aucun n'est documenté sur Discoverer, DOC-028) : un dossier temporaire
par test, HOME à part, caches des outils dans le dossier de travail, 180 s au plus par test (comme Aider), puis tout le
groupe de processus est tué.

  preparer --travail T               télécharge l'archive du banc (commit fixé), l'extrait dans T/donnees/polyglot et écrit
                                     l'index des exercices (exercices.json).
  activation --avant A --apres B --sortie S
                                     variables posées par l'activation de l'environnement nova-polyglot (installation),
                                     rejouées pour chaque test : l'environnement n'est jamais activé dans une tâche GPU.
  valider --travail T                solutions de référence des exercices (.meta) passées aux tests : contrôle des outils,
                                     sans modèle ; resultats/polyglot/validation.json et une ligne par langage.
  generer --role R --config F --travail T
                                     (GPU) premier essai, tests, second essai des échecs avec la sortie des tests, tests ;
                                     resultats/polyglot/<phase>.essai1.jsonl et .essai2.jsonl, bilan par langage.
Exercices © Exercism (pistes sous licence MIT) : mesure interne seulement, jamais d'entraînement dessus.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

COMMIT = '7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f'
URL = f'https://github.com/Aider-AI/polyglot-benchmark/archive/{COMMIT}.tar.gz'
LANGUES = ('cpp', 'go', 'java', 'javascript', 'python', 'rust')
DELAI_TEST_S = 180
DELAI_PREMIER_S = 900  # premier test de chaque langage : téléchargements (Gradle et dépendances Maven, crates)
IGNORES = {'.meta', '.docs', '.approaches', '.articles'}
NON_MODIFIABLES = {'CMakeLists.txt', 'Cargo.toml'}  # comme Aider
RESULTATS = Path('resultats') / 'polyglot'
SUFFIXES = {'.py': 'python', '.js': 'javascript', '.go': 'go', '.rs': 'rust', '.java': 'java', '.cpp': 'cpp',
            '.h': 'cpp', '.hpp': 'cpp', '.cc': 'cpp'}
FORMAT = ('Return the complete new content of every file you change: write the file path alone on one line, then the whole '
          'file in a fenced code block. Do not change the tests.')
VALIDATION_VERSION = 3  # 13/10 : dossier au nom de l'exercice (C++), Cargo-example.toml (Rust) ; 14/10 : g++ du système (C++),
                        # classes d'aide des références Java ; le lanceur refait le contrôle quand ce numéro change
VERROU_JAVA = threading.BoundedSemaphore(2)  # Gradle : une JVM ou deux par test
GRADLE: Path | None = None  # cache de Gradle propre au rôle (gradle_du_role) ; sinon le cache commun T/cache/gradle


def dossier_banc(travail: Path) -> Path:
    return travail / 'donnees' / 'polyglot'


def preparer(travail: Path) -> list[dict]:
    dossier = dossier_banc(travail)
    dossier.mkdir(parents=True, exist_ok=True)
    racine = dossier / f'polyglot-benchmark-{COMMIT}'
    if not (racine / '.extrait').exists():
        archive = dossier / f'polyglot-{COMMIT[:8]}.tar.gz'
        if not archive.exists():
            tmp = archive.with_name(f'{archive.name}.{os.getpid()}.partiel')
            with urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'nova-polyglot/1.0'}),
                                        timeout=600) as r, open(tmp, 'wb') as f:
                shutil.copyfileobj(r, f, 1 << 22)
            tmp.replace(archive)
        with tarfile.open(archive) as t:
            t.extractall(dossier, filter='data')  # pas de chemin hors du dossier
        (racine / '.extrait').write_text(COMMIT + '\n', encoding='utf-8')
    exercices = []
    for langue in LANGUES:
        pratique = racine / langue / 'exercises' / 'practice'
        for d in sorted(pratique.iterdir()) if pratique.exists() else []:
            if not d.is_dir() or not (d / '.meta' / 'config.json').exists():
                continue
            fichiers = json.loads((d / '.meta' / 'config.json').read_text(encoding='utf-8')).get('files', {})
            consigne = '\n\n'.join((d / '.docs' / n).read_text(encoding='utf-8').strip()
                                   for n in ('introduction.md', 'instructions.md', 'instructions.append.md')
                                   if (d / '.docs' / n).exists())
            exercices.append({'id': f'{langue}/{d.name}', 'langue': langue, 'nom': d.name,
                              'dossier': d.relative_to(travail).as_posix(), 'solution': fichiers.get('solution', []),
                              'test': fichiers.get('test', []), 'exemple': fichiers.get('example', []), 'consigne': consigne})
    (dossier / 'exercices.json').write_text(json.dumps(exercices, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    compte = ' ; '.join(f"{l} {sum(e['langue'] == l for e in exercices)}" for l in LANGUES)
    print(f'POLYGLOT_PREPARE : {len(exercices)} exercices ({compte})', flush=True)
    return exercices


def charger_index(travail: Path) -> list[dict]:
    return json.loads((dossier_banc(travail) / 'exercices.json').read_text(encoding='utf-8'))


def exercices_valides(travail: Path) -> list[dict]:
    """Exercices dont la solution de référence passe les tests sur le cluster (contrôle « valider ») : un exercice que
    même sa référence rate ne peut rien dire d'un modèle (14/10 : cpp/parallel-letter-frequency, TBB de conda-forge)."""
    exercices = charger_index(travail)
    f = travail / RESULTATS / 'validation.json'
    if not f.exists():
        return exercices
    details = json.loads(f.read_text(encoding='utf-8')).get('details', {})
    return [ex for ex in exercices if details.get(ex['id'], {}).get('reussi') is True]


def modifiables(ex: dict) -> list[str]:
    """Fichiers que le modèle peut changer : ceux de la solution, sauf CMakeLists.txt, Cargo.toml, tests et références."""
    exclus = set(ex['test']) | set(ex['exemple'])
    return [s for s in ex['solution'] if Path(s).name not in NON_MODIFIABLES and s not in exclus
            and not s.startswith(('.meta/', '.docs/'))]


def activation(avant: Path, apres: Path, sortie: Path) -> None:
    a = json.loads(avant.read_text(encoding='utf-8'))
    b = json.loads(apres.read_text(encoding='utf-8'))
    variables = {k: v for k, v in b.items() if k not in ('PATH', 'PWD', 'OLDPWD', 'SHLVL', '_') and a.get(k) != v}
    anciens = set(a.get('PATH', '').split(':'))
    chemins = [p for p in b.get('PATH', '').split(':') if p and p not in anciens]
    sortie.write_text(json.dumps({'variables': variables, 'chemins': chemins}, ensure_ascii=False, indent=1) + '\n',
                      encoding='utf-8')
    print(f"POLYGLOT_ACTIVATION : {len(variables)} variables ({', '.join(sorted(variables))[:400]}), "
          f"chemins ajoutés : {' '.join(chemins)}", flush=True)


def environnement(travail: Path, maison: Path) -> dict:
    """Variables d'un test : outils de nova-polyglot (variables d'activation enregistrées), caches dans T/cache, HOME
    dans le dossier temporaire du test."""
    p = travail / 'envs' / 'nova-polyglot'
    env = dict(os.environ)
    for cle in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONPATH', 'PYTHONHOME'):  # réglages de vLLM et DeepGEMM : pas pour
        env.pop(cle, None)                                                      # les outils de nova-polyglot
    act = p / '.activation.json'
    if act.exists():
        a = json.loads(act.read_text(encoding='utf-8'))
        env.update(a.get('variables', {}))
        env['PATH'] = os.pathsep.join(a.get('chemins', []) + [env.get('PATH', '')])
    elif (p / 'bin').exists():
        env['PATH'] = os.pathsep.join([str(p / 'bin'), env.get('PATH', '')])
    cache = travail / 'cache'
    env.update({'HOME': str(maison), 'CARGO_HOME': str(cache / 'cargo'), 'GOPATH': str(cache / 'go'),
                'GOCACHE': str(cache / 'go-build'), 'GOMODCACHE': str(cache / 'go' / 'mod'), 'GOTOOLCHAIN': 'local',
                'GRADLE_USER_HOME': str(GRADLE or cache / 'gradle'), 'npm_config_cache': str(cache / 'npm'),
                'CMAKE_PREFIX_PATH': str(p), 'CI': 'true', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'})
    return env


def commande(langue: str) -> list[str]:
    if langue == 'python':
        if os.environ.get('POLYGLOT_TEST_UNITTEST'):  # essais sur le PC, sans pytest (faux exercices écrits à la main)
            return [sys.executable, '-m', 'unittest', 'discover', '-s', '.', '-p', '*_test.py']
        return ['python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider']
    return {'rust': ['cargo', 'test', '--', '--include-ignored'],
            'go': ['go', 'test', './...'],
            'javascript': ['npm', 'run', 'test'],
            # compilateur du système (comme l'image d'Aider) : le g++ de conda-forge, sans racine système, échouait à
            # l'édition des liens (14/10 : 0/26) ; CMake et Boost restent ceux de nova-polyglot
            'cpp': ['bash', '-c', 'export CC=$(command -v /usr/bin/gcc || command -v gcc) CXX=$(command -v /usr/bin/g++ || command -v g++); '
                                  'mkdir -p build && cd build && cmake -DEXERCISM_RUN_ALL_TESTS=1 -G "Unix Makefiles" .. && make'],
            'java': ['bash', './gradlew', 'test', '--no-daemon', '--console=plain']}[langue]


def preparer_dossier(travail: Path, ex: dict, fichiers: dict[str, str], racine_tmp: Path) -> Path:
    """Copie de l'exercice (sans .meta ni .docs), fichiers du modèle ou de référence, tests d'origine remis, tests
    désactivés réactivés (Java @Disabled, JavaScript xtest), paquets npm communs."""
    src = travail / ex['dossier']
    racine_tmp.mkdir(parents=True, exist_ok=True)
    # dossier au nom exact de l'exercice : le CMakeLists.txt des exercices C++ en tire le nom des fichiers (13/10 : 0/26)
    d = Path(tempfile.mkdtemp(prefix=f"{ex['langue']}-", dir=racine_tmp)) / ex['nom']
    d.mkdir()
    for e in src.iterdir():
        if e.name not in IGNORES:
            (shutil.copytree if e.is_dir() else shutil.copy2)(e, d / e.name)
    for nom, contenu in fichiers.items():
        cible = d / nom
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(contenu, encoding='utf-8')
    for t in ex['test']:
        if (src / t).is_file():
            (d / t).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / t, d / t)
    if ex['langue'] == 'java':
        for t in ex['test']:
            f = d / t
            if f.is_file():
                f.write_text(re.sub(r'@Disabled(\([^)]*\))?\s*\n', '', f.read_text(encoding='utf-8')), encoding='utf-8')
        if (d / 'gradlew').exists():
            os.chmod(d / 'gradlew', 0o755)
    if ex['langue'] == 'javascript':
        for f in d.glob('*.spec.js'):
            f.write_text(f.read_text(encoding='utf-8').replace('xtest(', 'test('), encoding='utf-8')
        modules = travail / 'polyglot' / 'npm' / 'node_modules'
        if modules.exists() and not (d / 'node_modules').exists():
            os.symlink(modules, d / 'node_modules', target_is_directory=True)
    return d


def lancer(cmd: list[str], dossier: Path, env: dict, delai: float) -> tuple[bool, str, float]:
    """Commande de test dans son propre groupe de processus (tué ensuite, avec ce qu'il a lancé) ; sous Linux, temps de
    calcul et taille des fichiers bornés (pas la mémoire : la JVM et Go réservent beaucoup d'adresses)."""
    if os.name == 'posix':
        cmd = ['bash', '-c', 'ulimit -t 900 -f 4000000 2>/dev/null; exec "$@"', 'test', *cmd]
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, cwd=dossier, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return False, f'commande impossible : {e}', 0.0
    expire = False
    try:
        sortie, _ = p.communicate(timeout=delai)
    except subprocess.TimeoutExpired:
        expire = True
        tuer(p)
        try:  # un processus détaché (démon de Gradle) peut garder la sortie ouverte : on n'attend pas plus de 30 s
            sortie, _ = p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            sortie = b''
            with contextlib.suppress(OSError):
                p.stdout.close()
    finally:
        tuer(p)
    texte = (sortie or b'').decode('utf-8', 'replace') + ('\nTests timed out!' if expire else '')
    return p.returncode == 0 and not expire, texte, time.time() - t0


def tuer(p) -> None:
    if os.name == 'posix':
        with contextlib.suppress(OSError):
            os.killpg(p.pid, signal.SIGKILL)
    elif p.poll() is None:
        p.kill()


def nettoyer(sortie: str, dossier: Path, nom: str) -> str:
    return re.sub(r'\bin \d+\.\d+s\b', '', sortie.replace(str(dossier), nom))


def tronquer(texte: str, n: int) -> str:
    if len(texte) <= n:
        return texte
    tete = n // 4
    return texte[:tete] + '\n[...]\n' + texte[-(n - tete):]


def tester(travail: Path, ex: dict, fichiers: dict[str, str], racine_tmp: Path, delai: float = DELAI_TEST_S) -> dict:
    d = preparer_dossier(travail, ex, fichiers, racine_tmp)
    try:
        maison = d / '.maison'
        maison.mkdir()
        verrou = VERROU_JAVA if ex['langue'] == 'java' else contextlib.nullcontext()
        with verrou:
            ok, sortie, s = lancer(commande(ex['langue']), d, environnement(travail, maison), delai)
        return {'reussi': ok, 'sortie': tronquer(nettoyer(sortie, d, ex['nom']), 20000), 'secondes': round(s, 1)}
    finally:
        shutil.rmtree(d.parent, ignore_errors=True)


def gradle_du_role(travail: Path, role: str) -> None:
    """15/10 : l'élève et le professeur peuvent tester du Java en même temps, sur deux nœuds ; les verrous de Gradle ne
    protègent pas un cache partagé d'un nœud à l'autre. Chaque rôle a donc son cache, rempli une fois par le test d'une
    solution de référence (téléchargement de Gradle et de JUnit, délai long, comme le contrôle) ; si ce test échoue, le
    cache commun, contrôlé à l'installation, reste employé. Lancé pendant le chargement du modèle (code_reel.py)."""
    global GRADLE
    propre = travail / 'cache' / f'gradle-{role}'
    if (propre / '.pret').exists():
        GRADLE = propre
        print(f'POLYGLOT_GRADLE {role} : cache propre au rôle ({propre.name})', flush=True)
        return
    java = [ex for ex in exercices_valides(travail) if ex['langue'] == 'java' and correspondance(ex)]
    if not java:
        return
    ex = java[0]
    src = travail / ex['dossier']
    try:
        fichiers = {s: (src / e).read_text(encoding='utf-8') for e, s in correspondance(ex).items()}
        propre.mkdir(parents=True, exist_ok=True)
        GRADLE = propre
        v = tester(travail, ex, fichiers, travail / 'tmp' / 'polyglot' / f'gradle-{role}-{os.getpid()}', DELAI_PREMIER_S)
    except Exception as e:
        v = {'reussi': False, 'sortie': f'{type(e).__name__}: {e}', 'secondes': 0}
    if v['reussi']:
        (propre / '.pret').write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
        print(f"POLYGLOT_GRADLE {role} : cache propre au rôle rempli ({ex['id']}, référence réussie en {v['secondes']} s)",
              flush=True)
    else:
        GRADLE = None
        print(f"POLYGLOT_GRADLE {role} : cache propre pas rempli, cache commun employé ({tronquer(v['sortie'], 300)!r})",
              flush=True)


def correspondance(ex: dict) -> dict[str, str] | None:
    """Fichier de référence (.meta) -> fichier de solution : même nom ; en Java, une classe d'aide de la référence va à
    côté de la solution sous son propre nom (14/10 : Frame.java avait écrasé BowlingGame.java) ; sinon le seul fichier de
    même extension (example.rs -> src/lib.rs, proof.ci.js -> bowling.js)."""
    cibles = modifiables(ex)
    out = {}
    for e in ex['exemple']:
        nom, ext = Path(e).name, Path(e).suffix
        meme_nom = [s for s in cibles if Path(s).name == nom]
        meme_ext = [s for s in cibles if Path(s).suffix == ext]
        if len(meme_nom) == 1:
            out[e] = meme_nom[0]
        elif ex['langue'] == 'java' and cibles:
            out[e] = (Path(cibles[0]).parent / nom).as_posix()
        elif len(meme_ext) == 1 and sum(Path(x).suffix == ext for x in ex['exemple']) == 1:
            out[e] = meme_ext[0]
        else:
            return None
    return out or None


def valider(travail: Path, processus: int) -> int:
    exercices = charger_index(travail)
    racine_tmp = travail / 'tmp' / 'polyglot' / f'validation-{os.getpid()}'

    def un(ex, delai):
        m = correspondance(ex)
        if m is None:
            return ex, {'reussi': None, 'sortie': 'pas de correspondance entre la référence et la solution', 'secondes': 0}
        src = travail / ex['dossier']
        fichiers = {s: (src / e).read_text(encoding='utf-8') for e, s in m.items()}
        if (src / '.meta' / 'Cargo-example.toml').exists():  # référence Rust qui emploie des bibliothèques (crates)
            fichiers['Cargo.toml'] = (src / '.meta' / 'Cargo-example.toml').read_text(encoding='utf-8')
        return ex, tester(travail, ex, fichiers, racine_tmp, delai)

    premiers = {}
    for ex in exercices:
        premiers.setdefault(ex['langue'], ex)
    t0 = time.time()
    resultats = [un(ex, DELAI_PREMIER_S) for ex in premiers.values()]  # seuls : caches des outils remplis une fois
    with ThreadPoolExecutor(processus) as pool:
        resultats += list(pool.map(lambda ex: un(ex, DELAI_TEST_S), [e for e in exercices if e not in premiers.values()]))
    bilan = {}
    for langue in LANGUES:
        r = [(ex, v) for ex, v in resultats if ex['langue'] == langue]
        echecs = [ex['id'] for ex, v in r if v['reussi'] is False]
        bilan[langue] = {'exercices': len(r), 'reussis': sum(v['reussi'] is True for _, v in r), 'echecs': echecs,
                         'sans_correspondance': [ex['id'] for ex, v in r if v['reussi'] is None]}
        b = bilan[langue]
        texte_echecs = f" ; échecs : {len(echecs)} ({' '.join(echecs[:8])})" if echecs else ''
        texte_sans = f" ; sans correspondance : {len(b['sans_correspondance'])}" if b['sans_correspondance'] else ''
        print(f"POLYGLOT_VALIDATION {langue} : {b['reussis']}/{b['exercices']} solutions de référence passent leurs tests"
              f"{texte_echecs}{texte_sans}", flush=True)
        for ex, v in r:
            if v['reussi'] is False:  # premier échec de chaque langage : la fin de la sortie, pour comprendre
                lignes = v['sortie'].strip().splitlines()
                utiles = [l for l in lignes if re.search(r'undefined reference|cannot find|ld:|error|FAILED|Exception|expected|'
                                                         r'not found', l, re.I)][:6]
                print(f"POLYGLOT_VALIDATION_DETAIL {ex['id']} : {' | '.join(utiles or lignes[-6:])[:700]}", flush=True)
                break
    sortie = travail / RESULTATS
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / 'validation.json').write_text(json.dumps({'validation_version': VALIDATION_VERSION, 'commit': COMMIT, 'secondes': round(time.time() - t0), 'bilan': bilan,
                                                        'details': {ex['id']: v for ex, v in resultats}},
                                                       ensure_ascii=False) + '\n', encoding='utf-8')
    total = sum(b['reussis'] for b in bilan.values())
    print(f'POLYGLOT_VALIDATION_BILAN : {total}/{len(exercices)} en {time.time() - t0:.0f} s', flush=True)
    return 0


def invite(ex: dict, travail: Path) -> str:
    src = travail / ex['dossier']
    liste = modifiables(ex)
    parties = [ex['consigne'].strip(), '', '####', '', f"Use the above instructions to modify the supplied files: {' '.join(liste)}",
               "Don't change the names of existing functions or classes, as they may be referenced from other code like "
               "unit tests.", "Only use standard libraries, don't suggest installing any packages.", '']
    for s in liste:
        contenu = (src / s).read_text(encoding='utf-8') if (src / s).is_file() else ''
        parties += [s, f"```{SUFFIXES.get(Path(s).suffix, '')}", contenu.rstrip('\n'), '```', '']
    parties.append(FORMAT)
    return '\n'.join(parties)


def invite_correction(ex: dict, sortie_tests: str) -> str:
    return '\n'.join([tronquer(sortie_tests, 6000), '', '####', '', 'See the testing errors above.',
                      "The tests are correct, don't try and change them.",
                      f"Fix the code in {' '.join(modifiables(ex))} to resolve the errors.", FORMAT])


BLOC = re.compile(r'^```[^\n]*\n(.*?)^```[ \t]*$', re.S | re.M)


def trouver(ligne: str, cibles: list[str]) -> str | None:
    mots = re.sub(r'[`*#"\'<>()\[\]]', ' ', ligne).replace(':', ' ').split()
    for s in sorted(cibles, key=len, reverse=True):
        if any(m == s or m.endswith('/' + s) for m in mots):
            return s
    for s in cibles:
        if any(Path(m).name == Path(s).name for m in mots):
            return s
    return None


def extraire_fichiers(texte: str, cibles: list[str]) -> dict[str, str]:
    """Blocs de code de la réponse -> fichiers. Le chemin est sur la ligne qui précède le bloc (décorations Markdown
    retirées) ou dans l'en-tête du bloc ; un seul fichier à modifier et aucun chemin reconnu : le dernier bloc."""
    texte = texte or ''
    out, blocs = {}, []
    for m in BLOC.finditer(texte):
        avant = texte[:m.start()].rstrip().splitlines()
        entete = texte[m.start():texte.find('\n', m.start())]
        blocs.append(((avant[-1] if avant else ''), entete, m.group(1)))
    for ligne, entete, contenu in blocs:
        cible = trouver(ligne, cibles) or trouver(entete.lstrip('`'), cibles)
        if cible:
            out[cible] = contenu
    if not out and len(cibles) == 1 and blocs:
        out[cibles[0]] = blocs[-1][2]
    return out


def lire_jsonl(chemin: Path) -> dict[str, dict]:
    """Lignes déjà écrites, par exercice. Une dernière ligne coupée par l'arrêt brutal d'une tâche (pas de saut de ligne
    final) est retirée du fichier, comme dans pilote.py : sinon chaque relance échouerait en le lisant."""
    if not chemin.exists():
        return {}
    brut = chemin.read_bytes()
    if brut and not brut.endswith(b'\n'):
        garde = brut[:brut.rfind(b'\n') + 1]
        chemin.write_bytes(garde)
        print(f'PILOTE_REPARATION {chemin.name} : dernière ligne incomplète retirée ({len(brut) - len(garde)} octets)',
              flush=True)
        brut = garde
    return {r['id']: r for r in (json.loads(l) for l in brut.decode('utf-8').splitlines() if l.strip())}


def ajouter(chemin: Path, lignes: list[dict]) -> None:
    with chemin.open('a', encoding='utf-8', newline='\n') as f:
        f.write(''.join(json.dumps(l, ensure_ascii=False) + '\n' for l in lignes))
        f.flush()
        os.fsync(f.fileno())


def essai(moteur, phase: dict, exercices: list[dict], conversations: list[list[dict]], base: dict[str, dict],
          travail: Path, racine_tmp: Path, processus: int, ouvert: bool, numero: int) -> tuple[list[dict], float]:
    """Une génération pour tous ces exercices, puis leurs tests en parallèle. base : fichiers de l'essai précédent."""
    import pilote as P
    t0 = time.time()
    sorties = moteur.generer(conversations, phase)
    duree = time.time() - t0
    lignes = []
    for ex, ech in zip(exercices, sorties):
        e = ech[0]
        raisonnement, reponse = P.separer(e['texte'], ouvert)
        nouveaux = extraire_fichiers(reponse, modifiables(ex))
        lignes.append({'id': ex['id'], 'langue': ex['langue'], 'phase': phase['nom'], 'essai': numero, 'reponse': reponse,
                       'raisonnement_caracteres': len(raisonnement or ''), 'jetons': e['jetons'], 'fin': e['fin'],
                       'fichiers_rendus': sorted(nouveaux), 'contenus': {**base.get(ex['id'], {}), **nouveaux}})
    with ThreadPoolExecutor(processus) as pool:
        verdicts = list(pool.map(lambda x: tester(travail, x[0], x[1]['contenus'], racine_tmp), zip(exercices, lignes)))
    for l, v in zip(lignes, verdicts):
        l.update(reussi=v['reussi'], sortie=v['sortie'], secondes_test=v['secondes'])
    return lignes, duree


def bilan_phase(exercices: list[dict], e1: dict, e2: dict) -> dict:
    par = {}
    for langue in LANGUES + ('TOTAL',):
        ids = [ex['id'] for ex in exercices if langue in ('TOTAL', ex['langue'])]
        un = sum(bool(e1.get(i, {}).get('reussi')) for i in ids)
        deux = sum(bool(e1.get(i, {}).get('reussi')) or bool(e2.get(i, {}).get('reussi')) for i in ids)
        par[langue] = {'exercices': len(ids), 'reussis_essai1': un, 'reussis_2_essais': deux,
                       'sans_fichier_essai1': sum(not e1.get(i, {}).get('fichiers_rendus') for i in ids),
                       'coupes_essai1': sum(e1.get(i, {}).get('fin') == 'length' for i in ids)}
    return par


def executer_phase(moteur, phase: dict, exercices: list[dict], dossier: Path, travail: Path, debut: float,
                   limite_s: float, processus: int) -> str:
    nom = phase['nom']
    f1, f2 = dossier / f'{nom}.essai1.jsonl', dossier / f'{nom}.essai2.jsonl'
    racine_tmp = travail / 'tmp' / 'polyglot' / f'{nom}-{os.getpid()}'
    ouvert = moteur.ouvert(phase.get('chat_kwargs') or {})
    # par lots, écrits (réponses et tests) dès qu'ils sont finis (15/10) : une tâche arrêtée par sa limite ne perd qu'un
    # lot. Durée prévue d'un lot complet : celle d'un premier essai au prorata, au moins la moitié (la réponse la plus
    # longue fixe la fin d'un lot) ; ensuite celle du lot précédent (le 11/10, un lot a pris 1,8 fois la durée prévue)
    taille = max(1, phase.get('lot') or len(exercices))
    duree_lot = 60.0 * phase.get('duree_essai_minutes', 0) * min(1.0, max(taille / max(len(exercices), 1), 0.5))
    for numero, fichier in ((1, f1), (2, f2)):
        e1, faits = lire_jsonl(f1), lire_jsonl(fichier)
        a_faire = [ex for ex in exercices if ex['id'] not in faits and (numero == 1 or not e1[ex['id']]['reussi'])]
        nombre = -(-len(a_faire) // taille)
        for k in range(nombre):
            paquet = a_faire[k * taille:(k + 1) * taille]
            prevu = max(duree_lot * len(paquet) / taille, 0.5 * duree_lot)
            if time.time() - debut + 1.3 * prevu > limite_s:
                print(f"PILOTE_POLYGLOT_ARRET {nom} : plus le temps pour le {'premier' if numero == 1 else 'second'} essai "
                      f"({len(paquet)} exercices, {prevu / 60:.0f} min prévues)", flush=True)
                return 'arretee'
            if numero == 1:
                conv, base = [[{'role': 'user', 'content': invite(ex, travail)}] for ex in paquet], {}
            else:
                conv = [[{'role': 'user', 'content': invite(ex, travail)},
                         {'role': 'assistant', 'content': e1[ex['id']]['reponse'] or '(no answer)'},
                         {'role': 'user', 'content': invite_correction(ex, e1[ex['id']]['sortie'])}] for ex in paquet]
                base = {ex['id']: e1[ex['id']]['contenus'] for ex in paquet}
            lignes, duree = essai(moteur, phase, paquet, conv, base, travail, racine_tmp, processus, ouvert, numero)
            ajouter(fichier, lignes)
            duree_lot = duree * taille / len(paquet)
            longues = sum(l['fin'] == 'invite_trop_longue' for l in lignes)
            fin = ((f' ; invites trop longues {longues}' if longues else '')
                   + (f' (lot {k + 1}/{nombre})' if nombre > 1 else ''))
            if numero == 1:
                print(f"PILOTE_POLYGLOT_ESSAI {nom} 1 : {sum(l['reussi'] for l in lignes)}/{len(lignes)} réussis ; "
                      f"{sum(l['jetons'] for l in lignes) / 1e6:.2f} M jetons en {duree / 60:.1f} min ; coupés "
                      f"{sum(l['fin'] == 'length' for l in lignes)} ; sans fichier reconnu "
                      f"{sum(not l['fichiers_rendus'] for l in lignes)}{fin}", flush=True)
            else:
                print(f"PILOTE_POLYGLOT_ESSAI {nom} 2 : {sum(l['reussi'] for l in lignes)}/{len(lignes)} corrigés ; "
                      f"{sum(l['jetons'] for l in lignes) / 1e6:.2f} M jetons en {duree / 60:.1f} min{fin}", flush=True)
    e1, e2 = lire_jsonl(f1), lire_jsonl(f2)
    bilan = bilan_phase(exercices, e1, e2)
    (dossier / f'{nom}.bilan.json').write_text(json.dumps(bilan, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (dossier / f'{nom}.fini').write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
    t = bilan['TOTAL']
    detail = ' ; '.join(f"{l} {bilan[l]['reussis_2_essais']}/{bilan[l]['exercices']}" for l in LANGUES if bilan[l]['exercices'])
    print(f"PILOTE_POLYGLOT {nom} : {t['reussis_essai1']}/{t['exercices']} au premier essai "
          f"({100 * t['reussis_essai1'] / max(t['exercices'], 1):.1f} %), {t['reussis_2_essais']}/{t['exercices']} en deux "
          f"essais ({100 * t['reussis_2_essais'] / max(t['exercices'], 1):.1f} %) ; {detail}", flush=True)
    shutil.rmtree(racine_tmp, ignore_errors=True)
    return 'finie'


class MoteurReference:
    """Faux moteur pour les essais sur le PC : au premier essai, la solution de référence pour un exercice sur deux et
    une réponse sans code pour les autres ; au second essai, toujours la référence."""

    def __init__(self, travail: Path, exercices: list[dict], tp: int):
        self.tp = tp
        self.travail = travail
        self.par_invite = {invite(ex, travail): (i, ex) for i, ex in enumerate(exercices)}

    def ouvert(self, chat_kwargs: dict) -> bool:
        return bool(chat_kwargs.get('enable_thinking'))

    def generer(self, messages: list, phase: dict) -> list[list[dict]]:
        raisonne = self.ouvert(phase.get('chat_kwargs') or {})
        sorties = []
        for conv in messages:
            i, ex = self.par_invite[conv[0]['content']]
            if len(conv) > 1 or i % 2 == 0:
                src = self.travail / ex['dossier']
                texte = '\n'.join(f"Here is the file.\n\n**{s}**\n```{SUFFIXES.get(Path(s).suffix, '')}\n"
                                  f"{(src / e).read_text(encoding='utf-8')}```\n" for e, s in correspondance(ex).items())
            else:
                texte = 'The code looks correct already.'
            texte = ('Je relis la consigne.</think>' if raisonne else '') + texte
            sorties.append([{'texte': texte, 'jetons': len(texte.split()), 'fin': 'stop'}])
        return sorties


def generer(args, moteur=None, debut: float | None = None, phases: list[dict] | None = None, seul: bool = True) -> int:
    """moteur, debut, phases : passés par code_reel.py (un seul chargement pour les deux bancs, seul=False : le bilan
    de la tâche est le sien)."""
    import pilote as P
    travail = Path(args.travail)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    role = config['roles'][args.role]
    dossier = travail / RESULTATS
    dossier.mkdir(parents=True, exist_ok=True)
    exercices = exercices_valides(travail)
    if phases is None:
        phases = [p for p in role['phases'] if p.get('banc', 'polyglot') == 'polyglot']
    phases = [p for p in phases if not (dossier / f"{p['nom']}.fini").exists()]
    print(f"PILOTE_POLYGLOT_DEBUT {args.role} : modèle {role['modele']} ; {len(exercices)} exercices ; phases restantes : "
          f"{', '.join(p['nom'] for p in phases) or 'aucune'}", flush=True)
    if not phases:
        if seul:
            print('PILOTE_POLYGLOT_BILAN=FINI', flush=True)
        return 0
    for cle, valeur in (role.get('env') or {}).items():  # avant l'import de vLLM
        os.environ[cle] = str(valeur)
    debut = time.time() if debut is None else debut
    limite_s = 60 * (args.limite_minutes if args.limite_minutes is not None else role['limite_minutes'])
    processus = max(2, int(os.environ.get('SLURM_CPUS_PER_TASK') or os.cpu_count() or 2) - 4)
    global VERROU_JAVA
    VERROU_JAVA = threading.BoundedSemaphore(max(1, min(6, processus // 4)))
    tp = role['vllm'].get('tensor_parallel_size', 1)
    if moteur is not None:
        pass
    elif args.simulation:
        moteur = MoteurReference(travail, exercices, tp)
    else:
        chemin = str(travail / role['modele'])
        essais = [{}] + ([role['repli']] if role.get('repli') else [])
        moteur, _ = P.charger(lambda o: P.MoteurVllm(chemin, {**role['vllm'], **o}, config.get('graine', 0)), essais,
                              60 * role.get('limite_chargement_minutes', 70), P.arreter_processus_enfants)
        if moteur is None:
            print('PILOTE_POLYGLOT_BILAN=ECHEC : moteur jamais prêt', flush=True)
            return 4
    for p in phases:
        if executer_phase(moteur, p, exercices, dossier, travail, debut, limite_s, processus) == 'arretee':
            if seul:
                print('PILOTE_POLYGLOT_BILAN=A_REPRENDRE', flush=True)
            return 3
    if seul:
        print('PILOTE_POLYGLOT_BILAN=FINI', flush=True)
    return 0


def main():
    global VERROU_JAVA
    sys.stdout.reconfigure(encoding='utf-8')
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('commande', choices=('preparer', 'activation', 'valider', 'generer'))
    a.add_argument('--travail')
    a.add_argument('--processus', type=int, default=2)
    a.add_argument('--avant')
    a.add_argument('--apres')
    a.add_argument('--sortie')
    a.add_argument('--role', choices=('professeur', 'eleve'))
    a.add_argument('--config')
    a.add_argument('--limite-minutes', type=float)
    a.add_argument('--simulation', action='store_true')
    args = a.parse_args()
    if args.commande == 'preparer':
        preparer(Path(args.travail))
    elif args.commande == 'activation':
        activation(Path(args.avant), Path(args.apres), Path(args.sortie))
    elif args.commande == 'valider':
        VERROU_JAVA = threading.BoundedSemaphore(max(1, min(2, args.processus)))
        return valider(Path(args.travail), args.processus)
    else:
        return generer(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
