"""For chosen paths, show which workflow STEP was running at every file
event (create/access), using the step start/end times in jobs.json.

This answers "who actually read this directory?" for one run: if the only
accesses fall inside an upload-artifact step, the upload is the sole reader.

Step times from the GitHub API have one-second resolution, so events are
matched to a step if they fall within [started_at, completed_at + 1s).

Usage: python scripts/access_by_step.py <raw run dir> <job name> <path prefix>...
  e.g. python scripts/access_by_step.py data/raw/JSON-java-37208714988 "build-17 (17)" target/site/ target/surefire-reports/
Output: printed table + results/access_by_step_<run>_<job>.csv
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from dateutil import parser as dtp

ROOT = Path(__file__).resolve().parent.parent


def main(run_dir, job_name, prefixes):
    run_dir = Path(run_dir)
    jobs = json.loads((run_dir / "jobs.json").read_text())
    job = next(j for j in jobs if j["name"] == job_name)
    steps = [(s["name"], dtp.isoparse(s["started_at"]), dtp.isoparse(s["completed_at"]) + timedelta(seconds=1))
             for s in job["steps"] if s.get("started_at") and s.get("completed_at")]
    csv_path = next((run_dir / "inotify" / f"inotifywait-{job_name}").glob("*.csv"))

    def step_at(ts):
        hits = [n for n, a, b in steps if a <= ts < b]
        return hits[-1] if hits else "(between steps)"

    rows = []
    for line in csv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(";")
        if len(parts) != 4:
            continue
        ts, d, f, ev = parts
        full = d + "/" + f
        rel = full.split("/", 6)[-1] if full.startswith("/home/runner/work/") else full
        pref = next((p for p in prefixes if rel.startswith(p)), None)
        if pref is None:
            continue
        # The watcher also emits IN_DELETE (e.g. `mvn clean`), which the
        # classifier ignores; label it explicitly rather than lumping it in.
        kind = ("ACCESS" if "IN_ACCESS" in ev else "CREATE" if "IN_CREATE" in ev
                else "DELETE" if "IN_DELETE" in ev else ev)
        if "IN_ISDIR" in ev:
            kind += "(dir)"
        rows.append({"prefix": pref, "ts": ts, "event": kind, "path": rel, "step": step_at(dtp.isoparse(ts))})

    run = run_dir.name
    out = ROOT / "results" / f"access_by_step_{run}_{job_name.replace(' ', '_').replace('(', '').replace(')', '')}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["prefix", "ts", "event", "path", "step"])
        w.writeheader()
        w.writerows(rows)

    table = defaultdict(Counter)
    for r in rows:
        if not r["event"].endswith("(dir)"):
            table[r["prefix"]][(r["event"], r["step"])] += 1
    for pref in prefixes:
        print(f"\n== {pref}")
        for (ev, step), n in sorted(table[pref].items(), key=lambda x: (x[0][0], x[0][1])):
            print(f"   {ev:7} {n:5}  during step: {step}")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
