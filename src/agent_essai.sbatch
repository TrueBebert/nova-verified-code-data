#!/bin/bash
# Travail en agent, essai sans modèle (préparé le 01/11/2026, 0 heure GPU) : isolation du conteneur (réseau, dossier du projet,
# dossier personnel, place), puis la chaîne entière sur de vrais bugs de SWE-bench Verified : correction officielle passée par
# le vrai terminal, aucune correction, tâche arrêtée en route puis reprise ; verdict par l'outil officiel. Lancé par
# l'utilisateur (Essai_Agent_Discoverer.bat). Relançable : chaque essai a son propre dossier.
#SBATCH --job-name=nova-agent-essai
#SBATCH --account=@@COMPTE@@
#SBATCH --partition=@@PARTITION@@
#SBATCH --qos=@@QOS_CPU@@
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=@@TRAVAIL@@/journaux/agent-essai-%j.log
set -o pipefail
umask 077
T="@@TRAVAIL@@"
C="$T/code/discoverer"
E="$T/envs/nova-swebench"
export TMPDIR="$T/tmp" XDG_CACHE_HOME="$T/cache" APPTAINER_CACHEDIR="$T/cache/apptainer" PYTHONNOUSERSITE=1
mkdir -p "$TMPDIR" "$APPTAINER_CACHEDIR"
echo "debut $(date -Is) sur $(hostname)"
[ -f "$E/.pret" ] || { echo "AGENT_ESSAI_BILAN=ECHEC : environnement nova-swebench absent"; exit 2; }
"$E/bin/python" -B "$C/agent_code.py" essai --config "$C/agent_code_v1.json" --travail "$T"
code=$?
echo "fin $(date -Is) ; code $code"
exit "$code"
