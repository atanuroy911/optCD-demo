"""Fetch every GitHub Actions workflow file for the paper's evaluated repos.

Two snapshots per repo:
  head  - the default branch today
  paper - the default branch as of PAPER_CUTOFF (approximates the workflow
          versions the paper's own OptCD runs saw; see FLOW.md for why)

Output:
  data/workflows/<snapshot>/<owner>__<repo>/<workflow file>
  data/workflows/manifest.json   (commit SHA per repo/snapshot, errors)

Usage: python scripts/fetch_workflows.py
Needs GITHUB_API_TOKEN in the environment.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO_LIST = ROOT.parent / "eval" / "repos-with-commit-counts.csv"
OUT = ROOT / "data" / "workflows"
PAPER_CUTOFF = "2024-11-01T00:00:00Z"

API = "https://api.github.com"
SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {os.environ['GITHUB_API_TOKEN']}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
})


def get(url, **params):
    for attempt in range(5):
        r = SESSION.get(url, params=params)
        if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
            wait = int(r.headers.get("X-RateLimit-Reset", time.time() + 60)) - int(time.time()) + 5
            print(f"  rate limited, sleeping {wait}s", flush=True)
            time.sleep(max(wait, 5))
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        return r
    return r


def resolve_sha(repo, snapshot):
    if snapshot == "head":
        r = get(f"{API}/repos/{repo}")
        if r.status_code != 200:
            return None, f"repo lookup {r.status_code}"
        branch = r.json()["default_branch"]
        r = get(f"{API}/repos/{repo}/commits/{branch}")
        return (r.json()["sha"], None) if r.status_code == 200 else (None, f"head commit {r.status_code}")
    r = get(f"{API}/repos/{repo}/commits", until=PAPER_CUTOFF, per_page=1)
    if r.status_code != 200 or not r.json():
        return None, f"paper commit {r.status_code}"
    return r.json()[0]["sha"], None


def fetch_snapshot(repo, snapshot):
    sha, err = resolve_sha(repo, snapshot)
    if err:
        return {"sha": None, "error": err, "files": []}
    r = get(f"{API}/repos/{repo}/contents/.github/workflows", ref=sha)
    if r.status_code != 200:
        return {"sha": sha, "error": f"workflows dir {r.status_code}", "files": []}
    dest = OUT / snapshot / repo.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for entry in r.json():
        name = entry["name"]
        if entry["type"] != "file" or not name.endswith((".yml", ".yaml")):
            continue
        raw = SESSION.get(entry["download_url"])
        if raw.status_code == 200:
            (dest / name).write_bytes(raw.content)
            files.append(name)
    return {"sha": sha, "error": None, "files": files}


def main():
    repos = []
    for line in REPO_LIST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            repos.append(line.split(";")[1])

    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    for i, repo in enumerate(repos, 1):
        if repo in manifest and all(s in manifest[repo] for s in ("head", "paper")):
            continue
        print(f"[{i}/{len(repos)}] {repo}", flush=True)
        manifest[repo] = {
            "analyzed_workflows": next(l.split(";")[2].split(",") for l in REPO_LIST.read_text(encoding="utf-8").splitlines() if l.split(";")[1] == repo),
            "head": fetch_snapshot(repo, "head"),
            "paper": fetch_snapshot(repo, "paper"),
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))

    ok = sum(1 for m in manifest.values() if m["paper"]["files"])
    print(f"done: {len(manifest)} repos, {ok} with paper-era workflows")


if __name__ == "__main__":
    sys.exit(main())
