# OptCD: Correctness and Limitations of Generated-Artifact Analysis

An empirical investigation into whether OptCD's "created but never accessed
within this workflow run" definition of *unused* is a reliable proxy for
*unnecessary* in real, modern CI/CD pipelines. All evidence below comes from
real GitHub Actions runs against real projects (`jhy/jsoup`, `google/gson`),
run through this repo's fixed implementation (`optcd/`) — not simulation or
speculation. Raw supporting data is in `evidence/`.

## 1. What was investigated, and how

Three real GitHub Actions executions were analyzed:

1. **`jsoup` (single-module Maven project)** — a straightforward case, used
   as a sanity baseline. Full run history: `run-history/20260904T054153Z/`.
2. **`google/gson` (multi-module Maven reactor, 6 sub-modules, 7 CI jobs)**
   — its real, unmodified `build.yml`, run as-is. Full run history:
   `run-history/20260904T054153Z/` (later section) and `out.txt` copied to
   `evidence/gson-real-build-out.txt`.
3. **Two purpose-built experiment workflows**, added to the `gson` fork
   specifically to isolate questions the real projects' own workflows don't
   naturally answer:
   - `evidence/research-consumption.yml` — two jobs, each building a real
     Maven jar, one consumed via `docker build` + `COPY`, one uploaded via
     `actions/upload-artifact` with no downloader anywhere. (Result:
     confounded — see §4.)
   - `evidence/research-isolated.yml` — one job, four independent
     non-Maven-generated files (so nothing but the tested mechanism could
     touch them), covering: never touched, read in-job, uploaded-but-never-
     downloaded, and Docker-`COPY`-consumed. (Result: clean — see §4.)

Method for each: point `optcd.sh` at the workflow, let it push, wait for the
real run, download the real `inotifywait` CSV + job logs, and inspect both
OptCD's own classification (`out.txt`, `responsible_plugins.json`) **and**
the raw event timeline it was computed from, so every claim below is
checkable against primary data, not OptCD's own summary of itself.

## 2. Behavior successfully reproduced

- The paper's/README's core scenario reproduces exactly: on a `jsoup`
  commit matching the README's own captured example, OptCD found
  `target/surefire-reports/` and `target/japicmp/` as unused, attributed
  both to `mvn -X verify -B --file pom.xml` in the "Maven Verify" step, and
  Gemini suggested the *identical* two flags (`-DdisableXmlReport=true`,
  `-Djapicmp.skip=true`) shown in the README.
- The classifier's core created-vs-accessed logic is correct at the
  mechanism level: in the isolated experiment (§4), the untouched control
  file was correctly flagged unused and the in-job-read control file was
  correctly *not* flagged — the primitive works as designed.
- Docker `COPY` consumption is genuinely detected, not missed. This was an
  open question going in; the isolated experiment settles it (§4).

## 3. Why the flagged artifacts are unused (and mostly correctly so)

Standing pattern across both projects: build directories that Maven creates
as a side effect of a plugin goal, and that nothing later in *that specific
CI job* opens, read, or uploads:

- `target/surefire-reports/` — raw + XML test result files from Surefire,
  never consumed unless something later reads them (test-report action,
  Codecov, etc.) — neither `jsoup` nor `gson`'s workflows do.
- `target/japicmp/` (`jsoup` only) — API-compatibility diff/report files
  from `japicmp`, likewise never read again in-run.
- `.git/hooks/` (both projects) — created by `actions/checkout`, standard
  and expected; correctly attributed to `Checkout`, not a Maven plugin.

These are the tool's strongest, most defensible findings — a human auditing
the same build logs would likely reach the same conclusion for these three.

## 4. Concrete incorrect / insufficient classifications found

### 4a. False negative: artifact uploaded but never consumed (**confirmed, clean evidence**)

`evidence/research-isolated.yml`, job `isolated-test`, four independently
created files:

