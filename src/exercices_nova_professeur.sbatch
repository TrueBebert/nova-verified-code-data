#!/bin/bash
# Exercices Nova (préparés le 17/10/2026, lancés par l'utilisateur après son accord) : GLM-5.3 sur un nœud entier (8 GPU,
# 3 h 55 au plus, soit 31 h GPU au plus par créneau) invente des exercices pratiques dans 6 langages, les résout, casse et
# répare des programmes ; les tests tournent sur les processeurs de la tâche (outils de nova-polyglot). Seules les
# réponses vérifiées par les tests deviennent des données (resultats/exercices_nova/donnees.jsonl). Relançable (créneau
# suivant). Réglages dans exercices_nova_v1.json. Mémoire : 1200G, comme le pilote.
#SBATCH --job-name=nova-exo-prof
#SBATCH --account=@@COMPTE@@
#SBATCH --qos=@@QOS@@
#SBATCH --partition=@@PARTITION@@
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=64
#SBATCH --mem=1200G
#SBATCH --time=03:55:00
#SBATCH --output=@@TRAVAIL@@/journaux/exercices-prof-%j.log
set -o pipefail  # pas de -u : /etc/profile et module lisent des variables non définies
umask 077
T="@@TRAVAIL@@"
export TMPDIR="$T/tmp" XDG_CACHE_HOME="$T/cache" TRITON_CACHE_DIR="$T/cache/triton" PYTHONNOUSERSITE=1
export DG_JIT_CACHE_DIR="$T/cache/deep_gemm"  # par défaut ~/.dj : le dossier personnel ne fait que 2 Gio
export HF_HUB_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1  # rien ne part vers l'extérieur
mkdir -p "$TMPDIR" "$TRITON_CACHE_DIR" "$DG_JIT_CACHE_DIR"
# CUDA 12.9 de conda-forge pour les noyaux de DeepGEMM et libstdc++ récente (écrits par installer_deepgemm.sbatch)
. "$T/envs/nova-vllm/etc/deepgemm_env.sh" || { echo "ECHEC : réglages de DeepGEMM absents (installer DeepGEMM d'abord)"; exit 2; }
echo "debut $(date -Is) sur $(hostname)"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
[ -f "$T/envs/nova-polyglot/.pret" ] || { echo "ECHEC : outils de nova-polyglot absents (Preparer_Code_Reel_Discoverer.bat)"; exit 2; }
[ -f "$T/resultats/polyglot/validation.json" ] || { echo "ECHEC : exercices polyglot pas contrôlés (gabarits des langages)"; exit 2; }
"$T/envs/nova-vllm/bin/python" -B "$T/code/discoverer/exercices_nova.py" generer \
  --config "$T/code/discoverer/exercices_nova_v1.json" --travail "$T"
code=$?
echo "fin $(date -Is) ; code $code"
exit "$code"
