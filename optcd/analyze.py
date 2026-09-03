import os

from tabulate import tabulate

import classifier.utils
import clusterer.utils
import mapper.utils

HEADERS = ["Unused directory", "Responsible plugin", "Responsible command", "Name of the step"]


def analyze_job(inotify_log_path: str, workflow_log_text: str, input_yaml_filename: str, job_name: str) -> list[tuple[str, str, str, str]] | None:
    """Returns the (unused_dir, plugin, command, step_name) tuples for one
    job, or None if no inotify log is available for it (e.g. the job was
    cancelled before it could upload its artifact)."""
    if not os.path.isfile(inotify_log_path):
        return None

    with open(inotify_log_path, "r") as f:
        inotify_log = f.read()

    unused_files, used_files, timestamps = classifier.utils.classify_files(inotify_log)
    unused_dirs = clusterer.utils.cluster_files(list(unused_files), list(used_files))
    responsible_plugins = mapper.utils.get_responsible_plugins(
        workflow_log_text, unused_dirs, timestamps, input_yaml_filename, job_name,
    )
    responsible_plugins.sort(key=lambda x: x[1], reverse=True)
    return responsible_plugins


def format_table(responsible_plugins: list[tuple[str, str, str, str]]) -> str:
    return tabulate(responsible_plugins, headers=HEADERS, tablefmt="fancy_grid") + "\n"


def append_report(output_file: str, text: str) -> None:
    if not output_file:
        print(text)
        return
    # encoding="utf-8" is required on Windows: tabulate's fancy_grid tables
    # use Unicode box-drawing characters, and Python's default file encoding
    # on Windows is cp1252, which crashes on them.
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(text)


def to_maven_dicts(responsible_plugins: list[tuple[str, str, str, str]]) -> list[dict]:
    return [
        {
            "Unused directory": unused_dir,
            "Responsible plugin": plugin,
            "Responsible command": command,
            "Name of the step": step_name,
        }
        for unused_dir, plugin, command, step_name in responsible_plugins
        if plugin != "Not responsible by maven plugins"
    ]
