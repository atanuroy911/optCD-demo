import json
import os
import subprocess
import time

import requests


def _gh(args: list[str]) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def _gh_json(args: list[str]):
    out = _gh(args)
    return json.loads(out) if out else None


def get_latest_run(owner: str, repo: str, workflow_path: str) -> dict | None:
    """Returns the most recent run for a workflow, or None if it can't be
    resolved yet (e.g. the workflow file was only just pushed and GitHub
    hasn't indexed it under that path on this branch yet)."""
    try:
        runs = _gh_json([
            "run", "list", "--repo", f"{owner}/{repo}", "--workflow", workflow_path,
            "--limit", "1", "--json", "databaseId,headSha,name",
        ])
    except RuntimeError:
        return None
    return runs[0] if runs else None


def wait_for_new_run(owner: str, repo: str, workflow_path: str, baseline_run_id, poll_interval: int = 10) -> dict:
    while True:
        run = get_latest_run(owner, repo, workflow_path)
        if run and run["databaseId"] != baseline_run_id:
            return run
        time.sleep(poll_interval)


def wait_for_completion(owner: str, repo: str, run_id, poll_interval: int = 10) -> None:
    last_status = None
    while True:
        status = _gh_json(["run", "view", str(run_id), "--repo", f"{owner}/{repo}", "--json", "status"])["status"]
        if status == "completed":
            return
        if status != last_status:
            print(f"Run status of modified workflow (run_id: {run_id}) is: {status}")
        last_status = status
        time.sleep(poll_interval)


def cancel_sibling_runs(owner: str, repo: str, run_to_keep: dict) -> None:
    """Cancels other in-flight runs that were triggered by the *same push*
    as the run we want to keep, so the original (unmodified) workflow's run
    doesn't waste CI minutes.

    This is scoped by head_sha (the commit that triggered both runs) rather
    than blanket-cancelling every queued/in-progress run in the repo, which
    is the behavior the original utils.sh had -- and which cancelled our own
    target run outright in one observed case.
    """
    head_sha = run_to_keep["headSha"]
    run_id_to_keep = run_to_keep["databaseId"]

    for status in ("queued", "in_progress"):
        runs = _gh_json([
            "run", "list", "--repo", f"{owner}/{repo}", "--status", status,
            "--json", "databaseId,headSha",
        ]) or []
        for run in runs:
            if run["headSha"] == head_sha and run["databaseId"] != run_id_to_keep:
                subprocess.run(
                    ["gh", "run", "cancel", str(run["databaseId"]), "--repo", f"{owner}/{repo}"],
                    capture_output=True, text=True,
                )


def get_jobs(owner: str, repo: str, run_id) -> list[dict]:
    data = _gh_json(["run", "view", str(run_id), "--repo", f"{owner}/{repo}", "--json", "jobs"])
    return data["jobs"]


def download_artifacts(owner: str, repo: str, run_id, dest_dir: str) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    subprocess.run(
        ["gh", "run", "download", str(run_id), "--repo", f"{owner}/{repo}", "-D", dest_dir],
        capture_output=True, text=True,
    )


def fetch_job_log(owner: str, repo: str, job_id, github_api_token: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/jobs/{job_id}/logs"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_api_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text
