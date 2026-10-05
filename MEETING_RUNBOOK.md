# Meeting runbook: showing and replicating every OptCD experiment

Covers September (`000-research/`) and the October follow-up
(`001-investigation/`). Each entry has four parts:

1. **Command** to run
2. **What it does**, in plain words
3. **Evidence**: where the saved proof lives
4. **Details**: what to say if asked

There are two kinds of command:

- **REPLAY** commands re-analyze data already saved on this laptop. They
  take seconds, need no internet, and give the same answer every time. Use
  these in the meeting.
- **LIVE** commands run a fresh build on GitHub Actions. They take about
  3-10 minutes, need internet, and can be flaky. Only use them if someone
  asks to see a real run happen.

---

## 0. Setup (once per new terminal)

Open **Git Bash** (not PowerShell, not cmd) and paste:

```bash
cd "/c/Users/atanu/Desktop/OptCD - Shanto Maam"
export PATH="/c/Users/atanu/bin:$PATH:/c/Program Files/GitHub CLI"
set -a; source .env; set +a
export GITHUB_API_TOKEN=$(gh auth token)
python3 --version && gh auth status 2>&1 | head -2
```

**What it does:** moves into the project folder, makes `python3` and `gh`
available, loads the Gemini key from `.env`, and borrows the GitHub login
from the `gh` tool.

**Details:**
- The `GITHUB_API_TOKEN` line is there because the token in `.env` is
  currently rejected by GitHub ("Bad credentials"). It uses the `gh` login
  instead. Once `.env` has a working token, that line can be dropped.
- `/c/Users/atanu/bin` holds a small `python3` shim. Windows' built-in
  `python3` is a Microsoft Store stub that doesn't work.

---

## 1. One-screen summary (start here in the meeting)

```bash
python3 001-investigation/scripts/show_headlines.py all
```

**What it does:** prints the key numbers for all three questions and both
controlled experiments, in about a second. Use `q1`, `q2`, `q3`, `e1` or
`e2` instead of `all` to show just one.

**Evidence:** reads `001-investigation/results/*.json` and
`001-investigation/logs/E1_flagged_comparison.log`.

**Expected output (abridged):**

```
Q1  STORED-ONLY (never read back): 118 (46%) ... stored-only treated as used: 19 flagged unused: 0
Q2  WRONG: 110 (7.5%) ... parallel 34.8% vs sequential 4.7%
Q3  ...whose prompt included maven-status: 29 (of 216)
E1  target/site/css/ flagged only in the no-upload run
E2  sequential correct 5/5, parallel -T 4 correct 1/5
```

---

# Part A: September (`000-research/`)

## A1. The tool works: reproducing the paper's own example (jsoup)

**REPLAY: show the saved result**

```bash
cat 000-research/evidence/incremental-compilation-gemini-exchange.txt | head -40
ls run-history/
```

**LIVE: run it again (about 5-10 min; see "How to do a LIVE run safely")**

```bash
gh workflow enable opt-build.yml --repo atanuroy911/jsoup
git -C ../jsoup rm -q .github/workflows/opt-build.yml
git -C ../jsoup commit -qm "meeting: reset opt-build" && git -C ../jsoup push -q
python3 optcd.py ../jsoup/.github/workflows/build.yml ../jsoup/.github/workflows/opt-build.yml \
  atanuroy911 jsoup meeting-jsoup-out.txt --log-dir run-history
```

**What it does:** points OptCD at the jsoup project's real build. OptCD
adds a "file watcher" to the build, runs it on GitHub, finds folders that
were created but never opened, works out which tool made them, and asks
Gemini how to stop making them.

**Evidence:**
- `run-history/<timestamp>/run.log`: every git command, GitHub call, and
  Gemini prompt and answer for a run.
- `docs/findings.md`: September write-up.

**Details:**
- The jsoup fork (`atanuroy911/jsoup`, branch `optcd-run`) is pinned to
  commit `b29ba354`, which matches the JDK 8/17/21 setup in the paper's
  README example.
