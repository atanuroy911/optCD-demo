"""Cross-reference uploaded artifact paths with OptCD's own published results.

For every upload step in a workflow the paper analyzed (paper-era snapshot),
check whether OptCD flagged the uploaded location as an *unused directory*
in the paper's per-job results (eval/all_results/*.json).

Expected outcomes:
  - Upload step runs on every build  -> the upload reads the files ->
    OptCD should never flag them, whether or not anything consumes them.
  - Upload step guarded by if: failure() -> skipped on green builds ->
    files go unread -> OptCD may flag them, and its fix would delete the
    very diagnostics that are only needed when a build fails.

Usage: python scripts/crossref_paper_results.py
Output: results/crossref_paper_results.csv
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALL_RESULTS = ROOT.parent / "eval" / "all_results"
RESULTS = ROOT / "results"
RUNNER_PREFIX = re.compile(r"^/home/runner/work/[^/]+/[^/]+/")


def repo_result_files(repo):
    owner, name = repo.split("/")
    prefix = f"{owner}_{name}_"
    return [p for p in ALL_RESULTS.iterdir() if p.name.startswith(prefix)]


def unused_dirs_for(repo):
    """All unused dirs OptCD reported for this repo, relative to the checkout."""
    out = []
    for p in repo_result_files(repo):
        for row in json.loads(p.read_text(encoding="utf-8")):
            rel = RUNNER_PREFIX.sub("", row["Unused directory"]).rstrip("/")
            out.append({"rel": rel, "job_file": p.name, "plugin": row["Responsible plugin"]})
    return out


def upload_globs(path_field):
    """Upload `path:` may list several globs separated by newlines."""
    out = []
    for part in re.split(r"\s*\|\s*|\n", path_field):
        part = part.strip()
        while part.startswith("./"):
            part = part[2:]
        if part and not part.startswith("!"):
            out.append(part)
    return out


def overlaps(glob, unused_rel):
    """Does unused dir `unused_rel` contain files matched by upload `glob`?

    anchored glob (target/x/**)   : static root R; overlap if the unused dir
                                    is R or under it, or R is under the dir.
    relative glob (**/target/x/*) : static tail T may sit anywhere; overlap
                                    if the dir ends with T or is under a T.
    A static part that names a file (target/rat.txt) also matches when the
    unused dir is that file's parent.
    """
    anchored = not glob.startswith("**/")
    tail = glob if anchored else glob[3:]
    static = re.split(r"[*?\[{$]", tail, maxsplit=1)[0].rstrip("/")
    if not static:
        return False  # pure wildcard: undecidable, do not count
    d = "/" + unused_rel.strip("/") + "/"
    s = "/" + static + "/"
    parent = "/" + static.rsplit("/", 1)[0] + "/" if "/" in static and "." in static.rsplit("/", 1)[1] else None
    if anchored:
        return d.startswith(s) or s.startswith(d) or (parent is not None and d == parent)
    return s in d or (parent is not None and d.endswith(parent))


def main():
    with open(RESULTS / "artifacts_paper.csv", encoding="utf-8") as f:
        uploads = [r for r in csv.DictReader(f) if r["analyzed_by_paper"] == "True"]

    rows = []
    for up in uploads:
        unused = unused_dirs_for(up["repo"])
        globs = upload_globs(up["path"])
        hits = [u for u in unused if any(overlaps(g, u["rel"]) for g in globs)]
        rows.append({
            "repo": up["repo"], "workflow_file": up["workflow_file"], "job": up["job"],
            "artifact_name": up["artifact_name"], "path": up["path"], "if": up["if"],
            "category": up["category"],
            "optcd_result_files": len(repo_result_files(up["repo"])),
            "flagged_unused_by_optcd": bool(hits),
            "flagged_dirs": "; ".join(sorted({h["rel"] for h in hits})),
            "attributed_plugins": "; ".join(sorted({h["plugin"] for h in hits})),
        })

    fields = list(rows[0].keys()) if rows else []
    with open(RESULTS / "crossref_paper_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    with_results = [r for r in rows if r["optcd_result_files"]]
    flagged = [r for r in with_results if r["flagged_unused_by_optcd"]]
    print(f"uploads in paper-analyzed workflows: {len(rows)}")
    print(f"  ...in repos with OptCD results:   {len(with_results)}")
    print(f"  ...flagged unused by OptCD:        {len(flagged)}")
    for r in flagged:
        print(f"    {r['repo']} [{r['category']}] if='{r['if']}' path={r['path']} -> {r['flagged_dirs']}")


if __name__ == "__main__":
    main()
