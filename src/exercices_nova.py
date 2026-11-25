"""Exercices Nova (préparés le 17/10/2026, oui de l'utilisateur pour la préparation ; heures GPU seulement après son
accord) : données d'entraînement « corriger du vrai code » pour Nova, écrites par GLM-5.3 et vérifiées par l'exécution.

1. creation : GLM-5.3 invente des exercices pratiques dans les 6 langages du banc polyglot (énoncé, fichier de départ,
   tests, solution), sur des thèmes et des genres tirés au sort. Un exercice est gardé si sa solution passe ses tests et si
   le fichier de départ les rate ; puis on écarte ce qui ressemble à Exercism (le banc polyglot en vient : il reste
   réservé à la mesure) et les doublons.
2. resolution : GLM-5.3 en effort élevé résout chaque exercice à partir de l'énoncé et du fichier de départ (tests
   cachés), avec plusieurs formulations de demande (pas celle du banc) ; second essai avec la sortie des tests.
3. injection : GLM-5.3 casse une solution juste par un bogue réaliste ; gardé si les tests le détectent sans erreur de
   compilation et si la modification est petite.
4. reparation : GLM-5.3 répare ces programmes, à partir de la sortie des tests ou d'un rapport d'utilisateur.
5. export : seules les réponses dont les tests passent deviennent des exemples (donnees.jsonl), raisonnement compris.

Les tests tournent sur les processeurs de la tâche, avec les outils de nova-polyglot (pilote_polyglot.tester) ; les
fichiers techniques de chaque langage (CMake, Gradle, Cargo, Jest...) viennent d'un exercice polyglot pris pour gabarit.
Le code écrit par un modèle ne tourne que sur le cluster, jamais sur le PC de l'utilisateur.

  python exercices_nova.py generer --config exercices_nova_v1.json --travail T [--simulation]
Codes : 0 fini, 3 à reprendre (plus le temps dans cette tâche), 4 moteur jamais prêt, 6 erreur de code (essai à blanc
avant le chargement, ou pendant les phases ; témoin professeur.erreur_code, mis de côté par le lanceur).
"""
from __future__ import annotations

import argparse
import collections
import difflib
import hashlib
import json
import os
import random
import re
import shutil
import sys
import tarfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pilote_polyglot as PP  # noqa: E402

RESULTATS = Path('resultats') / 'exercices_nova'
RESULTATS_ELEVE = Path('resultats') / 'exercices_nova_eleve'  # mesure de l'élève (23/10), jamais des données
DONNEES = Path('donnees') / 'exercices_nova'
EXERCISM = Path('donnees') / 'exercism_specs'
EXERCISM_URL = 'https://github.com/exercism/problem-specifications/archive/refs/heads/main.tar.gz'
E5 = Path('modeles') / 'multilingual-e5-small'
NOMS = {'cpp': 'C++', 'go': 'Go', 'java': 'Java', 'javascript': 'JavaScript', 'python': 'Python', 'rust': 'Rust'}
CLOTURES = {'cpp': 'cpp', 'go': 'go', 'java': 'java', 'javascript': 'javascript', 'python': 'python', 'rust': 'rust'}

# thèmes réalistes (logiciels de tous les jours), loin des énigmes classiques ; genres de code
DOMAINES = [
    ('stock-reservations', 'warehouse inventory with stock reservations and releases'),
    ('subscription-billing', 'subscription billing with plan changes and proration'),
    ('room-bookings', 'hotel room booking calendar with overlapping stays'),
    ('train-connections', 'train timetable with connections and transfer times'),
    ('shift-planner', 'employee shift scheduling with rest-time rules'),
    ('expense-claims', 'expense report validation against a company policy'),
    ('loyalty-points', 'customer loyalty points with tiers and expiry'),
    ('parcel-routing', 'parcel routing between delivery depots'),
    ('support-tickets', 'support desk ticket queue with priorities and deadlines'),
    ('feature-flags', 'feature flag rollout rules per user segment'),
    ('access-roles', 'role-based access control with inherited permissions'),
    ('layered-config', 'configuration files with sections, defaults and overrides'),
    ('log-windows', 'log line aggregation by time window and severity'),
    ('latency-stats', 'request latency statistics with percentiles'),
    ('api-throttle', 'API client rate limiting with a simulated clock'),
    ('retry-policy', 'retry policies with backoff on a simulated clock'),
    ('expiring-cache', 'a cache with entry expiry and capacity limits'),
    ('semver-ranges', 'version numbers with comparison and range matching'),
    ('build-targets', 'build target dependencies with cycle detection'),
    ('text-templates', 'text templates with placeholders, defaults and escaping'),
    ('cli-options', 'command-line option parsing with validation'),
    ('recipe-scaling', 'recipe scaling with unit conversion'),
    ('money-amounts', 'money amounts with exact decimal arithmetic and rounding rules'),
    ('tax-brackets', 'progressive tax calculation with brackets and deductions'),
    ('loan-schedule', 'loan amortization schedules'),
    ('league-fixtures', 'round-robin fixture generation with home and away balance'),
    ('elevator-dispatch', 'elevator dispatch simulation'),
    ('traffic-signals', 'traffic signal control for a road intersection'),
    ('board-turns', 'the turn engine of an original board game'),
    ('card-scoring', 'the scoring rules of an original card game'),
    ('sheet-formulas', 'spreadsheet cells with formulas and references'),
    ('record-filters', 'filter expressions evaluated over records'),
    ('sales-report', 'a sales report with grouping, subtotals and formatting'),
    ('line-diff', 'line-based comparison of two text documents'),
    ('drawing-history', 'undo and redo history for a drawing tool'),
    ('grid-collisions', 'collision checks between shapes on a grid'),
    ('warehouse-paths', 'path finding for robots on a warehouse grid'),
    ('ip-ranges', 'IP address and CIDR range utilities'),
    ('signup-validation', 'sign-up form validation with detailed error lists'),
    ('password-policy', 'password policy checking with reasons'),
    ('quest-inventory', 'inventory and weight limits for a game character'),
    ('class-timetable', 'school timetable conflict detection'),
    ('parking-fees', 'parking fees with time bands and daily caps'),
    ('event-replay', 'rebuilding account state from an event log'),
    ('order-lifecycle', 'an order lifecycle with allowed state transitions'),
    ('image-filters', 'filters on small grayscale images stored as matrices'),
    ('workout-stats', 'workout statistics for a fitness tracker'),
    ('playlist-rules', 'playlist ordering under constraints'),
    ('path-globbing', 'file path normalization and wildcard matching'),
    ('http-routing', 'HTTP-like request routing with path parameters'),
    ('nested-queries', 'path queries over nested JSON-like data'),
    ('binary-records', 'binary record encoding and decoding with checksums'),
    ('fixed-offsets', 'date and time arithmetic with fixed UTC offsets'),
    ('recurring-events', 'expansion of recurring calendar events'),
    ('auction-bids', 'auction bidding rules and winner determination'),
    ('ranked-ballots', 'ranked-choice vote counting'),
    ('seat-allocation', 'theater seat allocation with group preferences'),
    ('chem-formulas', 'chemical formula parsing and molar mass'),
    ('statement-matching', 'bank statement reconciliation against invoices'),
    ('task-pipeline', 'a job pipeline with stages, retries and failure handling'),
]
GENRES = [
    ('engine', 'a class or struct holding state, with methods that enforce the rules'),
    ('parser', 'a parser turning text input into structured data, with precise error reporting'),
    ('validator', 'a validator returning all detected problems in a defined order'),
    ('calculator', 'pure functions computing results from structured inputs'),
    ('simulator', 'a step-by-step simulation driven by explicit inputs'),
    ('planner', 'a planner or scheduler satisfying constraints'),
    ('index', 'a specialised data structure with documented invariants and operations'),
    ('interpreter', 'a small interpreter for a mini-language or rule set'),
    ('report', 'a report generator producing exactly formatted text'),
]
# campagne 2 (25/10/2026) : 140 thèmes et 3 genres de plus, pour des milliers d'exercices sans répéter le même thème dans
# un langage (les listes de l'essai restent celles ci-dessus) ; écartés car trop proches d'exercices d'Exercism : classement
# de championnat, rendu de monnaie, comptage de mots, numéros de téléphone, tableaux Markdown, jeux de dés
DOMAINES_V2 = DOMAINES + [
    ('invoice-numbering', 'invoice numbering with yearly sequences and gap detection'),
    ('vat-returns', 'VAT return computation from sales and purchase lines'),
    ('payroll-slips', 'payroll slips with overtime, bonuses and deductions'),
    ('currency-exchange', 'currency conversion with dated exchange rates'),
    ('budget-envelopes', 'envelope budgeting with monthly carry-over'),
    ('split-bills', 'splitting shared expenses between friends and settling debts'),
    ('stock-portfolio', 'stock portfolio positions with average cost and realized gains'),
    ('credit-scoring', 'rule-based credit scoring with explanations'),
    ('insurance-claims', 'insurance claim checks with coverage limits and deductibles'),
    ('commission-plans', 'sales commission plans with tiers and accelerators'),
    ('refund-rules', 'refund eligibility rules for online orders'),
    ('coupon-stacking', 'coupon and discount stacking rules at checkout'),
    ('shipping-rates', 'shipping rates by weight, zone and carrier rules'),
    ('cart-totals', 'shopping cart totals with taxes, discounts and rounding'),
    ('payment-dunning', 'failed payment retries and dunning schedules'),
    ('ledger-postings', 'double-entry ledger postings and trial balances'),
    ('transaction-categories', 'automatic categorization of bank transactions by rules'),
    ('price-history', 'price history with change detection and promotions'),
    ('gift-cards', 'gift card balances with partial redemptions and expiry'),
    ('rent-indexation', 'rent schedules with indexation and prorated months'),
    ('fleet-maintenance', 'vehicle fleet maintenance scheduling by mileage and date'),
    ('delivery-slots', 'home delivery slot booking with capacity per zone'),
    ('pallet-loading', 'pallet loading plans with weight and height limits'),
    ('pick-lists', 'warehouse pick list generation and batching'),
    ('returns-inspection', 'returned goods inspection and restocking decisions'),
    ('cold-chain', 'cold chain temperature log validation'),
    ('bus-timetables', 'bus timetable lookup with service days and exceptions'),
    ('ride-pooling', 'ride pooling that matches riders along a route'),
    ('bike-sharing', 'bike sharing station balancing and trip pricing'),
    ('flight-itineraries', 'flight itinerary building with minimum connection times'),
    ('port-berths', 'ship berth allocation in a port'),
    ('toll-charges', 'motorway toll charges by entry and exit'),
    ('parcel-lockers', 'parcel locker allocation and pickup codes'),
    ('route-stops', 'delivery route stop ordering with time windows'),
    ('fuel-logs', 'fuel log analysis and consumption reports'),
    ('medication-schedule', 'medication dosage schedules with intervals and limits'),
    ('clinic-appointments', 'clinic appointment booking with practitioner availability'),
    ('vaccination-records', 'vaccination record checks against a schedule'),
    ('nutrition-labels', 'nutrition labels computed from recipe ingredients'),
    ('course-grades', 'course grades with weighted averages and rounding rules'),
    ('exam-seating', 'exam seating plans with spacing constraints'),
    ('library-loans', 'library loans, holds and overdue fines'),
    ('course-prerequisites', 'course registration with prerequisites and capacity'),
    ('attendance-tracking', 'attendance tracking with justified absences'),
    ('election-results', 'election results aggregation by district with recount rules'),
    ('permit-workflow', 'building permit application status workflow'),
    ('benefit-eligibility', 'social benefit eligibility rules with household income'),
    ('blood-donations', 'blood donation eligibility intervals and stock'),
    ('team-transfers', 'sports team roster transfers under salary caps'),
    ('race-timing', 'race timing with chip splits and age categories'),
    ('changelog-builder', 'changelog generation from commit messages with conventions'),
    ('dependency-resolver', 'package dependency version resolution'),
    ('config-linter', 'a configurable linter for a simple configuration format'),
    ('stale-toggles', 'detection of stale feature toggles from usage logs'),
    ('cron-schedules', 'cron expression parsing and next run times'),
    ('log-redaction', 'redaction of sensitive data in log lines'),
    ('env-files', 'environment file parsing with variable interpolation'),
    ('migration-plans', 'database migration ordering and rollback plans'),
    ('api-pagination', 'cursor and offset pagination over a simulated API'),
    ('cache-tags', 'cache invalidation by tags and dependencies'),
    ('job-queue', 'background job queue with retries and dead letters'),
    ('circuit-breaker', 'a circuit breaker on a simulated clock'),
    ('metric-rollups', 'metric rollups into time buckets with downsampling'),
    ('alert-rules', 'alerting rules with thresholds, durations and silences'),
    ('access-logs', 'access log parsing and per-client statistics'),
    ('url-shortener', 'a URL shortener with collision handling and expiry'),
    ('row-filters', 'evaluation of SQL-like WHERE filters on rows'),
    ('json-patch', 'applying JSON patch operations to nested data'),
    ('csv-cleaning', 'CSV cleaning with type inference and error reporting'),
    ('schema-validation', 'validation of records against a simple schema'),
    ('changeset-summary', 'summaries of changes between two versions of a record set'),
    ('release-versions', 'release version bumping from change types'),
    ('test-sharding', 'splitting test suites into balanced shards by duration'),
    ('build-cache', 'build cache keys from inputs and invalidation'),
    ('code-owners', 'code owner rules matched against file paths'),
    ('ticket-sla', 'support ticket SLA tracking within business hours'),
    ('storage-quotas', 'storage quota accounting per user and group'),
    ('session-tokens', 'session token issuing and expiry on a simulated clock'),
    ('password-reset', 'password reset flows with expiring codes and attempts'),
    ('audit-trail', 'an audit trail of record changes with author and time'),
    ('treasure-hunt', 'treasure hunt clue validation on a grid map'),
    ('tile-slider', 'moves and win detection in an original sliding tile game'),
    ('card-draft', 'card drafting rounds with pick order'),
    ('fantasy-points', 'fantasy sports points from match events'),
    ('quiz-scoring', 'quiz scoring with time bonuses and penalties'),
    ('escape-rooms', 'escape room booking and team scoring'),
    ('chess-clock', 'a chess clock with increments and delays'),
    ('elimination-brackets', 'single-elimination bracket generation with byes'),
    ('loot-tables', 'loot table rolls driven by a given number sequence'),
    ('crafting-recipes', 'crafting recipes with inventory consumption'),
    ('achievement-tracker', 'achievement unlocking from game events'),
    ('save-files', 'versioned game save files with migration'),
    ('pet-needs', 'virtual pet needs simulated over ticks'),
    ('karaoke-scores', 'karaoke scoring from pitch samples'),
    ('cinema-showtimes', 'cinema showtime scheduling across screens'),
    ('thermostat-schedule', 'thermostat schedules with overrides and holidays'),
    ('energy-tariffs', 'electricity bills with time-of-use tariffs'),
    ('solar-production', 'solar production estimates and self-consumption'),
    ('water-meter', 'water meter readings with leak detection'),
    ('light-scenes', 'smart light scenes and automation rules'),
    ('garden-watering', 'garden watering plans from weather data'),
    ('home-inventory', 'home inventory with locations and warranties'),
    ('chore-rotation', 'fair household chore rotation'),
    ('meal-planner', 'weekly meal planning with dietary constraints'),
    ('shopping-lists', 'shopping list merging and unit normalization'),
    ('ev-charging', 'electric vehicle charging schedules under power limits'),
    ('sensor-calibration', 'sensor reading calibration and outlier rejection'),
    ('alarm-zones', 'home alarm zones, arming and event handling'),
    ('address-normalization', 'postal address normalization and validation'),
    ('contact-dedup', 'contact list deduplication with merge rules'),
    ('name-matching', 'person name matching with explicit rules'),
    ('text-justify', 'text wrapping and justification with hyphenation rules'),
    ('kanban-boards', 'a kanban board with work-in-progress limits and card moves'),
    ('subtitle-timing', 'subtitle timing shifts and overlap fixes'),
    ('search-snippets', 'search result snippet extraction with highlighted terms'),
    ('slug-generation', 'URL slug generation with transliteration rules'),
    ('citation-styles', 'bibliography citations formatted in a defined style'),
    ('invoice-parsing', 'parsing semi-structured invoice text into fields'),
    ('email-routing', 'email routing rules for a shared inbox'),
    ('form-autofill', 'form autofill matching saved profiles'),
    ('compound-units', 'unit conversion with compound units'),
    ('meeting-times', 'meeting time suggestions across fixed time offsets'),
    ('busy-blocks', 'calendar conflict detection with recurring busy blocks'),
    ('elevator-faults', 'elevator maintenance logs and fault statistics'),
    ('vending-stock', 'vending machine restocking and sales reports'),
    ('garage-levels', 'parking garage occupancy and level assignment'),
    ('queue-tickets', 'ticket queues with priorities and service counters'),
    ('kitchen-orders', 'restaurant order routing to kitchen stations'),
    ('table-reservations', 'restaurant table reservations with joined tables'),
    ('hotel-housekeeping', 'hotel housekeeping assignments by room status'),
    ('laundry-booking', 'shared laundry machine booking and fees'),
    ('print-queue', 'print queue scheduling with priorities and page quotas'),
    ('gym-lockers', 'gym locker assignment and renewals'),
    ('membership-tiers', 'membership tiers with upgrades and downgrades'),
    ('event-tickets', 'event ticket allocation with seat categories and limits'),
    ('volunteer-shifts', 'volunteer shift signups with skill requirements'),
    ('carpool-rotation', 'carpool driver rotation with availability'),
    ('donation-matching', 'donation matching campaigns with caps'),
    ('raffle-draws', 'raffle draws from a given number sequence with eligibility rules'),
    ('lost-and-found', 'lost and found item matching from descriptions'),
]
GENRES_V2 = GENRES + [
    ('codec', 'an encoder and decoder between a compact text or binary format and structured data'),
    ('reconciler', 'a reconciler that matches two data sets and reports every difference'),
    ('migrator', 'a migrator that upgrades data between versions of a format, with validation'),
]
DIFFICULTES = {'moyen': 'medium: about 60 to 150 lines in the solution and 8 to 15 test cases',
               'difficile': 'hard: about 150 to 300 lines in the solution, several interacting rules and 12 to 25 test cases'}