- Expected result: `target/surefire-reports/` (test reports) and
  `target/japicmp/` (API-compatibility report) flagged as unused and
  blamed on `mvn -X verify`. Gemini then suggests `-DdisableXmlReport=true`
  and `-Djapicmp.skip=true`, the same two flags as the paper's README.
- Getting this working took seven fixes to the tool's plumbing (Windows
  paths, a retired Gemini model, and so on). See `docs/findings.md`. One of
  them ("bug 6") was later found to be misdiagnosed; see B8.

## A2. First hint of Q1: an upload counts as a "use" (4-file experiment)

**REPLAY**

```bash
cat 000-research/evidence/research-isolated.yml
cat 000-research/evidence/experiment2-isolated-out.txt
cat 000-research/evidence/experiment2-inotify-timeline.csv
```

**LIVE (about 3 min)**

```bash
gh workflow enable opt-research-isolated.yml --repo atanuroy911/gson
git -C ../gson rm -q .github/workflows/opt-research-isolated.yml
git -C ../gson commit -qm "meeting: reset opt-research-isolated" && git -C ../gson push -q
python3 optcd.py ../gson/.github/workflows/research-isolated.yml ../gson/.github/workflows/opt-research-isolated.yml \
  atanuroy911 gson meeting-isolated-out.txt --log-dir run-history
```

**What it does:** a tiny made-up build creates four text files:
- **A:** never touched again
- **B:** read with `cat`
- **C:** uploaded to GitHub storage, never downloaded
- **D:** copied into a Docker image

OptCD should call A unused and the rest used, except C, which nothing
really needs.

**Evidence:** `000-research/README.md` §4a; the three files above.

**Details:**
- Result: only A was flagged. C was called "used".
- The timeline shows why: C's only "open" happens 0.47 s after creation,
  exactly when the upload step runs. The upload reads the file in order to
  send it, and OptCD can't tell that apart from real use.
- D (Docker) was correctly called used, because Docker genuinely reads the file.

## A3. First hint of Q2/Q3: gson, and Gemini disabling incremental compilation

**REPLAY**

```bash
cat 000-research/evidence/incremental-compilation-gemini-exchange.txt
cat 000-research/evidence/incremental-compilation-fix.diff
```

**What it does:** shows the exact prompt OptCD sent to Gemini about the
`maven-status` folder, Gemini's answer, and the change OptCD then committed
to the real gson workflow.

**Evidence:** both files above; full run log
`run-history/20260904T073800Z/run.log`; commit `7a02d6a9` on
`github.com/atanuroy911/gson`.

**Details:**
- `maven-status/` is Maven's memory of what it already compiled, so the
  *next* build can skip work.
- OptCD only watches one build, so it never sees that memory being used and
  calls it "unused".
- Gemini's answer, `-Dmaven.compiler.useIncrementalCompilation=false`,
  turns that speed-up off. It makes builds slower, not faster.

---

# Part B: October follow-up (`001-investigation/`)

The professor asked:
1. Is the upload problem common?
2. Does OptCD blame the wrong tool systematically?
3. Why does `maven-status` still reach Gemini?

**No OptCD code was changed in this round.** Everything below is measurement.

## B1. Q1: how many uploads are never used? (paper's 110 projects)

**REPLAY (about 10 s)**

```bash
python3 001-investigation/scripts/scan_artifacts.py | tail -25
python3 001-investigation/scripts/show_headlines.py q1
```

**What it does:** reads every GitHub Actions workflow of the 110 projects
the paper studied, finds every "upload a file to GitHub storage" step, and
checks whether anything ever downloads it.

**Evidence:**
- `001-investigation/results/artifacts_paper.csv`: one row per upload,
  with category and proof.
- `001-investigation/results/artifact_summary.json`
- `001-investigation/data/workflows/`: the actual workflow files.
- `001-investigation/evidence/q1_artifacts.md`: full write-up.

**Details:**
- 40 of 110 projects upload artifacts, 259 uploads in total:
  - 33% are downloaded by something.
  - 21% are failure-only diagnostics: uploaded only when a build fails, for
    a person to inspect.
  - **46% are stored-only:** uploaded on every build, never downloaded by
    any workflow.
- The workflows come from two snapshots: as of 2024-11-01, around when the
  paper ran, and today.