| Variant | What happens to it | OptCD verdict | Correct? |
|---|---|---|---|
| A | Created, nothing else touches it | **unused** | ✅ correct |
| B | Created, `cat`'d in the same job | not unused | ✅ correct |
| C | Created, `actions/upload-artifact`'d, **no job or workflow ever downloads it** | **not unused** | ❌ wrong — this is a genuinely orphaned artifact |
| D | Created, `COPY`'d into a Docker image via `docker build` | not unused | ✅ correct |

Raw evidence (`evidence/experiment2-inotify-timeline.csv`) for variant C:

```
12:17:24.532288Z ... variant-c;data.txt;IN_CREATE
12:17:25.002775Z ... variant-c/data.txt;IN_ACCESS      <- 0.47s later
```

That single `IN_ACCESS`, 0.47 seconds after creation, lines up exactly with
when the `actions/upload-artifact@v4` step runs — it is the upload action's
*own* internal read of the file to package and transmit it, not any genuine
downstream consumer. Nothing in this workflow or any other ever downloads
`variant-c-orphan`. OptCD reports it as used regardless.

**Mechanism**: `actions/upload-artifact` (and by extension `actions/cache`,
and any similar "read this and ship it somewhere" action) performs a real
file read as an implementation detail of doing its job, which is
indistinguishable, from a single job's inotify trace, from someone actually
needing the content. OptCD's classifier has no way to tell "read to satisfy
a genuine build dependency" from "read to satisfy an upload mechanism."

**Why this matters in modern CI/CD**: uploading build artifacts that
nothing downloads is one of the most common CI hygiene problems in real
pipelines — accumulated over time as workflows evolve and downstream
consumers get removed but the upload step doesn't. This is precisely the
kind of waste OptCD's stated goal is to find, and it is structurally blind
to the most common shape of it once the artifact leaves a job boundary via
a standard Actions primitive.

### 4b. Confound discovered en route: Maven's own packaging masks the question for build outputs

Before landing on the clean experiment above, `evidence/research-consumption.yml`
tried the same question using a real Maven-built jar (Docker-`COPY`'d in one
job, orphan-uploaded in the other). Both jars came back "used" — but the
raw timeline (`evidence/experiment1-jar-timing-sample.csv`) shows why that's
not evidence of anything:

```
12:14:00.899356Z gson-2.14.1-SNAPSHOT.jar;IN_CREATE
12:14:01.541302Z gson-2.14.1-SNAPSHOT.jar;IN_ACCESS   <- 206 IN_ACCESS events total, all within ~2s
```

206 access events land within two seconds of the jar's creation, in both
jobs, well before the Docker or upload steps even start — this is Maven's
own packaging lifecycle (jar verification, attached-artifact handling,
possibly checksum generation) re-reading the file it just built. **For a
Maven-produced final artifact, OptCD's classifier will almost always call
it "used" regardless of what happens to it afterward**, simply because
Maven itself touches it. This isn't wrong, exactly, but it means OptCD
provides no real signal one way or the other about whether a build's
*primary output* is genuinely needed downstream — it happens to look
"used" for reasons unrelated to the question. This is why Experiment 2 was
redesigned around plain non-Maven files with no such internal re-access.

### 4c. False positive: multi-module reactor builds get misattributed to the wrong module

Real `gson` build (`evidence/gson-real-build-out.txt`), job `build (17)`:

```
/home/runner/work/gson/gson/test-shrinker/target/maven-status/.../testCompile/
  -> surefire:3.5.6:test (default-test) @ test-shrinker        [OK, same module]

/home/runner/work/gson/gson/gson/target/maven-status/.../testCompile/
  -> resources:3.5.0:copy-resources (pre-obfuscate-class) @ gson
```

vs. earlier in the same job:

```
/home/runner/work/gson/gson/gson/target/maven-status/.../compile/
  -> bnd:6.4.0:bnd-process (default) @ gson
```

