# Investigation flow (lab notebook)

Follow-up to `000-research/`, answering the professor's three questions:

1. **Q1:** Is the uploaded-artifact misclassification a recurring limitation
   across real-world workflows? Separate artifacts that are later consumed
   from artifacts that are only stored.
2. **Q2:** Does producer (plugin) attribution go wrong systematically in
   multi-module projects? Verify the true producer for each case.
3. **Q3:** Why does `maven-status` still reach Gemini, despite the filter in
   `fixer.py`?

Everything used (scripts, fetched workflows, logs, intermediate data) is
kept in this folder. Entries below are chronological.

## Folder layout

| Path | Contents |
|---|---|
| `scripts/` | Every script used, runnable as-is |
| `data/` | Raw inputs fetched or derived (workflow YAMLs, manifests) |
| `results/` | Script outputs (CSVs, JSON summaries) |
| `evidence/` | Curated excerpts that back each claim |
| `logs/` | Console output of each script run |

---

## 2026-10-04: Step 1, fetch real-world workflows (Q1)

**Population.** The repos the paper itself evaluated:
`eval/repos-with-commit-counts.csv` (110 repos; the paper reports 89 after
its own filtering). Using the paper's population, rather than hand-picked
repos, avoids cherry-picking, and OptCD's published results for these repos
already exist in `eval/all_results/` (614 per-job JSON files, matching the
paper's "614 jobs").

**Two snapshots per repo.**
- `head`: default branch today.
- `paper`: default branch as of 2024-11-01. The plugin versions in
  `eval/all_results/` (e.g. `surefire:3.5.0`, released Aug 2024) place the
  paper's runs around autumn 2024, so this snapshot approximates the
  workflows OptCD actually analyzed. Workflows drift, so cross-referencing
  with the paper's results uses this snapshot, not today's.

**Script:** `scripts/fetch_workflows.py` writes `data/workflows/<snapshot>/<owner>__<repo>/`
plus `data/workflows/manifest.json` (commit SHA and errors per repo and
snapshot). Log: `logs/fetch_workflows.log`.

**Issue hit:** the first attempt returned HTTP 401 for all 110 repos,
because the `GITHUB_API_TOKEN` in `.env` (created last month) has expired.
Re-ran with the `gh` CLI's still-valid token (`GITHUB_API_TOKEN=$(gh auth token)`).
The `.env` token must be regenerated before any further `optcd.sh` runs.

## 2026-10-04: Step 2, classify every artifact upload (Q1)

**Script:** `scripts/scan_artifacts.py`. For each `actions/upload-artifact`
or `upload-pages-artifact` step, it searches all workflows in the same repo
for an automated consumer and assigns one category:

| Category | Meaning |
|---|---|
| `consumed-same-workflow` | a `download-artifact` in the same workflow matches by name or pattern, or downloads everything |
| `consumed-cross-workflow` | another workflow fetches it (`workflow_run` + `run-id`, `dawidd6/action-download-artifact`, `gh run download`, test-report actions) |
| `consumed-pages` | `upload-pages-artifact` followed by `deploy-pages` |
| `diagnostic-on-failure` | no automated consumer; the upload only runs on `failure()`/`always()`, i.e. it is meant for a human debugging a failed run |
| `no-automated-consumer` | nothing in the repo ever reads it back |

**Known limit:** a person downloading an artifact through the GitHub UI is
invisible here; GitHub's API exposes no artifact download counts.
`no-automated-consumer` therefore means no workflow consumes the artifact,
not that no human ever looked at it.

**Script:** `scripts/crossref_paper_results.py`. For uploads in workflows
the paper analyzed, it checks whether OptCD's published results flagged the
uploaded location as unused. Hypotheses:
- An upload that runs on every build reads its files, so OptCD never flags
  them, consumed or not. This is the false negative from `000-research/` §4a.
- An upload guarded by `if: failure()` is skipped on green builds, so the
  files go unread and OptCD may flag them. Its fix would then remove the
  diagnostics a failed build needs. That would be a false positive.

## 2026-10-04: Step 3, trace `maven-status` through the pipeline (Q3)

**Code trace.** `grep -rn "maven-status"` over the original implementation
(`legacy/`, `classifier/`, `clusterer/`, `mapper/`, `logger/`) finds one
filter: `legacy/fixer/run_gemini_with_confirmation.py` L214. It runs after
the Gemini call (L164), the YAML rewrite (L187) and the re-run (L191), and
only filters the "fixed" list in the `try` branch. The `except
FileNotFoundError` branch (L227-238) reports `all_unused_old`, maven-status
included, as fixed.

**Paper data.** Script `scripts/q3_maven_status_in_paper.py`, log
`logs/q3_maven_status_in_paper.log`. In the paper's own fixer experiment
(`eval/fixer/updated_prompt_result.json`), 29 of 216 commands (13%) sent a
`maven-status` dir to Gemini, and 5 of them sent nothing else.

**Finding.** For those 5, `maven-status` stopped being "unused" on the
re-run even when Gemini's "fix" was the unchanged command (rocketmq) or an
unrelated flag (litemall, `-Dmaven.compiler.showWarnings=false`). Its
classification flips between runs on its own. The L214 filter most likely
exists to keep this noise out of the success tally. It does not stop
detection or the Gemini prompt.

Evidence write-up: `evidence/q3_maven_status_flow.md`.

## 2026-10-04: Step 4, check plugin attribution against ground truth (Q2)

**Script:** `scripts/q2_attribution_check.py`. Ground truth comes from
Maven's directory conventions (e.g. `maven-status/maven-compiler-plugin/compile`
is written by `compiler:compile`). Rows without an unambiguous convention
are left unverifiable. It runs on the paper's 614 jobs (original mapper)
and on our runs.

