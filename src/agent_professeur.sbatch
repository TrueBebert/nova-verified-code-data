#!/bin/bash
# Travail en agent, mesure du professeur (préparée le 01/11/2026, lancée par l'utilisateur après son accord) : GLM-5.3 sur un nœud
# entier (8 GPU, 3 h 55 au plus, soit 31 h GPU au plus par créneau) corrige les bugs contrôlés de SWE-bench Verified dans un
# terminal. Mesure seulement, jamais des données d'entraînement. Essai à blanc et sonde du conteneur avant le chargement du
# modèle. Relançable : chaque tour est écrit, le créneau suivant reprend. Réglages : agent_code_v1.json. Mémoire : 1200G, comme le
# pilote (préchargement des 704 Gio du point de contrôle).
#SBATCH --job-name=nova-agent-prof
#SBATCH --account=@@COMPTE@@
#SBATCH --qos=@@QOS@@
#SBATCH --partition=@@PARTITION@@
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=64
#SBATCH --mem=1200G
#SBATCH --time=03:55:00
#SBATCH --output=@@TRAVAIL@@/journaux/agent-prof-%j.log
set -o pipefail  # pas de -u : /etc/profile et module lisent des variables non définies
umask 077
T="@@TRAVAIL@@"
export TMPDIR="$T/tmp" XDG_CACHE_HOME="$T/cache" TRITON_CACHE_DIR="$T/cache/triton" PYTHONNOUSERSITE=1
export DG_JIT_CACHE_DIR="$T/cache/deep_gemm" APPTAINER_CACHEDIR="$T/cache/apptainer"
export HF_HUB_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1  # rien ne part vers l'extérieur
mkdir -p "$TMPDIR" "$TRITON_CACHE_DIR" "$DG_JIT_CACHE_DIR" "$APPTAINER_CACHEDIR"
. "$T/envs/nova-vllm/etc/deepgemm_env.sh" || { echo "ECHEC : réglages de DeepGEMM absents (installer DeepGEMM d'abord)"; exit 2; }
echo "debut $(date -Is) sur $(hostname)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
[ -f "$T/donnees/swebench/controle_images.jsonl" ] || { echo "ECHEC : bugs de SWE-bench pas contrôlés"; exit 2; }
"$T/envs/nova-vllm/bin/python" -B "$T/code/discoverer/agent_code.py" generer --role professeur \
  --config "$T/code/discoverer/agent_code_v1.json" --travail "$T"
code=$?
echo "fin $(date -Is) ; code $code"
exit "$code"
