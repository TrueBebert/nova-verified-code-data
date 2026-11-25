"""Liste d'exclusion des exemples de la campagne 2 (01/11/2026), après l'audit : rien n'est effacé ni réécrit, la liste dit
quel exemple écarter et pourquoi. Elle sera appliquée à la construction des données d'entraînement. Lecture seule, aucun
code de modèle exécuté.

Sorties : outputs/nova_122b_preparation/exercices_nova/exclusions_v2_20261101.json et extraits_exclusions_v2_20261101.txt
"""
import collections
import difflib
import json
import random
import re
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import audit_campagne2 as A  # noqa: E402
import audit_campagne2_coherence as C  # noqa: E402
import exercices_nova as EN  # noqa: E402

R = A.R
META = re.compile(r'injected bug|planted|benchmark|\bpuzzle\b|\bgrader\b|\bharness\b|debugging exercise|generated (debugging |rust |go |java |python |c\+\+ )?exercise'
                  r'|constructed (puzzle|exercise)|bugs? (was|were) (intentionally|deliberately)|intentional bugs?', re.I)
COMMENTAIRE = re.compile(r'^\s*(//|#|/\*|\*|--)')
DEUX_BOGUES = re.compile(r'\b(two|both|2|second|multiple|several) (\w+ )?(bugs?|issues?|problems?|defects?|mistakes?|causes?)\b|\bbug (2|two)\b|\b(two|both) (\w+ ){0,2}(fix|bug)', re.I)


