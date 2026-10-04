# Q1: Is the uploaded-artifact problem recurring?

## Method

**Population.** The 110 repos in the paper's own evaluation list
(`eval/repos-with-commit-counts.csv`), not hand-picked repos.

**Workflow snapshots.** Every workflow file of every repo, fetched twice by
`scripts/fetch_workflows.py`:
- `paper`: default branch as of 2024-11-01, approximating what the paper's
  OptCD runs saw. Used for everything below unless noted.
- `head`: default branch today, for comparison.

Raw files are in `data/workflows/`, with commit SHAs in
`data/workflows/manifest.json`.

**Classification.** `scripts/scan_artifacts.py` finds every artifact upload
(`actions/upload-artifact`, `upload-pages-artifact`) and searches all of the
repo's workflows for an automated consumer:

| Category | Meaning | What OptCD should see on a green build |
|---|---|---|
| `consumed-same-workflow` | a `download-artifact` in the same workflow matches by name or pattern, or downloads everything | upload reads the files, so "used" (correct) |
| `consumed-cross-workflow` | another workflow fetches it (`workflow_run` + `run-id`, `dawidd6/action-download-artifact`, `gh run download`, or a `github-script` `downloadArtifact` call) | "used" (correct) |
| `consumed-pages` | `upload-pages-artifact` followed by `deploy-pages` | "used" (correct) |
| `failure-only-diagnostic` | no consumer; the upload runs only when the build fails | upload skipped, files unread, so "unused". That would remove diagnostics a failed build needs |
| `stored-only` | no consumer; the upload also runs on green builds | upload reads the files, so "used", though nothing ever reads the artifact back |

**Known limit.** A person downloading an artifact from the GitHub UI is
invisible to this analysis; GitHub's API exposes no download counts.
`stored-only` means no workflow consumes the artifact, not that no person
ever looked at it.

**OptCD's verdict.** `scripts/crossref_paper_results.py` checks, for each
upload in a workflow the paper analyzed, whether OptCD's published results
(`eval/all_results/`) report the uploaded location as an unused directory.

## Scanner validation (manual review)

The scanner was checked by hand and fixed twice before any numbers were
used:

1. **False "consumed" (netty).** A test-report action
   (`scacap/action-surefire-report`) in a `workflow_run` workflow was
   treated as downloading every upstream artifact, so netty's jars were
   marked consumed. In fact the workflow downloads only `test-results-*`
   (via `dawidd6/action-download-artifact`); the reporter reads files
   already on disk. Fixed: a test-report action counts as a consumer only
   if it fetches an artifact itself (an `artifact:` input).
2. **Missed consumer (nacos).** `pr-e2e-test.yml` downloads the `nacos`
   and `pr` artifacts through `actions/github-script` JavaScript
   (`github.actions.downloadArtifact`, filtered by `artifact.name == "pr"`).
   Fixed: `github-script` steps calling `downloadArtifact` are parsed for
   the artifact names they filter on. This pattern occurs in 4 repos (nacos,
   camel, rocketmq, trino).
3. **Category design.** The first version lumped `if: always()` with
   `if: failure()`. For OptCD these behave oppositely: `always()` uploads
   run on green builds and read the files, while `failure()` uploads are
   skipped. They were split into `stored-only` and `failure-only-diagnostic`.

Then a fixed random sample (`scripts/sample_for_manual_review.py 4 42`,
saved as `results/manual_review_sample.csv`, log
`logs/sample_for_manual_review.log`) was checked against the YAML:

| Sampled upload | Scanner label | Manual check | Verdict |
|---|---|---|---|
| netty `build-android-jars-aars` | stored-only | name appears only at its upload (`ci-build.yml:228`) | agree |
| nacos `testlog-*-nodejs.txt` | stored-only | names appear only at their uploads in `pr-e2e-test.yml` | agree |
| rocketmq `benchmark-report` | stored-only | name not referenced anywhere else | agree |
| shardingsphere `sql-report` | stored-only | name not referenced anywhere else | agree |
| quarkus `documentation` | consumed-cross-workflow | `preview.yml:40`, `download-artifact` with `run-id`, `name: documentation` | agree |
| openapi-generator `openapi-generator-cli.jar` | consumed-same-workflow | `download-artifact` at lines 100 and 139, matching name | agree |
| jitsi `javah` | consumed-same-workflow | `download-artifact` at lines 122 and 322, matching name | agree |
| netty `test-results-*` | consumed-cross-workflow | `ci-pr-reports.yml:47`, `dawidd6` download `name: test-results-${{ matrix.setup }}` | agree |
| nacos `nacos`, `pr` | consumed-cross-workflow | `github-script` `downloadArtifact` filtered by name | agree (after fix 2) |
| netty / zookeeper `surefire-reports` | failure-only-diagnostic | `if: ${{ failure() }}` | agree |