SOUCHES = {'python': 'raise NotImplementedError in each function or method body',
           'javascript': "throw new Error('Remove this line and implement the function') in each function body",
           'go': 'panic("Please implement") in each function body',
           'rust': 'todo!() in each function body',
           'java': 'throw new UnsupportedOperationException("Delete this statement and write your own implementation.") '
                   'in each method body',
           'cpp': 'functions return default values such as {} or 0'}
COMPTE_TESTS = {'python': r'^\s*def test_', 'javascript': r'^\s*(test|it)\(', 'rust': r'#\[test\]',
                'java': r'@Test\b', 'cpp': r'^\s*TEST_CASE\(', 'go': r'^func Test|^\s*\{?\s*(name|description)\s*:'}
COMPILATION = {'python': r'SyntaxError|IndentationError|ImportError|ModuleNotFoundError',
               'javascript': r'SyntaxError|Cannot find module',
               'go': r'\[build failed\]|\[setup failed\]|syntax error',
               'rust': r'error\[E\d+\]|could not compile',
               'java': r'compileJava FAILED|compileTestJava FAILED',
               'cpp': r'error:|undefined reference'}

# demandes de résolution (données d'entraînement : plusieurs formulations, aucune n'est celle du banc polyglot)
DEMANDES = [
    '{consigne}\n\nImplement this in {langage}. Here are the starting files:\n\n{fichiers}\n\nReturn the complete content of '
    'each file you change: put the file path alone on a line, then the full file in a fenced code block.',
    'I need help with this {langage} exercise.\n\n## Task\n\n{consigne}\n\n## Files\n\n{fichiers}\n\nPlease write the full '
    'implementation. Give each modified file in full, preceded by its path on its own line.',
    'Complete the implementation below so that it satisfies the specification.\n\nSpecification:\n\n{consigne}\n\n{fichiers}\n\n'
    'Only use the standard library. Reply with the whole updated file(s), each preceded by its file name on a separate line.',
    'Can you implement this for me in {langage}?\n\n{consigne}\n\nThe project already contains these files:\n\n{fichiers}\n\n'
    'Show me the final version of every file you edit (file path on one line, then the code block).',
]
RELANCES = [
    'The tests fail with this output:\n\n```\n{sortie}\n```\n\nThe tests are correct. Fix the code and give the full corrected '
    'file(s), each preceded by its path.',
    'I ran the test suite and got:\n\n```\n{sortie}\n```\n\nPlease fix the implementation (not the tests) and send the '
    'complete files again, with each file path on the line before its code block.',
]
REPARATIONS = {
    'tests': 'The following {langage} code should implement this specification:\n\n{consigne}\n\n{fichiers}\n\nWhen I run the '
             'tests, I get:\n\n```\n{sortie}\n```\n\nFind the bug and fix it. Reply with the complete corrected file(s), each '
             'preceded by its path on its own line.',
    'rapport': "I'm getting a bug in this {langage} code.\n\nWhat it should do:\n\n{consigne}\n\nWhat happens: {rapport}\n\n"
               "{fichiers}\n\nPlease find the cause and fix it. Give me the full corrected file(s), with each file's path on "
               'the line before its code block.',
}
# campagne 2 (25/10) : correction de la référence qui rate ses propres tests ; énoncé et tests fixes
CORRECTION_REFERENCE = (
    'You wrote this {langage} exercise: a specification, tests and a reference solution. The reference solution fails '
    'some of its own tests.\n\nSpecification:\n\n{consigne}\n\nTests:\n\n{tests}\n\nReference solution:\n\n{fichiers}\n\n'
    'Test output:\n\n```\n{sortie}\n```\n\nThe specification and the tests are final and will not change. Fix the reference '
    'solution so that it follows the specification and passes every test. Reply with the complete corrected file(s), each '
    'preceded by its path on its own line.')
# niveaux de bogue injecté : simple (essai de 600), subtil et double (campagne 2, pour des réparations qui demandent
# un vrai débogage : dans l'essai, le raisonnement des réparations faisait une cinquantaine de jetons)
NIVEAUX_BOGUE = {
    'simple': ('introduce exactly one realistic bug of the kind developers actually make (for example an off-by-one error, '
               'a wrong comparison, a forgotten edge case, a wrong default value, an error raised with the wrong type or '
               'message, a shared value modified by mistake). The code must still compile and run; the bug must make some, '
               'but not all, of the behaviour wrong; nothing may hint at it (no comment, no unusual name).', 1),
    'subtil': ('introduce exactly one subtle, realistic bug. The code must still compile, run and look correct to a reviewer '
               'reading it once; most of the behaviour must stay right, and the bug must only show up for some inputs, for '
               'example an edge case or an interaction between two rules of the specification. Nothing may hint at it (no '
               'comment, no unusual name).', 1),
    'double': ('introduce exactly two independent, realistic bugs in two different places of the code (different functions '
               'or methods when possible). The code must still compile and run; each bug must make some, but not all, of '
               'the behaviour wrong; nothing may hint at them (no comment, no unusual name).', 2),
}
# repères de section ; tolère « ### », « ** », des espaces, des minuscules et un chemin entre ` ou "
MARQUE = re.compile(r'^[ \t#*>]*=== *(TITLE|INSTRUCTIONS|BUG|REPORT|END|(STUB|TEST|SOLUTION|FILE) *: *([^\n=]+?)) *===[ \t*]*$',
                    re.M | re.I)


def formes(slug: str) -> dict[str, str]:
    mots = slug.split('-')
    return {'camel': ''.join(m[:1].upper() + m[1:] for m in mots), 'snake': '_'.join(mots), 'kebab': slug,
            'flat': ''.join(mots)}


def motif(chemin: str, nom: str) -> str:
    """Chemin d'un fichier du gabarit -> motif ({camel}, {snake}, {kebab}, {flat}) ; les formes les plus longues d'abord."""
    v = formes(nom)
    for cle in sorted(v, key=lambda c: -len(v[c])):
        chemin = chemin.replace(v[cle], '{' + cle + '}')
    return chemin


def lire_jsonl(chemin: Path, cle: str = 'id') -> dict[str, dict]:
    if not chemin.exists():
        return {}
    brut = chemin.read_bytes()
    if brut and not brut.endswith(b'\n'):  # ligne coupée par l'arrêt brutal d'une tâche
        garde = brut[:brut.rfind(b'\n') + 1]
        chemin.write_bytes(garde)
        print(f'PILOTE_REPARATION {chemin.name} : dernière ligne incomplète retirée ({len(brut) - len(garde)} octets)', flush=True)
        brut = garde
    return {r[cle]: r for r in (json.loads(l) for l in brut.decode('utf-8').splitlines() if l.strip())}


