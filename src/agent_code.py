"""Travail en agent de Nova (DEC-019 ; préparé le 01/11/2026, heures GPU seulement après l'accord de l'utilisateur) : un modèle
corrige de vrais bugs dans un terminal, commande après commande, au lieu de répondre d'un seul coup avec les bons fichiers
sous les yeux. Mesure GLM-5.3 contre l'élève sur les bugs contrôlés de SWE-bench Verified, avant toute génération de
trajectoires. SWE-bench reste réservé à la mesure : ces trajectoires ne servent jamais à l'entraînement.

- Protocole : une commande par réponse, dans un bloc ```bash, identique pour les deux modèles (pas de format d'outil propre à
  un modèle) ; « submit » termine. Le raisonnement de chaque tour est gardé dans la trajectoire, pas renvoyé au modèle.
- Conteneur : un par bug, Apptainer, calque temporaire ; sans réseau, sans le dossier du projet ni le dossier personnel
  (contrôlé par la sonde avant le chargement du modèle : si ce n'est pas le cas, le modèle n'est pas chargé).
- Sauvegarde : chaque tour est écrit dès qu'il est fini, avec l'état des fichiers (git, index à part). Une tâche arrêtée par sa
  limite reprend au créneau suivant, dans un conteneur neuf où l'on réapplique cet état.
- Verdict : la correction finale passe par swebench_apptainer.py evaluer, sur processeur, dans un conteneur neuf (outil officiel).
- Avant de charger le modèle : essai à blanc sur une copie des résultats (faux moteur, faux terminal, rien n'est exécuté) et
  sonde d'un vrai conteneur. Sur erreur : témoin <rôle>.erreur_code, code 6, le créneau suivant ne recharge rien.

  python agent_code.py generer --role eleve --config agent_code_v1.json --travail T [--simulation]
  python agent_code.py essai --config agent_code_v1.json --travail T    (sans modèle ni GPU : correction officielle par le
                                                                         vrai terminal, verdict de l'outil officiel)
Codes : 0 fini, 3 à reprendre (plus le temps dans cette tâche), 4 moteur jamais prêt, 6 erreur de code ou de conteneur.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import queue
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilote as P  # noqa: E402
import swebench_apptainer as SW  # noqa: E402

RESULTATS = 'resultats/swebench_agent'
USAGE = "mesure seulement : SWE-bench n'est jamais une donnée d'entraînement"
NOTE_REPRISE = ('(Note: the terminal was restarted. Your changes to the files are kept, but background processes and files '
                'outside the repository are gone.)')
INVITE = """I need help with a bug in a software project. The repository is checked out at /testbed and you have a terminal in it.

<issue>
{issue}
</issue>

Find the cause and fix it in the source code. The fix must solve the issue in general, not only for the example given. You can run the existing tests to check your work; you do not need to add tests to the repository.

How to work:
- Each of your replies must contain exactly one shell command, in a fenced block:
```bash
<command>
```
- I run it and send you its output, then you continue. The working directory and exported variables stay the same from one command to the next. A command may last {delai} seconds at most. There is no network.
- Long outputs are cut, so prefer targeted commands (grep, sed -n, head, one test file at a time).
- To edit a file, use sed, a heredoc or a small python script.
- When the fix is done and checked, reply with only this block:
```bash
submit
```"""
SANS_COMMANDE = ('I did not find a command in your reply. Reply with exactly one shell command in a ```bash block, or with submit '
                 'in a ```bash block if the fix is done.')
COUPEE = 'Your reply was cut before it gave a command: it was too long. Think less at each step and give one command.'
PLUSIEURS = '(Only the first command block of your reply was run: give one command per reply.)'
HEREDOC = re.compile(r"""<<-?\s*['"]?([A-Za-z_]\w*)['"]?""")

BOUCLE = r'''#!/bin/bash
# Dans le conteneur : exécute les commandes à la demande du programme (ordres sur l'entrée standard, réponses sur la sortie
# standard ; la sortie des commandes va dans des fichiers : un processus resté en fond ne peut rien bloquer).
IO="${AGENT_IO:-/agent_io}"
RACINE="${AGENT_RACINE:-/testbed}"
export AGENT_IO="$IO" AGENT_RACINE="$RACINE"
cd "$RACINE" || { echo "echec depart"; exit 1; }
. "$IO/depart.sh" > "$IO/depart.log" 2>&1
cd "$RACINE" || { echo "echec depart"; exit 1; }
export PYTHONDONTWRITEBYTECODE=1 GIT_PAGER=cat PAGER=cat TERM=dumb OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
export GIT_CONFIG_COUNT=4 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0='*' GIT_CONFIG_KEY_1=core.fileMode GIT_CONFIG_VALUE_1=false
export GIT_CONFIG_KEY_2=core.checkStat GIT_CONFIG_VALUE_2=minimal GIT_CONFIG_KEY_3=core.trustctime GIT_CONFIG_VALUE_3=false
export -p > "$IO/env.sh"
[ -s "$IO/cwd" ] || pwd > "$IO/cwd"
# état de départ (03/11) : l'index de l'image avec ses dates (cp -p ; avec checkStat=minimal, git ne relit pas les fichiers
# inchangés : django démarrait en 257 s), puis seulement ce qui diffère déjà de l'image (fichiers modifiés ou non suivis)
cp -p .git/index "$IO/index0" 2>/dev/null
GIT_INDEX_FILE="$IO/index0" git update-index -q --refresh > /dev/null 2>"$IO/base.err"
GIT_INDEX_FILE="$IO/index0" git add -A -- . > /dev/null 2>>"$IO/base.err" || { echo "echec depart"; exit 1; }
echo pret
while read -r ordre n delai; do
  case "$ordre" in
    r) timeout -k 5 "$delai" bash "$IO/enveloppe.sh" "$IO/c$n.sh" > "$IO/o$n.txt" 2>&1 < /dev/null
       echo "$?" > "$IO/r$n"
       timeout -k 5 180 bash "$IO/instantane.sh" > /dev/null 2>"$IO/instantane.err" < /dev/null
       echo "fait $n" ;;
    a) git apply --binary --whitespace=nowarn "$IO/reprise.patch" > "$IO/reprise.log" 2>&1
       echo "applique $?" ;;
    q) exit 0 ;;
  esac
done
'''
ENVELOPPE = r'''IO="${AGENT_IO:-/agent_io}"
. "$IO/env.sh" 2>/dev/null
cd "$(cat "$IO/cwd")" 2>/dev/null
ulimit -c 0 2>/dev/null; ulimit -f 1000000 2>/dev/null; ulimit -v 64000000 2>/dev/null; ulimit -u 30000 2>/dev/null
trap 'pwd > "$AGENT_IO/cwd" 2>/dev/null; export -p > "$AGENT_IO/env.sh" 2>/dev/null' EXIT
. "$1"
'''
INSTANTANE = r'''IO="${AGENT_IO:-/agent_io}"
cd "${AGENT_RACINE:-/testbed}" || exit 1
# Rien n'est écrit dans le dépôt, ni objet ni index (03/11) : git « rafraîchit » la date de ses gros fichiers d'objets quand on
# y écrit un objet qui existe déjà, et le conteneur les recopie alors dans ses 64 Mo d'écriture (83 % pris au départ pour
# seaborn). Les fichiers suivis sont comparés à l'état de départ, les fichiers nouveaux ajoutés tels quels.
# cp -p : l'index garde sa date ; sinon git ne relit pas un fichier modifié dans la même seconde, à taille égale (<= changé en >=)
cp -p "$IO/index0" "$IO/index.tmp" || exit 1
export GIT_INDEX_FILE="$IO/index.tmp"
git diff --binary --no-color --no-ext-diff --no-renames -- . ':(exclude,glob)**/__pycache__/**' ':(exclude,glob)**/*.pyc' ':(exclude,glob)**/.pytest_cache/**' > "$IO/instantane.tmp" || exit 1
git ls-files --others --exclude-standard -z -- . ':(exclude,glob)**/__pycache__/**' ':(exclude,glob)**/*.pyc' ':(exclude,glob)**/.pytest_cache/**' > "$IO/nouveaux.lst" || exit 1
while IFS= read -r -d '' f; do
  git diff --no-index --binary --no-color --no-ext-diff -- /dev/null "$f" >> "$IO/instantane.tmp"
done < "$IO/nouveaux.lst"
mv "$IO/instantane.tmp" "$IO/instantane.patch"
'''