- The scanner was checked by hand on a random sample. Three of its rules
  were wrong at first (netty, nacos, and how `always()` was treated) and
  were fixed before any number was used; see `FLOW.md` step 7.
- **Limit:** a person downloading through the GitHub website leaves no
  trace we can see, so "stored-only" means "no workflow downloads it".

## B2. Q1: what OptCD said about those uploads (paper's own results)

**REPLAY**

```bash
python3 001-investigation/scripts/crossref_paper_results.py
```

**What it does:** for each upload in a workflow the paper analyzed, looks
up OptCD's published answer for that folder (`eval/all_results/`).

**Evidence:** `001-investigation/results/crossref_paper_results.csv`,
`001-investigation/results/q1_optcd_verdict_by_category.json`.

**Details:**
- **All 19 stored-only uploads were treated as "used"**, the same as the 7
  genuinely downloaded ones. OptCD's output can't tell the two apart.
- The 2 flagged uploads are apache/nifi's `failsafe-reports`, which it
  uploads only `if: failure()`. On a passing build nobody opens them, so
  OptCD said "unused", and they were sent to Gemini for removal (paper's
  fixer data, id 313). That is the opposite mistake: deleting reports
  developers need when a build breaks.
- Clearest real example: **stleary/JSON-java**. It uploads its test reports
  every build and nothing downloads them, and they are never flagged.

## B3. E1: proving the upload alone fools OptCD (JSON-java, controlled)

**REPLAY**

```bash
python3 001-investigation/scripts/show_headlines.py e1
python3 001-investigation/scripts/access_by_step.py 001-investigation/data/raw/JSON-java-37208714988 "build-17 (17)" target/site/
python3 001-investigation/scripts/access_by_step.py 001-investigation/data/raw/JSON-java-37209308766 "build-17 (17)" target/site/
diff 001-investigation/workflows/E1-json-java/e1-with-upload.yml 001-investigation/workflows/E1-json-java/e1-no-upload.yml
```

**LIVE (about 4 min each; stop with Ctrl+C after the "Analysis for job" line)**

```bash
# with uploads
gh workflow enable opt-e1-with-upload.yml --repo atanuroy911/JSON-java
git -C ../JSON-java rm -q .github/workflows/opt-e1-with-upload.yml
git -C ../JSON-java commit -qm "meeting: reset" && git -C ../JSON-java push -q
python3 optcd.py ../JSON-java/.github/workflows/e1-with-upload.yml ../JSON-java/.github/workflows/opt-e1-with-upload.yml \
  atanuroy911 JSON-java meeting-E1-with-out.txt --log-dir 001-investigation/logs/optcd-runs

# without uploads
gh workflow enable opt-e1-no-upload.yml --repo atanuroy911/JSON-java
git -C ../JSON-java rm -q .github/workflows/opt-e1-no-upload.yml
git -C ../JSON-java commit -qm "meeting: reset" && git -C ../JSON-java push -q
python3 optcd.py ../JSON-java/.github/workflows/e1-no-upload.yml ../JSON-java/.github/workflows/opt-e1-no-upload.yml \
  atanuroy911 JSON-java meeting-E1-no-out.txt --log-dir 001-investigation/logs/optcd-runs
```

**What it does:** runs the same real build twice, once with its three
upload steps and once without, changing nothing else. The `diff` command
proves the upload steps are the only difference.

**Evidence:**
- `001-investigation/workflows/E1-json-java/`: both workflow versions.
- `001-investigation/data/raw/JSON-java-37208714988/` (with uploads) and
  `.../JSON-java-37209308766/` (without): raw file-watcher logs, build logs,
  step timings.
- `001-investigation/logs/E1-*`: console output, flagged-folder comparison,
  and who-read-what tables.
- `001-investigation/evidence/E1_E2_controlled_experiments.md`

**Details:**
- `target/site/` (an HTML test report) is read **15 times with uploads,
  all inside the "Upload Test Report" step**, and **0 times without**.
- With uploads it is not flagged; without them OptCD flags
  `target/site/css/`. Removing the uploads alone flipped the answer.