def ajouter(chemin: Path, lignes: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open('a', encoding='utf-8', newline='\n') as f:
        f.write(''.join(json.dumps(l, ensure_ascii=False) + '\n' for l in lignes))
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------- gabarits (fichiers techniques de chaque langage)

def gabarits(travail: Path) -> dict[str, dict]:
    """Pour chaque langage, l'exercice polyglot contrôlé le plus simple, au nom en plusieurs mots (motifs sans ambiguïté),
    sans fichier d'aide imposé ni bibliothèque Rust externe : ses fichiers techniques serviront aux nouveaux exercices."""
    out = {}
    for langue in NOMS:
        candidats = []
        for ex in PP.exercices_valides(travail):
            if ex['langue'] != langue or '-' not in ex['nom'] or not ex['test']:
                continue
            d = travail / ex['dossier']
            cfg = json.loads((d / '.meta' / 'config.json').read_text(encoding='utf-8')).get('files', {})
            mod = PP.modifiables(ex)
            if cfg.get('editor') or not mod or not any(v in ex['test'][0] for v in formes(ex['nom']).values()):
                continue
            if langue == 'rust' and re.search(r'^\[dependencies\][ \t]*\n[ \t]*[\w-]', (d / 'Cargo.toml').read_text(
                    encoding='utf-8'), re.M):
                continue
            if langue == 'cpp' and sorted(Path(m).suffix for m in mod) != ['.cpp', '.h']:  # en-tête ET source (consignes)
                continue
            candidats.append((len(mod), sum(f.is_file() for f in d.rglob('*')), ex['nom'], ex))
        if candidats:
            out[langue] = min(candidats, key=lambda c: c[:3])[3]
    return out


def chemins_tache(gabarit: dict, slug: str) -> tuple[list[str], str]:
    """(fichiers de départ et de solution, fichier de tests) du nouvel exercice, d'après les motifs du gabarit."""
    v = formes(slug)
    stubs = [motif(c, gabarit['nom']).format(**v) for c in PP.modifiables(gabarit)]
    return stubs, motif(gabarit['test'][0], gabarit['nom']).format(**v)


def lignes_import(travail: Path, gabarit: dict, slug: str) -> list[str]:
    """Lignes d'import du fichier de tests du gabarit, noms remplacés : la convention sans le contenu de l'exercice."""
    texte = (travail / gabarit['dossier'] / gabarit['test'][0]).read_text(encoding='utf-8')
    v, g = formes(slug), formes(gabarit['nom'])
    out = []
    for l in texte.splitlines()[:40]:
        if l.rstrip().endswith('('):  # import sur plusieurs lignes (Python, Go) : la première seule ne dit rien
            continue
        if re.match(r'\s*(import |from \S+ import|use |#include|#ifdef|#else|#endif|package |const .*require\()', l):
            for cle in sorted(g, key=lambda c: -len(g[c])):
                l = l.replace(g[cle], v[cle])
            # noms importés du gabarit (fonctions d'un exercice Exercism) remplacés : seule la forme de l'import compte
            l = re.sub(r'^(\s*from \S+ import ).*$', r'\1...', l)
            l = re.sub(r'^(\s*import )\{[^}]*\}(\s*from .*)$', r'\1{ ... }\2', l)
            l = re.sub(r'^(\s*import )\w+(\s*from .*)$', r'\1...\2', l)
            l = re.sub(r'^(\s*const )\{[^}]*\}(\s*=\s*require\(.*)$', r'\1{ ... }\2', l)
            l = re.sub(r'^(\s*use \w+::)(\{[^}]*\}|\w+);', r'\1*;', l)
            if l not in out:
                out.append(l)
    return out


def conventions(langue: str, slug: str, stubs: list[str], test: str) -> str:
    v = formes(slug)
    return {
        'python': f'Python 3.11. The tests use the unittest module (they are run with pytest) and import the solution with '
                  f'`from {v["snake"]} import ...`. Raise exceptions such as ValueError with the specified messages; tests '
                  f'check them with `with self.assertRaises(ValueError) as err:` and `err.exception.args[0]`.',
        'javascript': f'JavaScript (ES modules, Node 20). The solution exports its API with `export`; the tests use Jest 29 '
                      f'(`describe`, `test`, `expect`) and import with `import {{ ... }} from \'./{v["kebab"]}\';`. Throw '
                      f'`Error` objects with the specified messages; tests use `expect(() => ...).toThrow(new Error(\'...\'))`.',
        'go': f'Go 1.2x. Package `{v["flat"]}` in both files; tests use only the standard `testing` package; in table-driven '
              f'tests, give every case a `name` field and run it with `t.Run(tc.name, ...)`. Report errors as `error` values; '
              f'when a message is specified, tests compare `err.Error()`. No unused imports or variables (they do not compile).',
        'rust': f'Rust, 2021 edition, library crate `{v["snake"]}` (Cargo package `{v["kebab"]}`); the solution is '
                f'`{stubs[0]}`; the integration tests in `{test}` start with `use {v["snake"]}::*;`. Use `Result<T, E>` with '
                f'an error enum deriving `Debug, PartialEq, Eq` when errors are tested. No external crates.',
        'java': f'Java 21, default package (no package declaration). Main class `{v["camel"]}` in `{stubs[0]}`; helper types go '
                f'in the same file (nested static classes, records or non-public classes). Tests use JUnit 5 '
                f'(`org.junit.jupiter.api.Test`) with AssertJ 3 (`org.assertj.core.api.Assertions.assertThat`, '
                f'`assertThatThrownBy`); test class `{v["camel"]}Test`.',
        'cpp': f'C++17 compiled with -Wall -Wextra -Wpedantic -Werror: no warning is allowed (unused parameters in the stub '
               f'must be unnamed or cast to void). Declarations in the header (with include guards), definitions in the .cpp '
               f'file, everything in namespace `{v["snake"]}`. Tests use Catch2 v2 with `TEST_CASE("...")`, `REQUIRE` and '
               f'`REQUIRE_THROWS_AS`; they include the header first, then Catch2 exactly as in the lines below.',
    }[langue]


def ecrire_tache(travail: Path, gabarit: dict, spec: dict, parties: dict, donnees: Path = DONNEES) -> dict:
    """Écrit le nouvel exercice comme un exercice Exercism (fichiers techniques du gabarit, départ, tests, référence dans
    .meta, énoncé dans .docs) et renvoie son entrée d'index (même forme que celle du banc polyglot)."""
    langue, slug = spec['langue'], spec['slug']
    src, dest = travail / gabarit['dossier'], travail / donnees / langue / slug
    g, v = formes(gabarit['nom']), formes(slug)
    cfg = json.loads((src / '.meta' / 'config.json').read_text(encoding='utf-8')).get('files', {})
    exclus = set(PP.modifiables(gabarit)) | set(gabarit['test']) | set(gabarit['exemple']) | set(cfg.get('editor', []))
    for f in sorted(src.rglob('*')):
        rel = f.relative_to(src).as_posix()
        if f.is_dir() or rel.split('/')[0] in PP.IGNORES or rel.split('/')[0] == '.exercism' or rel in exclus:
            continue
        nouveau = rel
        for cle in sorted(g, key=lambda c: -len(g[c])):
            nouveau = nouveau.replace(g[cle], v[cle])
        cible = dest / nouveau
        cible.parent.mkdir(parents=True, exist_ok=True)
        try:
            texte = f.read_text(encoding='utf-8') if f.stat().st_size < 200_000 else None
        except UnicodeDecodeError:
            texte = None
        if texte is None:
            shutil.copy2(f, cible)
            continue
        for cle in sorted(g, key=lambda c: -len(g[c])):
            texte = texte.replace(g[cle], v[cle])
        cible.write_text(texte, encoding='utf-8', newline='\n')
        shutil.copymode(f, cible)
    for rel, contenu in parties['stub'].items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(contenu, encoding='utf-8', newline='\n')
    for rel, contenu in parties['test'].items():
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text(contenu, encoding='utf-8', newline='\n')
    for rel, contenu in parties['solution'].items():
        (dest / '.meta' / 'reference' / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / '.meta' / 'reference' / rel).write_text(contenu, encoding='utf-8', newline='\n')
    (dest / '.docs').mkdir(parents=True, exist_ok=True)
    (dest / '.docs' / 'instructions.md').write_text(parties['instructions'] + '\n', encoding='utf-8', newline='\n')
    stubs = list(parties['stub'])
    entree = {'id': f'{langue}/{slug}', 'langue': langue, 'nom': slug, 'dossier': dest.relative_to(travail).as_posix(),
              'solution': stubs, 'test': list(parties['test']), 'exemple': [f'.meta/reference/{s}' for s in stubs],
              'consigne': parties['instructions'], 'titre': parties['title'], 'domaine': spec['domaine'],
              'genre': spec['genre'], 'difficulte': spec['difficulte']}
    (dest / '.meta' / 'config.json').write_text(json.dumps({'files': {'solution': stubs, 'test': entree['test'],
                                                                      'example': entree['exemple']}}, indent=1) + '\n',
                                                encoding='utf-8')
    return entree


# ---------------------------------------------------------------- création

def specifications(config: dict) -> list[dict]:
    """Thème, genre et difficulté de chaque exercice à créer, tirés sans remise par langage (graine fixe), les langages
    mêlés (chaque lot les contient tous : un langage en défaut se voit dès le premier lot)."""
    par_langue = []
    domaines, genres = (DOMAINES_V2, GENRES_V2) if config.get('themes') == 2 else (DOMAINES, GENRES)
    for langue in config['langages']:
        rng = random.Random(f"{config.get('graine', 0)}-{langue}")
        paires = [(d, g) for d in domaines for g in genres]
        rng.shuffle(paires)
        n = config['taches_par_langage']
        if config.get('themes') == 2:  # thèmes à tour de rôle : chacun revient au plus ceil(n / nombre de thèmes) fois
            paires, vues = [], set()
            while len(paires) < min(n, len(domaines) * len(genres)):
                ordre = list(domaines)
                rng.shuffle(ordre)
                for d in ordre:
                    libres = [g for g in genres if (d[0], g[0]) not in vues]
                    if libres and len(paires) < n:
                        g = rng.choice(libres)
                        vues.add((d[0], g[0]))
                        paires.append((d, g))
        difficiles = set(rng.sample(range(n), round(n * config.get('part_difficile', 0.4))))
        par_langue.append([{'id': f'{langue}/{dslug}-{gslug}', 'langue': langue, 'slug': f'{dslug}-{gslug}', 'domaine': dtexte,
                            'genre': gtexte, 'difficulte': 'difficile' if k in difficiles else 'moyen'}
                           for k, ((dslug, dtexte), (gslug, gtexte)) in enumerate(paires[:n])])
    return [s for rang in zip(*par_langue) for s in rang]


def invite_creation(spec: dict, gabarit: dict, travail: Path, interdits: list[str]) -> str:
    langue, slug = spec['langue'], spec['slug']
    stubs, test = chemins_tache(gabarit, slug)
    cl = CLOTURES[langue]
    imports = lignes_import(travail, gabarit, slug)
    lignes = [
        f'You are writing a new programming exercise for {NOMS[langue]} developers. It will be used to train and test a '
        f'coding assistant.', '',
        f'Topic: {spec["domaine"]}.', f'Kind of code: {spec["genre"]}.', f'Difficulty: {DIFFICULTES[spec["difficulte"]]}.', '',
        'Requirements:',
        '- Invent an original, realistic task on this topic. It must not be a known puzzle or textbook exercise; in '
        'particular it must not be one of the Exercism exercises listed at the end, nor a close variant of one.',
        '- The instructions must fully specify the task: exact public names and signatures, input and output formats, every '
        'rule, edge case and error case that the tests check, with exact error types and messages when the tests check '
        'them. Include one or two short examples.',
        '- Deterministic behaviour only: no randomness, current time, network, files, environment variables, threads or '
        'console input. Standard library only. Never write three backticks inside a file.',
        f'- The stub must compile and define the whole public API, but must not implement the behaviour ({SOUCHES[langue]}).',
        '- The tests must compile against the stub and fail on it, be independent, and use only the public API described in '
        'the instructions. Write each test case as a separate test (its own test function or method; in Go, its own named '
        'entry of a test table).',
        f'- The solution must be complete, correct and idiomatic {NOMS[langue]}, and pass every test.', '',
        'Conventions: ' + conventions(langue, slug, stubs, test),
    ]
    if imports:
        lignes += ['An existing test file of this kind starts with these lines:', '```' + cl, *imports, '```']
    lignes += ['', 'Use exactly these file paths: ' + ', '.join(stubs) + f' for the stub and the solution, {test} for the tests.',
               '', 'Answer in exactly this format, with nothing after === END ===:', '=== TITLE ===', '<a short title>',
               '=== INSTRUCTIONS ===', '<the instructions in Markdown, written for the person who will implement the stub; '
               'do not mention the tests or the file paths>']
    for s in stubs:
        lignes += [f'=== STUB: {s} ===', '```' + cl, '<complete file>', '```']
    lignes += [f'=== TEST: {test} ===', '```' + cl, '<complete file>', '```']
    for s in stubs:
        lignes += [f'=== SOLUTION: {s} ===', '```' + cl, '<complete file>', '```']
    lignes += ['=== END ===', '', 'Exercism exercises that must not be reproduced: ' + ', '.join(interdits)]
    return '\n'.join(lignes)


def sans_cloture(corps: str) -> str:
    """Contenu d'un fichier : entre la clôture ouvrante et la DERNIÈRE ligne ``` seule (une phrase ajoutée après le bloc
    est ignorée, des ``` dans le fichier restent)."""
    lignes = corps.strip('\n').splitlines()
    if lignes and lignes[0].lstrip().startswith('```'):
        fin = next((k for k in range(len(lignes) - 1, 0, -1) if lignes[k].strip() == '```'), len(lignes))
        lignes = lignes[1:fin]
    return '\n'.join(lignes).rstrip() + '\n'


def lire_sections(texte: str) -> dict:
    """Sections === NOM === d'une réponse ; les fichiers sous leur chemin, sans la clôture ``` qui les entoure."""
    out = {'stub': {}, 'test': {}, 'solution': {}, 'file': {}}
    marques = list(MARQUE.finditer(texte or ''))
    for k, m in enumerate(marques):
        if m.group(1).upper() == 'END':
            break
        corps = texte[m.end():marques[k + 1].start() if k + 1 < len(marques) else len(texte)]
        if m.group(2):
            out[m.group(2).lower()][m.group(3).strip().strip('`"\'')] = sans_cloture(corps)
        else:  # texte (titre, énoncé, rapport) : sans clôture s'il est entièrement dans un bloc ```markdown
            c = corps.strip()
            out[m.group(1).lower()] = sans_cloture(c).strip() if c.startswith('```') and c.endswith('```') else c
    return out


def verifier_creation(parties: dict, stubs: list[str], test: str) -> str | None:
    """Raison du rejet d'une création mal formée, sinon None."""
    if not parties.get('title') or len(parties.get('instructions') or '') < 200:
        return 'titre ou énoncé absent'
    if sorted(parties['stub']) != sorted(stubs) or sorted(parties['solution']) != sorted(stubs) or list(parties['test']) != [test]:
        return f"fichiers inattendus (départ {sorted(parties['stub'])}, solution {sorted(parties['solution'])}, tests {list(parties['test'])})"
    if all(parties['stub'][s].strip() == parties['solution'][s].strip() for s in stubs):
        return 'départ identique à la solution'
    return None


def nombre_tests(langue: str, texte: str) -> int:
    return len(re.findall(COMPTE_TESTS[langue], texte, re.M))


# ---------------------------------------------------------------- Exercism : corpus pour écarter ce qui y ressemble

def corpus_exercism(travail: Path) -> list[dict]:
    """Énoncés d'Exercism : problem-specifications (téléchargé une fois, lu sans extraction) et les 225 du banc polyglot."""
    f = travail / EXERCISM / 'corpus.json'
    if f.exists():
        return json.loads(f.read_text(encoding='utf-8'))
    corpus = {}
    try:
        for ex in PP.charger_index(travail):
            corpus[ex['nom']] = {'slug': ex['nom'], 'titre': ex['nom'].replace('-', ' '), 'texte': ex['consigne']}
    except (OSError, ValueError):
        pass
    archive = travail / EXERCISM / 'problem-specifications.tar.gz'
    try:
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            tmp = archive.with_name(f'{archive.name}.{os.getpid()}.partiel')
            with urllib.request.urlopen(urllib.request.Request(EXERCISM_URL, headers={'User-Agent': 'nova-exercices/1.0'}),
                                        timeout=300) as r, open(tmp, 'wb') as o:
                shutil.copyfileobj(r, o, 1 << 20)
            tmp.replace(archive)
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                p = m.name.split('/')
                if m.isfile() and len(p) == 4 and p[1] == 'exercises' and p[3] in (
                        'description.md', 'instructions.md', 'introduction.md', 'metadata.toml'):
                    texte = t.extractfile(m).read().decode('utf-8', 'replace')
                    e = corpus.setdefault(p[2], {'slug': p[2], 'titre': p[2].replace('-', ' '), 'texte': ''})
                    titre = re.search(r'^title\s*=\s*"([^"]+)"', texte, re.M) if p[3] == 'metadata.toml' else None
                    if titre:
                        e['titre'] = titre.group(1)
                    elif p[3] != 'metadata.toml':
                        e['texte'] += '\n' + texte
    except Exception as e:  # sans réseau : le banc polyglot seul
        print(f'EXERCICES_NOVA_EXERCISM : problem-specifications indisponible ({type(e).__name__}: {e}) ; corpus du banc '
              f'polyglot seul', flush=True)
    out = sorted(corpus.values(), key=lambda e: e['slug'])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'EXERCICES_NOVA_EXERCISM : {len(out)} exercices d\'Exercism pour le filtrage', flush=True)
    return out


