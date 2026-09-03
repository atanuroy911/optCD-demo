---
title: Architecture
---

[← Back to overview](index.md)

# Architecture

## Repository layout

```
optcd.sh / optcd.py     single entrypoint (thin wrapper -> optcd/cli.py)
optcd/                  the orchestrator: git + GitHub Actions + analysis + Gemini fixer
classifier/  clusterer/
mapper/      logger/    pure-logic modules the orchestrator calls into
legacy/                 the original shell+Python implementation (superseded, kept for reference)
eval/                   one-off scripts + result data behind the paper's 89-project evaluation
docs/                   this site, plus the original paper PDF
```

`classifier/`, `clusterer/`, `mapper/`, and `logger/` are unchanged from the
original implementation — they're pure functions with no bugs found during
this review, so the rewrite reuses them as-is rather than re-deriving the
same logic.

## Data flow for one run

```
 you run:  python optcd.py <input.yml> <output.yml> [owner] [repo] [out.txt]
                    |
                    v
   optcd/cli.py  write_instrumented_yaml()  -- wraps logger/utils.py
                    |  (writes <output.yml> with the inotify-watching step injected)
                    v
   optcd/git_ops.py  push_modified_yaml()   -- git add/commit/push to your fork
                    |
                    v
   optcd/gh_ops.py   wait_for_new_run() / wait_for_completion()
                    |  (polls `gh run list` / `gh run view` until the real
                    |   GitHub Actions build finishes)
                    v
   optcd/gh_ops.py   cancel_sibling_runs()
                    |  (stops the *original*, unmodified workflow's run that
                    |   the same push also triggered, so it doesn't waste CI minutes)
                    v
   optcd/gh_ops.py   download_artifacts() + fetch_job_log()   per job
                    v
   optcd/analyze.py  analyze_job()
                    |  classifier.classify_files()
                    |  -> clusterer.cluster_files()
                    |  -> mapper.get_responsible_plugins()
                    v
   optcd/cli.py   responsible_plugins_maven  (aggregated across all jobs)
                    |
                    v
   optcd/fixer.py    run_fixer()
                    |  for each distinct Maven command:
                    |    ask Gemini for a fix -> optcd/git_ops + gh_ops again
                    |    (push -> wait -> analyze) to verify it worked
                    v
              out.txt (human-readable report)
```

## Why this was consolidated into one Python flow

The original implementation split this same flow across three shell scripts
and four Python scripts, handing state between them through files, env vars,
and positional CLI arguments (`optcd.sh` → `modify_yaml.py`, `utils.sh` →
`find_plugins.py`, `fixer/run_gemini_with_confirmation.py` → back into
`utils.sh` as a subprocess). See [`legacy/README.md`](../legacy/README.md)
for the original files.

That shape made a few real gaps hard to spot until we hit them directly (see
[Findings & limitations](findings.md)):

- A missing `rev` utility on Windows silently emptied several path variables,
  which then made downstream `git` commands fail — but the script's own
  `> /dev/null 2>&1` redirections hid the failure until the whole run stalled.
- A `UnicodeEncodeError` in the report-writing step crashed the process
  partway through a multi-job run, discarding whatever hadn't been written
  yet.
- `cancel_runs`'s original scope (every queued/in-progress run repo-wide,
  rather than just the sibling run from the same push) let it cancel the
  *correct* run outright in one observed case.

Consolidating the orchestration into `optcd/` doesn't change what the tool
computes — `classifier`/`clusterer`/`mapper` are untouched — it just makes
the control flow (push → poll → download → analyze → fix → verify) traceable
in one place with one log stream, and fixes the three issues above at their
root instead of papering over them with shims.
