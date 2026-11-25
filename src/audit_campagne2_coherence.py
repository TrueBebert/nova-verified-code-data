"""Suite de l'audit de la campagne 2 (01/11/2026) : énoncé et tests sont-ils d'accord ? La correction des références a
parfois tordu la solution pour passer des tests faux ; un exercice incohérent n'est réussi qu'en s'adaptant aux tests.
Mesure par exercice, par type d'exemple, et ce que retirerait chaque règle. Lecture seule, aucun code de modèle exécuté.

Sorties : outputs/nova_122b_preparation/exercices_nova/audit_coherence_v2_20261101.json et extraits_coherence_v2_20261101.txt
"""
import collections
import difflib
import json
import re
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import audit_campagne2 as A  # noqa: E402
import exercices_nova as EN  # noqa: E402

R = A.R
CONFLIT = re.compile(r"(tests?|expect\w*|assertions?) (is|are|seems?|looks?|must be|might be|may be) (wrong|incorrect|inconsistent|buggy|broken|mistaken)"
                     r"|contradict|inconsisten|disagree|conflict|\bspec\w* says .{0,120} but\b|\bbut (the )?tests? (expects?|wants?|requires?)\b", re.I)
COMMENTAIRE = re.compile(r'(//|#|/\*|^\s*\*|--)\s*.*(\btest suite\b|\bthe tests?\b|\bfinal tests?\b|\btests? (expects?|requires?|wants?)\b|\bquirk\b|\bas (the )?tests?\b)', re.I | re.M)
LITTERAL = A.LITTERAL


def fichiers_appris(e, e1, e2, rep):
    i = e['exercice']
    if e['type'].startswith('reparer_bogue_'):
        return rep[i].get('contenus', {})
    return (e2 if e['type'] == 'reparer_apres_tests' else e1)[i].get('contenus', {})