## Result 1: uploads with no consumer are common

Paper-era snapshot, 110 repos (`results/artifact_summary.json`,
`results/artifacts_paper.csv`):

| | Uploads | Share |
|---|---|---|
| Repos with at least one upload | 40 of 110 | |
| Total uploads | 259 | 100% |
| Consumed (same workflow, cross workflow, Pages) | 86 | 33% |
| Failure-only diagnostic | 55 | 21% |
| **Stored-only (no consumer, runs on green builds)** | **118** | **46%** |

Restricted to the workflows the paper actually analyzed (39 uploads in 15
repos): 7 consumed, 9 failure-only, **23 stored-only (59%)**.

The `head` snapshot (today) shows the same picture at larger scale: 463
uploads in 55 repos, 190 consumed (41%), 97 failure-only (21%), 176
stored-only (38%).

## Result 2: OptCD treats stored-only exactly like consumed

OptCD's published verdicts, for uploads in paper-analyzed workflows of
repos that have results (11 repos; `results/q1_optcd_verdict_by_category.json`,
`results/crossref_paper_results.csv`):

| Category | Uploads | OptCD flagged unused | OptCD treated as used |
|---|---|---|---|
| consumed (same and cross workflow) | 7 | 0 | **7** |
| **stored-only** | **19** | **0** | **19** |
| failure-only-diagnostic | 8 | **2** | 6 |

Stored-only uploads (6 repos: gson, rocketmq, bytecode-viewer, janusgraph,
JSON-java, linkis) are never flagged, exactly like genuinely consumed ones.
OptCD's output carries no signal that separates the two.

**Paired example, stleary/JSON-java.** Its workflow uploads
`target/surefire-reports/`, `target/site/` and `target/*.jar` on every
build (13 upload steps across its jobs and matrix). The scanner finds no consumer
for any of them. Across the paper's dataset `surefire-reports` is the most
commonly flagged unused directory (1,285 correctly attributed rows; see
Q2), yet in JSON-java it is never flagged. The only difference is the
upload step, whose read of the files makes them look used.

## Result 3: failure-only diagnostics get flagged and sent to Gemini

The two flagged uploads are both apache/nifi's `failsafe-reports`,
uploaded only `if: failure() || cancelled()`:
- `system-tests.yml`: `nifi-system-tests/nifi-system-test-suite/target/failsafe-reports/**/*.txt`
- `integration-tests.yml`: `**/target/failsafe-reports/**/*.txt`

On a green build the upload is skipped, the reports go unread, and OptCD
reported `nifi-system-test-suite/target/failsafe-reports/` as unused
(`eval/maven_only_results/apache_nifi_system-tests_build_and_test (ubuntu-latest, 21)_maven_only.json`).
In the paper's fixer experiment this directory was **sent to Gemini to be
eliminated** (`eval/fixer/updated_prompt_result.json`, id 313). Gemini
returned no fix that time, so no harm was done. But had it suggested the
usual `-DdisableXmlReport=true`-style flag, the reports nifi uploads
precisely when its system tests fail would no longer exist.

The other 6 failure-only uploads were not flagged. Possible reasons: the
directory was read by something else in the build, or it was never
created on the analyzed run. This is not established; it would need raw
run data.

## What this establishes, and what it does not

**Establishes:**
- Uploading artifacts that nothing consumes is common, not a corner case:
  46% of uploads in the paper's own population, and 59% within the
  workflows the paper analyzed.
- OptCD's published output treats all 19 such uploads as "used", identical
  to consumed ones.
- The opposite error exists in the paper's own data: a failure-only
  diagnostic was flagged as unused and sent to Gemini.

**Mechanism, confirmed on a real workflow (E1):** JSON-java's real job run
with and without its upload steps. With uploads, `target/site/` is read 15
times, all inside the upload step, and is never flagged. Without them it is
read 0 times and OptCD flags `target/site/css/`. Nothing else changed. See
`evidence/E1_E2_controlled_experiments.md`.

**Does not establish:**
- Human downloads through the UI, which are unobservable.
- Why 6 of the 8 failure-only uploads were not flagged in the paper's runs
  (no raw data for those runs).
