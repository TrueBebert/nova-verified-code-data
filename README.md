# Nova — test-verified code data and agent harness

This repository contains part of the work behind **Nova**, a European general-purpose model project run by a solo founder (Hexon). The plan is to distill **GLM-5.3** (the teacher) into **Qwen3.5-122B-A10B** (the student) on the EuroHPC supercomputer **Discoverer**, using 8× NVIDIA H200 nodes and a 5,000 GPU-hour allocation.

The project is run by one person directing AI coding agents. The code, the audits and the numbers below come from that work. Code comments and reports are in French.

## What is here

| Folder | Content |
|---|---|
| `src/exercices_nova.py` | The data pipeline: GLM-5.3 writes programming exercises in 6 languages, solves them, injects bugs and repairs them. Only answers that pass the tests become examples. |
| `src/audit_*.py`, `src/appliquer_exclusions_v2.py`, `src/trier_essai600.py` | Data audit and exclusion rules, applied to new files: the source data is never modified. |
| `src/agent_code.py` | Agent harness: a model fixes real bugs in a terminal, one command per turn, inside an isolated container. Turns are saved, so work resumes in the next job. |
| `src/*.sbatch`, `src/*.json` | SLURM job templates and run settings. |
| `data/sample_v2.jsonl` | 58 examples from campaign 2, covering all 6 languages and all 4 example types. |
| `data/stats.json` | Counts for the full cleaned datasets. |
| `reports_fr/` | The original audit and plan reports, in French. |

## The pipeline

1. **Create.** GLM-5.3 (reasoning effort `high`) writes an exercise: statement, starter file, tests and a reference solution. It is kept only if the reference passes its tests and the starter fails them without compilation errors.
2. **Filter.** Near-duplicates are removed, using multilingual-e5 embeddings with a relative z-score rule and lexical checks. So are exercises too close to Exercism, which stays an evaluation set and is never used for training.
3. **Solve.** GLM-5.3 solves each exercise from the statement alone. A second attempt sees the failing test output.
4. **Break and repair.** A subtle or double bug is injected into a verified solution. GLM-5.3 repairs it from either the test output or a user-style bug report.
5. **Export.** Only test-verified answers are exported, with the teacher's reasoning kept apart from the answer.

Safeguards built after real failures:
- **Dry run:** every GPU job first replays its remaining phases on a copy of the real results, with a fake engine. A code error stops the job before the model loads.
- **Lot sizing:** batches are sized to the time left in the job.
- **Queue limit:** job chains respect the cluster's queue limit.

## Results (measured)

| | Trial (Oct 2026) | Campaign 2 (Oct 25–30, 2026) |
|---|---|---|
| Exercises requested | 600 | 2,869 |
| Valid creations | 348 | 2,194 |
| Kept after filtering | 306 | 1,845 |
| Test-verified examples | 541 | 2,909 |
| **Kept after audit** | **514** | **2,533** |
| GPU hours (H200) | 61 | 346 |

Campaign 2 in detail:
- **Solving:** GLM-5.3 solved 1,323 of 1,845 exercises at the first try, and 1,671 in two tries.
- **Bug injection:** 1,294 bugs were valid.
- **Repair:** 1,238 of them were repaired.

**Teacher versus student, on the trial exercises (paired):**

| | First try | Two tries |
|---|---|---|
| GLM-5.3 | 250 / 306 | 299 / 306 |
| Qwen3.5-122B (student) | 155 / 306 | 231 / 306 |

The gap is significant (exact McNemar test, p ≈ 7e-18). The exercises are useful to teach the student.

**Real-code benchmarks, used for evaluation only:**
- **Aider polyglot (224 exercises, two tries):** GLM-5.3 (`high`) 178, student 150. The gap is significant.
- **SWE-bench Verified (92 bugs, files given, one try):** GLM-5.3 54, student 48. The gap is not significant.

## What the audit found

The audit was not a formality. Its findings changed the data:
- **Reference correction.** When a reference solution failed its own tests, a correction prompt that treated the tests as final made the teacher bend code to pass wrong tests. Evidence, from first tries made without seeing the tests: GLM-5.3 solved 83 % of uncorrected exercises but only 11 % of corrected exercises where a contradiction was reported. Those exercises were removed.
- **Double bugs.** In some double-bug repairs, one of the two bugs stayed in the repaired code because the tests did not see it. These repairs were removed.
- **File extraction.** A nested code fence in the teacher's answer broke file extraction and caused false failures. The affected examples were removed.
- **Answers about the test itself.** Answers talking about the test ("grader", "injected bug") were removed.

Each exclusion has its reason recorded. The source files are untouched, and every output file comes with a SHA-256 manifest.

## Agent harness (in progress)

`src/agent_code.py` runs a model in a terminal on real bugs. Each bug gets an Apptainer container with no network, no project directory and no home directory; a probe checks this before the model is loaded. The harness saves each turn and resumes after the job ends, and verdicts come from the official SWE-bench grader in a fresh container.

A model-free trial on the cluster passed:
- the container is isolated;
- the official fix, applied through the terminal, resolves the bug;
- no fix leaves the bug unresolved;
- a stopped run resumes without losing work.

The GPU measurement (teacher against student, in agent mode) has not been run yet. SWE-bench is used for measurement only and never for training.

## Data format

Each line of `data/sample_v2.jsonl` is one example:

- `id`, `exercice`, `langage`, `difficulte`, `type`: identifiers. `type` is one of `ecrire`, `reparer_apres_tests`, `reparer_bogue_tests` or `reparer_bogue_rapport`.
- `professeur`, `effort`, `verification`: provenance.
- `messages`: the conversation. The last assistant message is the one to learn, flagged `"entrainer": true`. Its reasoning is in `raisonnement`, separate from `content`.

## Running the tests

```bash
cd src
python test_agent_code.py
```

The tests need git and bash, but no GPU and no network. They use a fake engine, a fake terminal and the real terminal loop, run with our own commands.

## License

- **Code:** Apache-2.0 (see `LICENSE`).
- **Data:** the sample was generated by GLM-5.3, which is released under its own license (zai-org). Check those terms before reusing the data. The exercises are synthetic, and no benchmark content is included.
