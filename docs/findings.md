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

## Documentation/behavior mismatch

The README describes `optcd.sh` as taking `owner`, `repo`, and `output-file`
as CLI parameters (Table I), but the original script only ever read `$1`
(input) and `$2` (output) — owner/repo were always auto-derived from
`git remote get-url origin`, and the extra parameters were dead code (the
lines assigning them were commented out). The rewritten CLI
(`optcd/cli.py`) actually implements the documented interface: owner/repo
are accepted as optional positional args and fall back to git-remote
auto-detection when omitted.

## Result on current `jsoup`

Running against `jhy/jsoup` at its current `HEAD` (post-`1.23.2` release),
using the exact same `mvn -X verify -B --file pom.xml` command shown in the
README's own captured example output, OptCD found **zero unused
directories** across all three Linux matrix jobs (JDK 8, 17, 25).

This is a legitimate negative result, not a tool failure: the README's
sample output (showing `surefire-reports` and `japicmp` as unused) was
presumably captured against an older `jsoup` commit. Upstream `jsoup`
appears to have since changed its Maven plugin configuration such that these
directories are no longer generated, or are now consumed by something. It
also means our validation run never exercised the Gemini-fixer path
end-to-end — that would require pointing OptCD at either an older commit of
`jsoup` (from around when the README example was captured) or a different
project that currently exhibits this waste.

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