Across the full report, the *same* `maven-status` directory path pattern
under `gson/target/` gets attributed to different plugins in different jobs
(`resources:3.5.0:copy-resources`, `bnd:6.4.0:bnd-process`,
`compiler:3.15.0:compile`) depending on which plugin happened to be
executing closest to that timestamp in that specific run — not because the
attribution logic checks which module or plugin actually owns that
directory. **`mapper/utils.py`'s `get_responsible_plugins` picks "whichever
plugin was running most recently before this timestamp," globally, with no
awareness of Maven reactor module boundaries.** In a single-module project
(`jsoup`) this can't manifest — there's only one module's plugins to be
confused with. In a 6-module reactor like `gson`, it produces plausible-
looking but not-necessarily-correct attributions on every multi-module run.

### 4d. Insufficient analysis: incremental-build state flagged as waste, and "fixed" by disabling the optimization

Every `gson` job flags `target/maven-status/maven-compiler-plugin/{compile,testCompile}/`
as unused. This directory is not a report or a side artifact — it is
**Maven's own incremental-compilation bookkeeping**, written specifically so
a *future* Maven invocation can determine what needs recompiling. Within a
single ephemeral CI run, by definition nothing will ever read it again
(the VM is destroyed after the job), so OptCD's "used within this run"
window can never see its purpose — but that's true of every project using
this optimization, and it isn't waste.

The consequence is visible directly in the run's own Gemini-fixer output
(`evidence/gson-real-build-out.txt`, "Command: mvn clean test..."):

```
Fixes: ['-Dtemplating.skip=true', '-DdisableXmlReport=true',
        '-Dproguard.skip=true', '-Dbnd.skip=true']
```

and, more tellingly, in another job's fix list:

```
Fixes: [..., '-Dmaven.compiler.useIncrementalCompilation=false', ...]
```

The raw prompt/response behind that line — not a paraphrase — is preserved
in `evidence/incremental-compilation-gemini-exchange.txt`:

```
Gemini prompt:
The command `mvn test --activate-profiles native-image-test ...` creates the
following unused directory: .../gson/target/maven-status/maven-compiler-plugin/testCompile/
while running the plugin `proguard:2.7.0:proguard (obfuscate-test-class) @ gson`:
... Please suggest an updated command to avoid creating this unnecessary directory ...

Gemini response:
mvn test --activate-profiles native-image-test --projects test-graal-native-image
  --also-make -Dmaven.compiler.useIncrementalCompilation=false ${{ matrix.extra-mvn-args || '' }}
```

This wasn't hypothetical — the merged fix was actually committed and pushed
to a real branch and re-run on real GitHub Actions to verify it, exactly
like every other fix OptCD generates. The literal diff
(`evidence/incremental-compilation-fix.diff`, commit `7a02d6a9` on
`github.com/atanuroy911/gson`, branch `optcd-run`):

```diff
       - name: Build and run tests
         run: mvn test --activate-profiles native-image-test --projects test-graal-native-image
-          --also-make ${{ matrix.extra-mvn-args || '' }}
+          --also-make ${{ matrix.extra-mvn-args || '' }} -Dbnd.skip=true -DdisableXmlReport=true
+          -Dmaven.compiler.test.skip=true -Dmaven.compiler.useIncrementalCompilation=false
```

The same exchange also catches the multi-module misattribution (§4c) in
the act: the prompt at line 15 blames `proguard:2.7.0:proguard` for
`gson/target/maven-status/.../testCompile/`, while the very next exchange
(line 28) blames a *different* plugin, `bnd:6.4.0:bnd-process`, for a
`maven-status/` path one directory over — same directory family, same job,
attributed to two unrelated plugins purely because each happened to be
running closest in time to when that sub-path was written.

Gemini — working from exactly the prompt it's given, with no way to know
`maven-status/` is a caching mechanism rather than a report — suggested
disabling Maven's incremental compilation entirely to stop the directory
from appearing. That is a real optimization regression, not a cleanup, and
it was verified and accepted as a working fix by the pipeline. Notably, the
codebase already shows *partial* awareness of this exact problem:
`optcd/fixer.py` line 150 explicitly excludes `maven-status` paths when
tallying which directories were "confirmed fixed" after re-running —

