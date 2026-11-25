"""Applique la liste d'exclusion de la campagne 2 des exercices Nova (décision de l'utilisateur du 01/11/2026) : les exemples
gardés vont dans un nouveau fichier ; le fichier d'origine et la liste ne changent pas. Seule retouche : les chemins du
cluster dans les sorties de tests montrées à GLM (jamais dans une réponse apprise). Chaque exemple gardé reste sinon
identique, octet pour octet. Refuse d'écraser un résultat différent. Aucun code de modèle n'est exécuté.

Sorties : outputs/nova_122b_preparation/exercices_nova/donnees_v2_propres_20261101.jsonl et .manifeste.json
"""
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parents[2]
SOURCE = ICI / 'pilote' / 'resultats_cluster' / 'resultats' / 'exercices_nova_v2' / 'donnees.jsonl'
SORTIES = RACINE / 'outputs' / 'nova_122b_preparation' / 'exercices_nova'
LISTE = SORTIES / 'exclusions_v2_20261101.json'
PROPRES = SORTIES / 'donnees_v2_propres_20261101.jsonl'
MANIFESTE = SORTIES / 'donnees_v2_propres_20261101.manifeste.json'
# chemins vus dans les sorties de tests : la Go et les paquets Python de l'environnement du cluster
NORMALISATIONS = (
    (re.compile(r'/cluster_fs/projects/ehpc-[\w-]+/scratch/\w+/envs/nova-polyglot/go/'), '/usr/local/go/'),
    (re.compile(r'(?:\.\./)+envs/nova-polyglot/lib/'), '/usr/local/lib/'),
)
INTERDITS = re.compile(r'CLUSTER_USER|cluster_fs|ehpc-|PROJECT_ID|envs/nova|nova-polyglot|/scratch/\w+/')
echecs = []


def controle(nom: str, observe, attendu) -> None:
    ok = observe == attendu
    print(f"{'OK   ' if ok else 'ECHEC'} {nom} : {observe}" + ('' if ok else f' (attendu : {attendu})'))
    if not ok:
        echecs.append(nom)