**Checker bug caught.** The first run reported 77.6% wrong. Inspecting the
top "wrong" attribution showed `maven-surefire-plugin:*:test` blamed for
`surefire-reports`, which is correct: older Maven prints the full plugin
artifactId instead of the prefix. Added `normalize_plugin`, re-ran. The
buggy run's log was overwritten by the corrected run; its headline numbers
(1,143 of 1,473 "wrong", top entry `maven-surefire-plugin:*:test` x 977)
are recorded here. Only the corrected run is used.

**Corrected result (paper data):** 110 of 1,473 verifiable rows wrong
(7.5%), in 30 jobs across 7 repos. `maven-status` is the worst type: 20 of
47 wrong (43%).

## 2026-10-04: Step 5, classify the error mechanisms (Q2)

**Script:** `scripts/q2_error_patterns.py`, log `logs/q2_error_patterns.log`.
Every one of the 110 wrong rows falls into a mechanism:

| Mechanism | Rows | Supporting signal |
|---|---|---|
| H1. Parallel build (`-T`), blamed plugin from another module | 47 | wrong rate 34.8% in `-T` builds vs 4.7% sequential |
| H2. Nested build (`maven-invoker-plugin`) | 38 | all nested-IT outputs blamed on `invoker:run` |
| H3. Blamed plugin runs just before the true producer | 20 | vs 5 blaming one that runs after |
| Same module, blamed plugin runs after | 5 | javaparser only |

**Open items:**
- H1 rests on one repo (seata is the only `-T` build in the dataset). Plan:
  a controlled CI run of one project sequential vs `-T`.
- H3 is a hypothesis about a timing offset between log-line and file-event
  timestamps. Plan: measure the offset from raw inotify and log data of a
  real run.
- Our runs show a far higher `maven-status` error rate than the paper's.
  This may come from our rewrite's timestamp fallback. Plan: re-run the
  original mapper on the same raw data before using our-run numbers.

**Data-retention note:** the raw inotify CSVs and logs from the September
gson/jsoup runs were deleted during an earlier cleanup of the repo root
(`000-research/` only kept excerpts). GitHub retains artifacts for 90 days,
so they can still be re-downloaded (those runs were 2026-09-04). From now
on all raw data goes into `001-investigation/data/`.

Evidence write-up: `evidence/q2_attribution_errors.md`.

