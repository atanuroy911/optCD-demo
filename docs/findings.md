---
title: Findings & limitations
---

[← Back to overview](index.md)

# Findings & limitations

Observations from actually running this tool end-to-end against a real
project ([`jsoup`](https://github.com/jhy/jsoup), forked to a personal
GitHub account) rather than just reading the paper.

## Bugs fixed in this pass

1. **Windows encoding crash.** `find_plugins.py` (now `optcd/analyze.py`)
   wrote its report table with Python's default file encoding. On Windows
   that's `cp1252`, which can't represent the Unicode box-drawing characters
   `tabulate`'s `fancy_grid` format uses — so writing *any* table, even an
   empty one, raised `UnicodeEncodeError` and aborted that job's analysis.
   Fixed by opening the report file with `encoding="utf-8"` explicitly.

2. **Missing `rev` dependency.** The original `optcd.sh` parsed the
   input/output YAML paths with `rev | cut -d'/' -f1-3 | rev`. Git Bash on
   Windows doesn't ship `rev`, so every one of those variables silently
   became empty — and because the surrounding commands redirected
   stderr to `/dev/null`, the failure was invisible until `git -C ""` started
   misbehaving several steps later. Fixed by doing the path splitting in
   Python (`optcd/cli.py: split_output_path`), which needs no external
   coreutils.

3. **`cancel_runs` race condition.** A single `git push` to the target repo
   triggers *two* workflow runs at once: the original, unmodified workflow
   (still present in `.github/workflows/`) and the newly-added instrumented
   copy. The original implementation's `cancel_runs` (in `utils.sh`) canceled
   *every* queued/in-progress run in the repo except one ID it believed was
   the run to keep. In one observed run, a stray leftover process (from an
   earlier failed attempt that hadn't fully exited) called this with the
   wrong "keep" ID, and it canceled the run we actually wanted, discarding
   real results with zero indication anything had gone wrong beyond a 0-row
   report. The rewritten `optcd/gh_ops.py: cancel_sibling_runs` scopes
   cancellation to runs sharing the *same commit SHA* as the run being kept,
   which is a strictly narrower and correct condition regardless of timing.

4. **Platform-dependent path separators corrupting every result.** This was
   the big one, and it's why the tool initially looked like it "worked" but
   just found nothing. `classifier/utils.py` and `clusterer/utils.py` built
   file paths using `os.sep`, which is `\` on Windows -- but every path in
   the inotify log always comes from GitHub's Linux runner and uses `/`,
   regardless of what OS is running the *analysis* step. Mixing `/` and `\`
   in the same string silently broke every `startswith`/prefix comparison
   the clustering algorithm depends on, so it always concluded "no unused
   directories" without ever raising an error. Fixed by hardcoding POSIX
   path handling (`posixpath` / literal `'/'`) in both modules, since the
   input is never platform-dependent even though the code that processes it
   now can be.

5. **A directory's own "used" status gets clobbered by the watcher's own
   bookkeeping.** `mapper/utils.py` looked up each unused directory's
   creation timestamp by exact key match in the timestamps dict. But
   `inotify.adapters.InotifyTree` (the recursive watcher the Logger
   injects) itself opens every newly-created subdirectory to register a
   watch on it -- and that open is indistinguishable from a real
   `IN_ACCESS`, so the classifier immediately re-marks the directory
   "used" and erases its creation timestamp seconds after recording it.
   The directory was never actually read by anything in the build; the
   watcher just needed to look inside it. This made the mapper skip real
   unused directories outright. Fixed by falling back to the earliest
   surviving timestamp among the files still recorded under that directory
   when the directory's own entry is missing.

6. **Off-by-one in step attribution.** `mapper/utils.py` locates which
   build step was running when a directory was created by counting how many
   step-boundary marker files (`touch optcd-N.txt`, inserted between steps)
   came before it, via `bisect_right`. When a directory's timestamp falls
   after the *last* marker (e.g. the final instrumented step), this returns
   an index one past the end of the steps list and crashes with
   `IndexError` -- an existing latent bug the previous two fixes newly
   exposed by letting real results reach this code path at all. Fixed by
   clamping to the last known step.

7. **Deprecated Gemini model.** `gemini-1.5-flash`, hardcoded in the
   original fixer, has been fully retired by Google since the paper was
   published; the next fallback we tried (`gemini-2.5-flash`) is also
   no longer available to new API keys. Updated to `gemini-3.6-flash`,
   the model Google's own API currently points deprecated callers to. This
   is exactly the kind of drift an LLM-dependent tool should expect over
   time and treat as configuration, not a hardcoded constant, going
   forward.

Bugs 4-6 compounded: each one independently caused the *same* symptom ("0
unused directories found," no error), so fixing them one at a time and
re-testing against the same real, already-downloaded inotify data (rather
than spending a new CI run per attempt) was what made it tractable to find
all three rather than stopping at the first fix and declaring victory.

## Documentation/behavior mismatch

The README describes `optcd.sh` as taking `owner`, `repo`, and `output-file`
as CLI parameters (Table I), but the original script only ever read `$1`
(input) and `$2` (output) — owner/repo were always auto-derived from
`git remote get-url origin`, and the extra parameters were dead code (the
lines assigning them were commented out). The rewritten CLI
(`optcd/cli.py`) actually implements the documented interface: owner/repo
are accepted as optional positional args and fall back to git-remote
auto-detection when omitted.

## Result: the full pipeline confirmed working end-to-end

After fixing bugs 4-7 above, we ran OptCD against `jhy/jsoup` at the commit
matching the README's own JDK 8/17/21 matrix (`b29ba354`, before JDK 25 was
added), and it reproduced the README's example almost exactly:

- Detected `target/surefire-reports/` and `target/japicmp/` as unused,
  correctly attributed to `mvn -X verify -B --file pom.xml` in the "Maven
  Verify" step, across all three matching Linux jobs.
- Gemini suggested `-DdisableXmlReport=true` and `-Djapicmp.skip=true` — the
  *same two flags* the README's own captured output shows.
- Re-ran the build with the patched command on a second real CI run and
  confirmed both directories no longer appeared.

This is the first time this exercise reached the Gemini-fixer stage at all
— every earlier attempt (including against current `jsoup` `HEAD`) reported
zero unused directories, which given bugs 4-6 above was itself unreliable:
the pipeline was silently returning false negatives, not a real "nothing to
find" result.

Re-checking current `jsoup` `HEAD` (post-`1.23.2`, JDK 8/17/25 matrix) with
the fully fixed pipeline confirms this: it also has real unused directories
(`surefire-reports`, `japicmp`, same as the older commit) — the earlier
"zero results on HEAD" finding was **wrong**, entirely caused by bugs 4-6.
There was never a real behavior change in upstream `jsoup`; the tool was
just broken.

## Confirmed: a "verified" fix can break other jobs in the same build matrix

The Fixer's own verification step only re-analyzes `ubuntu-latest` jobs (the
only OS the Logger/Classifier support), but the patched Maven command gets
written into a workflow file shared by the *entire* build matrix — including
Windows and macOS jobs OptCD never looks at again. We hit this directly,
twice, on real CI runs against `jsoup`:

- Before the patch: `test (windows-latest, 17)`, `(windows-latest, 8)`, etc.
  all pass.
- After OptCD applies Gemini's fix (`-DdisableXmlReport=true
  -Djapicmp.skip=true`) and reports it as verified (because the `ubuntu-*`
  jobs it checks now pass and no longer show the unused directories), the
  *same* Windows jobs fail with
  `org.apache.maven.lifecycle.LifecyclePhaseNotFoundException: Unknown
  lifecycle phase ".skip=true"`.

We traced this as far as: the pushed YAML is byte-for-byte correct (verified
via the run-history transcript — no corruption from Gemini's response or
from the ruamel YAML round-trip), yet Maven's own debug output on the
Windows runner shows `Tasks: [verify, .skip=true]` — meaning
`-Djapicmp.skip=true` arrives at Maven's argument parser split into two
separate tokens. That split happens somewhere in Windows's default `pwsh`
shell invoking `mvn.cmd`, outside OptCD's control — but OptCD's design is
what lets a broken fix get reported as "confirmed working" without anyone
noticing, since it only ever re-checks the OS it can analyze. **A real
result from this exercise: never trust an OptCD "fixed" verdict for a
multi-OS build matrix without separately confirming the non-Linux jobs
still pass.**

## Structural limitations (from reading the paper + code, not yet independently re-verified)

- **Linux + GitHub Actions + Maven only.** The Logger only knows how to
  instrument workflows that run on `ubuntu-latest` runners (Windows/macOS
  jobs in a build matrix are explicitly skipped — see the "Skipped
  incompatible job" messages), and the Mapper only parses Maven's
  `[INFO] --- plugin:version:goal ---` log format. A Gradle or npm build, or
  a non-GitHub-Actions CI service, is entirely out of scope as designed.
- **Real infrastructure cost per run.** There is no dry-run or simulation
  mode — every invocation pushes a commit and consumes real GitHub Actions
  minutes on the target repo, once for detection and once more per distinct
  fixable command for verification. The paper's own 89-project evaluation
  covers 614 real CI jobs.
- **LLM-suggested fixes are not guaranteed safe or complete.** Per the
  paper's own numbers, Gemini produced a usable patch for only 131 of 216
  responsible commands, and of those, only 80 were confirmed (by re-running)
  to actually eliminate the unused directory without breaking tests; the
  rest either skipped tests, skipped unrelated checks, or otherwise
  regressed the build and were discarded. Any fix this tool proposes still
  needs a human or CI gate to review before merging, not just the tool's own
  single re-run.
- **Single point of truth for "used."** A file is only "used" if something
  *reads* it during the same workflow run OptCD observes. A file that is
  read only in a later, separate workflow (e.g. a nightly job that consumes
  an artifact a CI job produced) would be misclassified as unused. We have
  not tested this scenario directly but it follows from the Classifier's
  logic in `classifier/utils.py`.
