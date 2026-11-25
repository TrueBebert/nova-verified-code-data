"""Mêmes règles d'exclusion que la campagne 2 pour les 541 exemples de l'essai de 600 (01/11/2026, « fais la suite » de
l'utilisateur après le tri proposé) : l'essai n'a ni référence corrigée ni bogue double, restent les autres règles. Écrit la
liste, puis le fichier propre avec appliquer_exclusions_v2 ; la source n'est que lue. Aucun code de modèle n'est exécuté.

Sorties : outputs/nova_122b_preparation/exercices_nova/exclusions_v1_20261101.json, donnees_v1_propres_20261101.jsonl et
son manifeste.
"""
import collections
import json
import re
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import appliquer_exclusions_v2 as APPLI  # noqa: E402
import audit_campagne2 as A  # noqa: E402
import audit_campagne2_coherence as C  # noqa: E402
import audit_campagne2_exclusions as X  # noqa: E402
import exercices_nova as EN  # noqa: E402

R = A.R1
LISTE = A.SORTIE / 'exclusions_v1_20261101.json'


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    exemples = [json.loads(l) for l in (R / 'donnees.jsonl').read_bytes().decode('utf-8').split('\n') if l]
    gardes = set(json.loads((R / 'taches_finales.json').read_text(encoding='utf-8'))['gardes'])
    e1, e2 = EN.lire_jsonl(R / 'resolution.essai1.jsonl'), EN.lire_jsonl(R / 'resolution.essai2.jsonl')
    pollues = {i for i, r in e1.items() if not r['reussi'] and re.search(r'^\s*```', '\n'.join(r.get('contenus', {}).values()), re.M)}
    contradiction2 = {i for i, r in e2.items() if r['reussi'] and C.CONFLIT.search(r.get('raisonnement') or '')}
    raisons = collections.defaultdict(list)
    for e in exemples:
        i = e['exercice']
        final = e['messages'][-1]
        rais, texte = final.get('raisonnement') or '', final['content']
        if i not in gardes:
            raisons[e['id']].append('exercice écarté par le filtre')
        if i in contradiction2:
            raisons[e['id']].append('au deuxième essai, GLM évoque une contradiction entre énoncé et tests')
        if e['type'] == 'reparer_apres_tests' and i in pollues:
            raisons[e['id']].append("premier essai raté à cause de l'extraction des fichiers (clôture ``` dans le fichier)")
        m = X.META.search(rais) or X.META.search(texte)
        if m:
            raisons[e['id']].append("parle du test ou de l'exercice lui-même (" + m[0].lower() + ')')
        if not rais.strip():
            raisons[e['id']].append('raisonnement vide')
        if A.CJK.search(rais + texte):
            raisons[e['id']].append('caractères chinois ou japonais')
        if re.search(r'exercism|polyglot', rais + texte, re.I):
            raisons[e['id']].append('Exercism cité')
        if texte.count('```') % 2 and e['id'] not in raisons:
            raisons[e['id']].append('bloc de code non refermé')
    gardes_ex = [e for e in exemples if e['id'] not in raisons]
    res = {
        'exemples': len(exemples), 'exclus': len(raisons), 'restent': len(gardes_ex),
        'raisons_cumulables': dict(collections.Counter(re.sub(r' \(.*', '', x) for v in raisons.values() for x in v).most_common()),
        'restent_par_type': dict(collections.Counter(e['type'] for e in gardes_ex)),
        'restent_par_langage': dict(collections.Counter(e['langage'] for e in gardes_ex)),
        'restent_par_difficulte': dict(collections.Counter(e['difficulte'] for e in gardes_ex)),
        'restent_exercices': len({e['exercice'] for e in gardes_ex}),
        'exclusions': {k: v for k, v in sorted(raisons.items())},
    }
    texte_liste = json.dumps(res, ensure_ascii=False, indent=1) + '\n'
    print(f'{LISTE.name} : {APPLI.ecrire_sans_ecraser(LISTE, texte_liste.encode("utf-8"))}')
    print(json.dumps({k: v for k, v in res.items() if k != 'exclusions'}, ensure_ascii=False, indent=1))
    print(json.dumps(res['exclusions'], ensure_ascii=False, indent=0))
    code = APPLI.appliquer(R / 'donnees.jsonl', LISTE, A.SORTIE / 'donnees_v1_propres_20261101.jsonl',
                           A.SORTIE / 'donnees_v1_propres_20261101.manifeste.json',
                           "« fais la suite » de l'utilisateur du 01/11/2026, après le tri proposé de l'essai de 600 (mêmes règles que la campagne 2)")
    if code:
        return code
    # les deux campagnes ne doivent avoir aucun exemple en commun
    deja = {json.loads(l)['id'] for l in (A.SORTIE / 'donnees_v2_propres_20261101.jsonl').read_bytes().decode('utf-8').split('\n') if l}
    commun = deja & {e['id'] for e in gardes_ex}
    print(f'exemples communs aux deux fichiers propres : {len(commun)} ; total {len(deja) + len(gardes_ex)}')
    return 1 if commun else 0


if __name__ == '__main__':
    sys.exit(main())
