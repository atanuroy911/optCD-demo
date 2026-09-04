from dateutil import parser
from bisect import bisect_right
import yaml


def _resolve_directory_timestamp(unused_dir: str, timestamps: dict[str, str]) -> str | None:
    """Returns when `unused_dir` started being populated.

    Prefers the directory's own creation timestamp, but that entry gets
    silently erased whenever inotify also reports an IN_ACCESS on the
    directory itself -- which InotifyTree does as a side effect of opening
    a newly-created subdirectory to set up its recursive watch, unrelated to
    anything actually reading the directory's contents. When that happens,
    fall back to the earliest timestamp among the files still recorded
    under this directory.
    """
    if unused_dir in timestamps:
        return timestamps[unused_dir]
    nested = [ts for path, ts in timestamps.items() if path.startswith(unused_dir)]
    return min(nested, key=parser.isoparse) if nested else None


def get_responsible_plugins(log: str, unused_dirs: list[str], timestamps: dict[str, str], input_yaml_filename: str, job_name: str) -> list[tuple[str, str, str, str]]:
    dummy_file_timestamps = []
    for file, timestamp in timestamps.items():
        if "optcd" in file:
            dummy_file_timestamps.append(parser.isoparse(timestamp))

    run_commands_in_steps = []
    uses_in_steps = []
    names_of_steps = []
    with open(input_yaml_filename, "r") as input_yaml:
        loaded_yaml = yaml.safe_load(input_yaml)
        job_id = job_name.split("(")[0].strip()
        for step in loaded_yaml["jobs"][job_id]["steps"]:
            run_commands_in_steps.append(step.get("run"))
            uses_in_steps.append(step.get("uses"))
            names_of_steps.append(step.get("name") or step.get("uses") or step.get("run"))

    in_maven = False
    tmp_plugin_timestamps = []
    tmp_plugin_names = []
    plugin_timestamps = []
    plugin_names = []
    responsible_plugins = []
    for line in log.splitlines():
        tokens = line.split(" ")
        if "##[group]" in line and in_maven:  # maven part ended
            in_maven = False
            timestamp = parser.isoparse(tokens[0])
            tmp_plugin_timestamps.append(timestamp)
            plugin_timestamps.append(tmp_plugin_timestamps)
            plugin_names.append(tmp_plugin_names)
            tmp_plugin_timestamps = []
            tmp_plugin_names = []
            continue
        if len(tokens) < 3:
            continue
        if tokens[1] != "[INFO]" or tokens[2] != "---":
            continue
        in_maven = True
        timestamp = parser.isoparse(tokens[0])
        name = ' '.join(tokens[3:-1])
        tmp_plugin_timestamps.append(timestamp)
        tmp_plugin_names.append(name)

    for unused_dir in unused_dirs:
        dir_timestamp = _resolve_directory_timestamp(unused_dir, timestamps)
        if dir_timestamp is None:
            continue
        timestamp = parser.isoparse(dir_timestamp)
        # bisect_right can return one-past-the-end when the directory's
        # timestamp falls after the last step-boundary marker (e.g. files
        # still being written right as the final instrumented step starts).
        # Clamp to the last known step rather than index out of range.
        j = min(bisect_right(dummy_file_timestamps, timestamp), len(run_commands_in_steps) - 1)
        for k in range(len(plugin_timestamps)):
            i = bisect_right(plugin_timestamps[k], timestamp)
            if 0 < i < len(plugin_timestamps[k]):
                responsible_plugins.append((unused_dir, plugin_names[k][i - 1], run_commands_in_steps[j] or uses_in_steps[j], names_of_steps[j]))
                break
        else:
            responsible_plugins.append((unused_dir, "Not responsible by maven plugins", run_commands_in_steps[j] or uses_in_steps[j], names_of_steps[j]))

    return responsible_plugins
