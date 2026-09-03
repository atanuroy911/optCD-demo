import argparse
import json
import os
import sys
from pathlib import Path

import yaml

import logger.utils
from optcd import analyze, fixer, git_ops, gh_ops


def split_output_path(output_yaml_filename: str) -> tuple[str, str]:
    """Splits '<...>/<repo>/.github/workflows/<file>.yml' into
    ('.github/workflows/<file>.yml', '<...>/<repo>')."""
    parts = Path(output_yaml_filename).parts
    if len(parts) < 3:
        raise ValueError(
            "output yaml file must live in <local_repo>/.github/workflows/, "
            f"got: {output_yaml_filename}"
        )
    path_to_yaml_file = "/".join(parts[-3:])
    path_to_local_repo = "/".join(parts[:-3]) or "."
    return path_to_yaml_file, path_to_local_repo


def write_instrumented_yaml(input_yaml_filename: str, output_yaml_filename: str, repo: str) -> None:
    with open(input_yaml_filename, "r") as f:
        yaml.safe_load(f)  # validates the file is parseable, matching modify_yaml.py's behavior
        f.seek(0)
        comments = [line.strip() for line in f if line.strip().startswith("#")]

    with open(input_yaml_filename, "r") as f:
        loaded_yaml = yaml.safe_load(f)

    modified_file = logger.utils.modify_file_content(repo, loaded_yaml)

    with open(output_yaml_filename, "w") as out:
        for comment in comments:
            out.write(comment + "\n")
        out.write("\n")
        out.write(modified_file)


def run_and_analyze(
    owner: str, repo: str, path_to_yaml_file: str, branch: str, workflow_file: str,
    path_to_local_repo: str, output_file: str, input_yaml_filename: str,
) -> list[dict]:
    """Pushes the (possibly just-updated) workflow file, waits for it to run
    to completion, analyzes every job's logs, appends to the report, and
    returns the maven-attributable unused directories found this round."""
    baseline = gh_ops.get_latest_run(owner, repo, path_to_yaml_file)
    baseline_id = baseline["databaseId"] if baseline else None

    git_ops.push_modified_yaml(path_to_local_repo, branch, path_to_yaml_file)
    print("Pushed the modified YAML file to remote repository.")

    print("Waiting until modified YAML workflow starts.")
    run = gh_ops.wait_for_new_run(owner, repo, path_to_yaml_file, baseline_id)
    print(f"Modified YAML workflow started with run_id: {run['databaseId']}")

    print("Waiting until modified YAML workflow is completed.")
    gh_ops.wait_for_completion(owner, repo, run["databaseId"])
    print("Modified YAML workflow completed.")

    gh_ops.cancel_sibling_runs(owner, repo, run)

    jobs = gh_ops.get_jobs(owner, repo, run["databaseId"])
    dest_dir = f"{repo}-{workflow_file}"
    gh_ops.download_artifacts(owner, repo, run["databaseId"], dest_dir)

    github_api_token = os.environ["GITHUB_API_TOKEN"]
    responsible_plugins_maven: list[dict] = []

    for job in jobs:
        job_id, name = job["databaseId"], job["name"]

        if "windows" in name or "mac" in name:
            print(f"Skipped incompatible job {name}")
            analyze.append_report(output_file, f"Skipped incompatible job {name}\n")
            continue

        analyze.append_report(output_file, f"Result for job {name}\n")

        log_text = gh_ops.fetch_job_log(owner, repo, job_id, github_api_token)
        inotify_csv = os.path.join(dest_dir, f"inotifywait-{name}", f"inotifywait-log-{name}.csv")

        responsible_plugins = analyze.analyze_job(inotify_csv, log_text, input_yaml_filename, name)
        if responsible_plugins is None:
            continue

        analyze.append_report(output_file, analyze.format_table(responsible_plugins))
        responsible_plugins_maven.extend(analyze.to_maven_dicts(responsible_plugins))

    return responsible_plugins_maven


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OptCD: find and fix unused directories in a Maven/GitHub Actions build.")
    parser.add_argument("input_yaml", help="Path to the GitHub Actions workflow YAML to analyze")
    parser.add_argument("output_yaml", help="Path to write the instrumented workflow YAML (must be unique, in .github/workflows/)")
    parser.add_argument("owner", nargs="?", default=None, help="GitHub owner/org (auto-detected from git remote if omitted)")
    parser.add_argument("repo", nargs="?", default=None, help="GitHub repo name (auto-detected from git remote if omitted)")
    parser.add_argument("output_file", nargs="?", default="out.txt", help="Path to write the human-readable report (default: out.txt)")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input_yaml):
        print(f"Input YAML file not found: {args.input_yaml}")
        return 1

    path_to_yaml_file, path_to_local_repo = split_output_path(args.output_yaml)
    branch = git_ops.get_branch(path_to_local_repo)

    if args.owner and args.repo:
        owner, repo = args.owner, args.repo
    else:
        owner, repo = git_ops.get_owner_repo(path_to_local_repo)

    workflow_file = Path(args.input_yaml).stem

    for stale in (args.output_file, "temp_out.txt", "responsible_plugins.json"):
        if os.path.exists(stale):
            os.remove(stale)

    write_instrumented_yaml(args.input_yaml, args.output_yaml, repo)
    print("Finished modifying the original YAML file to find unused directories.")

    responsible_plugins_maven = run_and_analyze(
        owner, repo, path_to_yaml_file, branch, workflow_file,
        path_to_local_repo, args.output_file, args.input_yaml,
    )

    with open("responsible_plugins.json", "w") as f:
        json.dump(responsible_plugins_maven, f, indent=2)

    if not responsible_plugins_maven:
        print("No maven-attributable unused directories found; nothing to fix.")
        return 0

    print("Finding and testing fixes for unused directories.")

    def rerun_and_analyze() -> list[dict]:
        return run_and_analyze(
            owner, repo, path_to_yaml_file, branch, workflow_file,
            path_to_local_repo, "temp_out.txt", args.input_yaml,
        )

    fixer.run_fixer(
        responsible_plugins_maven,
        modified_workflow_path=os.path.join(path_to_local_repo, path_to_yaml_file),
        rerun_and_analyze=rerun_and_analyze,
        initial_output_file=args.output_file,
    )

    print(f"The output is written to {args.output_file}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