**Correction to `000-research/README.md`:** it cites
`run-history/20260904T054153Z/` as the gson run, but that transcript is a
jsoup run. The gson real-build transcript is `run-history/20260904T073800Z/`.
To fix in `000-research/`.

## 2026-10-04: Step 6, raw-data timing test and mapper comparison (Q2)

**Raw data recovered.** `scripts/download_run_raw.py atanuroy911/gson 33849635845`
re-downloaded the gson detection run (2026-09-04) into
`data/raw/gson-33849635845/`: inotify CSVs, full job logs and `jobs.json`
for all 8 jobs. Log: `logs/download_gson-33849635845.log`. (`gh api` would
not print job logs containing terminal escape codes; the script uses
`requests`, like OptCD itself.)

**Script:** `scripts/q2_timing_and_mapper_compare.py`, log
`logs/q2_timing_and_compare_gson-33849635845.log`.

1. **Mapper comparison.** On identical classifier and clusterer output, the
   original mapper skips all 94 unused dirs: their own creation timestamps
   were erased by the watcher's self-access. Every attribution in our runs
   therefore came from our rewrite's fallback. Our-run numbers are dropped
   as Q2 evidence.
2. **Timing.** The first attempt used `target/classes` as the compiler's
   output marker. That is invalid, because `resources:resources` writes
   there first, and it produced spurious negative offsets. Switched to
   directories written only by one goal (`maven-status/.../compile`,
   `.../testCompile`, `surefire-reports`). Applying the paper's
   nearest-preceding-line rule to the first file event in each:
   `surefire:test` 21 of 22 correct; `compiler:compile` 1 of 28;
   `compiler:testCompile` 0 of 24.

**Hypothesis revised.** H3 ("a fixed offset blames the previous plugin")
does not hold. Here wrong picks are the *next* plugin (51 of 52), while the
paper data mostly blamed the previous one. Revised H3: nearest-timestamp
attribution is fragile at plugin boundaries. `maven-status` is written at
the end of a short compiler execution (often 100-250 ms), so small timing
differences land it in a neighboring plugin's window. Which neighbor gets
blamed depends on the environment. Evidence write-up updated:
`evidence/q2_attribution_errors.md`.

## 2026-10-04: Step 7, artifact classification and OptCD's verdicts (Q1)

**Fetch completed** for all 110 repos at both snapshots (`logs/fetch_workflows.log`).

**Scanner validated and fixed before use** (details in `evidence/q1_artifacts.md`):
1. Removed a rule that let test-report actions count as "downloads
   everything" (false "consumed" for netty's jars).
2. Added `github-script` `downloadArtifact` detection (missed consumers in
   nacos; the pattern occurs in 4 repos).
3. Split `if: always()` (runs on green builds) from `if: failure()`
   (skipped on green builds), giving `stored-only` vs
   `failure-only-diagnostic`.

Then manually checked a seeded sample against the YAML
(`scripts/sample_for_manual_review.py 4 42`). All sampled labels agreed.

**Cross-reference fixed before use.** The first run of
`crossref_paper_results.py` reduced `**/...` upload globs to an empty static
part, which matched every unused dir (nifi showed hundreds of "hits").
Rewrote the overlap check, unit-tested it on 8 cases (all pass), re-ran.

**Results** (logs: `logs/scan_artifacts.log`, `logs/crossref_paper_results.log`):
- 40 of 110 repos upload artifacts, 259 uploads: 33% consumed, 21%
  failure-only, **46% stored-only**. Within paper-analyzed workflows:
  **23 of 39 stored-only**.
- In OptCD's published results, **all 19 stored-only uploads were treated as
  used**, identical to the 7 consumed ones. Clearest case: JSON-java, where
  `surefire-reports` (flagged in most projects) is masked by an orphan
  upload.
- **Opposite error:** nifi's failure-only `failsafe-reports` was flagged
  unused and sent to Gemini (fixer id 313).

**Next (needs CI runs):**
- E1: JSON-java's real workflow with and without its upload steps, to show
  the upload alone flips OptCD's verdict.
- E2: gson sequential vs `-T 4`, to test H1 beyond seata.