def trigrammes(texte: str) -> set:
    m = re.findall(r'[a-z0-9]+', (texte or '').lower())
    return {tuple(m[i:i + 3]) for i in range(len(m) - 2)}


def plongements(travail: Path, textes: list[str]):
    """Vecteurs e5 (multilingual-e5-small, sur processeur) ; None si le modèle ou les bibliothèques manquent."""
    chemin = travail / E5
    if not (chemin / 'config.json').exists():
        return None
    try:
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(max(1, min(32, (os.cpu_count() or 2) - 2,
                                         int(os.environ.get('SLURM_CPUS_PER_TASK') or 64) - 2)))  # pas un seul cœur
        tok = AutoTokenizer.from_pretrained(str(chemin))
        mod = AutoModel.from_pretrained(str(chemin)).eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(textes), 32):
                b = tok(['query: ' + t for t in textes[i:i + 32]], max_length=512, truncation=True, padding=True,
                        return_tensors='pt')
                h = mod(**b).last_hidden_state
                m = b['attention_mask'].unsqueeze(-1).float()
                out.append(torch.nn.functional.normalize((h * m).sum(1) / m.sum(1), dim=-1).numpy())
        return np.concatenate(out) if out else None
    except Exception as e:
        print(f'EXERCICES_NOVA_E5 : indisponible ({type(e).__name__}: {e}) ; filtrage par les mots seulement', flush=True)
        return None


def regle_filtre(config: dict) -> dict:
    """Réglages du filtrage, gardés avec son résultat : un filtrage fait avec d'autres réglages est refait (19/10/2026)."""
    regle = {'version': 2, 'seuil_lexical_exercism': config.get('seuil_lexical_exercism', 0.25),
             'seuil_recopie_exercism': config.get('seuil_recopie_exercism', 0.35),
             'seuil_e5_exercism': config.get('seuil_e5_exercism', 0.95),
             'seuil_e5_z_exercism': config.get('seuil_e5_z_exercism', 3.0),
             'seuil_e5_doublon': config.get('seuil_e5_doublon', 0.95)}
    if config.get('campagnes_precedentes'):
        regle['campagnes_precedentes'] = list(config['campagnes_precedentes'])
    return regle


def proche_exercism(sims) -> tuple[int, float, float]:
    """Exercice d'Exercism le plus proche, sa note e5 et sa note relative z : écart à la moyenne des autres exercices
    d'Exercism, en écarts-types. Avec e5, des énoncés sans rapport notent 0,85 à 0,92 (ERR-140) : la note seule ne
    distingue pas un exercice d'Exercism reformulé d'un exercice quelconque, l'écart au reste du corpus si."""
    import numpy as np
    k = int(np.argmax(sims))
    autres = np.delete(sims, k)
    z = float((sims[k] - autres.mean()) / max(float(autres.std()), 1e-6)) if len(autres) > 1 else 0.0
    return k, float(sims[k]), z


def filtrer(travail: Path, config: dict, valides: list[dict], corpus: list[dict],
            plonger=None, anciens: list[dict] | None = None) -> tuple[list[str], list[dict]]:
    """Écarte les exercices proches d'Exercism (mots communs, sens proche par e5, titre) et les doublons du même langage
    (le premier est gardé). Sens proche : note relative z >= seuil_e5_z_exercism, ou note e5 >= seuil_e5_exercism
    (filet pour une quasi-copie) ; seuils calibrés le 19/10 sur le fond d'Exercism et des reformulations connues
    (audit_filtre_exercices.py). Renvoie (identifiants gardés, détail par exercice pour l'audit)."""
    import numpy as np
    regle = regle_filtre(config)
    seuil_lex, seuil_e5, seuil_z = regle['seuil_lexical_exercism'], regle['seuil_e5_exercism'], regle['seuil_e5_z_exercism']
    seuil_dbl = regle['seuil_e5_doublon']
    t_ex = [trigrammes(e['titre'] + ' ' + e['texte']) for e in corpus]
    titres_ex = {re.sub(r'[^a-z0-9]+', ' ', (e['titre'] or '').lower()).strip() for e in corpus} | {
        e['slug'].replace('-', ' ') for e in corpus}
    textes = [t['titre'] + '\n' + t['consigne'] for t in valides]
    plonger = plonger or plongements
    v_t = plonger(travail, textes) if valides else None
    v_e = plonger(travail, [e['titre'] + '\n' + e['texte'] for e in corpus]) if v_t is not None and corpus else None
    if valides and corpus and v_e is None:
        print('EXERCICES_NOVA_E5 : pas de vecteurs e5 ; filtrage par les mots et les titres seulement', flush=True)
    anciens = anciens or []  # 25/10 : exercices gardés des campagnes précédentes (doublons écartés aussi)
    v_a = plonger(travail, [a['titre'] + '\n' + a['consigne'] for a in anciens]) if anciens and v_t is not None else None
    t_anc = [trigrammes(a['titre'] + '\n' + a['consigne']) for a in anciens]
    seuil_recopie = regle['seuil_recopie_exercism']
    detail, gardes = [], []
    t_val = [trigrammes(x) for x in textes]
    rang = {t['id']: n for n, t in enumerate(valides)}
    for i, t in enumerate(valides):
        partages = [len(t_val[i] & b) for b in t_ex]
        lex = [p / max(len(t_val[i]), 1) for p in partages]  # part de l'exercice faite de phrases d'Exercism
        # part d'un énoncé d'Exercism recopiée dans l'exercice (un long exercice peut en contenir un tout entier)
        recopie = [p / max(len(b), 1) if p >= 25 else 0.0 for p, b in zip(partages, t_ex)]
        j = int(np.argmax(lex)) if lex else -1
        j2 = int(np.argmax(recopie)) if recopie else -1
        d = {'id': t['id'], 'titre': t['titre'], 'exercism_lexical': round(lex[j], 3) if j >= 0 else 0.0,
             'exercism_lexical_proche': corpus[j]['slug'] if j >= 0 else None,
             'exercism_recopie': round(recopie[j2], 3) if j2 >= 0 else 0.0,
             'exercism_recopie_proche': corpus[j2]['slug'] if j2 >= 0 else None}
        if v_e is not None:
            k, note, z = proche_exercism(v_e @ v_t[i])
            d.update(exercism_e5=round(note, 3), exercism_e5_z=round(z, 2), exercism_e5_proche=corpus[k]['slug'])
        titre = re.sub(r'[^a-z0-9]+', ' ', t['titre'].lower()).strip()
        raisons = []
        if d['exercism_lexical'] >= seuil_lex or d['exercism_recopie'] >= seuil_recopie:
            raisons.append('mots communs avec Exercism')
        if d.get('exercism_e5', 0) >= seuil_e5 or d.get('exercism_e5_z', 0) >= seuil_z:
            raisons.append('sens proche d\'Exercism')
        if titre in titres_ex:
            raisons.append('titre d\'Exercism')
        for k2 in gardes:  # doublons du même langage, parmi les exercices déjà gardés
            j2 = rang[k2]
            if valides[j2]['langue'] != t['langue']:
                continue
            meme = len(t_val[i] & t_val[j2]) / max(len(t_val[i]), 1) >= 0.5 or titre == re.sub(
                r'[^a-z0-9]+', ' ', valides[j2]['titre'].lower()).strip()
            if v_t is not None and float(v_t[i] @ v_t[j2]) >= seuil_dbl:
                meme = True
            if meme:
                raisons.append(f'doublon de {k2}')
                break
        if not any(r.startswith('doublon') for r in raisons):
            for j3, a in enumerate(anciens):
                if a['langue'] != t['langue']:
                    continue
                meme = len(t_val[i] & t_anc[j3]) / max(len(t_val[i]), 1) >= 0.5 or titre == re.sub(
                    r'[^a-z0-9]+', ' ', a['titre'].lower()).strip()
                if v_a is not None and float(v_t[i] @ v_a[j3]) >= seuil_dbl:
                    meme = True
                if meme:
                    raisons.append(f"doublon d'une campagne précédente : {a['id']}")
                    break
        d['raisons'] = raisons
        detail.append(d)
        if not raisons:
            gardes.append(t['id'])
    return gardes, detail


# ---------------------------------------------------------------- moteur, lots, tests

