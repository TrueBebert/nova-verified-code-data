"""Tests du travail en agent sur le PC (01/11/2026) : logique complète avec le faux moteur et le faux terminal, puis la vraie
boucle du terminal, lancée par bash sans conteneur, avec des commandes écrites ici (le code des modèles ne tourne jamais sur le
PC). Aucun GPU, aucun réseau.

  python test_agent_code.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import agent_code as A  # noqa: E402

BASH = next((b for b in (r'C:\Program Files\Git\bin\bash.exe', '/bin/bash') if Path(b).exists()), None)
GIT = shutil.which('git')
reussis = echecs = 0


def verifier(condition, nom, detail=''):
    global reussis, echecs
    if condition:
        reussis += 1
        print(f'OK    {nom}')
    else:
        echecs += 1
        print(f'ECHEC {nom} : {detail}')


CONFIG = {'tours_max': 8, 'delai_commande_s': 30, 'sortie_max': 2000, 'drapeaux': ['--containall'], 'dossier': 'resultats/swebench_agent',
          'sous_ensemble': 4,
          'roles': {'eleve': {'modele': 'modeles/x', 'limite_minutes': 10, 'agents_simultanes': 4, 'vllm': {},
                              'phases': [{'nom': 'agent_eleve', 'chat_kwargs': {'enable_thinking': True}, 'max_tokens': 100}]}}}


def instance(i):
    return {'instance_id': f'projet__bug-{i}', 'problem_statement': f'Le bug numéro {i} : une erreur.', 'patch': '', 'test_patch': '',
            'eval_script': '#!/bin/bash\nset -uxo pipefail\nsource /opt/miniconda3/bin/activate\nconda activate testbed\ncd /testbed\ngit status\nexport X=1\n'}


def faux_terminal(inst, cle):
    return A.TerminalFaux(inst)


def tests_protocole():
    verifier(A.lire_action('Voici.\n```bash\nls -l\n```\nFin') == ('ls -l', False, False), 'un bloc bash')
    verifier(A.lire_action('```bash\nsubmit\n```') == (None, True, False), 'submit seul')
    verifier(A.lire_action('```bash\ngit diff\nsubmit\n```') == ('git diff', True, False), 'commande puis submit')
    verifier(A.lire_action('```bash\nls\n```\n```bash\npwd\n```') == ('ls', False, True), 'deux blocs : le premier')
    verifier(A.lire_action('```\nls\n```') == ('ls', False, False), 'bloc sans langage accepté')
    verifier(A.lire_action('```python\nprint(1)\n```\n```bash\nls\n```')[0] == 'ls', 'bloc python ignoré si un bloc bash existe')
    verifier(A.lire_action('Je ne sais pas.') == (None, False, False), 'pas de commande')
    verifier(A.lire_action("```bash\ncat > r.md <<'FIN'\n```\nx\n```\nFIN\necho ok\n```")[0] == "cat > r.md <<'FIN'\n```\nx\n```\nFIN\necho ok", 'heredoc avec des ``` : bloc entier')
    verifier(A.lire_action('```bash\nls') == ('ls', False, False), 'bloc jamais refermé accepté')
    verifier(A.lire_action('```bash\npython -c "print(1 << n)"\n```\nFin.\n') == ('python -c "print(1 << n)"', False, False), 'décalage << : pas un heredoc')
    verifier(A.lire_action('Texte.\n```text\nsortie\n```') == (None, False, False), "bloc d'un autre langage : pas une commande")
    verifier(A.lire_action('') == (None, False, False), 'réponse vide')
    d = A.script_depart(instance(1))
    verifier('conda activate testbed' in d and 'set -u' not in d and 'cd /testbed' not in d and 'export X' not in d, 'départ : activation seulement', d)
    verifier('conda activate testbed' in A.script_depart({}), 'départ : valeur par défaut')
    o = A.observation({'code': 124, 'sortie': 'abc\n'}, 30, True)
    verifier('Exit code: 124' in o and 'stopped after 30' in o and 'first command' in o, 'observation : délai et deux blocs', o)
    for mot in ('benchmark', 'SWE-bench', 'swebench', 'hidden', 'dataset'):
        verifier(mot.lower() not in A.INVITE.lower(), f'invite sans le mot {mot}')


def lancer_phase(racine, cas, moteur=None, arret_apres=None, limite_s=600, phase=None):
    phase = phase or CONFIG['roles']['eleve']['phases'][0]
    return A.executer_phase(moteur or A.MoteurEssai(), phase, cas, racine, faux_terminal, CONFIG, time.time(), limite_s, 4, arret_apres)


def tests_boucle(tmp):
    cas = [instance(i) for i in range(16)]
    d = tmp / 'a'
    etat = lancer_phase(d, cas)
    traj = A.SW.lire_jsonl(d / 'agent_eleve.trajectoires.jsonl')
    pred = A.SW.lire_jsonl(d / 'agent_eleve.predictions.jsonl')
    fins = sorted({r['fin'] for r in traj.values()})
    verifier(etat == 'fini' and len(traj) == 16 and len(pred) == 16, '16 trajectoires et prédictions', (etat, len(traj), len(pred)))
    verifier((d / 'agent_eleve.genere').exists(), 'marque .genere à la fin')
    attendus = {'submit', 'tours_max', 'contexte_plein', 'sans_commande', 'environnement'}
    verifier(attendus <= set(fins), 'tous les types de fin rencontrés', fins)
    verifier(all(r['usage'] == A.USAGE for r in traj.values()), 'trajectoires marquées « mesure seulement »')
    verifier(all(set(p) >= {'instance_id', 'model_name_or_path', 'model_patch'} for p in pred.values()), 'prédictions au format de evaluer')
    corriges = [p for p in pred.values() if 'x.py' in p['model_patch']]
    verifier(corriges and all(i in p['model_patch'] for i, p in pred.items() if 'x.py' in p['model_patch']), 'correction propre à chaque bug', len(corriges))
    r = next(t for t in traj.values() if t['fin'] == 'submit' and t['nb_tours'] > 2)
    verifier(r['tours'][0]['raisonnement'] == 'Je réfléchis.' and r['tours'][0]['commande'], 'raisonnement gardé à part', r['tours'][0])
    m = A.Agent(cas[0], d / 'agent_eleve.etat', CONFIG).conversation()
    verifier(all('Je réfléchis' not in x['content'] for x in m), 'raisonnement jamais renvoyé au modèle')
    verifier(m[0]['role'] == 'user' and all(a['role'] != b['role'] for a, b in zip(m, m[1:])), 'tours alternés')
    avant = (d / 'agent_eleve.trajectoires.jsonl').read_bytes()
    verifier(lancer_phase(d, cas) == 'fini' and (d / 'agent_eleve.trajectoires.jsonl').read_bytes() == avant, 'relance : rien de refait')
    perdus = [t for t in traj.values() if t['fin'] == 'environnement']
    verifier(perdus and all(t['nb_tours'] == 1 and t['reprises'] >= 2 for t in perdus), 'terminal perdu : repris deux fois, puis fin environnement',
             [(t['nb_tours'], t['reprises']) for t in perdus])
    deux = next(t for t in traj.values() if '(Only the first' in t['tours'][0]['observation'])
    verifier(deux['tours'][0]['commande'] == 'ls', 'deux blocs : seul le premier est lancé, le modèle est prévenu', deux['tours'][0]['commande'])
    coupe = next(t for t in traj.values() if t['tours'] and t['tours'][0]['fin'] == 'length')
    verifier(coupe['tours'][0]['observation'] == A.COUPEE and coupe['tours'][0]['reponse'] == '', 'réponse coupée : le modèle est prévenu')

    # terminal toujours perdu : fin « environnement », pas de plantage
    d2 = tmp / 'b'
    mort = [{**instance(1), 'problem_statement': 'MORT_AU_DEPART'}]
    verifier(lancer_phase(d2, mort) == 'fini', 'départ impossible : la phase continue')
    t2 = A.SW.lire_jsonl(d2 / 'agent_eleve.trajectoires.jsonl')
    verifier(next(iter(t2.values()))['fin'] == 'environnement', 'départ impossible : fin environnement', t2)

    # arrêt en route, puis reprise sans perte
    d3 = tmp / 'c'
    petits = [instance(i) for i in range(16)]
    verifier(lancer_phase(d3, petits, arret_apres=6) == 'arret', 'arrêt demandé en route')
    verifier(not (d3 / 'agent_eleve.genere').exists(), 'pas de .genere après un arrêt')
    etats = {f.stem: A.lire_lignes(f) for f in (d3 / 'agent_eleve.etat').glob('*.jsonl')}
    tours_avant = {k: [l for l in v if 'n' in l] for k, v in etats.items()}
    verifier(any(tours_avant.values()), 'tours déjà écrits avant la reprise', {k: len(v) for k, v in tours_avant.items()})
    verifier(lancer_phase(d3, petits) == 'fini', 'reprise jusqu\'au bout')
    t3 = A.SW.lire_jsonl(d3 / 'agent_eleve.trajectoires.jsonl')
    verifier(len(t3) == 16, '16 trajectoires après reprise', len(t3))
    garde = all(t3[k]['tours'][:len(v)] == v for k, v in tours_avant.items() if k in t3 and v)
    verifier(garde, 'tours d\'avant la reprise inchangés')
    repris = [t for k, t in t3.items() if tours_avant.get(k) and t['fin'] != 'environnement']
    verifier(repris and all(t['reprises'] >= 1 for t in repris), 'reprise notée', [t['reprises'] for t in repris])
    k = next(k for k, v in tours_avant.items() if v)
    conv = A.Agent(next(i for i in petits if i['instance_id'] == k), d3 / 'agent_eleve.etat', CONFIG).conversation()
    verifier(any(A.NOTE_REPRISE in x['content'] for x in conv if x['role'] == 'user'), 'le modèle est prévenu de la reprise')

    # limite de temps
    d4 = tmp / 'd'
    verifier(A.executer_phase(A.MoteurEssai(), CONFIG['roles']['eleve']['phases'][0], cas, d4, faux_terminal, CONFIG, time.time() - 100, 1, 4) == 'arret', 'limite de temps : arrêt')

    # ligne coupée par un arrêt brutal
    f = next((d3 / 'agent_eleve.etat').glob('*.jsonl'))
    brut = f.read_bytes()
    f.write_bytes(brut + b'{"n": 99, "repon')
    verifier(all(l.get('n') != 99 for l in A.lire_lignes(f)) and f.read_bytes() == brut, 'dernière ligne coupée retirée')


def tests_generer(tmp):
    t = tmp / 'cluster'
    (t / 'donnees' / 'swebench').mkdir(parents=True)
    inst = [instance(i) for i in range(6)]
    (t / 'donnees' / 'swebench' / 'verified_v5.jsonl').write_text(''.join(json.dumps(i) + '\n' for i in inst), encoding='utf-8')
    (t / 'donnees' / 'swebench' / 'sous_ensemble_4.json').write_text(json.dumps([i['instance_id'] for i in inst]), encoding='utf-8')
    (t / 'donnees' / 'swebench' / 'controle_images.jsonl').write_text(
        ''.join(json.dumps({'instance_id': i['instance_id'], 'valide': k != 5}) + '\n' for k, i in enumerate(inst)), encoding='utf-8')
    cfg = tmp / 'config.json'
    cfg.write_text(json.dumps(CONFIG), encoding='utf-8')

    class Args:
        travail, config, role, limite_minutes, simulation = str(t), str(cfg), 'eleve', None, True

    code = A.generer(Args)
    d = t / 'resultats' / 'swebench_agent'
    verifier(code == 0 and (d / 'agent_eleve.genere').exists(), 'generer en simulation : fini', code)
    verifier(len(A.SW.lire_jsonl(d / 'agent_eleve.predictions.jsonl')) == 5, 'seuls les bugs contrôlés sont pris')
    verifier(A.generer(Args) == 0, 'relance : aucune phase restante')
    (d / 'agent_eleve.genere').unlink()
    (d / 'eleve.erreur_code').write_text('x', encoding='utf-8')
    verifier(A.generer(Args) == 6, 'témoin d\'erreur : le modèle n\'est pas chargé')
    (d / 'eleve.erreur_code').unlink()
    (d / 'eleve.moteur_jamais_pret').write_text('x', encoding='utf-8')
    verifier(A.generer(Args) == 4, 'témoin de moteur : arrêt aussitôt')
    (d / 'eleve.moteur_jamais_pret').unlink()

    # une erreur de code pendant l'essai à blanc : code 6, témoin écrit, le modèle n'est pas chargé
    vrai = A.executer_phase
    (d / 'agent_eleve.genere').write_text('', encoding='utf-8')
    (d / 'agent_eleve.genere').unlink()

    def casse(*a, **k):
        raise KeyError('erreur de code simulée')
    A.executer_phase = casse
    try:
        code = A.generer(Args)
    finally:
        A.executer_phase = vrai
    verifier(code == 6 and (d / 'eleve.erreur_code').exists(), 'erreur de code : code 6 et témoin', code)
    (d / 'eleve.erreur_code').unlink()
    # l'essai à blanc travaille sur une copie : la vraie phase commencée ne bouge pas
    d5 = tmp / 'copie'
    lancer_phase(d5, inst[:5], arret_apres=4)
    avant = {f.name: f.read_bytes() for f in (d5 / 'agent_eleve.etat').glob('*')}
    erreur, _ = A.essai_a_blanc(t, CONFIG, CONFIG['roles']['eleve']['phases'], inst[:5], d5)
    verifier(erreur is None, 'essai à blanc sur des trajectoires commencées', erreur)
    verifier(avant == {f.name: f.read_bytes() for f in (d5 / 'agent_eleve.etat').glob('*')} and not (d5 / 'agent_eleve.genere').exists(), 'essai à blanc : vrais résultats intacts')
    verifier(not list((t / 'tmp').glob('agent_essai_*')), 'essai à blanc : copie effacée')


def tests_moteur_vllm():
    """Enveloppes de vLLM avec un faux LLM : aucun GPU."""
    import types

    class FauxTok:
        def apply_chat_template(self, conv, tokenize=False, add_generation_prompt=True, **k):
            return ' '.join(m['content'] for m in conv)

        def encode(self, texte, add_special_tokens=False):
            return texte.split()

    class FauxLLM:
        def __init__(self):
            self.ajouts, self.n = [], 0
            self.llm_engine = self

        def get_tokenizer(self):
            return FauxTok()

        def enqueue_chat(self, convs, params, use_tqdm=True, chat_template_kwargs=None):
            self.n += 1
            self.ajouts.append((convs, params, chat_template_kwargs))
            return [str(self.n)]

        def step(self):
            s = []
            for i in range(self.n):
                sortie = types.SimpleNamespace(text=f'réponse {i + 1}', token_ids=[1, 2, 3], finish_reason='stop')
                s.append(types.SimpleNamespace(request_id=str(i + 1), finished=True, outputs=[sortie]))
            return s

    faux_vllm = types.ModuleType('vllm')
    faux_vllm.SamplingParams = lambda **k: types.SimpleNamespace(**k)
    sys.modules['vllm'] = faux_vllm
    try:
        m = A.P.MoteurVllm.__new__(A.P.MoteurVllm)
        m.llm, m.max_len, m.tp, m.id_fin, m.recomposes = FauxLLM(), 150, 2, None, 0
        m.decoder = lambda ids: ''
        c = A.MoteurContinu(m)
        phase = {'max_tokens': 50, 'temperature': 0.6, 'top_k': 20, 'chat_kwargs': {'enable_thinking': True}}
        verifier(c.ajouter('bug-1', [{'role': 'user', 'content': 'court'}], phase) and c.en_cours() == 1, 'moteur continu : demande ajoutée')
        verifier(m.llm.ajouts[0][2] == {'enable_thinking': True} and m.llm.ajouts[0][1].top_k == 20 and m.llm.ajouts[0][1].max_tokens == 50, 'moteur continu : réglages transmis')
        verifier(not c.ajouter('bug-2', [{'role': 'user', 'content': ' '.join(['mot'] * 200)}], phase), 'moteur continu : invite trop longue refusée')
        f = c.pas()
        verifier(f == [('bug-1', {'texte': 'réponse 1', 'jetons': 3, 'fin': 'stop'})] and c.en_cours() == 0, 'moteur continu : réponse rendue au bon agent', f)
        verifier(c.pas() == [], 'moteur continu : une demande inconnue est ignorée')
    finally:
        del sys.modules['vllm']


def tests_vrai_terminal(tmp):
    """boucle.sh, enveloppe.sh, instantane.sh vraiment exécutés par bash, sur un petit dépôt git, avec nos propres commandes."""
    if not BASH or not GIT:
        print('SAUTE vrai terminal : bash ou git absent')
        return
    depot = tmp / 'depot'
    depot.mkdir(parents=True)
    env = {**os.environ, 'GIT_AUTHOR_NAME': 'a', 'GIT_AUTHOR_EMAIL': 'a@a', 'GIT_COMMITTER_NAME': 'a', 'GIT_COMMITTER_EMAIL': 'a@a'}
    (depot / 'x.py').write_text('a = 1\n', encoding='utf-8', newline='\n')
    (depot / 'etat_de_base.txt').write_text('déjà là, jamais suivi\n', encoding='utf-8', newline='\n')
    for cmd in (['init', '-q'], ['add', 'x.py'], ['commit', '-q', '-m', 'base']):
        subprocess.run(['git', *cmd], cwd=depot, env=env, check=True, capture_output=True)

    def terminal(nom):
        d = tmp / nom
        d.mkdir(parents=True, exist_ok=True)
        e = {**env, 'AGENT_IO': d.as_posix(), 'AGENT_RACINE': depot.as_posix()}
        return A.Conteneur([BASH, (d / 'boucle.sh').as_posix()], d, 'export DEPART_LU=oui\n', env=e, sortie_max=2000)

    t = terminal('t1')
    t.demarrer()
    try:
        ok, lignes = A.sonder(t, isolation=False)
        for l in lignes:
            print('      ', l)
        verifier(ok, 'sonde complète du vrai terminal', [l for l in lignes if 'ECHEC' in l])
        r = t.executer('echo "[$DEPART_LU]"; exit 3', 30)
        verifier('[oui]' in r['sortie'] and r['code'] == 3, 'départ lu, code de sortie rendu, exit sans casser le terminal', r)
        r = t.executer('echo encore', 30)
        verifier(r['code'] == 0 and 'encore' in r['sortie'], 'le terminal répond après exit')
        verifier(t.instantane() == b'', 'fichier non suivi présent au départ : pas dans la correction', t.instantane()[:200])
        r = t.executer("sed -i 's/a = 1/a = 2/' x.py; echo nouveau > nouveau.txt; mkdir -p __pycache__; echo z > __pycache__/z.pyc; printf 'o\\377\\000k' > b.bin", 30)
        p = t.instantane()
        verifier(b'+a = 2' in p and b'nouveau.txt' in p and b'b.bin' in p and b'__pycache__' not in p, 'correction : modifié, créé, binaire ; pas les fichiers de cache', p[:400])
        verifier(b'GIT binary patch' in p, 'fichier binaire gardé dans la correction')
        cwd = t.cwd()
        verifier(cwd is not None, 'dossier courant lu', cwd)
        r = t.executer('cd etat_inconnu_qui_nexiste_pas', 30)
        verifier(r['code'] != 0, 'commande ratée : code rendu', r)
        r = t.executer('if then', 30)
        verifier(r['code'] != 0 and t.executer('echo vivant', 30)['code'] == 0, 'erreur de syntaxe : le terminal survit')
    finally:
        t.arreter()
    verifier(not (tmp / 't1').exists(), 'dossier du terminal effacé à l\'arrêt')
    subprocess.run(['git', 'status', '--short'], cwd=depot, env=env, check=True, capture_output=True)

    # reprise : fichiers remis à zéro comme dans un conteneur neuf, puis état réappliqué
    for f in ('nouveau.txt', 'b.bin'):
        (depot / f).unlink()
    shutil.rmtree(depot / '__pycache__', ignore_errors=True)
    subprocess.run(['git', 'checkout', '-q', '--', 'x.py'], cwd=depot, env=env, check=True, capture_output=True)
    t2 = terminal('t2')
    t2.demarrer(p, '/tmp')
    try:
        verifier((depot / 'x.py').read_text(encoding='utf-8') == 'a = 2\n' and (depot / 'nouveau.txt').exists()
                 and (depot / 'b.bin').read_bytes() == b'o\xff\x00k', 'reprise : fichiers remis, binaire compris')
        r = t2.executer('pwd', 30)
        verifier('/tmp' in r['sortie'], 'reprise : dossier courant remis', r)
        r = t2.executer('echo fin', 30)
        verifier(t2.instantane() == p, 'reprise : même correction qu\'avant', (len(t2.instantane()), len(p)))
    finally:
        t2.arreter()

    # reprise avec un changement de même taille : il tombe souvent dans la même seconde que l'index du départ, et le défaut du
    # 01/11 (copie de l'index sans sa date) le perdait une fois sur trois environ ; d'où la répétition
    subprocess.run(['git', 'checkout', '-q', '--', 'x.py'], cwd=depot, env=env, check=True, capture_output=True)
    for f in ('nouveau.txt', 'b.bin'):
        (depot / f).unlink(missing_ok=True)
    meme_taille = b'diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a = 1\n+a = 9\n'
    perdus = 0
    for k in range(8):
        t5 = terminal(f't5_{k}')
        t5.demarrer(meme_taille)
        try:
            t5.executer('true', 30)
            perdus += b'+a = 9' not in t5.instantane()
        finally:
            t5.arreter()
            subprocess.run(['git', 'checkout', '-q', '--', 'x.py'], cwd=depot, env=env, check=True, capture_output=True)
    verifier(perdus == 0, 'reprise avec un changement de même taille, 8 fois : jamais perdu', perdus)

    # la sauvegarde n'écrit rien dans le dépôt (03/11) : un objet déjà rangé dans un paquet faisait « rafraîchir » la date du
    # paquet, que le conteneur recopiait alors dans ses 64 Mo d'écriture
    subprocess.run(['git', 'gc', '-q'], cwd=depot, env=env, check=True, capture_output=True)
    paquets = {f: f.stat().st_mtime_ns for f in (depot / '.git' / 'objects' / 'pack').glob('*.pack')}
    t7 = terminal('t7')
    t7.demarrer()
    try:
        avant = sorted(str(f) for f in (depot / '.git' / 'objects').rglob('*') if f.is_file())
        index = (depot / '.git' / 'index').stat().st_mtime_ns
        t7.executer("sed -i 's/a = 1/a = 5/' x.py; echo n > neuf.txt", 30)
        t7.executer("sed -i 's/a = 5/a = 1/' x.py", 30)  # retour au contenu d'origine, déjà rangé dans le paquet
        p7 = t7.instantane()
        apres = sorted(str(f) for f in (depot / '.git' / 'objects').rglob('*') if f.is_file())
        verifier(paquets and all(f.stat().st_mtime_ns == m for f, m in paquets.items()), 'sauvegarde : dates des paquets de git inchangées')
        verifier(avant == apres and (depot / '.git' / 'index').stat().st_mtime_ns == index, 'sauvegarde : aucun objet ni index écrit dans le dépôt',
                 (len(avant), len(apres)))
        verifier(b'neuf.txt' in p7 and b'x.py' not in p7, 'sauvegarde : fichier remis à l\'identique absent, nouveau fichier présent', p7[:200])
    finally:
        t7.arreter()
        (depot / 'neuf.txt').unlink(missing_ok=True)

    # état impossible à réappliquer : signalé, pas ignoré
    t3 = terminal('t3')
    try:
        t3.demarrer(b'pas une correction\n')
        verifier(False, 'correction invalide refusée')
    except A.ConteneurMort as e:
        verifier('réappliquer' in str(e), 'correction invalide refusée', e)
    finally:
        t3.arreter()

    # lancement impossible : erreur claire
    d = tmp / 't4'
    t4 = A.Conteneur([BASH, '-c', 'echo probleme >&2; exit 7'], d, '')
    try:
        t4.demarrer(delai=20)
        verifier(False, 'lancement impossible signalé')
    except A.ConteneurMort as e:
        verifier('probleme' in str(e), 'lancement impossible signalé, avec son message', e)
    finally:
        t4.arreter()

    # programme de lancement absent : même chemin qu'un terminal perdu
    d6 = tmp / 't6'
    t6 = A.Conteneur(['programme_qui_nexiste_pas_agent'], d6, '')
    try:
        t6.demarrer(delai=10)
        verifier(False, 'programme absent signalé')
    except A.ConteneurMort as e:
        verifier('lancement impossible' in str(e), 'programme absent signalé', e)
    finally:
        t6.arreter()

    # la phase entière, vrai terminal, moteur scripté
    subprocess.run(['git', 'checkout', '-q', '--', 'x.py'], cwd=depot, env=env, check=True, capture_output=True)
    for f in ('nouveau.txt', 'b.bin'):
        (depot / f).unlink(missing_ok=True)
    (depot / 'etat_de_base.txt').unlink(missing_ok=True)
    correction = 'diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a = 1\n+a = 3\n'
    inst = {'instance_id': 'depot__essai', 'problem_statement': 'Un bug.'}

    def creer(i, cle):
        return terminal(f'phase{time.time_ns()}')
    d5 = tmp / 'phase_vraie'
    etat = A.executer_phase(A.MoteurScripte({inst['instance_id']: correction}), {'nom': 'p', 'chat_kwargs': {}, 'max_tokens': 1}, [inst], d5, creer,
                            CONFIG, time.time(), 120, 1)
    tr = A.SW.lire_jsonl(d5 / 'p.trajectoires.jsonl')[inst['instance_id']]
    verifier(etat == 'fini' and tr['fin'] == 'submit' and '+a = 3' in tr['model_patch'], 'phase entière par le vrai terminal', tr.get('model_patch'))
    verifier(tr['tours'][1]['code'] == 0, 'correction appliquée par le terminal', tr['tours'][1])


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    racine = Path(tempfile.mkdtemp(prefix='test_agent_')).resolve()
    try:
        tests_protocole()
        tests_boucle(racine / 'boucle')
        tests_generer(racine / 'generer')
        tests_moteur_vllm()
        tests_vrai_terminal(racine / 'terminal')
    finally:
        shutil.rmtree(racine, ignore_errors=True)
    print(f'\n{reussis}/{reussis + echecs} vérifications réussies')
    return 1 if echecs else 0


if __name__ == '__main__':
    sys.exit(main())