- Only `css/` shows up because the file watcher misses files created very
  quickly inside brand-new folders, a known weakness its README mentions.
- The jar is not a fair test: Maven re-reads its own jar while packaging,
  so it always looks used.

## B4. Q2: how often does OptCD blame the wrong tool? (paper's own data)

**REPLAY**

```bash
python3 001-investigation/scripts/q2_attribution_check.py > /dev/null && \
python3 001-investigation/scripts/q2_error_patterns.py > /dev/null && \
python3 001-investigation/scripts/show_headlines.py q2
```

**What it does:** many Maven folders say in their name which tool made
them; e.g. `maven-status/maven-compiler-plugin/compile/` can only come from
the compiler. The script checks OptCD's published blame against that, then
groups the mistakes by cause.

**Evidence:**
- `001-investigation/results/q2_attribution_rows.csv`: every checked row
  with its verdict.
- `001-investigation/results/q2_error_patterns.csv` and `*_summary.json`
- `001-investigation/evidence/q2_attribution_errors.md`

**Details:**
- 1,473 blames could be checked; **110 are wrong (7.5%)**, in 30 jobs
  across 7 projects. This is the paper's own output from its original
  code, so it isn't caused by our changes.
- Three causes:
  - **Parallel builds** (`mvn -T`): several parts build at once, so "last
    tool that started" is often in another part. 47 errors; wrong rate
    34.8% vs 4.7% for normal builds. Seen in apache seata.
  - **Builds inside builds** (`maven-invoker-plugin`): 38 errors, all
    blamed on the outer tool. Seen in fabric8 kubernetes-client.
  - **Bad timing at tool boundaries:** 25 errors. The folder is written
    just as one tool ends, so the neighbor gets blamed.
- Worst folder type: `maven-status`, 43% wrong.
- Our first checker version wrongly reported 77% errors, because older
  Maven prints tool names differently. This was caught and fixed;
  `FLOW.md` step 4.

## B5. Q2: timing problem shown on raw data (gson, September run)

**REPLAY**

```bash
python3 001-investigation/scripts/q2_timing_and_mapper_compare.py 001-investigation/data/raw/gson-33849635845 | tail -40
```

**What it does:** for each tool whose output folder is unmistakable, takes
the first file it wrote and asks "which tool does OptCD's rule blame for
this moment?"

**Evidence:**
- `001-investigation/results/q2_timing_gson-33849635845.csv`: one row per
  case, with the time gap and who got blamed.
- `001-investigation/results/q2_timing_and_compare_gson-33849635845.json`

**Details:**
- Test reports (`surefire`): **22 of 23** blamed correctly.
- The compiler's `maven-status`: only **1 of 56**.
- The compiler writes that folder in the last ~0.1-0.3 s of its run, by
  which time the next tool has already started.
- The same output shows that the paper's original "who made it" code blames
  **nothing at all** on today's GitHub runners, because the file watcher
  wipes each folder's creation time. Our September numbers therefore came
  from our own fallback and are not used as evidence.

## B6. E2: proving parallel builds cause wrong blame (gson, controlled)

**REPLAY**

```bash
python3 001-investigation/scripts/show_headlines.py e2
cat 001-investigation/logs/E2_surefire_picks.log
diff 001-investigation/workflows/E2-gson/e2-sequential.yml 001-investigation/workflows/E2-gson/e2-parallel.yml
```

**LIVE (about 6 min each; stop with Ctrl+C after "Analysis for job")**

```bash
for v in e2-sequential e2-parallel; do
  gh workflow enable opt-$v.yml --repo atanuroy911/gson
  git -C ../gson rm -q .github/workflows/opt-$v.yml
  git -C ../gson commit -qm "meeting: reset opt-$v" && git -C ../gson push -q
done
python3 optcd.py ../gson/.github/workflows/e2-sequential.yml ../gson/.github/workflows/opt-e2-sequential.yml \
  atanuroy911 gson meeting-E2-seq-out.txt --log-dir 001-investigation/logs/optcd-runs
# after it is stopped, then:
python3 optcd.py ../gson/.github/workflows/e2-parallel.yml ../gson/.github/workflows/opt-e2-parallel.yml \
  atanuroy911 gson meeting-E2-par-out.txt --log-dir 001-investigation/logs/optcd-runs
# then analyze the new runs (replace <run_id> with the id printed by optcd):
python3 001-investigation/scripts/download_run_raw.py atanuroy911/gson <run_id>
python3 001-investigation/scripts/q2_timing_and_mapper_compare.py 001-investigation/data/raw/gson-<run_id>
```

