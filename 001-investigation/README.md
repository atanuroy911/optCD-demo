# 001-investigation: Is OptCD's misclassification systematic?

Follow-up to `000-research/`, answering three questions from the
professor:

1. Is the uploaded-artifact problem recurring across real workflows?
   Separate consumed artifacts from stored-only ones.
2. Do plugin (producer) attributions go wrong systematically in
   multi-module projects? Verify what really produced each file.
3. Why does `maven-status` still reach Gemini despite the handling in
   `fixer.py`?

Everything used is kept here: scripts, fetched workflows, raw run data,
logs and results. `FLOW.md` is the step-by-step lab notebook, including the
mistakes in my own scripts that I caught and corrected along the way.

## Data sources

- **The paper's own population and results:** the 110 repos in
  `eval/repos-with-commit-counts.csv`, and OptCD's published per-job output
  for 614 jobs and 6,800 unused-dir rows in `eval/all_results/`. These
  results come from the paper's original code, so errors found in them
  belong to the paper's algorithm, not our rewrite.
- **Every workflow file of those 110 repos,** at a paper-era snapshot
  (2024-11-01) and today (`data/workflows/`).
- **Four new controlled GitHub Actions runs** (E1 x2, E2 x2) plus one
  re-downloaded September run, with full raw inotify logs and job logs
  (`data/raw/`).

## Q1: Uploaded artifacts. Yes, recurring and systematic.

Evidence: `evidence/q1_artifacts.md`, `evidence/E1_E2_controlled_experiments.md`.

- **Common.** 40 of 110 repos upload artifacts (259 uploads). 33% have an
  automated consumer, 21% are failure-only diagnostics, and **46% are
  stored-only**: uploaded on every build, never downloaded by any workflow.
  Within the workflows the paper analyzed it is 23 of 39 (59%).
- **Indistinguishable to OptCD.** In the paper's published results, all 19
  stored-only uploads were treated as "used", exactly like the 7 consumed
  ones.
- **Mechanism shown on a real workflow (E1, JSON-java).** Same job with
  and without its upload steps. With uploads, `target/site/` is read 15
  times, all by the upload step, and is not flagged. Without them it is
  read 0 times and is flagged. The upload's own read is what hides it.
- **The opposite error also occurs.** A failure-only diagnostic (apache/nifi
  `failsafe-reports`, uploaded only `if: failure()`) is unread on green
  builds, was flagged unused, and was **sent to Gemini for elimination** in
  the paper's own fixer experiment (id 313).
- **Limit.** Human downloads through the GitHub UI cannot be observed.

## Q2: Producer attribution. Yes, systematic, with three identifiable mechanisms.

Evidence: `evidence/q2_attribution_errors.md`, `evidence/E1_E2_controlled_experiments.md`.

- **Ground truth from Maven's directory conventions** (e.g.
  `maven-status/maven-compiler-plugin/compile/` is written by
  `compiler:compile`). In the paper's data, 1,473 attributions are
  verifiable this way; **110 are wrong (7.5%)**, in 30 jobs across 7 repos.
  `maven-status` is the worst directory type (43% wrong).
- **Every wrong row traces to a mechanism:**

  | Mechanism | Wrong rows | Verified by |
  |---|---|---|
  | Parallel builds (`mvn -T`): blames a plugin from another module | 47 | wrong rate 34.8% vs 4.7% sequential; **E2:** gson `surefire` 5/5 correct sequential vs 1/5 with `-T 4`, all errors cross-module |
  | Nested builds (`maven-invoker-plugin`): all outputs blamed on `invoker:run` | 38 | paper data (fabric8 kubernetes-client) |
  | Timing at plugin boundaries: blames the neighboring plugin | 25 | raw September gson data; compiler `maven-status` 1/56 correct vs `surefire` 22/23 |

- **Reproducibility.** On today's GitHub runners the paper's original
  mapper attributes **nothing** for gson: every directory's own creation
  timestamp is erased by the watcher's self-access, so the mapper skips
  them all. Our September gson attribution numbers came from our rewrite's
  fallback and are excluded as evidence.

## Q3: Why `maven-status` reaches Gemini

Evidence: `evidence/q3_maven_status_flow.md`.

- The only `maven-status` check in the original pipeline is one line
  (`legacy/fixer/run_gemini_with_confirmation.py` L214). It runs after the
  Gemini call (L164), the workflow rewrite (L187) and the re-run (L191),
  and only removes `maven-status` from the "fixed" list. Detection,
  attribution and prompt construction never check for it, and the second
  reporting branch (L227-238) reports it as fixed anyway.
- In the paper's own fixer experiment, **29 of 216 commands (13%)** sent
  `maven-status` to Gemini, and 5 sent nothing else. In our live gson run,
  Gemini's answer was `-Dmaven.compiler.useIncrementalCompilation=false`.
- `maven-status` flips between "unused" and "used" across runs on its own,
  even when the command is unchanged (rocketmq). That is likely why the
  filter exists: it keeps this noise out of the success tally without
  stopping it upstream.

## Side findings

- **Step attribution breaks when any path contains `optcd`**
  (`evidence/step_marker_substring_bug.md`). OptCD finds its step markers
  with `"optcd" in file`. Our branch name `optcd-run` made a git lock file
  match, shifting every step by one. Gemini was then asked to "fix"
  `actions/upload-artifact@v5`. This also corrects my September "bug 6"
  diagnosis in `000-research/` and `docs/findings.md`.
- **The watcher misses file creations** inside freshly made
  subdirectories, so some unused files can never be detected (E1).
- **Output is not deterministic** for identical steps across runs (E1
  `target/reports/` subfolders, `maven-status` in Q3).

## What this suggests (for discussion, not yet a design)

Both artifact usage and producer attribution are misclassified across
multiple projects, by mechanisms that are structural rather than
incidental:
- **Usage** is inferred from same-job file access, which cannot see past
  the job boundary (consumed vs stored-only look identical) or account for
  conditional steps (failure-only diagnostics look unused).
- **Producer** attribution is inferred from timestamp proximity to log
  lines, which breaks under concurrency (parallel modules), indirection
  (nested builds) and plugin-boundary timing.

The information that could resolve both largely exists already: the
workflow's artifact upload/download graph and step conditions, and Maven's
own module and execution structure (reactor order, each plugin's
configured output directories). The open question is how much of it is
needed, and whether it can be combined with OptCD's runtime trace.

## Folder layout

| Path | Contents |
|---|---|
| `FLOW.md` | chronological lab notebook |
| `evidence/` | write-ups backing each claim |
| `scripts/` | every script used (fetch, scan, cross-reference, attribution check, timing, raw-data download, step mapping) |
| `workflows/` | the E1 and E2 workflow variants as pushed |
| `data/workflows/` | fetched workflow YAMLs for 110 repos x 2 snapshots, plus `manifest.json` |
| `data/raw/` | raw inotify CSVs, job logs and `jobs.json` for each analyzed run |
| `results/` | CSV/JSON outputs of every script |
| `logs/` | console output of every script and OptCD run, plus OptCD run transcripts under `logs/optcd-runs/` |
| `runs/E2/` | working folder for the E2 OptCD runs |
