#!/bin/bash
# Travail en agent : corrections finales lancées chacune dans un conteneur neuf (Apptainer, mode simple, calque temporaire), verdict
# par l'outil officiel (swebench 5.0.2) ; sur processeur, 0 heure GPU. Soumise après les tâches GPU (afterany). Relançable : chaque
# bug corrigé est noté au fil de l'eau, une phase finie n'est pas refaite.
#SBATCH --job-name=nova-agent-eval
#SBATCH --account=@@COMPTE@@
#SBATCH --partition=@@PARTITION@@
#SBATCH --qos=@@QOS_CPU@@
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --output=@@TRAVAIL@@/journaux/agent-eval-%j.log
set -o pipefail
umask 077
T="@@TRAVAIL@@"
C="$T/code/discoverer"
E="$T/envs/nova-swebench"
R="$T/resultats/swebench_agent"
export TMPDIR="$T/tmp" XDG_CACHE_HOME="$T/cache" APPTAINER_CACHEDIR="$T/cache/apptainer" PYTHONNOUSERSITE=1
mkdir -p "$TMPDIR" "$APPTAINER_CACHEDIR"
echo "debut $(date -Is) sur $(hostname)"
[ -f "$E/.pret" ] || { echo "SWEBENCH_ECHEC : environnement nova-swebench absent"; exit 2; }
code=0
for g in "$R"/*.genere; do
  [ -f "$g" ] || { echo "SWEBENCH_EVAL_RIEN : aucune phase avec toutes ses réponses écrites"; break; }
  nom=$(basename "$g" .genere)
  if [ -f "$R/$nom.fini" ]; then echo "SWEBENCH_EVAL_DEJA $nom : déjà corrigée"; continue; fi
  "$E/bin/python" -B "$C/swebench_apptainer.py" evaluer --travail "$T" --predictions "$R/$nom.predictions.jsonl" \
    --processus 2 --mode simple
  c=$?
  if [ "$c" -eq 0 ]; then date -Is > "$R/$nom.fini"; else code=$c; fi
done
echo "fin $(date -Is) ; code $code"
exit "$code"
