"""Q2: on raw data from one real run, (1) measure the offset between
plugin log lines and the files those plugins write, and (2) compare the
original mapper with our rewrite's mapper on identical input.

(1) Timing (tests H3). For each plugin execution in a job log
    ("<ts> [INFO] --- plugin:ver:goal (exec) @ artifactId ---"), if the goal
    has a known output directory, find the first IN_CREATE event inside
    that module's directory in the inotify log and compute
        offset = first_file_event_ts - plugin_log_line_ts
    A negative offset means the plugin's files appear BEFORE its own log
    line, which makes nearest-preceding-line attribution pick the previous
    plugin (H3).

(2) Mapper comparison. Same classifier + clusterer output, attributed by:
    original - mapper/utils.py logic as in the paper: exact-key timestamp
               lookup (skip dir if missing), no index clamp
    rewrite  - current mapper/utils.py (earliest-file fallback, clamp)
    Each attribution is checked against the path-convention ground truth.

Usage: python scripts/q2_timing_and_mapper_compare.py data/raw/<run dir>
Output: results/q2_timing_<run>.csv, results/q2_mapper_compare_<run>.csv,
        results/q2_timing_and_compare_<run>.json
"""
import csv
import json
import re
import sys
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
from statistics import median

import yaml
from dateutil import parser as dtp

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import classifier.utils as classifier  # noqa: E402
import clusterer.utils as clusterer  # noqa: E402
import mapper.utils as rewrite_mapper  # noqa: E402
from q2_attribution_check import check_row, normalize_plugin  # noqa: E402

PLUGIN_LINE = re.compile(r"^(\S+)\s+\[INFO\] --- (\S+?):(\S+?):(\S+) \(([^)]*)\) @ (\S+) ---")
# Only directories written exclusively by one goal. (target/classes is NOT
# usable for compiler:compile: resources:resources writes into it first.)
GOAL_OUTPUT = {
    "compiler:compile": "target/maven-status/maven-compiler-plugin/compile/",
    "compiler:testCompile": "target/maven-status/maven-compiler-plugin/testCompile/",
    "surefire:test": "target/surefire-reports/",
}


def parse_plugin_lines(log_text):
    out = []
    for line in log_text.splitlines():
        line = line.lstrip("﻿")
        m = PLUGIN_LINE.match(line)
        if m:
            ts, plugin, ver, goal, exe, art = m.groups()
            out.append({"ts": dtp.isoparse(ts), "goal": f"{normalize_plugin(plugin)}:{goal}",
                        "exec": exe, "artifact": art, "raw": f"{plugin}:{ver}:{goal} ({exe}) @ {art}"})
    return out


def inotify_events(csv_path):
    for line in csv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(";")
        if len(parts) == 4:
            yield dtp.isoparse(parts[0]), parts[1] + "/" + parts[2], parts[3]


def module_dirs(events):
    """artifactId-agnostic: every '<...>/<module>/target/' prefix seen."""
    dirs = set()
    for _, path, _ in events:
        i = path.find("/target/")
        if i > 0:
            dirs.add(path[: i + 1])
    return dirs


def module_dir_for(artifact, dirs):
    best = None
    for d in dirs:
        name = d.rstrip("/").split("/")[-1].lower()
        a = artifact.lower()
        if name == a or name in a or a in name:
            if best is None or len(name) > len(best.rstrip("/").split("/")[-1]):
                best = d
    return best


def timing(log_text, events):
    plugins = parse_plugin_lines(log_text)
    dirs = module_dirs(events)
    creates = [(ts, p) for ts, p, ev in events if "IN_CREATE" in ev]
    rows = []
    for pl in plugins:
        out_rel = GOAL_OUTPUT.get(pl["goal"])
        mod = module_dir_for(pl["artifact"], dirs)
        if not out_rel or not mod:
            continue
        target = mod + out_rel
        first = next((ts for ts, p in creates if p.startswith(target) and ts >= pl["ts"].replace(microsecond=0) - __import__("datetime").timedelta(seconds=30)), None)
        if first is None:
            continue
        # what nearest-preceding-line attribution would pick for this event
        preceding = [p for p in plugins if p["ts"] <= first]
        pick = preceding[-1] if preceding else None
        rows.append({"goal": pl["goal"], "artifact": pl["artifact"], "output_dir": target,
                     "log_line_ts": pl["ts"].isoformat(), "first_file_event_ts": first.isoformat(),
                     "offset_ms": round((first - pl["ts"]).total_seconds() * 1000, 1),
                     "nearest_rule_picks": pick["raw"] if pick else "",
                     "nearest_rule_correct": bool(pick) and pick["goal"] == pl["goal"] and pick["artifact"] == pl["artifact"]})
    return rows


