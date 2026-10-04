# Q2: Producer (plugin) attribution errors

## Method

**Ground truth from Maven's directory conventions.** Many output directories
are written by exactly one plugin goal, and the path itself says which. For
example, `target/maven-status/maven-compiler-plugin/compile/` is written by
`compiler:compile`, `target/surefire-reports/` by `surefire:test`, and
`target/japicmp/` by `japicmp:cmp`. The full rule table is in
`scripts/q2_attribution_check.py` (`RULES`). Rows whose path has no
unambiguous producer are labelled **unverifiable** and excluded; nothing is
guessed.

**Data.**
- **Paper:** `eval/all_results/*.json`, the paper's own 614 jobs and 6,800
  unused-directory rows. These were produced by the paper's original mapper,
  so any error here belongs to the paper's algorithm, not to our rewrite.
- **Ours:** the `Analysis for job` entries in `run-history/*/run.jsonl`
  (our gson and jsoup runs), kept for comparison only.

**Name normalization.** Maven logs print plugins either by prefix
(`surefire:3.5.0:test`) or, in older versions, by full artifactId
(`maven-surefire-plugin:3.0.0:test`). The first version of the checker did
not normalize these and reported a false 77.6% error rate, mostly correct
`maven-surefire-plugin` rows counted as wrong. This was caught by inspecting
the top "wrong" attribution and fixed (`normalize_plugin`). Both runs are
logged in `logs/q2_attribution_check.log`; only the corrected numbers are
used below.

## Result: the paper's own data

Scripts: `scripts/q2_attribution_check.py`, `scripts/q2_error_patterns.py`.
Outputs: `results/q2_attribution_rows.csv` (every row with verdict),
`results/q2_attribution_summary.json`, `results/q2_error_patterns.csv`,
`results/q2_error_patterns_summary.json`.

| Measure | Value |
|---|---|
| Unused-dir rows in the paper's results | 6,800 |
| ...attributed to a Maven plugin | 6,530 |
| ...whose true producer is verifiable from the path | 1,473 |
| ...attributed **correctly** | 1,363 |
| ...attributed **wrongly** | **110 (7.5%)** |
| Jobs / repos containing at least one wrong attribution | 30 jobs / 7 repos |

Error rate by directory type (verifiable rows):

| Directory type | Correct | Wrong |
|---|---|---|
| `surefire-reports` | 1,285 | 80 |
| `maven-status` (compiler state) | 27 | **20 (43%)** |
| `classes` | 10 | 9 |
| `jacoco` report | 7 | 1 |
| others (`test-classes`, `japicmp`, `javadoc-bundle-options`, `failsafe-reports`) | 34 | 0 |

## Every wrong row traces to one of three mechanisms

| Mechanism | Wrong rows | Repos |
|---|---|---|
| **H1. Parallel build** (`mvn -T`): blamed plugin is from a different module | 47 | apache/incubator-seata |
| **H2. Nested build** (`maven-invoker-plugin`): nested project outputs blamed on `invoker:run` | 38 | fabric8io/kubernetes-client |
| **H3. Boundary timing**: same module, blamed plugin is the neighbor of the true producer; here it runs just *before* | 20 | shardingsphere, crate, karate, JanusGraph, javaparser |
| H3, neighbor that runs just *after* | 5 | javaparser |

### H1. Parallel builds attribute across modules

Mapper logic (`mapper/utils.py`): collect every `[INFO] --- plugin:goal ---`
line from the log with its timestamp, then for each unused directory pick
the plugin whose line came most recently before the directory was created.
This assumes plugins run one at a time. With `mvn -T 4C`, several modules
build concurrently and their log lines interleave, so "most recent line"
is often a plugin in another module.

| | Verifiable rows | Wrong | Wrong rate |
|---|---|---|---|
| Parallel (`-T`) builds | 135 | 47 | **34.8%** |
| Sequential builds | 1,338 | 63 | **4.7%** |