def extrait(texte, m, n=220):
    return texte[max(0, m.start() - n):m.end() + n].replace('\n', ' ')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    exemples = [json.loads(l) for l in (R / 'donnees.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    creation = EN.lire_jsonl(R / 'creation.jsonl')
    gardes = set(json.loads((R / 'taches_finales.json').read_text(encoding='utf-8'))['gardes'])
    e1, e2 = EN.lire_jsonl(R / 'resolution.essai1.jsonl'), EN.lire_jsonl(R / 'resolution.essai2.jsonl')
    inj, rep = EN.lire_jsonl(R / 'injection.jsonl'), EN.lire_jsonl(R / 'reparation.jsonl')
    taches = {i: creation[i]['entree'] for i in gardes}
    corrigees = {i for i in gardes if creation[i].get('reference_corrigee')}
    extraits = []

    # ------ références corrigées : réussite de GLM au premier essai (il n'a pas vu les tests) selon ce que dit la correction
    croise = collections.defaultdict(lambda: [0, 0])
    corr_conflit = set()
    for i in corrigees:
        c = creation[i]['correction_reference']
        rais = c.get('raisonnement') or ''
        drapeau = bool(CONFLIT.search(rais))
        if drapeau:
            corr_conflit.add(i)
        cle = 'contradiction évoquée' if drapeau else 'pas de contradiction évoquée'
        taille = 'raisonnement > 5000 car.' if len(rais) > 5000 else 'raisonnement court'
        for k in (cle, taille, f'{cle} ; {taille}'):
            croise[k][0] += e1[i]['reussi']
            croise[k][1] += 1

    # ------ deuxième essai : GLM voit la sortie des tests ; s'adapte-t-il à des tests faux ?
    e2_stat = collections.Counter()
    e2_tordus = set()
    for i, r in e2.items():
        if not r['reussi']:
            continue
        rais = r.get('raisonnement') or ''
        m = CONFLIT.search(rais)
        a = e1[i].get('contenus', {})
        b = r.get('contenus', {})
        ajoutes = [d[1:] for s in b for d in A.lignes_diff(a.get(s, ''), b[s]) if d.startswith('+')]
        litteraux = {x or y for l in ajoutes for x, y in LITTERAL.findall(l)}
        relance = r['invites'][-1] if r.get('invites') else ''
        anciens = '\n'.join(a.values())
        copies = sorted(x for x in litteraux if x in relance and x not in taches[i]['consigne'] and x not in anciens)
        code = '\n'.join(b.values())
        com = COMMENTAIRE.search(code)
        groupe = 'corrigée' if i in corrigees else 'non corrigée'
        e2_stat[groupe, 'réussis au 2e essai'] += 1
        e2_stat[groupe, 'contradiction évoquée'] += bool(m)
        e2_stat[groupe, 'commentaire de code qui parle des tests'] += bool(com)
        e2_stat[groupe, 'littéral copié de la sortie des tests'] += bool(copies)
        e2_stat[groupe, 'raisonnement > 5000 car.'] += len(rais) > 5000
        if m or com:
            e2_tordus.add(i)
            if len(extraits) < 26:
                ex = extrait(rais, m) if m else extrait(code, com, 160)
                extraits.append(f'[2e essai, {groupe}, {i}, {len(rais)} car.] {ex}')

    # ------ réponses apprises : commentaires qui parlent des tests, par type
    par_type = collections.defaultdict(collections.Counter)
    comm_ids = set()
    for e in exemples:
        code = '\n'.join(fichiers_appris(e, e1, e2, rep).values())
        final = e['messages'][-1]
        ty = e['type']
        par_type[ty]['n'] += 1
        m = COMMENTAIRE.search(code)
        if m:
            par_type[ty]['commentaire qui parle des tests'] += 1
            comm_ids.add(e['id'])
            if ty == 'ecrire' and par_type[ty]['commentaire qui parle des tests'] <= 6:
                extraits.append(f"[écrire, commentaire, {e['id']}] {extrait(code, m, 120)}")
        if CONFLIT.search(final.get('raisonnement') or ''):
            par_type[ty]['contradiction évoquée'] += 1
        if e['exercice'] in corrigees:
            par_type[ty]['exercice corrigé'] += 1

    # ------ règles candidates (retirer des exemples, sans rien effacer)
    def bilan_regle(retirer):
        gardes_ex = [e for e in exemples if not retirer(e)]
        return {'retires': len(exemples) - len(gardes_ex), 'restent': len(gardes_ex),
                'par_type': dict(collections.Counter(e['type'] for e in gardes_ex)),
                'par_langage': dict(collections.Counter(e['langage'] for e in gardes_ex))}

    def douteux(i):  # l'énoncé et les tests ne sont pas d'accord, selon une preuve indépendante ou le raisonnement
        return (i in corrigees and not e1[i]['reussi']) or i in e2_tordus

    regles = {
        'R1 exercices corrigés non réussis du premier coup retirés': bilan_regle(lambda e: e['exercice'] in corrigees and not e1[e['exercice']]['reussi']),
        'R2 = R1 + deuxièmes essais où GLM évoque une contradiction ou commente les tests': bilan_regle(lambda e: douteux(e['exercice'])),
        'R3 tous les exercices corrigés retirés': bilan_regle(lambda e: e['exercice'] in corrigees),
    }

    # ------ tests ratés par un bogue : par langage (le format de sortie ne donne pas toujours les tests réussis)
    parts = collections.defaultdict(lambda: collections.defaultdict(list))
    for b in inj.values():
        if b['statut'] == 'valide':
            p = A.part_tests_rates(b['langue'], b.get('sortie') or '')
            if p is not None:
                parts[b['niveau']][b['langue']].append(p)
    parts_res = {n: {l: {'n': len(v), 'mediane': round(sorted(v)[len(v) // 2], 3), 'tous_rates': sum(x == 1 for x in v)}
                     for l, v in sorted(d.items())} for n, d in parts.items()}

    # ------ doubles dont un endroit n'est pas touché : extraits à lire
    vus = 0
    partiels = 0
    for e in exemples:
        if not e['type'].startswith('reparer_bogue_') or inj[e['exercice']]['niveau'] != 'double':
            continue
        i = e['exercice']
        b, r = inj[i], rep[i]
        sol = {**e1[i].get('contenus', {}), **(e2.get(i, {}).get('contenus', {}) if not e1[i]['reussi'] else {})}
        for s in EN.PP.modifiables(taches[i]):
            if s not in b['contenus'] or s not in sol:
                continue
            _, restes = A.endroits_non_touches(sol[s], b['contenus'][s], r['contenus'].get(s, b['contenus'][s]))
            if restes:
                partiels += 1
                if vus < 8 and partiels % 12 == 1:
                    vus += 1
                    d0 = '\n'.join(difflib.unified_diff(sol[s].splitlines(), b['contenus'][s].splitlines(), 'juste', 'casse', lineterm='', n=0))
                    d1 = '\n'.join(difflib.unified_diff(b['contenus'][s].splitlines(), r['contenus'].get(s, b['contenus'][s]).splitlines(), 'casse', 'repare', lineterm='', n=0))
                    extraits.append(f"[double partiel, {e['id']}, {s}]\nAUTEUR : {b.get('bogue')}\n{d0[:900]}\n--- RÉPARATION\n{d1[:900]}\n--- RÉPONSE : {r['reponse'][:500]}")
                break

    # ------ contrôles isolés à lire
    for e in exemples:
        final = e['messages'][-1]
        rais, rep_txt = final.get('raisonnement') or '', final['content']
        for nom, texte in (('raisonnement', rais), ('réponse', rep_txt)):
            m = A.INJECTE.search(texte)
            if m and e['type'].startswith('reparer_bogue_'):
                extraits.append(f"[injecté dans {nom}, {e['id']}] {extrait(texte, m, 140)}")
            m = A.CJK.search(texte)
            if m:
                extraits.append(f"[CJK dans {nom}, {e['id']}] {extrait(texte, m, 100)}")
            m = re.search(r'[\x00-\x08\x0e-\x1f]', texte)
            if m:
                extraits.append(f"[contrôle dans {nom}, {e['id']}] {extrait(texte, m, 80)!r}")
            m = re.search(r'exercism|polyglot', texte, re.I)
            if m:
                extraits.append(f"[Exercism dans {nom}, {e['id']}] {extrait(texte, m, 140)}")
        if rep_txt.count('```') % 2 and sum('clôture' in x[:30] for x in extraits) < 4:
            extraits.append(f"[clôture impaire, {e['id']}] début : {rep_txt[:160]!r} ... fin : {rep_txt[-200:]!r}")

    res = {
        'gardes': len(gardes), 'corrigees_gardees': len(corrigees),
        'glm_premier_essai_selon_la_correction': {k: f'{a}/{b}' for k, (a, b) in sorted(croise.items())},
        'deuxieme_essai': {f'{g} : {k}': n for (g, k), n in sorted(e2_stat.items())},
        'reponses_apprises_par_type': {k: dict(v) for k, v in par_type.items()},
        'regles_candidates': regles,
        'part_des_tests_rates_par_langage': parts_res,
    }
    (A.SORTIE / 'audit_coherence_v2_20261101.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (A.SORTIE / 'extraits_coherence_v2_20261101.txt').write_text('\n\n'.join(extraits) + '\n', encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
