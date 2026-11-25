#!/bin/bash
# Travail en agent, mesure de l'élève (préparée le 01/11/2026, lancée par l'utilisateur après son accord) : Qwen3.5-122B-A10B-FP8
# sur 2 GPU (3 h au plus, soit 6 h GPU au plus par créneau) corrige les bugs contrôlés de SWE-bench Verified dans un terminal.
# Mesure seulement, jamais des données d'entraînement. Essai à blanc et sonde du conteneur avant le chargement du modèle.
# Relançable : chaque tour est écrit, le créneau suivant reprend. Réglages : agent_code_v1.json.
#SBATCH --job-name=nova-agent-eleve
#SBATCH --account=@@COMPTE@@
#SBATCH --qos=@@QOS@@
#SBATCH --partition=@@PARTITION@@
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=03:00:00
#SBATCH --output=@@TRAVAIL@@/journaux/agent-eleve-%j.log
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
"$T/envs/nova-vllm/bin/python" -B "$T/code/discoverer/agent_code.py" generer --role eleve \
  --config "$T/code/discoverer/agent_code_v1.json" --travail "$T"
code=$?
echo "fin $(date -Is) ; code $code"
exit "$code"