def par_lots(nom: str, elements: list, phase: dict, debut: float, limite_s: float, traiter) -> bool:
    """Lots écrits dès qu'ils sont finis ; durée prévue d'un lot complet : duree_lot_minutes, puis celle du lot précédent
    (au moins la moitié pour un lot plus petit : la réponse la plus longue fixe la fin d'un lot). Quand un lot complet ne
    tient plus dans le temps restant (avec la même marge de 1,3), un lot plus petit qui tient le remplace (26/10 : sinon
    un créneau de la campagne 2 ne faisait qu'un lot de création de 150, dans 1 h 42 sur 3 h 55). False : plus le temps."""
    taille = max(1, phase.get('lot') or len(elements) or 1)
    duree_lot = 60.0 * phase.get('duree_lot_minutes', 0)
    nombre = -(-len(elements) // taille)
    i, k = 0, 0
    while i < len(elements):
        k += 1
        paquet = elements[i:i + taille]
        prevu = max(duree_lot * len(paquet) / taille, 0.5 * duree_lot)
        ecoule = time.time() - debut
        if ecoule + 1.3 * prevu > limite_s:
            dispo = (limite_s - ecoule) / 1.3  # durée qu'un lot peut encore prendre
            n = int(taille * dispo / duree_lot) if duree_lot > 0 else 0
            if dispo >= 0.5 * duree_lot and 1 <= n < len(paquet):
                paquet = elements[i:i + n]
                prevu = max(duree_lot * len(paquet) / taille, 0.5 * duree_lot)
                print(f'EXERCICES_NOVA_LOT_AJUSTE {nom} : {len(paquet)} éléments au lieu de {taille}, pour finir dans le '
                      f'temps de la tâche ({prevu / 60:.0f} min prévues)', flush=True)
            else:
                print(f'EXERCICES_NOVA_ARRET {nom} : plus le temps dans cette tâche ({len(paquet)} éléments, {prevu / 60:.0f} '
                      f'min prévues)', flush=True)
                return False
        duree = traiter(paquet, k, nombre)
        if duree:  # lot sauté (langage arrêté) : la prévision reste celle d'avant
            duree_lot = duree * taille / len(paquet)
        i += len(paquet)
    return True


def generer_textes(moteur, conversations: list[list[dict]], phase: dict) -> tuple[list[dict], float]:
    """Réponses (raisonnement séparé, comme le pilote) et durée de la génération."""
    import pilote as P
    ouvert = moteur.ouvert(phase.get('chat_kwargs') or {})
    t0 = time.time()
    sorties = moteur.generer(conversations, phase)
    duree = time.time() - t0
    out = []
    for ech in sorties:
        e = ech[0]
        raisonnement, reponse = P.separer(e['texte'], ouvert)
        out.append({'raisonnement': raisonnement or '', 'reponse': reponse, 'jetons': e['jetons'], 'fin': e['fin']})
    return out, duree


def montrer(fichiers: dict[str, str], langue: str) -> str:
    return '\n\n'.join(f'{chemin}\n```{CLOTURES[langue]}\n{contenu.rstrip()}\n```' for chemin, contenu in fichiers.items())


def depart(travail: Path, ex: dict) -> dict[str, str]:
    src = travail / ex['dossier']
    return {s: (src / s).read_text(encoding='utf-8') for s in PP.modifiables(ex)}


def reference(travail: Path, ex: dict) -> dict[str, str]:
    src = travail / ex['dossier']
    return {s: (src / '.meta' / 'reference' / s).read_text(encoding='utf-8') for s in PP.modifiables(ex)}


def choix(cle: str, n: int) -> int:
    """Choix stable d'une variante (formulation de la demande) d'après l'identifiant."""
    return int(hashlib.sha256(cle.encode('utf-8')).hexdigest(), 16) % n


def tester_tous(travail: Path, cas: list[tuple[dict, dict]], racine_tmp: Path, processus: int) -> list[dict]:
    def un(c):  # 21/10 : un incident sur un exercice (fichier, dossier...) n'arrête plus toute la tâche
        try:
            return PP.tester(travail, c[0], c[1], racine_tmp)
        except Exception as e:
            return {'reussi': False, 'sortie': f'ERREUR_TEST {type(e).__name__}: {e}', 'secondes': 0.0}
    with ThreadPoolExecutor(processus) as pool:
        return list(pool.map(un, cas))


# ---------------------------------------------------------------- phases

class Pipeline:
    def __init__(self, travail: Path, config: dict, moteur, debut: float, limite_s: float, processus: int):
        self.travail, self.config, self.moteur = travail, config, moteur
        self.debut, self.limite_s, self.processus = debut, limite_s, processus
        self.dossier = travail / config.get('resultats', RESULTATS)  # campagne 2 (25/10) : dossiers à part
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.donnees = Path(config.get('donnees', DONNEES))  # exercices écrits, chemin relatif à travail
        self.tmp = travail / 'tmp' / 'exercices_nova' / f'{os.getpid()}'
        self.tester, self.plonger = tester_tous, None  # remplacés pendant l'essai à blanc (faux tests, sans e5)
        self.limite_essai = None  # essai à blanc : nombre de créations au plus

    def precedentes(self) -> tuple[set[str], list[dict]]:
        """Campagnes précédentes (campagnes_precedentes, 25/10) : identifiants déjà demandés et exercices gardés, pour
        ne pas redemander les mêmes et écarter les doublons d'une ancienne campagne. Lues seulement."""
        ids, gardes = set(), []
        for rel in self.config.get('campagnes_precedentes', []):
            d = self.travail / rel
            faits = lire_jsonl(d / 'creation.jsonl')
            ids |= set(faits)
            f = d / 'taches_finales.json'
            if f.exists():
                g = set(json.loads(f.read_text(encoding='utf-8'))['gardes'])
                gardes += [r['entree'] for i, r in faits.items() if i in g and 'entree' in r]
        return ids, gardes

    def niveau_bogue(self, t: dict) -> str:
        niveaux = self.config.get('bogues') or ['simple']
        return niveaux[choix(t['id'] + '/bogue', len(niveaux))]

    def phase(self, nom: str) -> dict:
        return self.config['phases'][nom]

    def fini(self, nom: str) -> bool:
        return (self.dossier / f'{nom}.fini').exists()

    def marquer(self, nom: str) -> None:
        (self.dossier / f'{nom}.fini').write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + '\n', encoding='utf-8')

    def taches(self) -> dict[str, dict]:
        """Exercices gardés après le filtrage, par identifiant."""
        f = self.dossier / 'taches_finales.json'
        if not f.exists():
            return {}
        gardes = set(json.loads(f.read_text(encoding='utf-8'))['gardes'])
        return {i: r['entree'] for i, r in lire_jsonl(self.dossier / 'creation.jsonl').items() if i in gardes}

    # 1. création
    def creation(self) -> bool:
        if self.fini('creation'):
            return True
        g = gabarits(self.travail)
        manquants = [l for l in self.config['langages'] if l not in g]
        if manquants:
            print(f'EXERCICES_NOVA_GABARIT : aucun gabarit pour {", ".join(manquants)} (langages sautés)', flush=True)
        print('EXERCICES_NOVA_GABARITS : ' + ' ; '.join(f'{l} {e["nom"]}' for l, e in sorted(g.items())), flush=True)
        corpus = corpus_exercism(self.travail)
        interdits = sorted({e['slug'] for e in corpus})
        fichier = self.dossier / 'creation.jsonl'
        faits = lire_jsonl(fichier)
        deja, _ = self.precedentes()
        a_faire = [s for s in specifications(self.config) if s['id'] not in faits and s['id'] not in deja and s['langue'] in g]
        if self.limite_essai:
            a_faire = a_faire[:self.limite_essai]
        bilan = {}  # langage -> [valides, essais], tenu à jour lot après lot
        for r in faits.values():
            bilan.setdefault(r['langue'], [0, 0])[0] += r.get('statut') == 'valide'
            bilan[r['langue']][1] += 1
        phase = self.phase('creation')
        arretes = set()

        def traiter(paquet, k, n):
            # un langage dont presque rien ne passe (gabarit ou conventions en défaut) n'est plus demandé
            for lg, (ok, tot) in bilan.items():
                if tot >= 10 and ok < 0.2 * tot and lg not in arretes:
                    arretes.add(lg)
                    print(f'EXERCICES_NOVA_LANGAGE_ARRETE {lg} : {ok}/{tot} exercices valides', flush=True)
            paquet = [s for s in paquet if s['langue'] not in arretes]
            if not paquet:
                return 0.0
            conv = [[{'role': 'user', 'content': invite_creation(s, g[s['langue']], self.travail, interdits)}] for s in paquet]
            reponses, duree = generer_textes(self.moteur, conv, phase)
            lignes, a_tester = [], []
            for s, c, r in zip(paquet, conv, reponses):
                stubs, test = chemins_tache(g[s['langue']], s['slug'])
                parties = lire_sections(r['reponse'])
                raison = verifier_creation(parties, stubs, test)
                ligne = {**s, 'invite': c[0]['content'], **r, 'statut': 'rejete' if raison else 'a_tester', 'raison': raison}
                if not raison:
                    ligne['nombre_tests'] = nombre_tests(s['langue'], parties['test'][test])
                    if ligne['nombre_tests'] < self.config.get('tests_minimum', 5):
                        ligne.update(statut='rejete', raison=f"{ligne['nombre_tests']} tests seulement")
                    else:
                        ligne['entree'] = ecrire_tache(self.travail, g[s['langue']], s, parties, self.donnees)
                        a_tester.append(ligne)
                lignes.append(ligne)
            cas = [(l['entree'], reference(self.travail, l['entree'])) for l in a_tester] + [(l['entree'], {}) for l in a_tester]
            verdicts = self.tester(self.travail, cas, self.tmp, self.processus)

            def selon_depart(l, v_dep):  # solution juste : le départ doit rater les tests, sans erreur de compilation
                if v_dep['reussi']:
                    l.update(statut='rejete', raison='le fichier de départ passe les tests')
                elif re.search(COMPILATION[l['langue']], v_dep['sortie']):  # départ ou tests qui ne compilent pas ensemble
                    l.update(statut='rejete', raison='le fichier de départ ne compile pas avec les tests')
                else:
                    l.update(statut='valide', raison=None)
            for l, v_ref, v_dep in zip(a_tester, verdicts[:len(a_tester)], verdicts[len(a_tester):]):
                l['test_reference'] = {'reussi': v_ref['reussi'], 'secondes': v_ref['secondes'], 'sortie': PP.tronquer(v_ref['sortie'], 3000)}
                l['test_depart'] = {'reussi': v_dep['reussi'], 'secondes': v_dep['secondes'], 'sortie': PP.tronquer(v_dep['sortie'], 1500)}
                if not v_ref['reussi']:
                    l.update(statut='rejete', raison='la solution rate ses propres tests')
                else:
                    selon_depart(l, v_dep)
            if self.config.get('corriger_reference'):  # campagne 2 : une correction de la référence, énoncé et tests fixes
                a_corriger = [(l, v_dep) for l, v_dep in zip(a_tester, verdicts[len(a_tester):])
                              if l['raison'] == 'la solution rate ses propres tests']
                if a_corriger:
                    duree += self.corriger_references(a_corriger, selon_depart, k, n)
            ajouter(fichier, lignes)
            par_langue = {}
            for l in lignes:
                for d in (par_langue, bilan):
                    d.setdefault(l['langue'], [0, 0])[0] += l['statut'] == 'valide'
                    d[l['langue']][1] += 1
            print(f"EXERCICES_NOVA_CREATION lot {k}/{n} : {sum(l['statut'] == 'valide' for l in lignes)}/{len(lignes)} valides ; "
                  + ' ; '.join(f'{lg} {a}/{b}' for lg, (a, b) in sorted(par_langue.items()))
                  + f" ; {sum(r['jetons'] for r in reponses) / 1e6:.2f} M jetons en {duree / 60:.1f} min ; coupées "
                  f"{sum(r['fin'] == 'length' for r in reponses)}", flush=True)
            raisons = {}
            for l in lignes:
                if l['statut'] != 'valide':
                    cle = re.sub(r'\(.*', '', l['raison'] or '').strip()
                    raisons[cle] = raisons.get(cle, 0) + 1
            if raisons:
                print('EXERCICES_NOVA_CREATION_REJETS : ' + ' ; '.join(f'{r} {n}' for r, n in sorted(raisons.items())), flush=True)
            return duree

        if not par_lots('creation', a_faire, phase, self.debut, self.limite_s, traiter):
            return False
        self.filtrage(corpus)
        self.marquer('creation')
        return True

    def corriger_references(self, a_corriger: list, selon_depart, k: int, n: int) -> float:
        """Campagne 2 (25/10) : une solution de référence qui rate ses propres tests est corrigée une fois par le
        professeur, l'énoncé et les tests restant tels quels (un tiers des créations de l'essai étaient perdues ainsi).
        L'exercice est gardé si la solution corrigée passe tous ses tests et si le départ les rate toujours, sans erreur
        de compilation. Un fichier que la réponse ne rend pas reste celui d'avant. Renvoie la durée de la génération."""
        phase = self.phase('correction_reference')
        conv = []
        for l, _ in a_corriger:
            e = l['entree']
            dos = self.travail / e['dossier']
            tests = {t: (dos / t).read_text(encoding='utf-8') for t in e['test'] if (dos / t).is_file()}
            conv.append([{'role': 'user', 'content': CORRECTION_REFERENCE.format(
                langage=NOMS[e['langue']], consigne=e['consigne'], tests=montrer(tests, e['langue']),
                fichiers=montrer(reference(self.travail, e), e['langue']),
                sortie=PP.tronquer(l['test_reference']['sortie'], 6000))}])
        reponses, duree = generer_textes(self.moteur, conv, phase)
        cas = []
        for (l, _), c, r in zip(a_corriger, conv, reponses):
            e = l['entree']
            nouveaux = PP.extraire_fichiers(r['reponse'], PP.modifiables(e))
            for s, contenu in nouveaux.items():
                cible = self.travail / e['dossier'] / '.meta' / 'reference' / s
                cible.parent.mkdir(parents=True, exist_ok=True)
                cible.write_text(contenu, encoding='utf-8', newline='\n')
            l['correction_reference'] = {'invite': c[0]['content'], **r, 'fichiers_rendus': sorted(nouveaux)}
            cas.append((e, reference(self.travail, e)))
        corriges = 0
        for (l, v_dep), v in zip(a_corriger, self.tester(self.travail, cas, self.tmp, self.processus)):
            l['correction_reference']['test'] = {'reussi': v['reussi'], 'secondes': v['secondes'],
                                                 'sortie': PP.tronquer(v['sortie'], 3000)}
            if v['reussi']:
                l['reference_corrigee'] = True
                selon_depart(l, v_dep)
                corriges += l['statut'] == 'valide'
            else:
                l['raison'] = 'la solution rate ses propres tests, même corrigée'
        print(f"EXERCICES_NOVA_CORRECTION lot {k}/{n} : {corriges}/{len(a_corriger)} exercices sauvés par une correction de "
              f"la référence ; {sum(r['jetons'] for r in reponses) / 1e6:.2f} M jetons en {duree / 60:.1f} min", flush=True)
        return duree

    def filtrage(self, corpus: list[dict]) -> None:
        """taches_finales.json : exercices valides gardés après le filtrage, avec les réglages employés (écrit d'un coup)."""
        valides = [r['entree'] for r in lire_jsonl(self.dossier / 'creation.jsonl').values() if r.get('statut') == 'valide']
        _, anciens = self.precedentes()
        gardes, detail = filtrer(self.travail, self.config, valides, corpus, self.plonger, anciens)
        f = self.dossier / 'taches_finales.json'
        tmp = f.with_name(f'{f.name}.{os.getpid()}')
        tmp.write_text(json.dumps({'regle': regle_filtre(self.config), 'gardes': gardes, 'detail': detail},
                                  ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        tmp.replace(f)
        ecartes = {}
        for d in detail:
            for r in d['raisons']:
                cle = ("doublon d'une campagne précédente" if r.startswith("doublon d'une")
                       else 'doublon' if r.startswith('doublon') else r)
                ecartes[cle] = ecartes.get(cle, 0) + 1
        par_langue = ' ; '.join(f"{l} {sum(i.startswith(l + '/') for i in gardes)}" for l in self.config['langages'])
        print(f'EXERCICES_NOVA_FILTRAGE : {len(gardes)}/{len(valides)} exercices valides gardés ({par_langue}) ; '
              f'{len(valides) - len(gardes)} écartés, raisons (cumulables) : '
              + (' ; '.join(f'{r} {n}' for r, n in sorted(ecartes.items())) or 'aucune'), flush=True)

    def refiltrer_si_besoin(self) -> None:
        """Avant la résolution : filtrage refait si ses réglages ont changé depuis la création (19/10/2026, seuil e5
        recalibré, ERR-140) ; l'ancien résultat est gardé à côté. Un exercice déjà traité puis écarté n'est plus exporté ;
        un exercice qui entre est traité par les phases restantes."""
        f = self.dossier / 'taches_finales.json'
        if not (self.fini('creation') and f.exists()):
            return
        ancien = json.loads(f.read_text(encoding='utf-8'))
        if ancien.get('regle') == regle_filtre(self.config):
            return
        archive = self.dossier / f"taches_finales.{time.strftime('%Y%m%dT%H%M%S')}.json"
        archive.write_text(f.read_text(encoding='utf-8'), encoding='utf-8')
        print(f"EXERCICES_NOVA_REFILTRAGE : réglages du filtrage changés ; {len(ancien.get('gardes', []))} exercices gardés "
              f"jusqu'ici, ancien filtrage dans {archive.name}", flush=True)
        self.filtrage(corpus_exercism(self.travail))

    # 2. résolution, deux essais
    def resolution(self) -> bool:
        if self.fini('resolution'):
            return True
        self.refiltrer_si_besoin()
        taches = self.taches()
        phase = self.phase('resolution')
        f1, f2 = self.dossier / 'resolution.essai1.jsonl', self.dossier / 'resolution.essai2.jsonl'
        for numero, fichier in ((1, f1), (2, f2)):
            e1, faits = lire_jsonl(f1), lire_jsonl(fichier)
            a_faire = [t for i, t in sorted(taches.items()) if i not in faits and (numero == 1 or not e1[i]['reussi'])]

            def traiter(paquet, k, n, numero=numero, fichier=fichier, e1=e1):
                conv = []
                for t in paquet:
                    demande = DEMANDES[choix(t['id'], len(DEMANDES))].format(
                        consigne=t['consigne'], langage=NOMS[t['langue']], fichiers=montrer(depart(self.travail, t), t['langue']))
                    c = [{'role': 'user', 'content': demande}]
                    if numero == 2:
                        r1 = e1[t['id']]
                        c += [{'role': 'assistant', 'content': r1['reponse'] or '(no answer)'},
                              {'role': 'user', 'content': RELANCES[choix(t['id'] + '/2', len(RELANCES))].format(
                                  sortie=PP.tronquer(r1['sortie'], 6000))}]
                    conv.append(c)
                reponses, duree = generer_textes(self.moteur, conv, phase)
                cas, lignes = [], []
                for t, c, r in zip(paquet, conv, reponses):
                    base = e1[t['id']]['contenus'] if numero == 2 else {}
                    nouveaux = PP.extraire_fichiers(r['reponse'], PP.modifiables(t))
                    contenus = {**base, **nouveaux}
                    cas.append((t, contenus))
                    lignes.append({'id': t['id'], 'langue': t['langue'], 'essai': numero, 'invites': [m['content'] for m in c
                                                                                                   if m['role'] == 'user'],
                                   **r, 'fichiers_rendus': sorted(nouveaux), 'contenus': contenus})
                for l, v in zip(lignes, self.tester(self.travail, cas, self.tmp, self.processus)):
                    l.update(reussi=v['reussi'], sortie=v['sortie'], secondes_test=v['secondes'])
                ajouter(fichier, lignes)
                print(f"EXERCICES_NOVA_RESOLUTION essai {numero} lot {k}/{n} : {sum(l['reussi'] for l in lignes)}/{len(lignes)} "
                      f"réussis ; {sum(r['jetons'] for r in reponses) / 1e6:.2f} M jetons en {duree / 60:.1f} min ; coupées "
                      f"{sum(r['fin'] == 'length' for r in reponses)}", flush=True)
                return duree

            if not par_lots(f'resolution essai {numero}', a_faire, phase, self.debut, self.limite_s, traiter):
                return False
        e1, e2 = lire_jsonl(f1), lire_jsonl(f2)
        un = sum(r['reussi'] for r in e1.values())
        deux = un + sum(r['reussi'] for r in e2.values())
        print(f'EXERCICES_NOVA_RESOLUTION : {un}/{len(e1)} au premier essai, {deux}/{len(e1)} en deux essais ; '
              + ' ; '.join(f"{l} {sum(r['reussi'] or e2.get(i, {}).get('reussi', False) for i, r in e1.items() if r['langue'] == l)}"
                           f"/{sum(r['langue'] == l for r in e1.values())}" for l in self.config['langages']), flush=True)
        self.marquer('resolution')
        return True

    def complets(self, t: dict, contenus: dict[str, str]) -> dict[str, str]:
        """Tous les fichiers modifiables de l'exercice : un fichier qu'une réponse n'a pas rendu reste celui du départ,
        c'est celui que les tests ont compilé (21/10 : un exercice C++ résolu sans renvoyer son .h faisait planter la
        réparation, KeyError)."""
        dep = depart(self.travail, t)
        return {s: contenus[s] if s in contenus else dep[s] for s in PP.modifiables(t)}

    def solutions(self) -> dict[str, dict[str, str]]:
        """Solution vérifiée de chaque exercice résolu (celle de GLM-5.3, premier ou second essai)."""
        e1, e2 = lire_jsonl(self.dossier / 'resolution.essai1.jsonl'), lire_jsonl(self.dossier / 'resolution.essai2.jsonl')
        out = {i: r['contenus'] for i, r in e1.items() if r['reussi']}
        out.update({i: r['contenus'] for i, r in e2.items() if r['reussi']})
        return out

    # 3. bogues injectés
    def injection(self) -> bool:
        if self.fini('injection'):
            return True
        taches, solutions = self.taches(), self.solutions()
        fichier = self.dossier / 'injection.jsonl'
        faits = lire_jsonl(fichier)
        a_faire = [taches[i] for i in sorted(solutions) if i in taches and i not in faits]
        phase = self.phase('injection')

        def traiter(paquet, k, n):
            conv = []
            for t in paquet:
                justes = self.complets(t, solutions[t['id']])
                consigne_bogue, nombre = NIVEAUX_BOGUE[self.niveau_bogue(t)]
                lignes = [f"Here is a correct {NOMS[t['langue']]} implementation of the task below. For a debugging exercise, "
                          + consigne_bogue, '', 'Task:', '', t['consigne'], '', 'Correct code:', '',
                          montrer(justes, t['langue']), '', 'Answer in exactly this format, with nothing after === END ===:',
                          '=== BUG ===', '<one sentence describing the bug, for the exercise author>' if nombre == 1 else
                          '<one sentence per bug, for the exercise author>', '=== REPORT ===',
                          '<a short bug report as a user would write it: the symptom, with a concrete input and the wrong '
                          'result, without the cause or the fix>' if nombre == 1 else
                          '<a short bug report as a user would write it: the symptoms, with concrete inputs and the wrong '
                          'results, without the causes or the fixes>']
                for s in justes:
                    lignes += [f'=== FILE: {s} ===', '```' + CLOTURES[t['langue']], '<the complete file with the bug>', '```']
                lignes.append('=== END ===')
                conv.append([{'role': 'user', 'content': '\n'.join(lignes)}])
            reponses, duree = generer_textes(self.moteur, conv, phase)
            lignes, cas = [], []
            for t, c, r in zip(paquet, conv, reponses):
                parties = lire_sections(r['reponse'])
                justes = self.complets(t, solutions[t['id']])
                casse = {s: parties['file'][s] for s in PP.modifiables(t) if s in parties['file']}
                niveau = self.niveau_bogue(t)
                nombre = NIVEAUX_BOGUE[niveau][1]
                l = {'id': t['id'], 'langue': t['langue'], 'niveau': niveau, 'invite': c[0]['content'], **r,
                     'bogue': parties.get('bug', ''), 'rapport': parties.get('report', ''), 'contenus': {**justes, **casse}}
                diffs = [d for s in casse for d in difflib.unified_diff(justes.get(s, '').splitlines(), casse[s].splitlines(),
                                                                        lineterm='', n=0)]
                changees = sum(1 for d in diffs if d[:1] in '+-' and not d.startswith(('+++', '---')))
                endroits = sum(1 for d in diffs if d.startswith('@@'))
                l.update(lignes_changees=changees, endroits_changes=endroits)
                if not casse or not l['rapport']:
                    l.update(statut='rejete', raison='réponse mal formée')
                elif changees == 0 or changees > nombre * self.config.get('lignes_bogue_max', 12):
                    l.update(statut='rejete', raison=f'{changees} lignes changées')
                elif endroits < nombre:  # deux bogues : au moins deux endroits du code
                    l.update(statut='rejete', raison=f'{endroits} endroit(s) changé(s) pour {nombre} bogues')
                else:
                    l['statut'] = 'a_tester'
                    cas.append((t, l['contenus']))
                lignes.append(l)
            a_tester = [l for l in lignes if l['statut'] == 'a_tester']
            for l, v in zip(a_tester, self.tester(self.travail, cas, self.tmp, self.processus)):
                l.update(sortie=v['sortie'], secondes_test=v['secondes'])
                if v['reussi']:
                    l.update(statut='rejete', raison='les tests ne voient pas le bogue')
                elif re.search(COMPILATION[l['langue']], v['sortie']):
                    l.update(statut='rejete', raison='erreur de compilation')
                else:
                    l['statut'] = 'valide'
            ajouter(fichier, lignes)
            print(f"EXERCICES_NOVA_INJECTION lot {k}/{n} : {sum(l['statut'] == 'valide' for l in lignes)}/{len(lignes)} bogues "
                  f"valides ; {sum(r['jetons'] for r in reponses) / 1e6:.2f} M jetons en {duree / 60:.1f} min", flush=True)
            return duree

        if not par_lots('injection', a_faire, phase, self.debut, self.limite_s, traiter):
            return False
        self.marquer('injection')
        return True

    # 4. réparation
    def reparation(self) -> bool:
        if self.fini('reparation'):
            return True
        taches = self.taches()
        bogues = {i: r for i, r in lire_jsonl(self.dossier / 'injection.jsonl').items() if r.get('statut') == 'valide'}
        fichier = self.dossier / 'reparation.jsonl'
        faits = lire_jsonl(fichier)
        a_faire = [bogues[i] for i in sorted(bogues) if i in taches and i not in faits]
        phase = self.phase('reparation')

        def traiter(paquet, k, n):
            conv, variantes = [], []
            for b in paquet:
                t = taches[b['id']]
                variante = ('tests', 'rapport')[choix(b['id'] + '/reparation', 2)]
                casses = self.complets(t, b['contenus'])
                conv.append([{'role': 'user', 'content': REPARATIONS[variante].format(
                    langage=NOMS[t['langue']], consigne=t['consigne'], fichiers=montrer(casses, t['langue']),
                    sortie=PP.tronquer(b['sortie'], 6000), rapport=b['rapport'])}])
                variantes.append(variante)
            reponses, duree = generer_textes(self.moteur, conv, phase)
            lignes, cas = [], []
            for b, c, r, variante in zip(paquet, conv, reponses, variantes):
                t = taches[b['id']]
                nouveaux = PP.extraire_fichiers(r['reponse'], PP.modifiables(t))
                contenus = {**b['contenus'], **nouveaux}
                cas.append((t, contenus))
                lignes.append({'id': b['id'], 'langue': b['langue'], 'variante': variante, 'invite': c[0]['content'], **r,
                               'fichiers_rendus': sorted(nouveaux), 'contenus': contenus})
            for l, v in zip(lignes, self.tester(self.travail, cas, self.tmp, self.processus)):
                l.update(reussi=v['reussi'], sortie=v['sortie'], secondes_test=v['secondes'])
            ajouter(fichier, lignes)
            print(f"EXERCICES_NOVA_REPARATION lot {k}/{n} : {sum(l['reussi'] for l in lignes)}/{len(lignes)} réparés ; "
                  f"{sum(r['jetons'] for r in reponses) / 1e6:.2f} M jetons en {duree / 60:.1f} min", flush=True)
            return duree

        if not par_lots('reparation', a_faire, phase, self.debut, self.limite_s, traiter):
            return False
        self.marquer('reparation')
        return True

    # 5. export
    def exporter(self) -> dict:
        """donnees.jsonl : un exemple par réponse vérifiée par les tests (reconstruit à chaque fois, sans doublon)."""
        taches = self.taches()
        e1, e2 = lire_jsonl(self.dossier / 'resolution.essai1.jsonl'), lire_jsonl(self.dossier / 'resolution.essai2.jsonl')
        rep = lire_jsonl(self.dossier / 'reparation.jsonl')
        niveaux = {i: b.get('niveau', 'simple') for i, b in lire_jsonl(self.dossier / 'injection.jsonl').items()}
        exemples = []

        def meta(t, type_):
            m = {'source': self.config.get('source_donnees', 'exercices_nova_v1'), 'professeur': 'GLM-5.3', 'effort': 'high',
                 'type': type_, 'langage': t['langue'], 'exercice': t['id'], 'titre': t['titre'],
                 'difficulte': t['difficulte'], 'verification': 'tests passés sur le cluster'}
            if type_.startswith('reparer_bogue_'):
                m['niveau_bogue'] = niveaux.get(t['id'], 'simple')
            return m
        for i, r in sorted(e1.items()):
            if r['reussi'] and i in taches:
                exemples.append({'id': f'{i}#ecrire', **meta(taches[i], 'ecrire'), 'messages': [
                    {'role': 'user', 'content': r['invites'][0]},
                    {'role': 'assistant', 'content': r['reponse'], 'raisonnement': r['raisonnement'], 'entrainer': True}]})
        for i, r in sorted(e2.items()):
            if r['reussi'] and i in taches:
                exemples.append({'id': f'{i}#reparer_apres_tests', **meta(taches[i], 'reparer_apres_tests'), 'messages': [
                    {'role': 'user', 'content': r['invites'][0]},
                    {'role': 'assistant', 'content': e1[i]['reponse'] or '(no answer)', 'entrainer': False},  # comme vu par GLM
                    {'role': 'user', 'content': r['invites'][1]},
                    {'role': 'assistant', 'content': r['reponse'], 'raisonnement': r['raisonnement'], 'entrainer': True}]})
        for i, r in sorted(rep.items()):
            if r['reussi'] and i in taches:
                exemples.append({'id': f'{i}#reparer_bogue_{r["variante"]}', **meta(taches[i], f'reparer_bogue_{r["variante"]}'),
                                 'messages': [{'role': 'user', 'content': r['invite']},
                                              {'role': 'assistant', 'content': r['reponse'], 'raisonnement': r['raisonnement'],
                                               'entrainer': True}]})
        tmp = self.dossier / f'donnees.jsonl.{os.getpid()}'
        tmp.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in exemples), encoding='utf-8')
        tmp.replace(self.dossier / 'donnees.jsonl')
        bilan = {}
        for e in exemples:
            b = bilan.setdefault(e['langage'], {})
            b[e['type']] = b.get(e['type'], 0) + 1
        (self.dossier / 'bilan.json').write_text(json.dumps({'exemples': len(exemples), 'par_langage': bilan},
                                                            ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        types = {}
        for e in exemples:
            types[e['type']] = types.get(e['type'], 0) + 1
        print(f'EXERCICES_NOVA_DONNEES : {len(exemples)} exemples vérifiés ('
              + ' ; '.join(f'{t} {n}' for t, n in sorted(types.items())) + ')', flush=True)
        return bilan


# ---------------------------------------------------------------- faux moteur (essais sur le PC, Python seulement)

class MoteurSimulation:
    """Faux GLM-5.3 pour le PC : exercices Python écrits à la main (le code d'un vrai modèle ne tourne jamais sur le PC).
    Dans l'ordre des demandes de création : deux bons exercices (A, B), une solution fausse, un exercice copié d'Exercism,
    une réponse sans tests, un doublon de A, un fichier de départ qui ne compile pas ; une phrase suit le bloc des tests.
    A est résolu du premier coup, B au second ; le bogue injecté dans A est vu par les tests, celui de B ne compile pas ;
    les réparations rendent la solution juste."""
    GENRES = ['bon', 'bon', 'solution_fausse', 'exercism', 'sans_tests', 'doublon', 'depart_casse']

    BONS = {
        'A': ('positive_total', 'Write `positive_total(values)` returning the sum of the strictly positive integers of the '
              'list `values`. Raise `ValueError("empty")` when `values` is empty. Positive values come from incoming stock '
              'movements; negative ones are corrections and are ignored by this total.',
              'def positive_total(values):\n    if not values:\n        raise ValueError("empty")\n'
              '    return sum(v for v in values if v > 0)\n',
              [('[1, 2, 3]', '6'), ('[1, -2, 3]', '4'), ('[0]', '0'), ('[-1]', '0'), ('[5]', '5')]),
        'B': ('even_count', 'Write `even_count(values)` returning how many integers of `values` are even. Raise '
              '`ValueError("empty")` when `values` is empty. Even counts pair items into boxes of two, so zero and '
              'negative even numbers count too.',
              'def even_count(values):\n    if not values:\n        raise ValueError("empty")\n'
              '    return sum(1 for v in values if v % 2 == 0)\n',
              [('[1, 2, 3]', '1'), ('[2, 4]', '2'), ('[1]', '0'), ('[0]', '1'), ('[-2, 7]', '1')]),
    }

    def __init__(self, exercism_texte: str):
        self.ordre = 0
        self.exercism_texte = exercism_texte
        self.par_fichier = {}  # nom du fichier de départ -> (genre, nom de fonction, solution)

    def ouvert(self, chat_kwargs: dict) -> bool:
        return True

    def exercice(self, genre: str, module: str, cle: str) -> str:
        fn, consigne, solution, cas = self.BONS[cle]
        tests = (f'import unittest\nfrom {module} import {fn}\n\n\nclass T(unittest.TestCase):\n'
                 + ''.join(f'    def test_{k}(self):\n        self.assertEqual({fn}({a}), {b})\n\n' for k, (a, b) in enumerate(cas))
                 + f'    def test_empty(self):\n        with self.assertRaises(ValueError) as err:\n            {fn}([])\n'
                 f'        self.assertEqual(err.exception.args[0], "empty")\n')
        if genre == 'solution_fausse':
            solution = solution.replace('if v > 0', '').replace('if v % 2 == 0', '')
        titre = 'Bank Account' if genre == 'exercism' else f'{fn.replace("_", " ").title()} for {module}'
        texte = self.exercism_texte if genre == 'exercism' else f'In the {module.replace("_", " ")} system: {consigne}'
        signature = f'def {fn}(values)' + ('' if genre == 'depart_casse' else ':')
        morceaux = [f'=== TITLE ===\n{titre}', f'=== INSTRUCTIONS ===\n{texte}',
                    f'=== STUB: {module}.py ===\n```python\n{signature}\n    raise NotImplementedError\n```']
        if genre != 'sans_tests':
            morceaux.append(f'=== TEST: {module}_test.py ===\n```python\n{tests}```\nThe tests use unittest only.')
        morceaux += [f'=== SOLUTION: {module}.py ===\n```python\n{solution}```', '=== END ===']
        return 'Je conçois l\'exercice.</think>' + '\n'.join(morceaux)

    def generer(self, messages: list, phase: dict) -> list[list[dict]]:
        sorties = []
        for conv in messages:
            texte = conv[0]['content']
            if texte.startswith('You are writing a new programming exercise'):
                module = re.search(r'Use exactly these file paths: (\w+)\.py', texte).group(1)
                genre = self.GENRES[self.ordre % len(self.GENRES)]
                cle = 'B' if self.ordre % len(self.GENRES) == 1 else 'A'
                self.ordre += 1
                rep = self.exercice(genre, module, cle)
                self.par_fichier[f'{module}.py'] = (cle, genre)
            else:
                module = next((f for f in self.par_fichier if f in texte), None)
                if module is None:  # autre processus (mesure de l'élève) : exercice reconnu à sa fonction et à son fichier
                    cle = next(k for k, b in self.BONS.items() if b[0] in texte)
                    module = re.search(r'^(\w+\.py)$', texte, re.M).group(1)
                else:
                    cle, _ = self.par_fichier[module]
                fn, _, solution, _ = self.BONS[cle]
                if 'The reference solution fails some of its own tests' in texte:  # campagne 2 : correction de la référence
                    rep = f'{module}\n```python\n{solution}```\n'
                elif 'introduce exactly two independent' in texte:  # deux bogues, à deux endroits (lignes 2 et 4)
                    casse = solution.replace('if not values:', 'if not values and False:').replace(
                        'v > 0', 'v > 1').replace('v % 2 == 0', 'v % 2 == 1')
                    rep = (f'=== BUG ===\nvide accepté ; mauvaise comparaison\n=== REPORT ===\nWith [] I get 0 instead of an '
                           f'error, and with [1, 2, 3] the result is wrong.\n=== FILE: {module} ===\n```python\n{casse}```\n'
                           f'=== END ===')
                elif 'introduce exactly one' in texte:  # bogue simple ou subtil
                    casse = (solution.replace('v > 0', 'v > 1') if cle == 'A' else solution.replace('return sum(', 'return sum(('))
                    rep = (f'=== BUG ===\nmauvaise comparaison\n=== REPORT ===\nWith [1, 2, 3] I get 5 instead of 6.\n'
                           f'=== FILE: {module} ===\n```python\n{casse}```\n=== END ===')
                elif len(conv) == 1 and cle == 'B' and 'Find the bug' not in texte and 'getting a bug' not in texte:
                    rep = f'{module}\n```python\ndef {fn}(values):\n    return 0\n```\n'  # premier essai raté
                else:
                    rep = f'{module}\n```python\n{solution}```\n'
                rep = 'Je réfléchis.</think>' + rep
            sorties.append([{'texte': rep, 'jetons': len(rep.split()), 'fin': 'stop'}])
        return sorties


# ---------------------------------------------------------------- mesure de l'élève (23/10/2026)

def mcnemar_exact(b: int, c: int) -> float:
    """Valeur p bilatérale exacte du test de McNemar (b et c : cas où un seul des deux réussit)."""
    import math
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n)


class PipelineEleve(Pipeline):
    """Mesure de l'élève (accord de l'utilisateur le 23/10/2026) : les exercices gardés par le filtrage du professeur,
    avec les mêmes demandes, la même relance avec la sortie des tests et les mêmes tests que GLM-5.3 (phase de
    résolution en deux essais). Les résultats du professeur sont seulement lus ; ceux de l'élève vont à part et ne sont
    jamais des données d'entraînement. Le bilan compare les deux, exercice par exercice."""

    def __init__(self, travail: Path, config: dict, moteur, debut: float, limite_s: float, processus: int):
        super().__init__(travail, config, moteur, debut, limite_s, processus)
        self.source = travail / config.get('source', RESULTATS)
        self.dossier = travail / config.get('resultats', RESULTATS_ELEVE)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.tmp = travail / 'tmp' / 'exercices_nova_eleve' / f'{os.getpid()}'

    def taches(self) -> dict[str, dict]:
        f = self.source / 'taches_finales.json'
        if not f.exists():
            return {}
        gardes = set(json.loads(f.read_text(encoding='utf-8'))['gardes'])
        return {i: r['entree'] for i, r in lire_jsonl(self.source / 'creation.jsonl').items() if i in gardes}

    def refiltrer_si_besoin(self) -> None:  # le filtrage est celui du professeur, déjà fait
        return

    def exporter(self) -> dict:
        """bilan_eleve.json : réussite de l'élève et de GLM-5.3 sur les mêmes exercices, tableau croisé en deux essais
        (avec McNemar exact), par langage et par difficulté. Rien n'est exporté comme donnée d'entraînement."""
        taches = self.taches()
        p1, p2 = lire_jsonl(self.source / 'resolution.essai1.jsonl'), lire_jsonl(self.source / 'resolution.essai2.jsonl')
        e1, e2 = lire_jsonl(self.dossier / 'resolution.essai1.jsonl'), lire_jsonl(self.dossier / 'resolution.essai2.jsonl')
        communs = sorted(set(e1) & set(p1) & set(taches))

        def deux(a1, a2, i):
            return bool(a1[i]['reussi'] or a2.get(i, {}).get('reussi', False))

        def compte(ids):
            pe = sum(bool(e1[i]['reussi']) for i in ids)
            de = sum(deux(e1, e2, i) for i in ids)
            pp = sum(bool(p1[i]['reussi']) for i in ids)
            dp = sum(deux(p1, p2, i) for i in ids)
            return {'n': len(ids), 'eleve_premier': pe, 'eleve_deux': de, 'glm_premier': pp, 'glm_deux': dp}

        tableaux = {}
        for nom, f in (('premier_essai', lambda a1, a2, i: bool(a1[i]['reussi'])), ('deux_essais', deux)):
            t = collections.Counter((f(p1, p2, i), f(e1, e2, i)) for i in communs)
            tableaux[nom] = {'les_deux': t[(True, True)], 'glm_seul': t[(True, False)], 'eleve_seul': t[(False, True)],
                             'aucun': t[(False, False)], 'mcnemar_p': mcnemar_exact(t[(True, False)], t[(False, True)])}
        bilan = {'exercices': len(communs), 'total': compte(communs), 'tableaux': tableaux,
                 'par_langage': {l: compte([i for i in communs if taches[i]['langue'] == l]) for l in self.config['langages']},
                 'par_difficulte': {d: compte([i for i in communs if taches[i]['difficulte'] == d]) for d in DIFFICULTES}}
        (self.dossier / 'bilan_eleve.json').write_text(json.dumps(bilan, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        t, d = bilan['total'], tableaux['deux_essais']
        print(f"EXERCICES_NOVA_ELEVE : {t['n']} exercices ; élève {t['eleve_premier']} au premier essai, {t['eleve_deux']} en "
              f"deux ; GLM-5.3 {t['glm_premier']} et {t['glm_deux']} ; en deux essais, GLM seul {d['glm_seul']}, élève seul "
              f"{d['eleve_seul']} (McNemar p = {d['mcnemar_p']:.2g}) ; "
              + ' ; '.join(f"{l} {v['eleve_deux']}/{v['glm_deux']}/{v['n']}" for l, v in bilan['par_langage'].items()),
              flush=True)
        return bilan


# ---------------------------------------------------------------- essai à blanc (21/10/2026)
# Le 21/10, une erreur de code (KeyError sur un .h) a arrêté deux créneaux de 8 GPU au début des réparations. Avant de
# charger GLM-5.3, chaque phase restante puis l'export passent donc sur une COPIE des résultats, avec les vraies données,
# un faux moteur aux réponses de forme plausible et de faux tests (rien n'est exécuté) : quelques secondes de processeur.

FICHIER_MONTRE = re.compile(r'^([^\n`=<][^\n`]*)\n```[\w+#-]*\n(.*?)\n```', re.M | re.S)
TEMOIN_CODE = 'professeur.erreur_code'


class MoteurEssai:
    """Faux GLM-5.3 de l'essai à blanc. Création (25/10) : un exercice factice bien formé, aux chemins demandés et avec six
    tests du langage (écrit dans la copie de l'essai). Bogue : les sections attendues, la première ligne du premier fichier
    et la dernière du dernier modifiées (deux endroits). Résolution, réparation et correction de la référence : les
    fichiers montrés renvoyés (légèrement changés pour la correction)."""
    TESTS = {'python': '    def test_cas_{k}(self):\n        pass', 'javascript': "test('cas {k}', () => {{}});",
             'rust': '#[test]\nfn cas_{k}() {{}}', 'java': '    @Test\n    void cas{k}() {{}}', 'cpp': 'TEST_CASE("cas {k}") {{}}',
             'go': 'func TestCas{k}(t *testing.T) {{}}'}

    def ouvert(self, chat_kwargs: dict) -> bool:
        return True

    def exercice(self, texte: str) -> str:
        m = re.search(r'Use exactly these file paths: (.+) for the stub and the solution, (\S+) for the tests\.', texte)
        langue = next(l for l, nom in NOMS.items() if f'for {nom} developers' in texte)
        stubs, test, cl = m.group(1).split(', '), m.group(2), CLOTURES[langue]
        morceaux = ['=== TITLE ===', 'Essai à blanc', '=== INSTRUCTIONS ===', "Exercice factice de l'essai à blanc. " * 8]
        for f in stubs:
            morceaux += [f'=== STUB: {f} ===', '```' + cl, f'// départ {f}', '```']
        morceaux += [f'=== TEST: {test} ===', '```' + cl, *(self.TESTS[langue].format(k=k) for k in range(6)), '```']
        for f in stubs:
            morceaux += [f'=== SOLUTION: {f} ===', '```' + cl, f'// solution {f}', 'ligne 2', 'ligne 3', '```']
        return '\n'.join(morceaux + ['=== END ==='])

    def generer(self, messages: list, phase: dict) -> list[list[dict]]:
        sorties = []
        for conv in messages:
            textes = [m['content'] for m in conv if m['role'] == 'user']
            if 'You are writing a new programming exercise' in textes[0]:
                reponse = self.exercice(textes[0])
            elif 'For a debugging exercise' in textes[0]:
                code = textes[0].split('Correct code:', 1)[-1].split('Answer in exactly this format', 1)[0]
                fichiers = FICHIER_MONTRE.findall(code)
                parties = ['=== BUG ===', 'An off-by-one error.', '=== REPORT ===', 'The first result is wrong.']
                for k, (chemin, contenu) in enumerate(fichiers):
                    lignes = contenu.splitlines() or ['']
                    if k == 0:
                        lignes[0] += ' '
                    if k == len(fichiers) - 1:
                        lignes[-1] += ' '
                    parties += [f'=== FILE: {chemin.strip()} ===', '```', *lignes, '```']
                reponse = '\n'.join(parties + ['=== END ==='])
            else:
                fin = ' ' if 'The reference solution fails some of its own tests' in textes[0] else ''
                reponse = '\n\n'.join(f'{c.strip()}\n```\n{f}{fin}\n```' for t in textes for c, f in FICHIER_MONTRE.findall(t))
            texte = 'Essai à blanc.</think>' + reponse
            sorties.append([{'texte': texte, 'jetons': len(texte.split()), 'fin': 'stop'}] * phase.get('n', 1))
        return sorties


def tests_essai(travail: Path, cas: list, racine_tmp: Path, processus: int) -> list[dict]:
    """Faux tests de l'essai à blanc : rien n'est exécuté ; réussite, échec ou erreur de compilation selon l'empreinte
    des fichiers, pour parcourir chaque branche du code."""
    out = []
    for ex, fichiers in cas:
        h = choix(ex['id'] + json.dumps(fichiers, sort_keys=True), 3)
        sortie = ('All tests passed.', 'FAILED: expected 1 but got 2', 'error: simulated build failure')[h]
        out.append({'reussi': h == 0, 'sortie': sortie, 'secondes': 0.0})
    return out


def essai_a_blanc(travail: Path, config: dict, restantes: list[str], classe=None) -> tuple[str | None, str]:
    """(erreur ou None, sortie) : les phases restantes puis l'export sur une copie des résultats de la classe (Pipeline,
    ou PipelineEleve), avec MoteurEssai et tests_essai, sans e5. Rien n'est écrit hors de la copie, qui est effacée
    ensuite ; les exercices (et, pour l'élève, les résultats du professeur) sont seulement lus."""
    import contextlib
    import io
    import tempfile
    import traceback
    (travail / 'tmp').mkdir(parents=True, exist_ok=True)
    copie = Path(tempfile.mkdtemp(prefix='exercices_nova_essai_', dir=travail / 'tmp'))
    tampon = io.StringIO()
    try:
        p = (classe or Pipeline)(travail, config, MoteurEssai(), time.time(), 1e9, 2)
        if p.dossier.exists():
            shutil.copytree(p.dossier, copie / 'resultats')
        p.dossier, p.tmp, p.tester, p.plonger = copie / 'resultats', copie / 'tmp', tests_essai, lambda *a: None
        p.dossier.mkdir(parents=True, exist_ok=True)
        p.donnees = Path(os.path.relpath(copie / 'donnees', travail))  # exercices factices écrits dans la copie
        p.limite_essai = 12  # création : deux exercices par langage suffisent pour parcourir le code
        with contextlib.redirect_stdout(tampon):
            for etape in restantes:
                if not getattr(p, etape)():
                    raise RuntimeError(f"essai à blanc : la phase {etape} s'est arrêtée avant la fin")
            p.exporter()
        return None, tampon.getvalue()
    except Exception:
        return traceback.format_exc(), tampon.getvalue()
    finally:
        shutil.rmtree(copie, ignore_errors=True)


# ---------------------------------------------------------------- tâche

def generer(args) -> int:
    import pilote as P
    travail = Path(args.travail)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    # rôle : le professeur fabrique les données ; l'élève (23/10) passe seulement les mêmes exercices, pour la mesure
    nom_role = config.get('role', 'professeur')
    role, eleve = config[nom_role], nom_role == 'eleve'
    classe, lanceur = ((PipelineEleve, 'Mesurer_Eleve_Exercices_Discoverer.bat') if eleve
                       else (Pipeline, 'Exercices_Nova_Discoverer.bat'))
    dossier = travail / config.get('resultats', RESULTATS_ELEVE if eleve else RESULTATS)
    etapes = ['resolution'] if eleve else ['creation', 'resolution', 'injection', 'reparation']
    restantes = [e for e in etapes if not (dossier / f'{e}.fini').exists()]
    print(f"EXERCICES_NOVA_DEBUT : {nom_role} ({role['modele']}) ; phases restantes : {', '.join(restantes) or 'aucune'}",
          flush=True)
    if eleve and restantes and not (travail / config.get('source', RESULTATS) / 'taches_finales.json').exists():
        print('EXERCICES_NOVA_BILAN=ECHEC : pas encore d\'exercices gardés du professeur (resultats/exercices_nova)', flush=True)
        return 2
    temoin = dossier / f'{nom_role}.moteur_jamais_pret'
    if restantes and temoin.exists():
        print(f"EXERCICES_NOVA_BILAN=ECHEC : la tâche précédente n'a jamais eu de moteur prêt "
              f"({temoin.read_text(encoding='utf-8').strip()}) ; relancer {lanceur}", flush=True)
        return 4
    debut = time.time()  # l'essai à blanc compte dans le temps de la tâche
    temoin_code = dossier / f'{nom_role}.erreur_code'
    if restantes and temoin_code.exists():  # une erreur de code se reproduirait : pas de chargement pour rien
        print("EXERCICES_NOVA_BILAN=ERREUR_CODE : une tâche précédente s'est arrêtée sur une erreur de code (voir son "
              f"journal) ; le modèle n'est pas chargé. Après correction, relancer {lanceur}", flush=True)
        return 6
    if restantes:
        t0 = time.time()
        erreur, sortie = essai_a_blanc(travail, config, restantes, classe)
        if erreur:
            dossier.mkdir(parents=True, exist_ok=True)
            temoin_code.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} tâche {os.environ.get('SLURM_JOB_ID', '?')}, "
                                   f"essai à blanc\n{erreur}", encoding='utf-8')
            print('EXERCICES_NOVA_ESSAI_A_BLANC=ECHEC : erreur de code sur les vraies données, modèle pas chargé', flush=True)
            for ligne in (sortie.strip().splitlines()[-5:] + erreur.strip().splitlines()[-15:]):
                print('EXERCICES_NOVA_ERREUR ' + ligne, flush=True)
            print('EXERCICES_NOVA_BILAN=ERREUR_CODE', flush=True)
            return 6
        donnees = next((l.split(' : ', 1)[1] for l in sortie.splitlines()
                        if l.startswith(('EXERCICES_NOVA_DONNEES', 'EXERCICES_NOVA_ELEVE'))), '?')
        print(f"EXERCICES_NOVA_ESSAI_A_BLANC=OK ({time.time() - t0:.0f} s) : {', '.join(restantes)} puis l'export, sur une "
              f"copie des résultats avec un faux moteur et de faux tests ; export d'essai : {donnees}", flush=True)
    limite_s = 60 * (args.limite_minutes if args.limite_minutes is not None else role['limite_minutes'])
    processus = max(2, int(os.environ.get('SLURM_CPUS_PER_TASK') or os.cpu_count() or 2) - 4)
    PP.VERROU_JAVA = threading.BoundedSemaphore(max(1, min(6, processus // 4)))
    moteur = None
    if restantes:
        for cle, valeur in (role.get('env') or {}).items():  # avant l'import de vLLM
            os.environ[cle] = str(valeur)
        # pendant le chargement : cache de Gradle propre au rôle et liste d'Exercism (les GPU n'attendent pas)
        fond = [threading.Thread(target=PP.gradle_du_role, args=(travail, nom_role), daemon=True),
                threading.Thread(target=corpus_exercism, args=(travail,), daemon=True)]
        for f in fond:
            f.start()
        if args.simulation:
            corpus = (travail / EXERCISM / 'corpus.json')
            texte = json.loads(corpus.read_text(encoding='utf-8'))[0]['texte'] if corpus.exists() else ''
            moteur = MoteurSimulation(texte)
        else:
            chemin = str(travail / role['modele'])
            essais = [{}] + ([role['repli']] if role.get('repli') else [])
            moteur, _ = P.charger(lambda o: P.MoteurVllm(chemin, {**role['vllm'], **o}, config.get('graine', 0)), essais,
                                  60 * role.get('limite_chargement_minutes', 70), P.arreter_processus_enfants)
            if moteur is None:
                temoin.parent.mkdir(parents=True, exist_ok=True)
                temoin.write_text(time.strftime('%Y-%m-%dT%H:%M:%S') + f" tâche {os.environ.get('SLURM_JOB_ID', '?')}\n",
                                  encoding='utf-8')
                print('EXERCICES_NOVA_BILAN=ECHEC : moteur jamais prêt, voir PILOTE_CHARGEMENT_ECHEC', flush=True)
                return 4
        for f in fond:
            f.join()
    p = classe(travail, config, moteur, debut, limite_s, processus)
    try:
        for etape in restantes:
            if not getattr(p, etape)():
                p.exporter()
                print('EXERCICES_NOVA_BILAN=A_REPRENDRE', flush=True)
                return 3
        p.exporter()
    except Exception:  # erreur de code malgré l'essai à blanc : le créneau suivant ne recharge pas le modèle pour rien
        import traceback
        erreur = traceback.format_exc()
        print(erreur, flush=True)
        temoin_code.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} tâche {os.environ.get('SLURM_JOB_ID', '?')}\n{erreur}",
                               encoding='utf-8')
        try:  # les lots finis restent exportés
            p.exporter()
        except Exception:
            pass
        print('EXERCICES_NOVA_BILAN=ERREUR_CODE : arrêt sur une erreur de code ; le créneau suivant ne charge pas le modèle',
              flush=True)
        return 6
    shutil.rmtree(p.tmp, ignore_errors=True)
    print('EXERCICES_NOVA_BILAN=FINI', flush=True)
    return 0


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('commande', choices=('generer',))
    a.add_argument('--travail', required=True)
    a.add_argument('--config', required=True)
    a.add_argument('--limite-minutes', type=float)
    a.add_argument('--simulation', action='store_true')
    return generer(a.parse_args())


if __name__ == '__main__':
    sys.exit(main())
