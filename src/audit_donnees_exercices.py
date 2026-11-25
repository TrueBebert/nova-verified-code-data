"""Audit des données des exercices Nova (23/10/2026), sur le PC, avant tout entraînement : contrôles sur les 541
exemples (forme, fuites, traces de l'essai à blanc, identité du professeur, longueurs, taille des réparations) et
échantillon stratifié à relire. Rien n'est exécuté du code des modèles.

Sorties : outputs/nova_122b_preparation/exercices_nova/audit_donnees_20261023.json et echantillon_donnees_20261023.txt
"""
import collections
import difflib
import json
import random
import re
import statistics as st
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import exercices_nova as EN  # noqa: E402

R = ICI / 'pilote' / 'resultats_cluster' / EN.RESULTATS
SORTIE = ICI.parents[2] / 'outputs' / 'nova_122b_preparation' / 'exercices_nova'
CJK = re.compile(r'[぀-ヿ㐀-鿿가-힯]')
IDENTITE = re.compile(r'\bGLM\b|ChatGLM|Zhipu|Z\.ai|\bQwen\b|\bClaude\b|OpenAI|\bChatGPT\b|\bGPT-[345]', re.I)
MARQUES = re.compile(r'^=== *(FILE|BUG|REPORT|END|TITLE|STUB|TEST|SOLUTION)\b', re.M)


def resume(x):
    x = sorted(x)
    if not x:
        return {}
    return {'n': len(x), 'min': x[0], 'mediane': st.median(x), 'q90': x[int(0.9 * (len(x) - 1))], 'max': x[-1]}