def empreinte(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def normaliser(exemple: dict) -> int:
    """Retouche les messages montrés à GLM (pas la réponse apprise) ; renvoie le nombre de chemins remplacés."""
    total = 0
    for message in exemple['messages'][:-1]:
        for motif, remplacement in NORMALISATIONS:
            message['content'], n = motif.subn(remplacement, message['content'])
            total += n
    return total


def ecrire_sans_ecraser(chemin: Path, octets: bytes) -> str:
    if chemin.exists():
        if chemin.read_bytes() != octets:
            print(f'REFUS : {chemin.name} existe déjà avec un contenu différent '
                  f'({empreinte(chemin.read_bytes())} contre {empreinte(octets)}) ; rien n\'est écrit')
            sys.exit(2)
        return 'déjà là, identique'
    temporaire = chemin.with_name(chemin.name + '.tmp')
    temporaire.write_bytes(octets)
    temporaire.replace(chemin)
    return 'écrit'


def appliquer(source: Path, chemin_liste: Path, propres: Path, chemin_manifeste: Path, decision: str) -> int:
    octets_source, octets_liste = source.read_bytes(), chemin_liste.read_bytes()
    liste = json.loads(octets_liste.decode('utf-8'))
    exclus = liste['exclusions']
    lignes = [l for l in octets_source.decode('utf-8').split('\n') if l]
    exemples = [json.loads(l) for l in lignes]
    ids = [e['id'] for e in exemples]

    controle('exemples dans la source', len(lignes), liste['exemples'])
    controle('identifiants en double dans la source', len(ids) - len(set(ids)), 0)
    controle('exclusions inconnues de la source', sorted(set(exclus) - set(ids)), [])
    controle('taille de la liste', len(exclus), liste['exclus'])

    gardees, retouches = [], {}
    for ligne, e in zip(lignes, exemples):
        if e['id'] in exclus:
            continue
        finale = json.dumps(e['messages'][-1], ensure_ascii=False)
        n = normaliser(e)
        if n:
            retouches[e['id']] = n
            controle(f"réponse apprise inchangée dans {e['id']}", json.dumps(e['messages'][-1], ensure_ascii=False) == finale, True)
            gardees.append(json.dumps(e, ensure_ascii=False))
        else:
            gardees.append(ligne)
    octets = ''.join(l + '\n' for l in gardees).encode('utf-8')

    # contrôles sur ce qui va être écrit, relu comme un fichier
    relus = [json.loads(l) for l in octets.decode('utf-8').split('\n') if l]
    ids_relus = [e['id'] for e in relus]
    controle('exemples gardés', len(relus), liste['restent'])
    controle('source moins exclusions', len(lignes) - len(exclus), len(relus))
    controle('identifiants en double', len(ids_relus) - len(set(ids_relus)), 0)
    controle('exemples exclus encore présents', sorted(set(ids_relus) & set(exclus)), [])
    controle('ordre de la source conservé', ids_relus == [i for i in ids if i not in exclus], True)
    for cle, champ in (('restent_par_type', 'type'), ('restent_par_langage', 'langage'), ('restent_par_difficulte', 'difficulte')):
        controle(cle, dict(sorted(collections.Counter(e[champ] for e in relus).items())), dict(sorted(liste[cle].items())))
    controle('exercices différents', len({e['exercice'] for e in relus}), liste['restent_exercices'])
    controle('lignes avec un chemin ou un compte du cluster', sum(bool(INTERDITS.search(l)) for l in gardees), 0)
    source_par_id = dict(zip(ids, lignes))
    controle('lignes différentes de la source hors retouches',
             sum(l != source_par_id[i] for i, l in zip(ids_relus, gardees) if i not in retouches), 0)
    controle("réponses apprises avec raisonnement vide", sum(not (e['messages'][-1].get('raisonnement') or '').strip() for e in relus), 0)
    if echecs:
        print(f'APPLICATION=ECHEC : {len(echecs)} contrôle(s) en échec, rien n\'est écrit : {echecs}')
        return 1

    empreinte_propres = empreinte(octets)
    print(f'{propres.name} : {ecrire_sans_ecraser(propres, octets)}, {len(octets) / 1e6:.1f} Mo')
    controle('empreinte du fichier relu sur le disque', empreinte(propres.read_bytes()), empreinte_propres)
    manifeste = {
        'decision': decision,
        'source': {'chemin': source.relative_to(RACINE).as_posix(), 'exemples': len(lignes), 'sha256': empreinte(octets_source)},
        'liste': {'chemin': chemin_liste.relative_to(RACINE).as_posix(), 'exclus': len(exclus), 'sha256': empreinte(octets_liste)},
        'propres': {'chemin': propres.relative_to(RACINE).as_posix(), 'exemples': len(relus), 'octets': len(octets), 'sha256': empreinte_propres},
        'par_type': dict(sorted(collections.Counter(e['type'] for e in relus).items())),
        'par_langage': dict(sorted(collections.Counter(e['langage'] for e in relus).items())),
        'par_difficulte': dict(sorted(collections.Counter(e['difficulte'] for e in relus).items())),
        'exercices': len({e['exercice'] for e in relus}),
        'chemins_du_cluster_remplaces': {'exemples': retouches, 'par': {m.pattern: r for m, r in NORMALISATIONS}},
    }
    texte = json.dumps(manifeste, ensure_ascii=False, indent=1) + '\n'
    print(f'{chemin_manifeste.name} : {ecrire_sans_ecraser(chemin_manifeste, texte.encode("utf-8"))}')
    if echecs:
        print(f'APPLICATION=ECHEC : {echecs}')
        return 1
    print(f"APPLICATION=OK : {len(relus)} exemples gardés sur {len(lignes)} ; {sum(retouches.values())} chemins remplacés dans "
          f"{len(retouches)} exemples ; sha256 {empreinte_propres}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    return appliquer(SOURCE, LISTE, PROPRES, MANIFESTE, "accord de l'utilisateur du 01/11/2026 sur la liste d'exclusion (« oui applique la liste »)")


if __name__ == '__main__':
    sys.exit(main())