def original_mapper(log, unused_dirs, timestamps, input_yaml, job_name):
    """mapper/utils.py get_responsible_plugins as published (Linux paths)."""
    dummy = sorted(dtp.isoparse(t) for f, t in timestamps.items() if "optcd" in f)
    with open(input_yaml) as f:
        y = yaml.safe_load(f)
    job_id = job_name.split("(")[0].strip()
    steps = y["jobs"][job_id]["steps"]
    runs = [s.get("run") for s in steps]
    uses = [s.get("uses") for s in steps]
    names = [s.get("name") or s.get("uses") or s.get("run") for s in steps]
    in_mvn, tmp_ts, tmp_n, p_ts, p_n = False, [], [], [], []
    for line in log.splitlines():
        tok = line.split(" ")
        if "##[group]" in line and in_mvn:
            in_mvn = False
            tmp_ts.append(dtp.isoparse(tok[0]))
            p_ts.append(tmp_ts)
            p_n.append(tmp_n)
            tmp_ts, tmp_n = [], []
            continue
        if len(tok) < 3 or tok[1] != "[INFO]" or tok[2] != "---":
            continue
        in_mvn = True
        tmp_ts.append(dtp.isoparse(tok[0]))
        tmp_n.append(" ".join(tok[3:-1]))
    out = []
    for d in unused_dirs:
        if d not in timestamps:
            out.append((d, "<skipped: no own timestamp>"))
            continue
        ts = dtp.isoparse(timestamps[d])
        j = bisect_right(dummy, ts)
        if j >= len(runs):
            out.append((d, "<IndexError in original>"))
            continue
        for k in range(len(p_ts)):
            i = bisect_right(p_ts[k], ts)
            if 0 < i < len(p_ts[k]):
                out.append((d, p_n[k][i - 1]))
                break
        else:
            out.append((d, "Not responsible by maven plugins"))
    return out


def main(run_dir):
    run_dir = Path(run_dir)
    run = run_dir.name
    workflow = REPO_ROOT.parent / "gson" / ".github" / "workflows" / "build.yml"
    timing_rows, compare_rows = [], []
    for log_path in sorted((run_dir / "joblogs").glob("*.log")):
        job = log_path.stem
        csvs = list((run_dir / "inotify" / f"inotifywait-{job}").glob("*.csv"))
        if not csvs:
            continue
        log = log_path.read_text(encoding="utf-8", errors="replace").lstrip("﻿")
        events = list(inotify_events(csvs[0]))
        for r in timing(log, events):
            timing_rows.append({"job": job, **r})

        inotify_text = csvs[0].read_text(encoding="utf-8", errors="replace")
        unused, used, ts = classifier.classify_files(inotify_text)
        dirs = clusterer.cluster_files(list(unused), list(used))
        orig = dict(original_mapper(log, dirs, ts, workflow, job))
        try:
            new = {d: p for d, p, _, _ in rewrite_mapper.get_responsible_plugins(log, dirs, ts, str(workflow), job)}
        except Exception as e:  # noqa: BLE001
            new = {d: f"<error: {e}>" for d in dirs}
        for d in dirs:
            o, n = orig.get(d, ""), new.get(d, "")
            compare_rows.append({"job": job, "unused_dir": d,
                                 "original_attribution": o, "original_verdict": check_row(d, o)["verdict"],
                                 "rewrite_attribution": n, "rewrite_verdict": check_row(d, n)["verdict"],
                                 "expected": check_row(d, n)["expected"]})

    for name, rows in (("timing", timing_rows), ("mapper_compare", compare_rows)):
        if rows:
            with open(ROOT / "results" / f"q2_{name}_{run}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

    by_goal = defaultdict(list)
    for r in timing_rows:
        by_goal[r["goal"]].append(r["offset_ms"])
    summary = {
        "timing_offset_ms_by_goal": {g: {"n": len(v), "min": min(v), "median": median(v), "max": max(v),
                                         "negative": sum(x < 0 for x in v)} for g, v in by_goal.items()},
        "nearest_rule_on_first_file_event": {g: {"correct": sum(1 for r in timing_rows if r["goal"] == g and r["nearest_rule_correct"]),
                                                 "wrong": sum(1 for r in timing_rows if r["goal"] == g and not r["nearest_rule_correct"])}
                                             for g in by_goal},
        "mapper_compare": {
            side: {v: sum(1 for r in compare_rows if r[f"{side}_verdict"] == v)
                   for v in sorted({r[f"{side}_verdict"] for r in compare_rows})}
            for side in ("original", "rewrite")
        },
        "original_skipped_no_own_timestamp": sum(1 for r in compare_rows if r["original_attribution"].startswith("<skipped")),
        "original_index_error": sum(1 for r in compare_rows if r["original_attribution"].startswith("<IndexError")),
    }
    (ROOT / "results" / f"q2_timing_and_compare_{run}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