## 2026-10-04: Step 8, E1 controlled experiment on JSON-java (Q1)

**Token.** The new `.env` PAT is rejected by GitHub ("Bad credentials",
HTTP 401 on `/user`; the token format looks valid: `github_pat_`, 93 chars,
no stray characters). Runs use `GITHUB_API_TOKEN=$(gh auth token)` instead;
`.env` is untouched.

**Setup.** Forked `stleary/JSON-java` to `atanuroy911/JSON-java`, branch
`optcd-run`. From its real `pipeline.yml`, the `build-17` job was copied
into two variants (`workflows/E1-json-java/`):
- `e1-with-upload.yml`: the job verbatim, with its 3 `upload-artifact` steps.
- `e1-no-upload.yml`: identical except those 3 steps are removed (`diff`
  confirms these are the only differences).

**Design note from reading the YAML first.** `target/surefire-reports/` has a
genuine in-job consumer (`mvn surefire-report:report-only` reads the XMLs),
so it is not a clean upload-only case. `target/site/` (generated by
`mvn site`) and the jar are the upload-only candidates.

**Run (with-upload).** Command:
`python3 optcd.py ../JSON-java/.github/workflows/e1-with-upload.yml ../JSON-java/.github/workflows/opt-e1-with-upload.yml atanuroy911 JSON-java 001-investigation/results/E1-with-upload-out.txt --log-dir 001-investigation/logs/optcd-runs`.
Console: `logs/E1-with-upload-console.log`. Detection run `37208714988`;
raw data in `data/raw/JSON-java-37208714988/` (`scripts/download_run_raw.py`).

**Who reads what** (`scripts/access_by_step.py`, `logs/access_by_step_E1-with-upload.log`):
- `target/site/`: **all 15 reads happen inside "Upload Test Report 17"**,
  in one 22 ms burst (14:18:29.886-.908). The generating step ended 2 s
  earlier. The upload is the only reader. OptCD did not flag `target/site/`.
- `target/surefire-reports/`: read by "Build Test Report" (surefire-report)
  and by its upload. Genuine consumer, not flagged (correct).
- `target/reports/` (surefire-report HTML): created, never read, flagged (correct).

**Own mistake caught and withdrawn.** `access_by_step.py` first labelled
every non-ACCESS event as CREATE, which made `mvn clean` look like it was
re-creating old files, and I briefly suspected a clean-resets-status false
positive. The raw lines show those events are `IN_DELETE`, which the
classifier ignores. Fixed the labels; the hypothesis is withdrawn.

**Side observations:**
- `target/site/`: 15 reads but only 4 recorded creates. The watcher missed
  creations inside freshly made subdirectories (the "recursive watching"
  race the README warns about). Files with missed creates can never be
  classified unused.
- **Step attribution shifted by one** (`evidence/step_marker_substring_bug.md`).
  OptCD finds step markers with `"optcd" in file` (`mapper/utils.py:26`,
  original code). Our branch `optcd-run` makes git create
  `.git/refs/heads/optcd-run.lock`, which matches. Effect seen live:
  `target/reports/` is blamed on `actions/upload-artifact@v5`, and Gemini
  is asked to rewrite that action. The merged "fix" is an unappliable
  garbled string. The same lock file is in all 8 jobs of the September gson
  run.
- **Correction to `000-research/` bug 6 and `docs/findings.md`:** the
  "IndexError fixed by clamping" was this spurious marker overflowing the
  index; the clamp hid it. Both docs corrected. Also corrected the
  `000-research/README.md` gson run-history citation (`20260904T073800Z`,
  not `20260904T054153Z`).

## 2026-10-04: Step 9, E2 controlled experiment on gson (Q2, H1)

**Setup.** From gson's real `build.yml`, the `build` job pinned to JDK 17,
in two variants (`workflows/E2-gson/`), identical except the Maven command:
`mvn verify javadoc:jar` vs `mvn -T 4 verify javadoc:jar`. Disabled the
gson fork's unrelated push-triggered workflows (`gh workflow disable`,
reversible) so they don't run on every push.

