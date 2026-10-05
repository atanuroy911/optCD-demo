# Meeting stories: one real example per finding

Each finding has a real case told step by step, the command or file to
show, and a one-line summary. For full commands and troubleshooting see
`MEETING_RUNBOOK.md`.

Setup in Git Bash first (once per terminal):

```bash
cd "/c/Users/atanu/Desktop/OptCD - Shanto Maam"
export PATH="/c/Users/atanu/bin:$PATH:/c/Program Files/GitHub CLI"
set -a; source .env; set +a
export GITHUB_API_TOKEN=$(gh auth token)
```

---

## How OptCD works (30-second version)

1. **Watch:** record every file the build creates and every file it opens.
2. **Decide:** a file created but never opened again is "unused".
3. **Blame:** whichever Maven tool logged "I started" most recently before
   the file appeared is blamed for it.
4. **Fix:** ask Gemini (an AI) for a setting that stops that tool making
   the file, apply it, and re-run the build to check.

**Upload / download in one picture.** Every build runs on a temporary
computer that is wiped afterwards. GitHub's storage is like a locker:

- **Upload** = put a file in the locker.
- **Download** = take it out later.
- **Consume** = actually use it.

To upload a file, the computer has to read it, the way you pick up a
letter to post it. OptCD only watches the one temporary computer, so it
can't see whether anyone ever takes the file out of the locker.

---

## 1. Uploading looks like using (JSON-java)

**Real case.** JSON-java's build makes an HTML test report in
`target/site/` and uploads it on every build. Nothing ever downloads it.

1. We ran the same real build twice; the only difference was that the
   second time the 3 upload steps were removed.
2. **With uploads:** the report folder was "opened" 15 times, all within
   0.02 seconds, during the step called "Upload Test Report". That was the
   upload reading the files to send them.
3. OptCD saw those reads and said the folder was **used**.
4. **Without uploads:** the folder was opened 0 times, and OptCD flagged
   `target/site/css/` as **unused**.

**Show:** `python3 001-investigation/scripts/show_headlines.py e1`

**One line:** "Remove the upload and OptCD says unused; keep it and OptCD
says used. The upload alone fools it."

---

## 2. This happens a lot (the paper's own 110 projects)

**Real case.** We read every workflow of the 110 projects the paper studied.

1. There are 259 uploads. **118 (46%) are never downloaded by anything.**
2. In the paper's own published results, all 19 of those in the workflows
   it analyzed were called **used**, the same answer as the 7 that are
   really downloaded.
3. Example: JSON-java uploads its test reports every build and OptCD never
   flags them, while in most other projects it does flag test reports as
   unused. The only difference is the upload.

**Show:** `python3 001-investigation/scripts/show_headlines.py q1`

**One line:** "Almost half of uploads are never downloaded, and OptCD can't
tell them apart from ones that are."

---

## 3. The opposite mistake: failure-only reports (apache/nifi)

**Real case.** nifi uploads its test reports **only when tests fail**, so
developers can see what broke:

```yaml
if: failure() || cancelled()
path: nifi-system-tests/nifi-system-test-suite/target/failsafe-reports/**/*.txt
```

1. The paper ran a **passing** build, so this upload was skipped.
2. Nobody opened the reports, so OptCD flagged `.../target/failsafe-reports/`
   as **unused**.
3. In the paper's own fixer experiment, that folder was **sent to Gemini
   for removal** (`eval/fixer/updated_prompt_result.json`, id 313).
4. Gemini happened to give no answer that time. If it had, the reports nifi
   needs exactly when tests fail would be gone.

**Show:** `python3 001-investigation/scripts/crossref_paper_results.py`

**One line:** "On a green build, emergency-only reports look unused, so
OptCD tries to delete the files you only need when things break."

---

## 4. Parallel builds blame the wrong part (gson, seata)

**Real case.** gson has 6 parts (modules). We ran the same build normally
and with `-T 4` (four parts at once).

1. **Normal:** each part's test reports were blamed on that part's own test
   tool, **5 of 5 correct**.
2. **Parallel:** **1 of 5 correct**. For example, `test-jpms`'s test reports
   were blamed on `proguard @ test-shrinker`, a different part entirely.
3. Why: with four parts building at once their log lines mix, and OptCD
   just picks whoever logged last.
4. The paper's own data shows the same in apache **seata**, which builds
   with `-T 4C`: `seata-spring-autoconfigure-client`'s test reports were
   blamed on `jacoco:report @ seata-spring-autoconfigure-server`.

**Show:** `python3 001-investigation/scripts/show_headlines.py e2`, then
`cat 001-investigation/logs/E2_surefire_picks.log`

**One line:** "Same project, same code: add parallel building and correct
blame drops from 5/5 to 1/5, always pointing at another part."

---

## 5. Builds inside builds (fabric8 kubernetes-client)

**Real case.** fabric8 uses a tool (`maven-invoker-plugin`) that launches
**mini-builds** of test projects inside its main build.

1. The mini-builds wrote their own test reports, e.g.
   `java-generator/it/target/it/datetime-fmt/target/surefire-reports/`.
2. Their details go to separate log files, not the main log.
3. So OptCD only saw the outer tool and blamed `invoker:3.8.0:run` for
   everything: 38 wrong blames.
4. Any "fix" would target the outer tool, not the test runner that really
   made the files.

**Show:** `001-investigation/evidence/q2_attribution_errors.md` (section H2)

**One line:** "When one tool runs a build inside a build, OptCD blames the
outer tool for everything inside."

---

## 6. Bad timing at the edges (gson compiler)

**Real case** (gson September run, job "build (17)").

1. In the `test-jpms` part the compiler logged "I started", then wrote its
   `maven-status` folder 0.108 seconds later.