```python
fixed_dirs = [d for d in (old_unused - new_unused) if "maven-status" not in d]
```

— but this filter only hides `maven-status` from the *final success report*.
It does nothing to stop `maven-status` from being detected in the first
place, sent to Gemini as a real problem, or having a (potentially harmful)
fix generated and pushed to a real branch for it. The mitigation is
cosmetic, not structural.

### 4e. Insufficient analysis: multi-line `run:` blocks with inline comments break the fixer

One `gson` command spans multiple lines with inline `#` comments:

```yaml
run: |
  mvn clean install -Dmaven.test.skip --projects '!metrics,...'
  # Run with `-Dbuildinfo.attach=false`; otherwise `artifact:compare` fails...
  # See https://issues.apache.org/jira/browse/MARTIFACT-57
  mvn clean verify artifact:compare -Dmaven.test.skip ...
```

OptCD's `extract_unique_commands`/diffing logic treats the entire block —
comments included — as one atomic "command" string. The resulting Gemini
exchange produced garbage tokens fed back as "fixes":

```
Fixes: ['-Dmaven.compiler.useIncrementalCompilation=false#', 'which#', '0)#',
        'https://issues.apache.org/jira/browse/MARTIFACT-57mvn', ...]
```

(`evidence/gson-real-build-out.txt`, final command block). The applied
"fixed command" is visibly malformed shell/YAML, and — tellingly — the
"following directories are fixed" list for this command came back **empty**:
the fix silently did nothing, with no error surfaced anywhere in the
report. A user reading `out.txt` alone would have no way to know this
command's fix attempt failed rather than succeeded with zero applicable
directories.

## 5. Limitations and assumptions that don't hold in modern CI/CD

1. **Single-workflow-run, single-job observation window.** OptCD can only
   see what happens inside the one job it instruments, once. Anything that
   crosses a job boundary (§4a, uploaded artifacts), a workflow boundary
   (`workflow_run` triggers, separate deploy/release workflows), or a
   *build* boundary (incremental-compilation caches, §4d; Maven local
   repository caches; Docker layer caches shared across runs) is invisible
   to it by construction, not by a fixable bug in the Classifier — the
   window is simply too short to ever contain the consumption event.
2. **No module/target awareness in a multi-module build.** §4c shows this
   isn't a hypothetical edge case — it fires on every job of a normal
   6-module open-source project. Any reactor build (extremely common in
   real-world Java/Maven CI) inherits this risk of misattributed "why is
   this unused" explanations, which directly undermines the Fixer's next
   step (patching the *wrong* command's flags for a *different* module's
   plugin).
3. **Any action that reads-to-transmit looks identical to genuine use.**
   `actions/upload-artifact` is the concrete case tested, but the same
   blind spot applies to `actions/cache`, artifact-store/registry pushes,
   and any custom script that `scp`s, `rsync`s, or uploads a directory
   without a human-visible "and then someone downloads it" step in the same
   job. This is a structural property of file-access-based "used"
   detection, not something more logging would fix without also knowing
   whether the *destination* is ever read.
4. **The Fixer's own verification is Linux-only** (a related finding from
   general project testing, not this investigation specifically, but
   directly relevant to trustworthiness): a fix OptCD reports as "confirmed
   working" is only confirmed on the `ubuntu-latest` jobs it can analyze,
   even when the same command is shared by Windows/macOS jobs in the same
   matrix that it silently never re-checks.
5. **LLM-suggested fixes are shaped by prompt framing, not build semantics.**
   §4d shows Gemini reasoning correctly *within* the prompt it's given
   ("stop generating this directory") while being blind to Maven-specific
   knowledge (this directory is a cache, not a report) that the prompt
   doesn't supply and that OptCD's own pipeline doesn't have access to
   either — the Mapper only knows "which plugin ran near this timestamp,"
   not "what this plugin's output is semantically for."

## 6. Most significant observations

