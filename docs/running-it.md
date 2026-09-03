---
title: Running it
---

[← Back to overview](index.md)

# Running it

## What you need

1. A **GitHub Personal Access Token** with `repo` + `workflow` scope, exported as `GITHUB_API_TOKEN`.
2. A free **Gemini API key** from [Google AI Studio](https://aistudio.google.com/app/apikey), exported as `GEMINI_API_KEY`.
3. The **GitHub CLI** (`gh`), authenticated: `gh auth login`, then `gh auth setup-git` so pushes don't hang waiting for a credential prompt.
4. **Push access** to the repository whose workflow you want to optimize (a fork you own works fine — that's what we used for validation).
5. Python 3 with `pip install -r requirements.txt`.

```bash
export GITHUB_API_TOKEN=<your-github-api-token>
export GEMINI_API_KEY=<your-gemini-api-key>
./optcd.sh <path-to-input-yaml> <path-to-output-yaml> [owner] [repo] [output-file]
```

The input and output YAML files must both live in `<local_repo>/.github/workflows/`,
and the output filename must not already exist as a workflow in that repo.

## Running on Windows

`inotify` — the file-watching mechanism — only ever runs on GitHub's own
Linux runners in the cloud, never on your machine. That means the
orchestration side (this repo's code) has no Linux-only dependency and runs
natively on Windows via Git Bash. No WSL, no Docker, no venv required. Two
things Windows environments are commonly missing that you'll want on `PATH`:

- **GitHub CLI** — `winget install --id GitHub.cli` (or `choco install gh`).
- **Python** reachable as `python3` — Windows Store's `python3` alias is
  often a non-functional stub; if `python3 --version` fails, either disable
  that App Execution Alias (Settings → Apps → Advanced app settings → App
  execution aliases) or add a one-line shim script named `python3` on your
  `PATH` that just runs `python "$@"`.

Git Bash on Windows can also be missing the `rev` coreutil, which the
*original* implementation's path-parsing relied on. The rewritten
`optcd/git_ops.py` no longer shells out to `rev`/`cut` at all — owner/repo
and path splitting are done in Python — so this is no longer a blocker
either way.

## Verifying it end-to-end

We validated the current implementation against a real fork of
[`jsoup`](https://github.com/jhy/jsoup) on GitHub Actions:

```
./optcd.sh ../jsoup/.github/workflows/build.yml \
           ../jsoup/.github/workflows/opt-build.yml \
           <your-github-username> jsoup
```

Result on current `jsoup` `HEAD`: **0 unused directories** across all 3
Linux matrix jobs (JDK 8/17/25). See [Findings & limitations](findings.md)
for why that's a legitimate (if unexciting) result rather than a bug, and
what it would take to exercise the Gemini-fixer path.

## If you delete your local working copy and start over

Re-running `optcd.sh` from a fresh checkout of *this* repo works
immediately — none of its logic depends on anything outside it. What does
**not** come back automatically is the target-repository side of the setup:

- Your fork/clone of the project you're optimizing (e.g. `jsoup`) — you'd
  need to `git clone` it again, laid out as a sibling directory to this repo
  (matching the README's example layout).
- The `.env` (or exported `GITHUB_API_TOKEN` / `GEMINI_API_KEY`) — these are
  gitignored on purpose and never committed, so they only exist wherever you
  put them locally.
- Machine-level setup (the `gh` CLI install, `gh auth login`, and — on
  Windows — a working `python3` on `PATH`) is external to any git repo and
  survives regardless of which working copy you delete.

In short: deleting a scratch **workdir** that just contains clones/forks is
safe and cheap to redo (a few `git clone` / `gh repo fork` commands); nothing
about the tool's own state lives there.

### One-command recovery

Run [`bootstrap.sh`](../bootstrap.sh) to check all of the above and re-clone
the target repo if it's missing:

```bash
./bootstrap.sh <github-owner>/<repo> [path-to-clone-into]
# e.g.
./bootstrap.sh atanuroy911/jsoup ../jsoup
```

It checks `git`/`gh`/`python3` are on `PATH`, that `gh` is authenticated,
that `.env` has both required keys, installs `requirements.txt`, and clones
the target repo only if it isn't already there — so it's safe to run
repeatedly, including right after wiping a workdir.