2. In those 0.108 seconds the compiler had already **finished**, and the
   next tool (`resources:testResources`) had already logged "I started".
3. OptCD picks whoever logged last, so it blamed
   `resources:testResources`, which is wrong.
4. Overall in that run: test reports **22 of 23** correct (the test tool
   runs for seconds), compiler `maven-status` **1 of 56** correct (written
   in the last instant).
5. The paper's own data shows it too: in crate, `server/target/maven-status/`
   was blamed on `antlr4`, the tool that runs just before the compiler.

**Show:** `001-investigation/results/q2_timing_gson-33849635845.csv`

**One line:** "Files written in a tool's last split second get blamed on
the neighboring tool, so `maven-status` is wrong almost every time."

---

## 7. `maven-status`: the speed-up notebook (gson, rocketmq)

**What it is.** Maven keeps a notebook of what it already compiled, so the
**next** build can skip that work (incremental compilation). It is like
writing "papers 1-100 graded" so tomorrow you only grade the 3 new ones.

**Real case (gson, our September run).**

1. The build ran:
   `mvn test --activate-profiles native-image-test --projects test-graal-native-image --also-make`.
2. Maven wrote its notebook at
   `gson/target/maven-status/maven-compiler-plugin/testCompile/`.
3. Nothing read it during this build, since it's for the next build, so
   OptCD called it **unused**.
4. OptCD asked Gemini (actual prompt): *"...creates the following unused
   directory: `.../gson/target/maven-status/maven-compiler-plugin/testCompile/`
   while running the plugin `proguard:2.7.0:proguard`... Please suggest an
   updated command to avoid creating this unnecessary directory."* Note the
   wrong tool: `proguard` doesn't write this folder, the compiler does.
5. Gemini answered: `... -Dmaven.compiler.useIncrementalCompilation=false`,
   i.e. throw away the notebook and recompile everything every time.
6. OptCD **committed that change** to the real workflow (commit `7a02d6a9`
   on our gson fork) and re-ran the build.

**Real case from the paper's own data (apache/rocketmq, id 112).** The only
"unused" folder was `remoting/target/maven-status/`. Gemini's "fix" was
**the exact same command, unchanged**, yet on the re-run the folder was no
longer "unused". It flips by itself.

**Why the ignore rule doesn't help.** The original code ignores
`maven-status` only at line 214, **after** asking Gemini (line 164),
changing the workflow (line 187) and re-running the build (line 191). It
hides the problem from the final report, after the damage is done. In the
paper's experiment, 29 of 216 Gemini prompts included `maven-status`.

**Show:**
- `000-research/evidence/incremental-compilation-gemini-exchange.txt` (the prompt and answer)
- `000-research/evidence/incremental-compilation-fix.diff` (the committed change)
- `python3 001-investigation/scripts/show_headlines.py q3`

**One line:** "OptCD asked the AI to remove Maven's speed-up notebook, the AI
said turn incremental compilation off, and OptCD committed it. The ignore
rule only hides this at the very end."

---

## 8. The original code blames nothing today (gson)

**Real case.** We ran the paper's **original** blame code on our real gson
build data.

1. It found 94 unused folders.
2. It **skipped all 94** and blamed nothing.
3. Why: today's file watcher "opens" every new folder the instant it is
   created, which erases the folder's creation time. The original code
   needs that time and gives up without it.
4. The paper's 2024 runs didn't hit this, so GitHub's environment has
   changed since.

**Show:** `001-investigation/results/q2_timing_and_compare_gson-33849635845.json`
(`"original_skipped_no_own_timestamp": 94`)

**One line:** "On today's GitHub, the paper's original code can't blame
anything at all; it only worked in the 2024 environment."

---

## 9. The "optcd" name clash (JSON-java)

**Real case** (our E1 run).

1. OptCD marks the boundaries between steps with bookmark files
   (`optcd-3.txt`, `optcd-4.txt`, ...) and finds them by checking "does the
   name contain `optcd`?" (`mapper/utils.py` line 26).
2. Our branch is named `optcd-run`, so git created `optcd-run.lock`
   (14:17:47), which matched by accident.
3. With one extra bookmark, every step answer shifted by one.
4. `target/reports/` was made in the "Build Test Report" step, but OptCD
   blamed the next step, "Upload Test Results".
5. So Gemini was asked to "fix" **`actions/upload-artifact@v5`**, which is
   not even a command. The result was garbage that could not be applied:
   `actions/upload-artifact@v5 --file -B -Dmaven.bundle.skip=true ... mvn package pom.xml ...`.

**Show:**
`grep "optcd-run.lock" "001-investigation/data/raw/JSON-java-37208714988/inotify/inotifywait-build-17 (17)/inotifywait-log-build-17 (17).csv"`

**One line:** "OptCD finds its bookmarks by name, and our branch name
matched by accident, so every step was off by one and Gemini was asked to
fix an upload action."

---

## The whole story in four sentences

1. OptCD decides "used" by watching **one job**, so it can't see whether an
   upload is ever downloaded (1, 2), and it misreads emergency-only
   reports (3).
2. It decides "who made it" from **timestamps alone**, which breaks with
   parallel builds (4), builds inside builds (5), and files written at a
   tool's very end (6, 7).
3. Its original code doesn't even work on today's GitHub (8), and it is
   fragile to file names (9).
4. **Research question:** what extra information (the upload/download map,
   Maven's own structure) would make these two judgments reliable?

## If asked "did you change OptCD?"

"Not in this round. Everything here is measurement, and most numbers come
from the paper's own published results. My own mistakes along the way are
recorded in `001-investigation/FLOW.md`."