- **The clean isolated experiment (§4a) is the most important result**: it
  is not a corner case reached through unusual configuration — uploading a
  build output as a CI artifact is one of the single most common CI/CD
  operations that exist, and OptCD is structurally blind to whether the
  upload is ever consumed.
- **The tool already half-knows about its own weakest case** (§4d, the
  `maven-status` exclusion in `optcd/fixer.py`) but only patches the
  symptom (hide it from the success tally) rather than the cause (don't
  treat Maven's own incremental-build state as a candidate for removal in
  the first place, or don't hand it to an LLM that will confidently suggest
  disabling a real optimization to satisfy a metric).
- **Reactor-build misattribution (§4c) was found on the very first
  multi-module project tested**, not after searching for an adversarial
  case — this suggests it is the common case for real multi-module Java
  projects, not a rare one.
- Docker `COPY` consumption **is** correctly detected (§4, item D) — the
  investigation's working assumption that containerization would be an
  obvious blind spot turned out to be wrong; the actual blind spot is one
  step removed from Docker specifically, at the artifact-upload layer.

## 7. Research question / gap this motivates

> **Can a decision procedure be built that classifies a generated CI
> artifact as "unnecessary" based on evidence beyond same-job file access —
> incorporating cross-job/cross-workflow artifact graphs (`upload-` /
> `download-artifact` pairs, `workflow_run` chains), build-tool-specific
> semantics (recognizing incremental-build caches, reactor module
> boundaries, and dependency-resolution state as categorically different
> from disposable reports), and a confidence signal the Fixer can act on
> differently (e.g., refuse to auto-generate a fix for an artifact type it
> cannot semantically classify, rather than treating every unused directory
> as equally safe to eliminate)?**

Concretely, this splits into two tractable sub-problems evidenced directly
above: (a) building an artifact-flow graph across a workflow's
`upload-artifact`/`download-artifact` (and `actions/cache`) calls before
concluding "unused," which would directly resolve §4a without needing any
ML; and (b) making the Mapper module-aware in a Maven reactor (attribute by
matching the unused path's module segment against the plugin execution's
own module context in the log, not merely by nearest-timestamp), which
would directly resolve §4c. Both are analysis-depth improvements to the
existing deterministic pipeline — no new ML/VLM method is needed to close
either gap; the gap is that the current analysis doesn't look at
information it already has access to (the full workflow YAML for artifact
flow; the full Maven log's module context lines for reactor attribution).

## Evidence index

| File | What it shows |
|---|---|
| `evidence/gson-real-build-out.txt` | Full real `gson` OptCD report: module misattribution (§4c), `maven-status` false positives + broken incremental-compilation "fix" (§4d), comment-corrupted fixer output (§4e) |
| `evidence/incremental-compilation-gemini-exchange.txt` | Raw, verbatim Gemini prompts/responses for §4d — includes the `useIncrementalCompilation=false` suggestion and a live example of §4c's misattribution in the same exchange |
| `evidence/incremental-compilation-fix.diff` | The actual `git show` diff of commit `7a02d6a9` on `github.com/atanuroy911/gson` — proof the fix was really committed, pushed, and re-run on GitHub Actions, not hypothetical |
| `evidence/research-consumption.yml` | Experiment 1 workflow (Maven jar, confounded — §4b) |
| `evidence/experiment1-jar-confound-out.txt` | Experiment 1 OptCD report |
| `evidence/experiment1-jar-timing-sample.csv` | Raw inotify timing proving the Maven self-access confound |
| `evidence/research-isolated.yml` | Experiment 2 workflow (four non-Maven variants — §4a, clean) |
| `evidence/experiment2-isolated-out.txt` | Experiment 2 OptCD report: only variant A flagged unused |
| `evidence/experiment2-inotify-timeline.csv` | Raw inotify timeline for all four variants, timestamps included |
| `../run-history/20260904T054153Z/` | Full git/gh/Gemini transcript for the real `gson` build run |
| `../run-history/20260906T121321Z/` | Full transcript for Experiment 1 |
| `../run-history/20260906T121658Z/` | Full transcript for Experiment 2 |