**What it does:** builds the same project, same code, same job, once
normally and once with `-T 4` (four parts at a time). The `diff` proves
`-T 4` is the only difference.

**Evidence:**
- `001-investigation/workflows/E2-gson/`
- `001-investigation/data/raw/gson-37208820120/` (normal) and
  `.../gson-37209217089/` (parallel)
- `001-investigation/logs/E2_surefire_picks.log`
- `001-investigation/evidence/E1_E2_controlled_experiments.md`

**Details:**
- Test reports blamed correctly: **5 of 5 normally, 1 of 5 in parallel.**
- All 4 parallel mistakes blamed a tool from a different part of the
  project; e.g. `test-jpms`'s test reports were blamed on `proguard @ test-shrinker`.
- This matches seata in the paper's data, so the parallel-build problem no
  longer rests on a single project.

## B7. Q3: why `maven-status` still reaches Gemini

**REPLAY**

```bash
grep -rn "maven-status" legacy/ classifier/ clusterer/ mapper/ logger/
grep -n "gemini.ask_prompt\|update_mvn_commands_in_yml(fix\|subprocess.run(\|except FileNotFoundError" legacy/fixer/run_gemini_with_confirmation.py
python3 001-investigation/scripts/q3_maven_status_in_paper.py
```

**What it does:**
- The first command shows the *only* place in the original code that
  mentions `maven-status`.
- The second shows the line numbers of the steps that happen before it.
- The third counts how often the paper's own experiment sent `maven-status`
  to Gemini.

**Evidence:** `001-investigation/evidence/q3_maven_status_flow.md`,
`001-investigation/results/q3_maven_status_paper.csv`, `q3_summary.json`.

**Details:**
- The ignore rule is at line 214. It runs **after**:
  - asking Gemini (line 164),
  - changing the workflow (187),
  - re-running the build (191).
- It only hides `maven-status` from the final "fixed" list. The other
  branch (line 227 onward) doesn't even do that.
- In the paper's experiment, **29 of 216** Gemini prompts included
  `maven-status`, and 5 contained nothing else.
- `maven-status` flips between "unused" and "used" across runs by itself.
  For rocketmq, Gemini's "fix" was the unchanged command, yet the folder
  disappeared. That noise is probably why the authors added the rule, but
  it only cleans up the scoreboard; it doesn't stop the problem.

## B8. Side finding: the "optcd" name clash

**REPLAY**

```bash
grep -n '"optcd" in' mapper/utils.py
grep "optcd-run.lock" "001-investigation/data/raw/JSON-java-37208714988/inotify/inotifywait-build-17 (17)/inotifywait-log-build-17 (17).csv"
```

**What it does:**
- Shows OptCD finding its bookmark files with "does the name contain
  'optcd'?"
- Shows git creating `optcd-run.lock` (named after our branch `optcd-run`),
  which matches by accident.

**Evidence:** `001-investigation/evidence/step_marker_substring_bug.md`.

**Details:**
- The extra "bookmark" shifts every "which step did this" answer by one.
- Seen live in E1: Gemini was asked to "fix" `actions/upload-artifact@v5`,
  an upload action rather than a command.
- This corrects September's "bug 6", which was blamed on an off-by-one; the
  real cause is this name clash.
- It was triggered by our branch name, but any path containing "optcd" would
  do the same.

---

## How to do a LIVE run safely

1. **Do the setup in section 0 first.**
2. **Enable the workflow and delete the old OptCD copy** (the
   `gh workflow enable` / `git rm` / `commit` / `push` lines above). Without
   this, OptCD has nothing new to push and waits forever (see
   Troubleshooting).
