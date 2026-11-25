"""Audit des données de la campagne 2 des exercices Nova (01/11/2026), sur le PC, avant tout entraînement : mêmes contrôles
que l'audit de l'essai (audit_donnees_exercices.py), plus l'encodage, les références corrigées, les bogues par niveau, et
la réparation de chaque endroit des bogues doubles. Tout est lu comme du texte : aucun code de modèle n'est exécuté.

Sorties : outputs/nova_122b_preparation/exercices_nova/audit_donnees_v2_20261101.json et echantillon_v2_20261101.txt
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

TRAVAIL = ICI / 'pilote' / 'resultats_cluster'
R = TRAVAIL / 'resultats' / 'exercices_nova_v2'
R1 = TRAVAIL / EN.RESULTATS
SORTIE = ICI.parents[2] / 'outputs' / 'nova_122b_preparation' / 'exercices_nova'
CJK = re.compile(r'[぀-ヿ㐀-鿿가-힯]')
IDENTITE = re.compile(r'\bGLM\b|ChatGLM|Zhipu|Z\.ai|\bQwen\b|\bClaude\b|OpenAI|\bChatGPT\b|\bGPT-[345]', re.I)
MARQUES = re.compile(r'^=== *(FILE|BUG|REPORT|END|TITLE|STUB|TEST|SOLUTION)\b', re.M)
MOJIBAKE = re.compile('Ã[\x80-\xbf]|â€|Â[\xa0-\xbf]|�')
CLUSTER = re.compile(r'CLUSTER_USER|cluster_fs|ehpc-|/scratch/|envs/nova')
TRICHE = re.compile(r'hard-?cod|special[- ]cas|just to pass|only to pass|make the tests? pass\b.*\b(even|regardless|anyway)|workaround|\bhack\b', re.I)
CONFLIT = re.compile(r"(tests?|expect\w*) (is|are|seems?|looks?) (wrong|incorrect|inconsistent)|contradict|inconsisten|"
                     r'disagree|conflict|spec\w* says .{0,80} but', re.I)
INJECTE = re.compile(r'\binject|\bintroduced? (a |the |two )?bugs?\b|deliberate|on purpose|debugging exercise', re.I)
INDICE = re.compile(r'(//|#|/\*|--)\s*.*\b(bug|bugs|fixme|wrong|incorrect|should be|mistake|oops)\b', re.I)
LITTERAL = re.compile(r'"([^"\n]{4,})"|\b(\d{3,})\b')


def resume(x):
    x = sorted(x)
    if not x:
        return {}
    return {'n': len(x), 'min': x[0], 'mediane': st.median(x), 'q90': x[int(0.9 * (len(x) - 1))], 'max': x[-1]}


def lignes_diff(a: str, b: str) -> list[str]:
    return [d for d in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm='', n=0)
            if d[:1] in '+-' and not d.startswith(('+++', '---'))]


def endroits_non_touches(juste: str, casse: str, repare: str) -> tuple[int, int]:
    """Endroits où le bogue a été injecté (juste -> cassé) et, parmi eux, ceux que la réparation ne touche pas."""
    a, b, c = juste.splitlines(), casse.splitlines(), repare.splitlines()
    bogues = [o for o in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != 'equal']
    reparations = [o for o in difflib.SequenceMatcher(None, b, c, autojunk=False).get_opcodes() if o[0] != 'equal']
    restes = 0
    for _, _, _, j1, j2 in bogues:
        if not any(i1 <= j2 and i2 >= j1 for _, i1, i2, _, _ in reparations):
            restes += 1
    return len(bogues), restes


def part_tests_rates(langue: str, sortie: str) -> float | None:
    """Part des tests ratés lue dans la sortie, quand le format la donne."""
    motifs = {'python': (r'(\d+) failed', r'(\d+) passed'), 'javascript': (r'Tests:\s+(\d+) failed', r'(\d+) passed'),
              'rust': (r'test result: FAILED\. \d+ passed; (\d+) failed', r'test result: FAILED\. (\d+) passed'),
              'cpp': (r'\|\s*(\d+) failed', r'test cases:\s*\d+ \|\s*(\d+) passed')}
    if langue == 'go':
        rates, reussis = len(re.findall(r'^\s*--- FAIL', sortie, flags=re.M)), len(re.findall(r'^\s*--- PASS', sortie, flags=re.M))
    elif langue in motifs:
        m1, m2 = re.search(motifs[langue][0], sortie), re.search(motifs[langue][1], sortie)
        if not m1:
            return None
        rates, reussis = int(m1[1]), int(m2[1]) if m2 else 0
    else:
        return None
    return rates / (rates + reussis) if rates + reussis else None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    exemples = [json.loads(l) for l in (R / 'donnees.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    creation = EN.lire_jsonl(R / 'creation.jsonl')
    finales = json.loads((R / 'taches_finales.json').read_text(encoding='utf-8'))
    gardes = set(finales['gardes'])
    taches = {i: r['entree'] for i, r in creation.items() if 'entree' in r}
    e1, e2 = EN.lire_jsonl(R / 'resolution.essai1.jsonl'), EN.lire_jsonl(R / 'resolution.essai2.jsonl')
    inj, rep = EN.lire_jsonl(R / 'injection.jsonl'), EN.lire_jsonl(R / 'reparation.jsonl')
    pb = collections.defaultdict(list)

    # ------------------------------------------------------------ contrôles sur chaque exemple
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
        if e['exercice'] not in gardes:
            pb['exercice écarté par le filtre'].append(e['id'])
        final = m[-1]
        rais = final.get('raisonnement') or ''
        tout = json.dumps(e, ensure_ascii=False)
        if 'Essai à blanc' in tout or 'simulated build failure' in tout:
            pb["trace de l'essai à blanc"].append(e['id'])
        if MOJIBAKE.search(tout):
            pb['encodage abîmé (mojibake) quelque part'].append(e['id'])
        if MOJIBAKE.search(final['content'] + rais):
            pb['encodage abîmé (mojibake) dans la réponse apprise'].append(e['id'])
        if re.search(r'[\x00-\x08\x0e-\x1f]', final['content'] + rais):
            pb['caractères de contrôle dans la réponse apprise'].append(e['id'])
        if not rais.strip():
            pb['raisonnement vide'].append(e['id'])
        if not final['content'].strip():
            pb['réponse vide'].append(e['id'])
        for nom, texte in (('raisonnement', rais), ('réponse', final['content'])):
            if IDENTITE.search(texte):
                pb[f'nom de modèle dans le {nom}'].append(e['id'])
            if CJK.search(texte):
                pb[f'caractères chinois ou japonais dans le {nom}'].append(e['id'])
            if CLUSTER.search(texte):
                pb[f'chemin ou compte du cluster dans le {nom}'].append(e['id'])
            if TRICHE.search(texte):
                pb[f'mot de triche possible dans le {nom}'].append(e['id'])
            if INJECTE.search(texte) and e['type'].startswith('reparer_bogue_'):
                pb[f'bogue dit injecté, ou exprès, dans le {nom}'].append(e['id'])
        if any(CLUSTER.search(x['content']) for x in m[:-1]):
            pb['chemin ou compte du cluster dans une invite'].append(e['id'])
        if MARQUES.search(final['content']):
            pb['repères === dans la réponse apprise'].append(e['id'])
        if re.search(r'exercism|polyglot', final['content'] + rais, re.I):
            pb['Exercism ou polyglot cité'].append(e['id'])
        if final['content'].count('```') % 2:
            pb['bloc de code non refermé dans la réponse'].append(e['id'])
        t = taches[e['exercice']]
        if not EN.PP.extraire_fichiers(final['content'], EN.PP.modifiables(t)):
            pb['aucun fichier reconnu dans la réponse'].append(e['id'])
        source = rep if e['type'].startswith('reparer_bogue_') else e2 if e['type'] == 'reparer_apres_tests' else e1
        if source[e['exercice']].get('fin') != 'stop':
            pb['réponse coupée par la limite de jetons'].append(e['id'])
        longueurs[e['type']]['invite'].append(len(m[0]['content']))
        longueurs[e['type']]['raisonnement'].append(len(rais))
        longueurs[e['type']]['reponse'].append(len(final['content']))

    # ------------------------------------------------------------ références corrigées
    corrigees = {i for i, r in creation.items() if r.get('reference_corrigee') and r.get('statut') == 'valide'}
    tentees = [r for r in creation.values() if 'correction_reference' in r]
    suspects, tailles_corr, conflits = [], [], []
    for i in corrigees:
        r = creation[i]
        c = r['correction_reference']
        t = r['entree']
        avant = EN.lire_sections(r['reponse'])['solution']
        apres = EN.PP.extraire_fichiers(c['reponse'], EN.PP.modifiables(t))
        diff = [d for s in apres for d in lignes_diff(avant.get(s, ''), apres[s])]
        tailles_corr.append(len(diff))
        doss = TRAVAIL / t['dossier']
        tests = ''.join((doss / x).read_text(encoding='utf-8', errors='replace') for x in t['test'] if (doss / x).is_file())
        ajoutes = [d[1:] for d in diff if d.startswith('+')]
        litteraux = {a or b for l in ajoutes for a, b in LITTERAL.findall(l)}
        copies = sorted(x for x in litteraux if x in tests and x not in t['consigne'] and x not in '\n'.join(avant.values()))
        mot = TRICHE.search((c.get('raisonnement') or '') + c['reponse'])
        if CONFLIT.search(c.get('raisonnement') or ''):
            conflits.append(i)
        if copies or mot:
            suspects.append({'id': i, 'litteraux_copies_des_tests': copies[:6], 'mot': mot[0] if mot else None, 'lignes': len(diff)})

    def taux(ensemble, fichier):
        n = [fichier[i]['reussi'] for i in ensemble if i in fichier]
        return f'{sum(n)}/{len(n)}'

    garde_corr = gardes & corrigees
    garde_norm = gardes - corrigees

    # ------------------------------------------------------------ bogues par niveau
    par_niveau = {}
    for niv in ('subtil', 'double'):
        lignes = [b for b in inj.values() if b['niveau'] == niv]
        valides = [b for b in lignes if b['statut'] == 'valide']
        rejets = collections.Counter(re.sub(r'^\d+ ', 'N ', b.get('raison') or '') for b in lignes if b['statut'] != 'valide')
        repares = [b['id'] for b in valides if rep.get(b['id'], {}).get('reussi')]
        ex = [e for e in exemples if e['type'].startswith('reparer_bogue_') and inj[e['exercice']]['niveau'] == niv]
        parts = [p for p in (part_tests_rates(b['langue'], b.get('sortie') or '') for b in valides) if p is not None]
        par_niveau[niv] = {
            'essayes': len(lignes), 'valides': len(valides), 'rejets': dict(rejets), 'repares': len(repares),
            'lignes_changees': resume([b['lignes_changees'] for b in valides]),
            'endroits_changes': resume([b['endroits_changes'] for b in valides]),
            'raisonnement_reparation_caracteres': resume([len(e['messages'][-1].get('raisonnement') or '') for e in ex]),
            'part_des_tests_rates': {'n': len(parts), 'mediane': round(st.median(parts), 3) if parts else None,
                                     'q90': round(sorted(parts)[int(0.9 * (len(parts) - 1))], 3) if parts else None,
                                     'tous_rates': sum(p == 1 for p in parts)},
            'jetons_reparation': resume([rep[i]['jetons'] for i in repares]),
        }
    indices = []
    for b in inj.values():
        if b['statut'] != 'valide':
            continue
        t = taches[b['id']]
        sol = {**e1[b['id']].get('contenus', {}), **(e2.get(b['id'], {}).get('contenus', {}) if not e1[b['id']]['reussi'] else {})}
        for s in EN.PP.modifiables(t):
            if s in b['contenus'] and s in sol:
                if any(d.startswith('+') and INDICE.search(d) for d in lignes_diff(sol[s], b['contenus'][s])):
                    indices.append(b['id'])
                    break
    rapports_fuite = [b['id'] for b in inj.values() if b['statut'] == 'valide' and INJECTE.search(b.get('rapport') or '')]

    # réparations : taille, retour exact, et pour les doubles, endroits laissés tels quels (bogue que les tests ne voient plus)
    tailles, retour, doubles_partiels, endroits_totaux, reste_lignes = [], collections.Counter(), [], 0, 0
    for e in exemples:
        if not e['type'].startswith('reparer_bogue_'):
            continue
        i = e['exercice']
        b, r, t = inj[i], rep[i], taches[i]
        if b.get('bogue') and b['bogue'].strip() and b['bogue'].strip() in e['messages'][0]['content']:
            pb["description du bogue (auteur) dans l'invite"].append(e['id'])
        sol = {**e1[i].get('contenus', {}), **(e2.get(i, {}).get('contenus', {}) if not e1[i]['reussi'] else {})}
        mod = [s for s in EN.PP.modifiables(t) if s in b['contenus']]
        repares = {s: r['contenus'].get(s, b['contenus'][s]) for s in mod}
        tailles.append(sum(len(lignes_diff(b['contenus'][s], repares[s])) for s in mod))
        retour[b['niveau'], all(repares[s].strip() == sol.get(s, repares[s]).strip() for s in mod)] += 1
        if b['niveau'] == 'double':
            total, restes = 0, 0
            for s in mod:
                if s in sol:
                    a, c = endroits_non_touches(sol[s], b['contenus'][s], repares[s])
                    total += a
                    restes += c
            endroits_totaux += total
            reste_lignes += restes
            if restes:
                doubles_partiels.append({'id': i, 'endroits': total, 'non_touches': restes})

    # ------------------------------------------------------------ réussite, thèmes, tests, doublons
    diff, dif_e2 = collections.defaultdict(lambda: [0, 0]), collections.defaultdict(lambda: [0, 0])
    for i, r in e1.items():
        d = taches[i]['difficulte']
        diff[d][0] += r['reussi']
        diff[d][1] += 1
    for i, r in e2.items():
        d = taches[i]['difficulte']
        dif_e2[d][0] += r['reussi']
        dif_e2[d][1] += 1
    domaines = collections.Counter(creation[i]['domaine'] for i in gardes)
    genres = collections.Counter(creation[i]['genre'] for i in gardes)
    titres = collections.Counter((taches[i]['langue'], creation[i]['entree'].get('titre', '')) for i in gardes)
    anciens = {r['entree'].get('consigne', '') for r in EN.lire_jsonl(R1 / 'creation.jsonl').values() if 'entree' in r}
    consignes = collections.Counter(taches[i]['consigne'] for i in gardes)
    tests_par_langue = collections.defaultdict(list)
    for i in gardes:
        tests_par_langue[taches[i]['langue']].append(creation[i].get('nombre_tests', 0))

    res = {
        'exemples': len(exemples),
        'par_type': dict(collections.Counter(e['type'] for e in exemples)),
        'par_langage': dict(collections.Counter(e['langage'] for e in exemples)),
        'par_difficulte': dict(collections.Counter(e['difficulte'] for e in exemples)),
        'controles_en_defaut': {k: {'nombre': len(v), 'exemples': v[:8]} for k, v in sorted(pb.items())},
        'longueurs_caracteres': {ty: {k: resume(v) for k, v in d.items()} for ty, d in longueurs.items()},
        'references': {
            'tentees': len(tentees), 'sauvees_valides': len(corrigees), 'gardees': len(garde_corr),
            'lignes_changees': resume(tailles_corr), 'suspects_heuristique': len(suspects), 'detail_suspects': suspects[:30],
            'conflit_enonce_tests_dans_le_raisonnement': len(conflits),
            'glm_premier_essai_corrigees': taux(garde_corr, e1), 'glm_premier_essai_autres': taux(garde_norm, e1),
            'glm_deuxieme_essai_corrigees': taux(garde_corr, e2), 'glm_deuxieme_essai_autres': taux(garde_norm, e2),
        },
        'bogues_par_niveau': par_niveau,
        'indice_dans_le_code_casse': {'nombre': len(indices), 'exemples': indices[:8]},
        'rapport_qui_dit_injecte': {'nombre': len(rapports_fuite), 'exemples': rapports_fuite[:8]},
        'reparations': {
            'lignes_changees': resume(tailles),
            'retour_exact_solution_glm': {f'{n} {"oui" if v else "non"}': c for (n, v), c in sorted(retour.items())},
            'doubles_endroits_total': endroits_totaux, 'doubles_endroits_non_touches': reste_lignes,
            'doubles_avec_un_endroit_non_touche': len(doubles_partiels), 'exemples_partiels': doubles_partiels[:10],
        },
        'glm_essai1_par_difficulte': {d: f'{a}/{b}' for d, (a, b) in diff.items()},
        'glm_essai2_par_difficulte': {d: f'{a}/{b}' for d, (a, b) in dif_e2.items()},
        'themes': {'differents': len(domaines), 'gardes_par_theme': resume(list(domaines.values())),
                   'genres': {k[:45]: v for k, v in genres.most_common()}},
        'titres_repetes_dans_un_langage': sum(1 for n in titres.values() if n > 1),
        'enonces_identiques': {'dans_la_campagne': sum(1 for n in consignes.values() if n > 1),
                               'avec_l_essai': sum(1 for c in consignes if c in anciens)},
        'nombre_de_tests': {k: resume(v) for k, v in sorted(tests_par_langue.items())},
        'demandes_utilisees': dict(collections.Counter(EN.choix(i, len(EN.DEMANDES)) for i in e1)),
    }
    SORTIE.mkdir(parents=True, exist_ok=True)
    (SORTIE / 'audit_donnees_v2_20261101.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))

    # ------------------------------------------------------------ échantillon à relire (graine fixe)
    rng = random.Random(20261101)
    morceaux = []

    def ajouter_exemple(e):
        final = e['messages'][-1]
        niveau = inj[e['exercice']]['niveau'] if e['type'].startswith('reparer_bogue_') else ''
        morceaux.append('=' * 110 + f"\n{e['id']} | {e['type']} {niveau} | {e['difficulte']} | {e['titre']}\n" + '-' * 40 + ' INVITE')
        inv = e['messages'][0]['content']
        morceaux.append(inv[:1300] + ('\n[...]\n' + inv[-500:] if len(inv) > 1800 else inv[1300:]))
        if len(e['messages']) > 2:
            morceaux.append('-' * 40 + ' RELANCE\n' + e['messages'][2]['content'][:800])
        rais = final.get('raisonnement') or ''
        morceaux.append('-' * 40 + f' RAISONNEMENT ({len(rais)} car.)\n' + rais[:900] + ('\n[...]\n' + rais[-400:] if len(rais) > 1300 else ''))
        morceaux.append('-' * 40 + f" RÉPONSE ({len(final['content'])} car.)\n" + final['content'][:1000])
        if e['type'].startswith('reparer_bogue_'):
            b, r = inj[e['exercice']], rep[e['exercice']]
            i = e['exercice']
            sol = {**e1[i].get('contenus', {}), **(e2.get(i, {}).get('contenus', {}) if not e1[i]['reussi'] else {})}
            for s in EN.PP.modifiables(taches[i]):
                if s not in b['contenus']:
                    continue
                d0 = '\n'.join(difflib.unified_diff(sol.get(s, '').splitlines(), b['contenus'][s].splitlines(), 'juste', 'casse', lineterm='', n=0))
                d1 = '\n'.join(difflib.unified_diff(b['contenus'][s].splitlines(), r['contenus'].get(s, b['contenus'][s]).splitlines(), 'casse', 'repare', lineterm='', n=0))
                if d0:
                    morceaux.append('-' * 40 + f' BOGUE {s}\n' + d0[:1200])
                if d1:
                    morceaux.append('-' * 40 + f' RÉPARATION {s}\n' + d1[:1200])
            morceaux.append(f"AUTEUR : {b.get('bogue', '')}\nRAPPORT : {b.get('rapport', '')[:600]}")

    for ty in sorted(res['par_type']):
        candidats = [e for e in exemples if e['type'] == ty]
        rng.shuffle(candidats)
        vus = set()
        for e in candidats:
            if e['langage'] not in vus:
                ajouter_exemple(e)
                vus.add(e['langage'])
            if len(vus) == 2:
                break
    for niv in ('subtil', 'double'):
        candidats = [e for e in exemples if e['type'].startswith('reparer_bogue_') and inj[e['exercice']]['niveau'] == niv]
        rng.shuffle(candidats)
        vus = set()
        for e in candidats:
            if e['langage'] not in vus:
                ajouter_exemple(e)
                vus.add(e['langage'])
            if len(vus) == 3:
                break

    def ajouter_correction(i, titre):
        r = creation[i]
        c = r['correction_reference']
        t = r['entree']
        avant = EN.lire_sections(r['reponse'])['solution']
        apres = EN.PP.extraire_fichiers(c['reponse'], EN.PP.modifiables(t))
        rais = c.get('raisonnement') or ''
        morceaux.append('=' * 110 + f'\n{titre} {i}\n' + '-' * 40 + f' RAISONNEMENT ({len(rais)} car.)\n' + rais[:1500]
                        + ('\n[...]\n' + rais[-500:] if len(rais) > 2000 else ''))
        for s in apres:
            d = '\n'.join(difflib.unified_diff(avant.get(s, '').splitlines(), apres[s].splitlines(), 'avant', 'corrige', lineterm='', n=1))
            morceaux.append('-' * 40 + f' CORRECTION {s}\n' + d[:1800])

    ordre = sorted(garde_corr)
    rng.shuffle(ordre)
    for i in ordre[:6]:
        ajouter_correction(i, 'RÉFÉRENCE CORRIGÉE (au hasard)')
    sus = sorted(suspects, key=lambda x: (not x['mot'], -len(x['litteraux_copies_des_tests'])))
    for x in sus[:10]:
        ajouter_correction(x['id'], f"RÉFÉRENCE SUSPECTE ({x['mot']} ; {x['litteraux_copies_des_tests']})")
    (SORTIE / 'echantillon_v2_20261101.txt').write_text('\n'.join(morceaux) + '\n', encoding='utf-8')
    print('échantillon -> echantillon_v2_20261101.txt', len('\n'.join(morceaux)), 'caractères')
    return 0


if __name__ == '__main__':
    sys.exit(main())
