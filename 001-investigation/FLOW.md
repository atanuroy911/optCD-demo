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
