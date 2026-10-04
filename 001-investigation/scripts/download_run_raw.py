"""Download the raw data of one instrumented GitHub Actions run.

Saves, under data/raw/<repo>-<run_id>/:
  inotify/<artifact>/...csv   inotify logs uploaded by OptCD's Logger step
  joblogs/<job name>.log      full job log (what the Mapper parses)
  jobs.json                   job list with step timings

Usage: python scripts/download_run_raw.py <owner/repo> <run_id>
Needs GITHUB_API_TOKEN (e.g. GITHUB_API_TOKEN=$(gh auth token)) and gh CLI.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def main(repo, run_id):
    dest = ROOT / "data" / "raw" / f"{repo.split('/')[1]}-{run_id}"
    (dest / "inotify").mkdir(parents=True, exist_ok=True)
    (dest / "joblogs").mkdir(exist_ok=True)

    subprocess.run(["gh", "run", "download", str(run_id), "--repo", repo, "-D", str(dest / "inotify")],
                   check=False)

    headers = {"Authorization": f"Bearer {os.environ['GITHUB_API_TOKEN']}",
               "Accept": "application/vnd.github+json"}
    jobs = requests.get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100",
                        headers=headers).json()["jobs"]
    (dest / "jobs.json").write_text(json.dumps(jobs, indent=2))
    for job in jobs:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/jobs/{job['id']}/logs", headers=headers)
        (dest / "joblogs" / f"{job['name']}.log").write_bytes(r.content)
        print(f"{job['name']}: log {r.status_code}, {len(r.content)} bytes")
    print(f"saved to {dest}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