class ConteneurMort(Exception):
    """Le terminal ne répond plus (conteneur arrêté, ou commande qui ne rend jamais la main malgré le délai)."""


def lire_sortie(chemin: Path, maxi: int) -> str:
    """Sortie d'une commande : tout si elle est courte, sinon le début et la fin, sans lire le milieu."""
    taille = chemin.stat().st_size if chemin.exists() else 0
    if taille == 0:
        return ''
    with chemin.open('rb') as f:
        if taille <= maxi:
            return f.read().decode('utf-8', 'replace')
        tete = f.read(maxi // 4).decode('utf-8', 'replace')
        f.seek(taille - (maxi - maxi // 4))
        queue_ = f.read().decode('utf-8', 'replace')
    return f'{tete}\n[... {taille - maxi} bytes cut ...]\n{queue_}'


def script_depart(inst: dict) -> str:
    """Environnement du projet : les lignes d'activation du script d'évaluation officiel, avant ses commandes git."""
    lignes = []
    for l in (inst.get('eval_script') or '').splitlines():
        if l.startswith('git '):
            break
        if l.startswith(('source ', 'conda activate ', 'export ', '. ')):
            lignes.append(l)
    return '\n'.join(lignes or ['source /opt/miniconda3/bin/activate', 'conda activate testbed']) + '\n'


class Conteneur:
    """Le terminal d'un agent. lancement : commande qui lance boucle.sh (Apptainer sur le cluster, bash seul dans les tests du
    PC, avec des commandes écrites par nous : le code des modèles ne tourne jamais sur le PC)."""

    def __init__(self, lancement: list[str], dossier: Path, depart: str, env: dict | None = None, sortie_max: int = 12000,
                 dossiers: tuple = ()):
        self.lancement, self.dossier, self.depart, self.env_proc, self.sortie_max = lancement, dossier, depart, env, sortie_max
        self.dossiers = dossiers  # dossiers du conteneur hors de /agent_io (calque, /tmp), effacés à l'arrêt
        self.p, self.n = None, 0
        self.lignes = queue.Queue()

    def _lecteur(self):
        for brut in self.p.stdout:
            self.lignes.put(brut.decode('utf-8', 'replace').strip())
        self.lignes.put(None)

    def _attendre(self, prefixe: str, delai: float) -> str:
        fin = time.time() + delai
        while True:
            try:
                ligne = self.lignes.get(timeout=max(0.0, fin - time.time()))
            except queue.Empty:
                raise ConteneurMort(f'pas de réponse en {delai:.0f} s (attendu : {prefixe})') from None
            if ligne is None:
                raise ConteneurMort(f"terminal arrêté ; {self._erreurs()}")
            if ligne.startswith(prefixe):
                return ligne
            if ligne.startswith('echec depart'):
                raise ConteneurMort(f"départ impossible ; {self._erreurs()}")

    def _erreurs(self) -> str:
        morceaux = []
        for nom in ('erreurs_lancement.txt', 'base.err', 'depart.log'):
            f = self.dossier / nom
            if f.exists() and f.stat().st_size:
                morceaux.append(f'{nom} : {lire_sortie(f, 600)}')
        return ' | '.join(morceaux)[:1500] or 'aucune erreur écrite'

    def _ordre(self, texte: str) -> None:
        try:
            self.p.stdin.write((texte + '\n').encode('utf-8'))
            self.p.stdin.flush()
        except OSError as e:
            raise ConteneurMort(f'ordre impossible : {e}') from e

    def demarrer(self, patch: bytes = b'', cwd: str | None = None, delai: float = 900) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        for d in self.dossiers:
            d.mkdir(parents=True, exist_ok=True)
        for nom, texte in (('boucle.sh', BOUCLE), ('enveloppe.sh', ENVELOPPE), ('instantane.sh', INSTANTANE), ('depart.sh', self.depart)):
            (self.dossier / nom).write_text(texte, encoding='utf-8', newline='\n')
        if cwd:
            (self.dossier / 'cwd').write_text(cwd + '\n', encoding='utf-8', newline='\n')
        with (self.dossier / 'erreurs_lancement.txt').open('wb') as erreurs:
            try:
                self.p = subprocess.Popen(self.lancement, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=erreurs,
                                          env=self.env_proc, start_new_session=os.name == 'posix')
            except OSError as e:
                raise ConteneurMort(f'lancement impossible : {e}') from e
        threading.Thread(target=self._lecteur, daemon=True).start()
        self._attendre('pret', delai)
        if patch:
            (self.dossier / 'reprise.patch').write_bytes(patch)
            self._ordre('a 0 0')
            r = self._attendre('applique', 300)
            if r != 'applique 0':
                raise ConteneurMort(f"état des fichiers impossible à réappliquer : {lire_sortie(self.dossier / 'reprise.log', 500)}")

    def executer(self, commande: str, delai: float) -> dict:
        self.n += 1
        n = self.n
        (self.dossier / f'c{n}.sh').write_text(commande + '\n', encoding='utf-8', newline='\n')
        t0 = time.time()
        self._ordre(f'r {n} {int(delai)}')
        self._attendre(f'fait {n}', delai + 240)
        sortie = lire_sortie(self.dossier / f'o{n}.txt', self.sortie_max)
        try:
            code = int((self.dossier / f'r{n}').read_text(encoding='utf-8').strip())
        except (OSError, ValueError):
            code = -1
        for f in (f'c{n}.sh', f'o{n}.txt', f'r{n}'):
            with contextlib.suppress(OSError):
                (self.dossier / f).unlink()
        return {'code': code, 'sortie': sortie, 'secondes': round(time.time() - t0, 1)}

    def instantane(self) -> bytes:
        f = self.dossier / 'instantane.patch'
        return f.read_bytes() if f.exists() else b''

    def cwd(self) -> str | None:
        with contextlib.suppress(OSError):
            return (self.dossier / 'cwd').read_text(encoding='utf-8').strip() or None
        return None

    def arreter(self) -> None:
        if self.p is not None:
            with contextlib.suppress(OSError, ConteneurMort):
                self._ordre('q 0 0')
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.p.wait(timeout=5)
            if os.name == 'posix':
                with contextlib.suppress(OSError):
                    os.killpg(self.p.pid, signal.SIGKILL)
            elif self.p.poll() is None:
                self.p.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.p.wait(timeout=30)
        for d in (self.dossier, *self.dossiers):
            shutil.rmtree(d, ignore_errors=True)


class TerminalFaux:
    """Faux terminal de l'essai à blanc et des tests : rien n'est exécuté, les sorties sont inventées."""

    def __init__(self, inst: dict):
        self.inst, self.patch, self.dossier_courant = inst, b'', '/testbed'

    def demarrer(self, patch: bytes = b'', cwd: str | None = None, delai: float = 900) -> None:
        if 'MORT_AU_DEPART' in self.inst.get('problem_statement', ''):
            raise ConteneurMort('faux départ impossible')
        self.patch, self.dossier_courant = patch, cwd or '/testbed'

    def executer(self, commande: str, delai: float) -> dict:
        if 'MORT' in commande:
            raise ConteneurMort('faux terminal arrêté')
        if 'CORRIGE' in commande:
            self.patch = (f"diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+{self.inst['instance_id']}\n").encode('utf-8')
        m = re.match(r'cd (\S+)', commande)
        if m:
            self.dossier_courant = m[1]
        return {'code': 124 if 'DELAI' in commande else 0, 'sortie': f'faux résultat de : {commande[:60]}\n', 'secondes': 0.0}

    def instantane(self) -> bytes:
        return self.patch

    def cwd(self) -> str | None:
        return self.dossier_courant

    def arreter(self) -> None:
        pass


# ---------------------------------------------------------------- moteurs

class MoteurContinu:
    """vLLM : demandes ajoutées pendant que d'autres tournent (LLM.enqueue_chat, puis LLMEngine.step) ; chaque agent avance à son
    rythme, sans attendre la réponse la plus longue de tous les autres."""

    def __init__(self, m):
        self.m, self.demandes = m, {}

    def ouvert(self, chat_kwargs: dict) -> bool:
        return self.m.ouvert(chat_kwargs)

    def en_cours(self) -> int:
        return len(self.demandes)

    def ajouter(self, cle: str, conversation: list[dict], phase: dict) -> bool:
        """Faux si l'invite ne laisse plus de place pour répondre (rien n'est envoyé)."""
        from vllm import SamplingParams
        chat_kwargs = phase.get('chat_kwargs') or {}
        budget = self.m.budgets([conversation], phase['max_tokens'], chat_kwargs)[0]
        if budget <= 0:
            return False
        options = {k: phase[k] for k in ('top_p', 'top_k', 'min_p', 'repetition_penalty') if k in phase}
        params = SamplingParams(n=1, temperature=phase.get('temperature', 0.0), max_tokens=budget, **options)
        ids = self.m.llm.enqueue_chat([conversation], params, use_tqdm=False, chat_template_kwargs=chat_kwargs)
        self.demandes[ids[0]] = cle
        return True

    def pas(self) -> list[tuple[str, dict]]:
        finies = []
        for s in self.m.llm.llm_engine.step():
            if s.finished and s.request_id in self.demandes:
                o = s.outputs[0]
                texte, recompose = P.recomposer(o.text, o.token_ids, self.m.id_fin, self.m.decoder)
                self.m.recomposes += recompose
                finies.append((self.demandes.pop(s.request_id), {'texte': texte, 'jetons': len(o.token_ids), 'fin': o.finish_reason}))
        return finies


class MoteurParLots:
    """Repli sur MoteurVllm.generer (appel éprouvé) : toutes les demandes prêtes partent ensemble, la plus longue fixe la fin."""

    def __init__(self, m):
        self.m, self.prets, self.phase = m, [], None

    def ouvert(self, chat_kwargs: dict) -> bool:
        return self.m.ouvert(chat_kwargs)

    def en_cours(self) -> int:
        return len(self.prets)

    def ajouter(self, cle: str, conversation: list[dict], phase: dict) -> bool:
        chat_kwargs = phase.get('chat_kwargs') or {}
        if self.m.budgets([conversation], phase['max_tokens'], chat_kwargs)[0] <= 0:
            return False
        self.prets.append((cle, conversation))
        self.phase = phase
        return True

    def pas(self) -> list[tuple[str, dict]]:
        prets, self.prets = self.prets, []
        sorties = self.m.generer([c for _, c in prets], self.phase)
        return [(cle, ech[0]) for (cle, _), ech in zip(prets, sorties)]


class MoteurEssai:
    """Faux moteur de l'essai à blanc et des tests : parcourt tous les cas (réponse normale, deux blocs, réponse coupée, sans
    commande, jamais fini, invite trop longue, terminal arrêté), à tour de rôle : les 8 premiers bugs passent par tous les cas."""

    def __init__(self, ouvert: bool = True):
        self.raisonne, self.prets, self.vus = ouvert, [], {}

    def ouvert(self, chat_kwargs: dict) -> bool:
        return self.raisonne

    def en_cours(self) -> int:
        return len(self.prets)

    def ajouter(self, cle: str, conversation: list[dict], phase: dict) -> bool:
        cas = self.vus.setdefault(cle, len(self.vus) % 8)
        tour = sum(m['role'] == 'assistant' for m in conversation) + 1
        if cas == 5 and tour == 3:  # invite trop longue
            return False
        self.prets.append((cle, conversation, cas, tour))
        return True

    def pas(self) -> list[tuple[str, dict]]:
        prets, self.prets = self.prets, []
        finies = []
        for cle, _, cas, tour in prets:
            fin = 'stop'
            if cas == 1 and tour == 1:
                corps = 'Two steps.\n```bash\nls\n```\nthen\n```bash\npwd\n```'
            elif cas == 2 and tour == 1:
                corps, fin = '', 'length'
            elif cas == 3 and tour <= 2:
                corps = 'I will look around first.'
            elif cas == 4:  # jamais fini
                corps = f'```bash\nsed -n {tour}p x.py\n```'
            elif cas == 6:  # jamais de commande
                corps = 'I am not sure what to do.'
            elif cas == 7 and tour == 2:
                corps = '```bash\necho MORT\n```'
            elif tour == 1:
                corps = 'Looking.\n```bash\ncd /testbed && grep -rn bug .\n```'
            elif tour <= 3:
                corps = 'The cause is here.\n```sh\necho CORRIGE > x.py\n```'
            else:
                corps = 'Done.\n```bash\nsubmit\n```'
            texte = ('Je réfléchis.</think>' if self.raisonne and fin == 'stop' else 'Je réfléchis' if self.raisonne else '') + corps
            finies.append((cle, {'texte': texte, 'jetons': len(texte.split()), 'fin': fin}))
        return finies


class MoteurScripte:
    """Sans modèle (essai du cluster, 0 heure GPU) : applique la correction officielle par le vrai terminal, ou rien."""

    def __init__(self, corrections: dict[str, str]):
        self.corrections, self.prets = corrections, []

    def ouvert(self, chat_kwargs: dict) -> bool:
        return False

    def en_cours(self) -> int:
        return len(self.prets)

    def ajouter(self, cle: str, conversation: list[dict], phase: dict) -> bool:
        tour = sum(m['role'] == 'assistant' for m in conversation) + 1
        patch = self.corrections.get(cle, '')
        if tour == 1:
            corps = '```bash\ngit status --short | head -5; python --version; which python\n```'
        elif tour == 2 and patch:
            corps = f"```bash\ncat > /tmp/correction.diff <<'FIN_CORRECTION'\n{patch}\nFIN_CORRECTION\ngit apply /tmp/correction.diff\n```"
        elif tour == 3 and patch:
            corps = '```bash\ncd /tmp\n```'
        else:
            corps = '```bash\nsubmit\n```'
        self.prets.append((cle, corps))
        return True

    def pas(self) -> list[tuple[str, dict]]:
        prets, self.prets = self.prets, []
        return [(cle, {'texte': corps, 'jetons': len(corps.split()), 'fin': 'stop'}) for cle, corps in prets]


# ---------------------------------------------------------------- un agent

def blocs_de_code(texte: str) -> list[tuple[str, str]]:
    """(langage, contenu) de chaque bloc entouré de ```, ligne par ligne. Une ligne ``` dans un heredoc ne ferme pas le bloc."""
    blocs, langage, corps, heredoc = [], '', None, None
    lignes = (texte or '').splitlines()
    for k, ligne in enumerate(lignes):
        nue = ligne.strip()
        if corps is None:
            if nue.startswith('```'):
                langage, corps, heredoc = nue[3:].strip().lower(), [], None
        elif heredoc:
            corps.append(ligne)
            if nue == heredoc:
                heredoc = None
        elif nue == '```':
            blocs.append((langage, '\n'.join(corps)))
            corps = None
        else:
            corps.append(ligne)
            m = HEREDOC.search(ligne)
            heredoc = m[1] if m and any(x.strip() == m[1] for x in lignes[k + 1:]) else None
    if corps is not None:  # bloc jamais refermé
        blocs.append((langage, '\n'.join(corps)))
    return blocs


def lire_action(reponse: str) -> tuple[str | None, bool, bool]:
    """(commande à lancer ou None, fini ou non, plusieurs blocs ou non). Blocs ```bash d'abord, sinon blocs sans langage."""
    blocs = blocs_de_code(reponse)
    choisis = [c for lang, c in blocs if lang in ('bash', 'sh', 'shell')] or [c for lang, c in blocs if not lang]
    if not choisis:
        return None, False, False
    lignes = choisis[0].strip().splitlines()
    fini = bool(lignes) and lignes[-1].strip() == 'submit'
    commande = '\n'.join(lignes[:-1] if fini else lignes).strip()
    return commande or None, fini, len(choisis) > 1


def observation(r: dict, delai: float, plusieurs: bool) -> str:
    note = PLUSIEURS + '\n' if plusieurs else ''
    if r['code'] in (124, 137):
        note += f'(The command was stopped after {int(delai)} seconds.)\n'
    return f"{note}Exit code: {r['code']}\nOutput:\n```\n{r['sortie'].rstrip()}\n```"


def lire_lignes(chemin: Path) -> list[dict]:
    """Lignes écrites ; une dernière ligne coupée par l'arrêt brutal d'une tâche est retirée."""
    if not chemin.exists():
        return []
    brut = chemin.read_bytes()
    if brut and not brut.endswith(b'\n'):
        brut = brut[:brut.rfind(b'\n') + 1]
        chemin.write_bytes(brut)
    return [json.loads(l) for l in brut.decode('utf-8').split('\n') if l]


class Agent:
    def __init__(self, inst: dict, dossier_etat: Path, config: dict):
        self.inst, self.id = inst, inst['instance_id']
        self.delai = config.get('delai_commande_s', 300)
        self.fichier = dossier_etat / f'{self.id}.jsonl'
        self.fichier_patch = dossier_etat / f'{self.id}.patch'
        self.lignes = lire_lignes(self.fichier)  # tours finis, et marques de reprise
        self.tours = [l for l in self.lignes if 'n' in l]
        self.patch = self.fichier_patch.read_bytes() if self.fichier_patch.exists() else b''
        self.a_reprendre = bool(self.tours)
        self.etat, self.env, self.futur, self.tour_en_cours, self.fini_apres = 'attente', None, None, None, False
        self.plusieurs, self.morts, self.sans_commande, self.rendu = False, 0, 0, None
        self.t0 = time.time()

    def conversation(self) -> list[dict]:
        m = [{'role': 'user', 'content': INVITE.format(issue=self.inst['problem_statement'].strip(), delai=int(self.delai))}]
        for l in self.lignes:
            if 'n' in l:
                m.append({'role': 'assistant', 'content': l['reponse'] or '(no answer)'})
                m.append({'role': 'user', 'content': l['observation']})
            elif l.get('reprise') and m[-1]['role'] == 'user':
                m[-1] = {'role': 'user', 'content': m[-1]['content'] + '\n\n' + NOTE_REPRISE}
        return m

    def ecrire(self, ligne: dict) -> None:
        self.lignes.append(ligne)
        if 'n' in ligne:
            self.tours.append(ligne)
        with self.fichier.open('a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def sauver_patch(self, patch: bytes) -> None:
        if patch != self.patch or not self.fichier_patch.exists():
            tmp = self.fichier_patch.with_name(self.fichier_patch.name + '.tmp')
            tmp.write_bytes(patch)
            tmp.replace(self.fichier_patch)
            self.patch = patch


def executer_phase(moteur, phase: dict, cas: list[dict], dossier: Path, creer_terminal, config: dict, debut: float, limite_s: float,
                   simultanes: int, arret_apres: int | None = None) -> str:
    """Tous les agents d'une phase. Renvoie 'fini' ou 'arret' (plus le temps : chaque tour fini est déjà écrit)."""
    nom = phase['nom']
    etat_dir = dossier / f'{nom}.etat'
    etat_dir.mkdir(parents=True, exist_ok=True)
    fichier_traj, fichier_pred = dossier / f'{nom}.trajectoires.jsonl', dossier / f'{nom}.predictions.jsonl'
    faits = SW.lire_jsonl(fichier_traj)
    SW.lire_jsonl(fichier_pred)  # répare une dernière ligne coupée
    choisis = cas[:phase['bugs']] if phase.get('bugs') else cas
    file = [Agent(i, etat_dir, config) for i in choisis if i['instance_id'] not in faits]
    tours_max, delai = config.get('tours_max', 60), config.get('delai_commande_s', 300)
    ouvert = moteur.ouvert(phase.get('chat_kwargs') or {})
    print(f"AGENT_PHASE_DEBUT {nom} : {len(choisis)} bugs, {len(faits)} déjà finis, {sum(a.a_reprendre for a in file)} à reprendre ; "
          f"{simultanes} à la fois ; {tours_max} tours au plus", flush=True)
    actifs, jetons_lances, tours_lances, t_debut, t_dernier = [], 0, 0, time.time(), time.time()
    pool = ThreadPoolExecutor(max_workers=simultanes + 8)

    def lancer(a):
        a.env = creer_terminal(a.inst, a.id)
        a.etat = 'demarrage'
        cwd = a.tours[-1].get('cwd') if a.tours else None
        a.futur = pool.submit(a.env.demarrer, a.patch, cwd)

    def terminer(a, raison):
        patch = a.patch.decode('utf-8', 'replace')
        jetons = sum(t.get('jetons', 0) for t in a.tours)
        SW.ajouter(fichier_pred, [{'instance_id': a.id, 'model_name_or_path': nom, 'model_patch': patch, 'fin': raison,
                                   'nb_tours': len(a.tours), 'jetons': jetons}])
        SW.ajouter(fichier_traj, [{'instance_id': a.id, 'phase': nom, 'usage': USAGE, 'fin': raison, 'tours': a.tours, 'nb_tours': len(a.tours),
                                   'jetons': jetons, 'reprises': sum(bool(l.get('reprise')) for l in a.lignes),
                                   'secondes_commandes': round(sum(t.get('secondes', 0) for t in a.tours), 1), 'model_patch': patch}])
        print(f"AGENT_FIN {a.id} : {raison} ; {len(a.tours)} tours, {jetons} jetons ; correction de {patch.count(chr(10))} lignes", flush=True)
        if a.env is not None:
            pool.submit(a.env.arreter)
        a.etat = 'fini'
        faits[a.id] = {'fin': raison, 'nb_tours': len(a.tours), 'jetons': jetons}
        if a in actifs:
            actifs.remove(a)

    def reponse_recue(a, e):
        nonlocal jetons_lances, tours_lances
        raisonnement, reponse = P.separer(e['texte'], ouvert)
        # une réponse coupée n'est jamais lancée : la commande peut être incomplète
        commande, fini, plusieurs = (None, False, False) if e['fin'] == 'length' else lire_action(reponse)
        jetons_lances += e['jetons']
        tours_lances += 1
        tour = {'n': len(a.tours) + 1, 'raisonnement': raisonnement, 'reponse': reponse, 'jetons': e['jetons'], 'fin': e['fin'], 'commande': commande}
        if commande is not None:
            a.sans_commande = 0
            a.tour_en_cours, a.fini_apres, a.plusieurs, a.etat = tour, fini, plusieurs, 'commande'
            a.futur = pool.submit(a.env.executer, commande, delai)
        elif fini:
            a.ecrire({**tour, 'observation': '', 'cwd': a.env.cwd()})
            terminer(a, 'submit')
        else:
            a.sans_commande += 1
            a.ecrire({**tour, 'observation': COUPEE if e['fin'] == 'length' else SANS_COMMANDE, 'cwd': a.env.cwd()})
            if a.sans_commande >= 3:
                terminer(a, 'sans_commande')
            else:
                a.etat = 'pret'

    def terminal_perdu(a, e):
        a.morts += 1
        print(f'AGENT_TERMINAL_PERDU {a.id} ({a.morts}) : {str(e)[:400]}', flush=True)
        pool.submit(a.env.arreter)
        if a.morts > 2:
            terminer(a, 'environnement')
        else:
            a.a_reprendre = bool(a.tours)
            a.tour_en_cours = None
            lancer(a)

    while file or actifs:
        temps_passe = time.time() - debut > limite_s
        if temps_passe or (arret_apres is not None and tours_lances >= arret_apres):
            print(f"AGENT_ARRET {nom} : {(time.time() - debut) / 60:.0f} min écoulées ; {len(faits)}/{len(choisis)} bugs finis ; "
                  f"{len(actifs)} en cours, repris au créneau suivant ; relancer pour continuer", flush=True)
            for a in actifs:
                if a.env is not None:
                    pool.submit(a.env.arreter)
            pool.shutdown(wait=True)
            return 'arret'
        while file and len(actifs) < simultanes and sum(a.etat == 'demarrage' for a in actifs) < 8:
            a = file.pop(0)
            actifs.append(a)
            lancer(a)
        for a in list(actifs):
            if a.etat == 'pret':
                if len(a.tours) >= tours_max:
                    terminer(a, 'tours_max')
                elif moteur.ajouter(a.id, a.conversation(), phase):
                    a.etat = 'generation'
                else:
                    terminer(a, 'contexte_plein')
        sorties = moteur.pas() if moteur.en_cours() else []
        par_id = {a.id: a for a in actifs}
        for cle, e in sorties:
            reponse_recue(par_id[cle], e)
        for a in list(actifs):
            if a.futur is None or not a.futur.done():
                continue
            futur, a.futur = a.futur, None
            try:
                r = futur.result()
            except ConteneurMort as e:
                terminal_perdu(a, e)
                continue
            if a.etat == 'demarrage':
                if a.a_reprendre:
                    a.ecrire({'reprise': True, 'apres_tour': len(a.tours)})
                    a.a_reprendre = False
                a.etat = 'pret'
            elif a.etat == 'commande':
                a.sauver_patch(a.env.instantane())
                a.ecrire({**a.tour_en_cours, 'code': r['code'], 'secondes': r['secondes'], 'cwd': a.env.cwd(),
                          'observation': observation(r, delai, a.plusieurs)})
                a.tour_en_cours = None
                if a.fini_apres:
                    terminer(a, 'submit')
                else:
                    a.etat = 'pret'
        if not sorties:
            time.sleep(0.02)
        if time.time() - t_dernier > 300:
            t_dernier = time.time()
            print(f'AGENT_PROGRES {nom} : {len(faits)}/{len(choisis)} bugs finis ; {len(actifs)} en cours ; {tours_lances} tours, '
                  f'{jetons_lances / 1e6:.2f} M jetons en {(t_dernier - t_debut) / 60:.0f} min', flush=True)
    pool.shutdown(wait=True)
    (dossier / f'{nom}.genere').write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')
    fins = {}
    for r in faits.values():
        fins[r['fin']] = fins.get(r['fin'], 0) + 1
    tours = [r['nb_tours'] for r in faits.values()] or [0]
    print(f"AGENT_PHASE {nom}=FINIE : {len(faits)} bugs ; fins : {' ; '.join(f'{k} {v}' for k, v in sorted(fins.items()))} ; tours médiane "
          f"{statistics.median(tours):.0f}, maximum {max(tours)} ; {sum(r['jetons'] for r in faits.values()) / 1e6:.2f} M jetons ; cette tâche : "
          f"{tours_lances} tours en {(time.time() - t_debut) / 60:.0f} min ; verdicts plus tard, sur processeur", flush=True)
    return 'fini'


# ---------------------------------------------------------------- contrôles avant le modèle

def lancement_apptainer(sif: Path, drapeaux: list[str], dossier: Path) -> list[str]:
    return ['apptainer', 'exec', *drapeaux, '--pwd', '/testbed', '--bind', f'{dossier}:/agent_io', str(sif), '/bin/bash', '/agent_io/boucle.sh']


def creer_apptainer(travail: Path, config: dict, drapeaux: list[str] | None = None):
    racine = Path(tempfile.mkdtemp(prefix='agent_', dir=travail / 'tmp'))
    # la tâche GPU charge les bibliothèques de DeepGEMM (deepgemm_env.sh) : Apptainer et ses outils prennent celles du système
    env = {k: v for k, v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'LD_PRELOAD')}

    def creer(inst: dict, cle: str):
        d = racine / f'{cle}.{time.time_ns()}'
        haut, tmp = d.with_name(d.name + '.calque'), d.with_name(d.name + '.tmp')  # {haut} et {tmp} dans les réglages
        drap = [x.replace('{haut}', str(haut)).replace('{tmp}', str(tmp)) for x in (drapeaux or config['drapeaux'])]
        return Conteneur(lancement_apptainer(travail / 'swebench' / 'images' / f"{inst['instance_id']}.sif", drap, d), d,
                         script_depart(inst), env=env, sortie_max=config.get('sortie_max', 12000), dossiers=(haut, tmp))
    return creer, racine


def sonder(env, isolation: bool = True) -> tuple[bool, list[str]]:
    """Un terminal déjà démarré fait-il ce qu'il faut ? Isolation : sans réseau, sans le projet ni le dossier personnel."""
    lignes, ok = [], True

    def controle(nom, commande, delai, test, bloquant=True):
        nonlocal ok
        r = env.executer(commande, delai)
        bon = bool(test(r))
        ok = ok and (bon or not bloquant)
        lignes.append(f"{nom} : {'OK' if bon else 'ECHEC'} ({r['secondes']:.0f} s) {' | '.join(r['sortie'].split(chr(10)))[:200]}")
        return r

    controle('terminal', 'echo bonjour', 30, lambda r: r['code'] == 0 and 'bonjour' in r['sortie'])
    controle('dossier changé', 'cd /tmp', 30, lambda r: r['code'] == 0)
    controle('dossier gardé', 'pwd', 30, lambda r: '/tmp' in r['sortie'])
    controle('retour au dépôt', 'cd "$AGENT_RACINE"; pwd', 30, lambda r: r['code'] == 0)
    controle('variable changée', 'export SONDE_AGENT=7', 30, lambda r: r['code'] == 0)
    controle('variable gardée', 'echo "[$SONDE_AGENT]"', 30, lambda r: '[7]' in r['sortie'])
    if isolation:
        controle('réseau coupé', 'timeout 5 bash -c "</dev/tcp/1.1.1.1/53"; echo "rc=$?"', 30, lambda r: 'rc=0' not in r['sortie'])
        controle('projet invisible', 'ls -d /cluster_fs 2>&1; echo "rc=$?"', 30, lambda r: 'rc=0' not in r['sortie'])
        controle('clés invisibles', 'ls -A "$HOME/.ssh" 2>&1; echo "rc=$?"', 30, lambda r: 'rc=0' not in r['sortie'])
        controle('place', 'df -k /testbed /tmp | tail -2; dd if=/dev/zero of=/tmp/.sonde bs=1M count=20 2>&1 | tail -1; echo "rc=${PIPESTATUS[0]}"; rm -f /tmp/.sonde',
                 60, lambda r: 'rc=0' in r['sortie'], bloquant=False)
    controle('délai respecté', 'sleep 30', 2, lambda r: r['code'] in (124, 137) and r['secondes'] < 20)
    controle('processus en fond sans blocage', 'sleep 60 &', 30, lambda r: r['secondes'] < 20)
    controle('longue sortie coupée', 'seq 1 200000', 30, lambda r: 'bytes cut' in r['sortie'] and len(r['sortie']) < 20000)
    controle('fichier créé', 'echo sonde > sonde_agent.txt', 30, lambda r: r['code'] == 0)
    p = env.instantane()
    ok = ok and b'sonde_agent.txt' in p
    lignes.append(f"état des fichiers après création : {'OK' if b'sonde_agent.txt' in p else 'ECHEC'} ({len(p)} octets)")
    controle('fichier retiré', 'rm -f sonde_agent.txt', 30, lambda r: r['code'] == 0)
    p = env.instantane()
    ok = ok and not p
    lignes.append(f"état des fichiers après retrait : {'OK' if not p else 'ECHEC'} ({len(p)} octets)")
    return ok, lignes


def essai_a_blanc(travail: Path, config: dict, phases: list[dict], cas: list[dict], dossier: Path) -> tuple[str | None, str]:
    """Les phases restantes sur une copie des résultats, faux moteur et faux terminal : (erreur ou None, journal). Rien n'est
    exécuté, et les trajectoires commencées sont reprises telles quelles."""
    (travail / 'tmp').mkdir(parents=True, exist_ok=True)
    copie = Path(tempfile.mkdtemp(prefix='agent_essai_', dir=travail / 'tmp'))
    sortie = io.StringIO()
    try:
        if dossier.exists():
            shutil.copytree(dossier, copie, dirs_exist_ok=True)
        with contextlib.redirect_stdout(sortie):
            for p in phases:
                faux = {**p, 'bugs': min(p.get('bugs') or 16, 16)}
                executer_phase(MoteurEssai(), faux, cas, copie, lambda inst, cle: TerminalFaux(inst), config, time.time(), 3600, 8)
                for f in (copie / f"{p['nom']}.predictions.jsonl", copie / f"{p['nom']}.trajectoires.jsonl"):
                    SW.lire_jsonl(f)
        return None, sortie.getvalue()
    except Exception:
        return traceback.format_exc(), sortie.getvalue()
    finally:
        shutil.rmtree(copie, ignore_errors=True)


def commande_tests(inst: dict) -> str | None:
    """La commande de test du script d'évaluation officiel (entre ses repères de sortie), pour mesurer la place qu'elle prend."""
    lignes = (inst.get('eval_script') or '').splitlines()
    debut = [k for k, l in enumerate(lignes) if 'Start Test Output' in l]
    fin = [k for k, l in enumerate(lignes) if 'End Test Output' in l]
    if not debut or not fin or fin[0] <= debut[0] + 1:
        return None
    return '\n'.join(lignes[debut[0] + 1:fin[0]])


def cas_valides(travail: Path, config: dict) -> list[dict]:
    instances = {r['instance_id']: r for r in SW.charger(travail)}
    ids = json.loads((travail / 'donnees' / 'swebench' / f"sous_ensemble_{config.get('sous_ensemble', SW.SOUS_ENSEMBLE)}.json").read_text(encoding='utf-8'))
    controle = SW.lire_jsonl(travail / 'donnees' / 'swebench' / 'controle_images.jsonl')
    return [instances[i] for i in ids if controle.get(i, {}).get('valide')]


def creer_moteur(travail: Path, config: dict, role: dict):
    """(moteur, journal) ; None si jamais prêt."""
    chemin = str(travail / role['modele'])
    essais = [{}] + ([role['repli']] if role.get('repli') else [])
    m, _ = P.charger(lambda o: P.MoteurVllm(chemin, {**role['vllm'], **o}, config.get('graine', 0)), essais,
                     60 * role.get('limite_chargement_minutes', 70), P.arreter_processus_enfants)
    if m is None:
        return None
    if config.get('continu', True) and hasattr(m.llm, 'enqueue_chat') and hasattr(m.llm.llm_engine, 'step'):
        print('AGENT_MOTEUR : continu (chaque agent à son rythme)', flush=True)
        return MoteurContinu(m)
    print('AGENT_MOTEUR : par lots (repli)', flush=True)
    return MoteurParLots(m)


def generer(args) -> int:
    travail = Path(args.travail)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    role = config['roles'][args.role]
    dossier = travail / config.get('dossier', RESULTATS)
    restantes = [p for p in role['phases'] if not (dossier / f"{p['nom']}.genere").exists()]
    print(f"AGENT_DEBUT {args.role} : modèle {role['modele']} ; phases restantes : {', '.join(p['nom'] for p in restantes) or 'aucune'}", flush=True)
    if not restantes:
        print('AGENT_BILAN=FINI', flush=True)
        return 0
    temoin, temoin_code = dossier / f'{args.role}.moteur_jamais_pret', dossier / f'{args.role}.erreur_code'
    for t, code, message in ((temoin, 4, "la tâche précédente n'a jamais eu de moteur prêt"), (temoin_code, 6, "une tâche précédente s'est arrêtée sur une erreur")):
        if t.exists():
            print(f"AGENT_BILAN=ECHEC : {message} ({t.read_text(encoding='utf-8').strip()[:300]}) ; le modèle n'est pas chargé ; relancer le lanceur après correction", flush=True)
            return code
    debut = time.time()
    dossier.mkdir(parents=True, exist_ok=True)
    (travail / 'tmp').mkdir(parents=True, exist_ok=True)

    def echec_code(raison: str) -> int:
        temoin_code.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} tâche {os.environ.get('SLURM_JOB_ID', '?')}\n{raison}", encoding='utf-8')
        for l in raison.strip().splitlines()[-15:]:
            print('AGENT_ERREUR ' + l, flush=True)
        print('AGENT_BILAN=ERREUR_CODE', flush=True)
        return 6

    cas = cas_valides(travail, config)
    if not cas:
        print('AGENT_BILAN=ECHEC : aucun bug contrôlé (donnees/swebench)', flush=True)
        return 2
    erreur, journal = essai_a_blanc(travail, config, restantes, cas, dossier)
    if erreur:
        print('AGENT_ESSAI_A_BLANC=ECHEC : erreur de code, modèle pas chargé', flush=True)
        for l in journal.strip().splitlines()[-5:]:
            print('AGENT_ERREUR ' + l, flush=True)
        return echec_code(erreur)
    print(f'AGENT_ESSAI_A_BLANC=OK ({time.time() - debut:.0f} s) : {len(journal.splitlines())} lignes de journal', flush=True)
    if args.simulation:
        moteur, creer, racine = MoteurEssai(), (lambda inst, cle: TerminalFaux(inst)), None
    else:
        creer, racine = creer_apptainer(travail, config)
        env = creer(cas[0], 'sonde')
        try:
            env.demarrer()
            bon, lignes = sonder(env)
        except ConteneurMort as e:
            bon, lignes = False, [f'terminal : ECHEC {e}']
        finally:
            env.arreter()
        for l in lignes:
            print('AGENT_SONDE ' + l, flush=True)
        if not bon:
            print('AGENT_SONDE=ECHEC : conteneur non conforme, modèle pas chargé', flush=True)
            return echec_code('sonde du conteneur en échec : ' + ' ; '.join(l for l in lignes if 'ECHEC' in l))
        print('AGENT_SONDE=OK', flush=True)
        for cle, valeur in (role.get('env') or {}).items():  # avant l'import de vLLM
            os.environ[cle] = str(valeur)
        moteur = creer_moteur(travail, config, role)
        if moteur is None:
            temoin.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} tâche {os.environ.get('SLURM_JOB_ID', '?')}\n", encoding='utf-8')
            print('AGENT_BILAN=ECHEC : moteur jamais prêt, voir PILOTE_CHARGEMENT_ECHEC', flush=True)
            return 4
    limite_s = 60 * (args.limite_minutes if args.limite_minutes is not None else role['limite_minutes'])
    try:
        for p in restantes:
            etat = executer_phase(moteur, p, cas, dossier, creer, config, debut, limite_s, role.get('agents_simultanes', 16))
            if etat == 'arret':
                print('AGENT_BILAN=A_REPRENDRE', flush=True)
                return 3
    except Exception:
        return echec_code(traceback.format_exc())
    finally:
        if racine is not None:
            shutil.rmtree(racine, ignore_errors=True)
    print('AGENT_BILAN=FINI', flush=True)
    return 0


def essai(args) -> int:
    """Sans modèle ni GPU (environnement nova-swebench) : isolation du conteneur, puis la chaîne entière sur de vrais bugs. La
    correction officielle passée par le vrai terminal doit résoudre le bug selon l'outil officiel, l'absence de correction ne
    doit pas le résoudre, et une tâche arrêtée en route doit reprendre sans rien perdre."""
    travail = Path(args.travail)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    # le pilote et la mesure exigent un essai réussi avec cette version du programme (discoverer.py, empreinte_agent)
    print(f"AGENT_ESSAI_CODE={hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest()[:16]}", flush=True)
    (travail / 'tmp').mkdir(parents=True, exist_ok=True)
    cas = cas_valides(travail, config)
    par_id = {i['instance_id']: i for i in cas}
    choisis = [par_id[i] for i in SW.PREFERES if i in par_id] or cas[:3]
    print(f"AGENT_ESSAI_BUGS : {', '.join(i['instance_id'] for i in choisis)} (sur {len(cas)} bugs contrôlés)", flush=True)
    print(f'AGENT_ESSAI_DEPART : {script_depart(choisis[0])!r}', flush=True)
    ok_flags = None
    for nom, drapeaux in [('réglages retenus', config['drapeaux'])] + [(k, v) for k, v in config.get('drapeaux_a_essayer', {}).items()]:
        creer, racine = creer_apptainer(travail, config, drapeaux)
        env = creer(choisis[0], 'sonde')
        try:
            env.demarrer()
            bon, lignes = sonder(env)
        except ConteneurMort as e:
            bon, lignes = False, [f'terminal : ECHEC {e}']
        finally:
            env.arreter()
            shutil.rmtree(racine, ignore_errors=True)
        for l in lignes:
            print(f'AGENT_SONDE [{nom}] {l}', flush=True)
        print(f"AGENT_SONDE [{nom}]={'OK' if bon else 'ECHEC'} : {' '.join(drapeaux)}", flush=True)
        if ok_flags is None:
            ok_flags = bon
    un_par_depot = {}
    for i in cas:
        un_par_depot.setdefault(i['repo'], i)
    creer, racine = creer_apptainer(travail, config)
    for depot, i in sorted(un_par_depot.items()):
        env = creer(i, 'depot')
        t0 = time.time()
        place = ''
        try:
            env.demarrer()
            depart = time.time() - t0
            r = env.executer('git status --short | wc -l; df -k / | tail -1; echo sonde > .sonde_agent; which python; python --version', 120)
            bon = r['code'] == 0 and b'.sonde_agent' in env.instantane()
            detail = f"départ {depart:.0f} s : " + ' | '.join(r['sortie'].strip().splitlines())[:220]
            tests = commande_tests(i)
            if tests:  # la vraie commande de test du logiciel, sans les tests du bug : la place qu'un agent peut prendre
                rt = env.executer(tests + '\necho "rc=$?"', 900)
                rp = env.executer("df -k / /tmp | tail -2 | awk '{print $6, $4 \" Ko libres\"}'; du -sk /tmp 2>/dev/null | cut -f1", 120)
                place = (f" ; tests du logiciel {rt['secondes']:.0f} s, {'rc=0' if 'rc=0' in rt['sortie'] else 'en échec (normal sans les tests du bug)'}"
                         f", ensuite : {' | '.join(rp['sortie'].strip().splitlines())} ; plus de place : {'OUI' if 'No space left' in rt['sortie'] else 'non'}")
                bon = bon and 'No space left' not in rt['sortie']
            else:
                place = ' ; commande de test introuvable'
        except ConteneurMort as e:
            bon, detail = False, str(e)[:300]
        finally:
            env.arreter()
        ok_flags = ok_flags and bon
        print(f"AGENT_ESSAI_DEPOT {depot} ({i['instance_id']}) : {'OK' if bon else 'ECHEC'} en {time.time() - t0:.0f} s : {detail}{place}", flush=True)
    shutil.rmtree(racine, ignore_errors=True)
    dossier = travail / 'resultats' / 'swebench_agent_essai' / time.strftime('%Y%m%d_%H%M%S')
    dossier.mkdir(parents=True, exist_ok=True)
    corrections = {i['instance_id']: i['patch'] for i in choisis}
    resultats, attendu = {}, {}
    creer, racine = creer_apptainer(travail, config)
    try:
        for nom, moteur, liste, arret, voulu in (('essai_correction', MoteurScripte(corrections), choisis, None, True),
                                                 ('essai_sans_correction', MoteurScripte({}), choisis[:1], None, False),
                                                 ('essai_reprise', MoteurScripte(corrections), choisis[:1], 3, True)):
            phase = {'nom': nom, 'chat_kwargs': {}, 'max_tokens': 1}
            etat = executer_phase(moteur, phase, liste, dossier, creer, config, time.time(), 3000, 4, arret)
            if arret is not None:
                print(f'AGENT_ESSAI_ARRET {nom} : {etat} (attendu : arret), reprise', flush=True)
                etat = executer_phase(MoteurScripte(corrections), phase, liste, dossier, creer, config, time.time(), 3000, 4)
            attendu[nom] = voulu
            resultats[nom] = etat
    finally:
        shutil.rmtree(racine, ignore_errors=True)
    bilan = bool(ok_flags)
    for nom, voulu in attendu.items():
        SW.evaluer(travail, dossier / f'{nom}.predictions.jsonl', 2, config.get('mode', 'simple'))
        rs = SW.lire_jsonl(dossier / f'{nom}.evaluation.jsonl')
        traj = SW.lire_jsonl(dossier / f'{nom}.trajectoires.jsonl')
        bons = all(bool(r.get('resolved')) == voulu for r in rs.values()) and resultats[nom] == 'fini' and bool(rs)
        if nom == 'essai_reprise':
            bons = bons and all(t.get('reprises', 0) >= 1 for t in traj.values())
        bilan = bilan and bons
        print(f"AGENT_ESSAI {nom} : {'OK' if bons else 'ECHEC'} ; attendu résolu = {voulu} ; "
              + ' ; '.join(f"{i} : résolu {r.get('resolved')}, {traj[i]['nb_tours']} tours, fin {traj[i]['fin']}, reprises {traj[i].get('reprises', 0)}"
                           for i, r in rs.items()), flush=True)
    print(f"AGENT_ESSAI_BILAN={'OK' if bilan else 'ECHEC'}", flush=True)
    return 0 if bilan else 1


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('commande', choices=('generer', 'essai'))
    a.add_argument('--travail', required=True)
    a.add_argument('--config', required=True)
    a.add_argument('--role', choices=('professeur', 'eleve', 'pilote'))
    a.add_argument('--limite-minutes', type=float)
    a.add_argument('--simulation', action='store_true')
    args = a.parse_args()
    return essai(args) if args.commande == 'essai' else generer(args)


if __name__ == '__main__':
    sys.exit(main())