def lignes_changees(a: str, b: str) -> int:
    return sum(1 for d in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm='', n=0)
               if d[:1] in '+-' and not d.startswith(('+++', '---')))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    exemples = [json.loads(l) for l in (R / 'donnees.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    taches = {i: r['entree'] for i, r in EN.lire_jsonl(R / 'creation.jsonl').items() if 'entree' in r}
    e1, e2 = EN.lire_jsonl(R / 'resolution.essai1.jsonl'), EN.lire_jsonl(R / 'resolution.essai2.jsonl')
    inj, rep = EN.lire_jsonl(R / 'injection.jsonl'), EN.lire_jsonl(R / 'reparation.jsonl')
    pb = collections.defaultdict(list)  # contrôle -> identifiants en défaut

    ids = [e['id'] for e in exemples]
    if len(set(ids)) != len(ids):
        pb['identifiants en double'] = [i for i, n in collections.Counter(ids).items() if n > 1]
    longueurs = collections.defaultdict(lambda: collections.defaultdict(list))
    for e in exemples:
        m = e['messages']
        roles = [x['role'] for x in m]
        if roles[0] != 'user' or roles[-1] != 'assistant' or any(a == b for a, b in zip(roles, roles[1:])):
            pb['tours mal ordonnés'].append(e['id'])
        appris = [x for x in m if x['role'] == 'assistant' and x.get('entrainer')]
        if len(appris) != 1 or appris[0] is not m[-1]:
            pb['réponse apprise mal placée'].append(e['id'])
        final = m[-1]
        texte_total = json.dumps(e, ensure_ascii=False)
        if 'Essai à blanc' in texte_total or 'simulated build failure' in texte_total:
            pb["trace de l'essai à blanc"].append(e['id'])
        if not (final.get('raisonnement') or '').strip():
            pb['raisonnement vide'].append(e['id'])
        if not final['content'].strip():
            pb['réponse vide'].append(e['id'])
        for nom, texte in (('raisonnement', final.get('raisonnement') or ''), ('réponse', final['content'])):
            if IDENTITE.search(texte):
                pb[f'nom de modèle dans le {nom}'].append(e['id'])
            if CJK.search(texte):
                pb[f'caractères chinois ou japonais dans le {nom}'].append(e['id'])
        if MARQUES.search(final['content']):
            pb['repères === dans la réponse apprise'].append(e['id'])
        if re.search(r'exercism|polyglot', final['content'] + (final.get('raisonnement') or ''), re.I):
            pb['Exercism ou polyglot cité'].append(e['id'])
        t = taches[e['exercice']]
        fichiers = EN.PP.extraire_fichiers(final['content'], EN.PP.modifiables(t))
        if not fichiers:
            pb['aucun fichier reconnu dans la réponse'].append(e['id'])
        longueurs[e['type']]['invite'].append(len(m[0]['content']))
        longueurs[e['type']]['raisonnement'].append(len(final.get('raisonnement') or ''))
        longueurs[e['type']]['reponse'].append(len(final['content']))

    # réparations de bogues : le rapport d'auteur ne doit pas être dans l'invite ; taille de la correction
    tailles, retour_exact = [], 0
    for e in exemples:
        if not e['type'].startswith('reparer_bogue_'):
            continue
        b, r = inj[e['exercice']], rep[e['exercice']]
        if b.get('bogue') and b['bogue'].strip() and b['bogue'].strip() in e['messages'][0]['content']:
            pb["description du bogue (auteur) dans l'invite"].append(e['id'])
        t = taches[e['exercice']]
        casses = {s: b['contenus'].get(s, '') for s in EN.PP.modifiables(t)}
        repares = {s: r['contenus'].get(s, casses[s]) for s in EN.PP.modifiables(t)}
        tailles.append(sum(lignes_changees(casses[s], repares[s]) for s in casses))
        sol = {**e1.get(e['exercice'], {}).get('contenus', {}), **(e2.get(e['exercice'], {}).get('contenus', {})
                                                                    if e2.get(e['exercice'], {}).get('reussi') else {})}
        retour_exact += all(repares[s].strip() == sol.get(s, repares[s]).strip() for s in repares)

    # difficulté : réussite de GLM au premier essai selon la difficulté annoncée
    diff = collections.defaultdict(lambda: [0, 0])
    for i, r in e1.items():
        d = taches[i]['difficulte']
        diff[d][0] += r['reussi']
        diff[d][1] += 1

    res = {
        'exemples': len(exemples),
        'par_type': dict(collections.Counter(e['type'] for e in exemples)),
        'controles_en_defaut': {k: {'nombre': len(v), 'exemples': v[:8]} for k, v in sorted(pb.items())},
        'longueurs_caracteres': {ty: {k: resume(v) for k, v in d.items()} for ty, d in longueurs.items()},
        'reparations_bogues': {'lignes_changees': resume(tailles), 'identiques_a_la_solution_de_GLM': retour_exact,
                               'total': len(tailles)},
        'reussite_glm_essai1_par_difficulte': {d: f'{a}/{b}' for d, (a, b) in diff.items()},
        'demandes_utilisees': dict(collections.Counter(EN.choix(i, len(EN.DEMANDES)) for i in e1)),
    }
    SORTIE.mkdir(parents=True, exist_ok=True)
    (SORTIE / 'audit_donnees_20261023.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n',
                                                        encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))

    # échantillon stratifié à relire : 2 par type, langages variés (graine fixe)
    rng = random.Random(20261023)
    choisis = []
    for ty in sorted(res['par_type']):
        candidats = [e for e in exemples if e['type'] == ty]
        rng.shuffle(candidats)
        vus = set()
        for e in candidats:
            if e['langage'] not in vus:
                choisis.append(e)
                vus.add(e['langage'])
            if len(vus) == 2:
                break
    morceaux = []
    for e in choisis:
        final = e['messages'][-1]
        morceaux.append('=' * 110 + f"\n{e['id']} | {e['type']} | {e['difficulte']} | {e['titre']}\n" + '-' * 40 + ' INVITE')
        inv = e['messages'][0]['content']
        morceaux.append(inv[:1500] + ('\n[...]\n' + inv[-700:] if len(inv) > 2200 else inv[1500:]))
        if len(e['messages']) > 2:
            morceaux.append('-' * 40 + ' RELANCE\n' + e['messages'][2]['content'][:900])
        rais = final.get('raisonnement') or ''
        morceaux.append('-' * 40 + f' RAISONNEMENT ({len(rais)} car.)\n' + rais[:900] + '\n[...]\n' + rais[-600:])
        morceaux.append('-' * 40 + f" RÉPONSE ({len(final['content'])} car.)\n" + final['content'][:1800])
        if e['type'].startswith('reparer_bogue_'):
            b, r = inj[e['exercice']], rep[e['exercice']]
            for s in EN.PP.modifiables(taches[e['exercice']]):
                avant, apres = b['contenus'].get(s, ''), r['contenus'].get(s, b['contenus'].get(s, ''))
                d = '\n'.join(difflib.unified_diff(avant.splitlines(), apres.splitlines(), 'casse', 'repare', lineterm='', n=1))
                if d:
                    morceaux.append('-' * 40 + f' CORRECTION {s}\n' + d[:1500])
            morceaux.append('-' * 40 + f" BOGUE INJECTÉ (auteur) : {b.get('bogue', '')}\nRAPPORT : {b.get('rapport', '')}")
    (SORTIE / 'echantillon_donnees_20261023.txt').write_text('\n'.join(morceaux) + '\n', encoding='utf-8')
    print(f'échantillon : {len(choisis)} exemples -> echantillon_donnees_20261023.txt')
    return 0


if __name__ == '__main__':
    sys.exit(main())