**E2-sequential.** Run from a separate working folder
(`001-investigation/runs/E2/`) so it would not share
`responsible_plugins.json` with the concurrent E1 run. Detection run
`37208820120`, raw data in `data/raw/gson-37208820120/`. Stopped during its
fixer stage, which is not needed for E2. `TaskStop` again left the Python
process alive (as in September); it exited on its own moments later, and
the stray verification build `37209120987` was cancelled.

Nearest-log-line rule on raw file events (`scripts/q2_timing_and_mapper_compare.py`):
`surefire:test` 5 of 5 correct; `compiler:compile` 1 of 6; `compiler:testCompile` 0 of 6.

**E2-parallel.** Detection run `37209217089` (`data/raw/gson-37209217089/`,
console `logs/E2-parallel-console.log`). Stopped after detection by killing
its PID directly (`taskkill`), not with `TaskStop`. `surefire:test`
attribution: **5/5 correct sequential vs 1/5 with `-T 4`**, and all 4
errors blame a plugin from another module (`logs/E2_surefire_picks.log`).
H1 confirmed beyond seata.

## 2026-10-04: Step 10, E1 no-upload and comparison (Q1)

Stopped the with-upload run during its fixer loop (PID killed directly;
nothing left in flight on the fork). Disabled the JSON-java fork's
`pipeline.yml` and leftover `opt-e1-with-upload.yml` workflows. Ran the
no-upload variant: detection run `37209308766`
(`data/raw/JSON-java-37209308766/`, console `logs/E1-no-upload-console.log`),
stopped after detection.

| | with-upload | no-upload |
|---|---|---|
| Reads of `target/site/` | 15, all in the upload step | **0** |
| `target/site/...` flagged by OptCD | no | **yes (`target/site/css/`)** |

The orphan upload alone flips OptCD's verdict
(`logs/E1_flagged_comparison.log`). Caveats: only `site/css/` is flagged
because the watcher missed other creates in new subdirectories, and the
flagged `target/reports/` subfolders differ between two identical steps
(nondeterminism).

Write-up: `evidence/E1_E2_controlled_experiments.md`. Updated
`evidence/q1_artifacts.md` and `evidence/q2_attribution_errors.md`.

**State of the forks afterwards.** `atanuroy911/gson` and
`atanuroy911/JSON-java`: unrelated workflows disabled manually; re-enable
with `gh workflow enable <file> --repo <fork>` if needed. No runs in flight.

## 2026-10-05: Step 11, nondeterminism found in my timing script, fixed

While preparing the meeting runbook, re-running
`q2_timing_and_mapper_compare.py` on unchanged raw data gave E2-sequential
`surefire` 4/4 instead of 5/5. Five repeated runs showed the `gson` module's
row appearing in some runs and missing in others.

**Cause.** `module_dir_for` iterated a Python `set` (hash-randomized order).
The repo root `/home/runner/work/gson/gson/` and the module
`/home/runner/work/gson/gson/gson/` both end in `gson`, so for artifact
`gson` the tie went either way. When the root won, no `surefire-reports`
was found there and the row was dropped.

**Fix.** Rank candidates deterministically: exact name match, then longest
name, then deeper path. Re-ran each raw dataset 4 times; results are now
identical every run.

**Corrected figures** (the conclusions do not change):

| Run | Measure | Before | After |
|---|---|---|---|
| gson Sept (`33849635845`) | `surefire:test` | 21/22 correct | **22/23** |
| | `compiler:compile` | 1/28 | **1/31** |
| | `compiler:testCompile` | 0/24 | **0/25** |
| | wrong compiler picks that blame a later plugin | 51 of 52 | **52 of 55** |
| E2 sequential (`37208820120`) | `surefire:test` | 5/5 | 5/5 (unchanged) |
| E2 parallel (`37209217089`) | `surefire:test` | 1/5 | 1/5 (unchanged) |

Updated `README.md` and `evidence/q2_attribution_errors.md`. The figures in
Step 6 above are the pre-fix values, kept as originally recorded.

Also added `scripts/show_headlines.py`, which prints the key numbers for
each question from saved results (no network, no CI), for presenting.