def bogues_restants(juste: str, casse: str, repare: str) -> list[list[str]]:
    """Endroits du bogue que la réparation ne touche pas du tout (une ligne d'écart près) ; les endroits faits seulement
    de commentaires, de lignes vides ou d'un changement de mise en forme ne comptent pas."""
    a, b, c = juste.splitlines(), casse.splitlines(), repare.splitlines()
    reparations = [o for o in difflib.SequenceMatcher(None, b, c).get_opcodes() if o[0] != 'equal']
    restes = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == 'equal':
            continue
        retires = [l.strip() for l in a[i1:i2] if l.strip() and not COMMENTAIRE.match(l)]
        ajoutes = [l.strip() for l in b[j1:j2] if l.strip() and not COMMENTAIRE.match(l)]
        if (not retires and not ajoutes) or ''.join(''.join(retires).split()) == ''.join(''.join(ajoutes).split()):
            continue
        if not any(i1r <= j2 + 1 and i2r >= j1 - 1 for _, i1r, i2r, _, _ in reparations):
            restes.append(ajoutes or retires)
    return restes


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    exemples = [json.loads(l) for l in (R / 'donnees.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    creation = EN.lire_jsonl(R / 'creation.jsonl')
    gardes = set(json.loads((R / 'taches_finales.json').read_text(encoding='utf-8'))['gardes'])
    e1, e2 = EN.lire_jsonl(R / 'resolution.essai1.jsonl'), EN.lire_jsonl(R / 'resolution.essai2.jsonl')
    inj, rep = EN.lire_jsonl(R / 'injection.jsonl'), EN.lire_jsonl(R / 'reparation.jsonl')
    taches = {i: creation[i]['entree'] for i in gardes}
    corrigees = {i for i in gardes if creation[i].get('reference_corrigee')}

    pollues = {i for i, r in e1.items() if not r['reussi'] and re.search(r'^\s*```', '\n'.join(r.get('contenus', {}).values()), re.M)}
    contradiction2 = {i for i, r in e2.items() if r['reussi'] and C.CONFLIT.search(r.get('raisonnement') or '')}
    raisons = collections.defaultdict(list)
    extraits = []
    rng = random.Random(20261101)
    restants, double_restants = [], collections.Counter()

    for e in exemples:
        i = e['exercice']
        final = e['messages'][-1]
        rais, texte = final.get('raisonnement') or '', final['content']
        if i in corrigees and not e1[i]['reussi']:
            raisons[e['id']].append('exercice corrigé que GLM ne réussit pas du premier coup (énoncé et tests sans doute en désaccord)')
        if i in contradiction2 and i not in corrigees:
            raisons[e['id']].append('au deuxième essai, GLM évoque une contradiction entre énoncé et tests')
        if e['type'] == 'reparer_apres_tests' and i in pollues:
            raisons[e['id']].append("premier essai raté à cause de l'extraction des fichiers (clôture ``` dans le fichier)")
        m = META.search(rais) or META.search(texte)
        if m:
            raisons[e['id']].append('parle du test ou de l\'exercice lui-même (' + m[0].lower() + ')')
            if rng.random() < 0.15:
                s = rais if META.search(rais) else texte
                extraits.append(f"[méta, {e['id']}] {C.extrait(s, META.search(s), 130)}")
        if not rais.strip():
            raisons[e['id']].append('raisonnement vide')
        if A.CJK.search(rais + texte):
            raisons[e['id']].append('caractères chinois ou japonais')
        if re.search(r'exercism|polyglot', rais + texte, re.I):
            raisons[e['id']].append('Exercism cité')
        if texte.count('```') % 2 and e['id'] not in raisons:
            raisons[e['id']].append('bloc de code non refermé')
        if e['type'].startswith('reparer_bogue_'):
            b, r = inj[i], rep[i]
            sol = {**e1[i].get('contenus', {}), **(e2.get(i, {}).get('contenus', {}) if not e1[i]['reussi'] else {})}
            restes = []
            for s in EN.PP.modifiables(taches[i]):
                if s in b['contenus'] and s in sol:
                    restes += bogues_restants(sol[s], b['contenus'][s], r['contenus'].get(s, b['contenus'][s]))
            annonce_deux = DEUX_BOGUES.search(r['reponse']) or DEUX_BOGUES.search(r.get('raisonnement') or '')
            reste = bool(restes) and b['niveau'] == 'double' and not annonce_deux
            double_restants[b['niveau'], reste] += 1
            if reste:
                raisons[e['id']].append('bogue double : un des deux bogues reste dans le code réparé (les tests ne le voient pas)')
                restants.append((e['id'], b, restes, r))

    for eid, b, restes, r in rng.sample(restants, min(16, len(restants))):
        extraits.append(f"[bogue restant, {eid}, {b['niveau']}]\nAUTEUR : {b.get('bogue')}\nRESTE : {restes}\nRÉPONSE : {r['reponse'][:350]}")

    gardes_ex = [e for e in exemples if e['id'] not in raisons]
    compte = collections.Counter(x for v in raisons.values() for x in v)
    compte_court = collections.Counter(re.sub(r' \(.*', '', x) for x in compte.elements())
    par_exercice = {k: f"{sum(e1[i]['reussi'] for i in gardes if taches[i]['difficulte'] == k and i not in corrigees)}/"
                       f"{sum(1 for i in gardes if taches[i]['difficulte'] == k and i not in corrigees)}" for k in ('moyen', 'difficile')}
    sans_pollution = [i for i in gardes if i not in corrigees]
    res = {
        'exemples': len(exemples), 'exclus': len(raisons), 'restent': len(gardes_ex),
        'raisons_cumulables': dict(compte_court.most_common()),
        'restent_par_type': dict(collections.Counter(e['type'] for e in gardes_ex)),
        'restent_par_langage': dict(collections.Counter(e['langage'] for e in gardes_ex)),
        'restent_par_difficulte': dict(collections.Counter(e['difficulte'] for e in gardes_ex)),
        'restent_exercices': len({e['exercice'] for e in gardes_ex}),
        'bogue_restant_par_niveau': {f'{n} {"reste" if v else "corrigé"}': c for (n, v), c in sorted(double_restants.items())},
        'premier_essai_rate_par_extraction': len(pollues),
        'glm_premier_essai_exercices_non_corriges_par_difficulte': par_exercice,
        'glm_premier_essai_non_corriges_extraction_comptee_comme_reussie_au_plus': f"{sum(e1[i]['reussi'] or i in pollues for i in sans_pollution)}/{len(sans_pollution)}",
        'raisonnement_reparation_apres_exclusion': {
            niv: A.resume([len(e['messages'][-1].get('raisonnement') or '') for e in gardes_ex
                           if e['type'].startswith('reparer_bogue_') and inj[e['exercice']]['niveau'] == niv])
            for niv in ('subtil', 'double')},
        'exclusions': {k: v for k, v in sorted(raisons.items())},
    }
    (A.SORTIE / 'exclusions_v2_20261101.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (A.SORTIE / 'extraits_exclusions_v2_20261101.txt').write_text('\n\n'.join(extraits) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in res.items() if k != 'exclusions'}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