3. **Run** the `python3 optcd.py ...` line. Progress prints live:
   - "Pushed..."
   - "started with run_id ..." (note this number)
   - "completed"
   - "Analysis for job ..."
4. **Press Ctrl+C** as soon as "Analysis for job" appears, unless you
   want to show the Gemini fix stage. That stage triggers more builds, one
   per command, which adds several minutes each.
5. **Clean up afterwards:**

   ```bash
   powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*optcd.py*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }"
   for r in jsoup gson JSON-java; do for id in $(gh run list --repo atanuroy911/$r --json databaseId,status --jq '.[] | select(.status!="completed") | .databaseId'); do gh run cancel $id --repo atanuroy911/$r; done; done
   ```

6. **Save the raw data** if the run should become evidence:

   ```bash
   python3 001-investigation/scripts/download_run_raw.py atanuroy911/<repo> <run_id>
   ```

Run only **one** LIVE run at a time from the project folder. Two at once
overwrite each other's `responsible_plugins.json`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Python was not found; run without arguments to install from the Microsoft Store` | `python3`/`python` resolves to the Windows Store stub, or the shim folder isn't on `PATH` | Run the `export PATH=...` line from section 0. Check with `which python3`, which should print `/c/Users/atanu/bin/python3`. If Python was reinstalled elsewhere, edit `/c/Users/atanu/bin/python3` and `/c/Users/atanu/bin/python` to point at the new `python.exe`. |
| `gh: command not found` | GitHub CLI not on this terminal's `PATH` | Run the `export PATH=...` line. |
| `401` / `Bad credentials` | GitHub token in `.env` invalid or expired | Run `export GITHUB_API_TOKEN=$(gh auth token)`. If `gh auth status` itself fails, run `gh auth login`. |
| OptCD prints "Waiting until modified YAML workflow starts." forever | Nothing new was pushed (the `opt-*.yml` file was identical, so git had "nothing to commit"), or the `opt-*` workflow is disabled on the fork | Ctrl+C, then do step 2 of "How to do a LIVE run safely" (enable + `git rm` + push) and run again. Check with `gh workflow list --repo atanuroy911/<repo> --all`. |
| `HTTP 404: workflow ... not found on the default branch` printed while waiting | GitHub hasn't indexed the new workflow file yet | Harmless; it resolves after a few polls. |
| Ctrl+C doesn't stop OptCD, or OptCD keeps running after the terminal closes | Windows doesn't always pass Ctrl+C to native `python.exe`, and stopping the shell can leave the child process alive (happened twice in this project) | Run the PowerShell clean-up line in step 5. It stops only `optcd.py` processes. |
| Many extra workflow runs appear on the fork | A push triggers every enabled push-triggered workflow | OptCD cancels sibling runs automatically; otherwise run the `gh run cancel` loop in step 5. Unneeded workflows on the forks are already disabled (`gh workflow enable <file> --repo <fork>` to undo). |
| `git push` hangs or asks for a password | git has no credential helper | Run `gh auth setup-git` once. |
| `cannot rebase: You have unstaged changes` in a run log | Leftover edits in the fork's local folder | Harmless for OptCD (it continues). To clean up: `git -C ../<repo> status`, then commit or discard the stray files. |
| `UnicodeEncodeError` when writing the report | Very old code version (September bug) | Pull the latest `main`; fixed in `optcd/analyze.py`. |
| `FutureWarning: All support for the google.generativeai package has ended` | Google deprecated the library OptCD uses | Harmless warning; Gemini calls still work. |
| `404 models/gemini-... is not found` | Google retired the Gemini model | Change the model name in `optcd/fixer.py` (`GenerativeModel("...")`). Current: `gemini-3.6-flash`. List available ones with the snippet in `docs/findings.md`. |
| A REPLAY script prints different numbers from this runbook | Saved results were regenerated from different raw data, or a script was edited | Re-run the analysis scripts in the order B1, B2, B4, B5. All scripts are deterministic; nondeterminism was found and fixed on 2026-10-05 (`FLOW.md` step 11). |
| `show_headlines.py` fails with `FileNotFoundError` | A `results/` file is missing | Run the REPLAY commands for that section first (they write the results files). |
