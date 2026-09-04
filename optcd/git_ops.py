import re
import subprocess

from optcd import run_logger


def _run(args: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    run_logger.log_git(args, cwd, result.returncode, result.stdout, result.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{result.stderr}")
    return result


def get_owner_repo(local_repo_path: str) -> tuple[str, str]:
    url = _run(["git", "remote", "get-url", "origin"], cwd=local_repo_path).stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(\.git)?$", url)
    if not match:
        raise ValueError(f"Could not parse owner and repo from URL: {url}")
    return match.group(1), match.group(2)


def get_branch(local_repo_path: str) -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=local_repo_path).stdout.strip()


def push_modified_yaml(local_repo_path: str, branch: str, path_to_yaml_file: str) -> None:
    """Fetches, rebases onto origin/branch, commits the modified workflow file, and pushes.

    Mirrors the original utils.sh git sequence, but tolerates "nothing to
    commit" (e.g. re-running against an already-pushed file) instead of
    treating it as a fatal error.
    """
    _run(["git", "fetch"], cwd=local_repo_path, check=False)
    _run(["git", "rebase", f"origin/{branch}"], cwd=local_repo_path, check=False)
    _run(["git", "push", "origin", branch], cwd=local_repo_path, check=False)
    _run(["git", "add", path_to_yaml_file], cwd=local_repo_path, check=False)
    commit = _run(["git", "commit", "-m", "add modified YAML file"], cwd=local_repo_path, check=False)
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        raise RuntimeError(f"git commit failed:\n{commit.stdout}\n{commit.stderr}")
    push = _run(["git", "push", "--set-upstream", "origin", branch], cwd=local_repo_path, check=False)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed:\n{push.stderr}")