All 47 parallel-build errors blame a plugin whose own `@ module` label
differs from the module in the path. Examples (seata, command
`./mvnw -T 4C clean test ...`):

| Unused dir (module in path) | Blamed plugin (module in label) |
|---|---|
| `seata-spring-autoconfigure-client/target/surefire-reports/` | `jacoco-maven-plugin:0.8.7:report @ seata-spring-autoconfigure-server` |
| `namingserver/target/surefire-reports/` | `maven-resources-plugin:3.2.0:resources @ seata-discovery-zk` |
| `core/target/surefire-reports/` | `maven-remote-resources-plugin:1.5:process @ seata-dis...` |
| `config/seata-config-nacos/target/surefire-reports/` | `maven-pmd-plugin:3.8:pmd @ seata-discovery-namingserver` |
| `discovery/seata-discovery-zk/target/surefire-reports/` | `maven-compiler-plugin:3.8.1:testCompile @ seata-core` |

**Limit:** seata is the only parallel-build repo in the paper's dataset.
A controlled experiment (same project, sequential vs `-T`) is planned to
test H1 beyond one repo.

### H2. Nested builds hide the real producer

fabric8io/kubernetes-client runs `maven-invoker-plugin`, which builds
separate integration-test projects under `java-generator/it/target/it/*/`.
Those nested builds write their own `surefire-reports/` and `maven-status/`,
but their plugin lines go to per-project `build.log` files, not to the main
CI log. The mapper only ever sees `invoker:run`, so it blames that for
everything:

| Unused dir | Blamed |
|---|---|
| `java-generator/it/target/it/datetime-fmt/target/surefire-reports/` | `invoker:3.8.0:run (integration-tests)` |
| `java-generator/it/target/it/datetime-fmt/target/maven-status/` | `invoker:3.8.0:run (integration-tests)` |

This is arguably "right at the top level" (invoker caused the build), but
any fix generated from it targets the wrong goal: the files are written by
nested surefire and compiler executions, which `-Dinvoker.*` flags only
control indirectly.

### H3. The plugin just before the true producer gets blamed

In single-module cases, 20 of the 25 wrong attributions blame a plugin that
runs **immediately earlier** in Maven's lifecycle than the true producer.
Only 5 blame one that runs later. Distinct cases:

| Directory | True producer (phase) | Blamed (phase) |
|---|---|---|
| `maven-status/` | `compiler:compile` (compile) | `antlr4:antlr4` (generate-sources) |
| `maven-status/` | `compiler:compile` (compile) | `resources:resources` (process-resources) |
| `maven-status/` | `compiler:compile` (compile) | `enforcer:enforce` (validate) |
| `maven-status/` | `compiler:compile` (compile) | `jacoco:prepare-agent` (initialize) |
| `classes/` | `compiler:compile` / `resources:resources` | `resources:copy-resources` |
| `jacoco-report/` | `jacoco:report` (verify) | `antrun:run` (package) |

My initial explanation was a fixed timing offset that always pushes
attribution to the preceding plugin. The raw-data test below shows the
direction is **not** fixed, so H3 is revised to *boundary fragility*.

### H3 revised: nearest-timestamp attribution is fragile at plugin boundaries

**Raw-data test.** Data: gson detection run `33849635845` (2026-09-04),
re-downloaded with `scripts/download_run_raw.py` into
`data/raw/gson-33849635845/` (8 jobs: inotify CSVs and full job logs).
Script: `scripts/q2_timing_and_mapper_compare.py`. Output:
`results/q2_timing_gson-33849635845.csv`,
`results/q2_timing_and_compare_gson-33849635845.json`.

For every plugin execution whose output directory is written by that goal
alone, the script finds the first file event in that module's directory
and applies the paper's rule directly: pick the plugin whose
`[INFO] --- ... ---` line came most recently before the event. Using raw
events, not our mapper, keeps our rewrite's fallback out of this test.

| True producer | Exclusive output dir | Median offset (file event minus own log line) | Rule picks correctly | Picks wrongly |
|---|---|---|---|---|
| `surefire:test` | `target/surefire-reports/` | +789 ms | **21** | 1 |
| `compiler:compile` | `target/maven-status/maven-compiler-plugin/compile/` | +603 ms | 1 | **27** |
| `compiler:testCompile` | `target/maven-status/maven-compiler-plugin/testCompile/` | +1128 ms | 0 | **24** |

(`target/classes` was excluded as a marker after a first attempt: it is
written first by `resources:resources`, which runs before the compiler.)

Example wrong picks (job `build (17)`):

| True producer @ module | File event after own log line | Rule picks instead |
|---|---|---|
| `compiler:compile @ test-jpms` | +108 ms | `resources:testResources @ test-jpms` |
| `compiler:compile @ test-shrinker` | +139 ms | `compiler:testCompile @ test-shrinker` |
| `compiler:compile @ gson-metrics` | +171 ms | `jar:jar @ gson-metrics` |
| `compiler:testCompile @ test-jpms` | +253 ms | `surefire:test @ test-jpms` |
| `compiler:compile @ gson` | +3,355 ms | `bnd:bnd-process @ gson` |
| `compiler:testCompile @ gson` | +4,944 ms | `proguard:proguard @ gson` |

**Interpretation.** The compiler writes its `maven-status` bookkeeping at
the end of its execution. For small or up-to-date modules that execution
takes only 100-250 ms, so by the time the files appear (as timestamped by
the watcher), Maven has already printed the next plugin's log line. Even
for the large `gson` module, the files land after `bnd`/`proguard` have
started. `surefire` runs for seconds and writes reports throughout its own
window, so it stays robust.

**Two datasets, opposite directions, same weakness.** In the paper's
autumn-2024 data, wrong same-module picks mostly fell on the *preceding*
plugin (20 vs 5). In our September-2026 data they fall on the *following*
plugin (51 of 52). Which direction errors take depends on the environment:
runner speed, watcher lag, log-line timestamping. In both, they concentrate
on directories written at a plugin's boundary, with `maven-status` the
worst case (43% wrong in the paper data, 98% here).

**Caveat.** The paper's mapper keys on each directory's own creation
timestamp, while this test uses the first file event inside it. Normally
the two differ by microseconds, since a directory is created immediately
before its first file. In this run the directories' own timestamps were
erased by the watcher's self-access (see below), so the first file event
is the closest available measurement.

## Our rewrite's mapper vs the original, on identical raw data

Same script and data as the raw-data test above. Classifier and clusterer
output is identical; only the mapper differs.

| | Original mapper (as published) | Our rewrite's mapper |
|---|---|---|
| Unused dirs to attribute | 94 | 94 |
| Skipped: directory's own creation timestamp missing | **94 (all)** | 0 |
| Attributed correctly | 0 | 31 |
| Attributed wrongly | 0 | 54 |

**Our-run attribution numbers are excluded as Q2 evidence.** In this run
every unused directory's own creation timestamp is erased: right after
creating a directory, the inotify watcher's recursive-watch setup opens it,
which the classifier records as an access (`000-research/` bug 5). The
original mapper then skips all of them and attributes nothing. Every
attribution in our gson runs, right or wrong, came through our rewrite's
earliest-file fallback (`mapper/utils.py`, `_resolve_directory_timestamp`).
The paper's published data (110 of 1,473 wrong) remains the evidence about
the paper's algorithm; the raw-data timing test above applies the paper's
rule to raw events and does not depend on either mapper implementation.

**Side finding (reproducibility).** On a September-2026 GitHub runner the
original mapper produces zero attributions for gson. The paper's
autumn-2024 runs evidently did not hit this, since its results contain
attributed `maven-status` and `surefire-reports` rows. Something in the
environment (runner image, kernel, or the unpinned `pip install inotify` in
the Logger step) changed the watcher's behavior. As published, OptCD's
mapper is not robust to that change.
