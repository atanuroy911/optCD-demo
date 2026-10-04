"""Classify every artifact upload in the fetched workflows by whether
anything automated ever consumes it.

For each `actions/upload-artifact` (and `actions/upload-pages-artifact`)
step, search all workflows of the same repo for a consumer:

  consumed-same-workflow   download-artifact in the same workflow whose
                           name/pattern matches (or downloads everything)
  consumed-cross-workflow  another workflow fetches it: workflow_run-triggered
                           download-artifact with run-id/github-token,
                           dawidd6/action-download-artifact, `gh run download`,
                           or a test-report action reading the artifact
  consumed-pages           upload-pages-artifact + deploy-pages
  failure-only-diagnostic  no automated consumer; the upload only runs when
                           the build fails (failure()/cancelled()/!success()),
                           i.e. diagnostics for a human. Skipped on green
                           builds, so its files go unread there.
  stored-only              no automated consumer, and the upload also runs on
                           green builds (no `if`, always(), success(), ...).
                           The upload reads the files, but nothing ever
                           reads the artifact back.

Caveat: downloads by a human through the GitHub UI are invisible to static
analysis (GitHub's API exposes no download counts). "stored-only" means no
workflow consumes it, not that no person ever looked at it.

Usage: python scripts/scan_artifacts.py
Output: results/artifacts_<snapshot>.csv, results/artifact_summary.json
"""
import csv
import fnmatch
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = ROOT / "data" / "workflows"
RESULTS = ROOT / "results"

UPLOAD_ACTIONS = ("actions/upload-artifact", "actions/upload-pages-artifact")
TEST_REPORT_ACTIONS = ("dorny/test-reporter", "EnricoMi/publish-unit-test-result-action",
                       "mikepenz/action-junit-report", "scacap/action-surefire-report")
EXPR = re.compile(r"\$\{\{.*?\}\}")


def skeleton(name):
    """Turn an artifact name with ${{ }} expressions into a glob."""
    return EXPR.sub("*", str(name)).strip()


def names_compatible(a, b):
    a, b = skeleton(a), skeleton(b)
    return fnmatch.fnmatchcase(a, b) or fnmatch.fnmatchcase(b, a)


def load_workflows(repo_dir):
    workflows = []
    for f in sorted(repo_dir.glob("*.y*ml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        triggers = data.get("on", data.get(True, {}))
        workflows.append({
            "file": f.name,
            "name": data.get("name") or f.name,
            "triggers": triggers if isinstance(triggers, dict) else {t: None for t in (triggers if isinstance(triggers, list) else [triggers])},
            "jobs": data.get("jobs") or {},
        })
    return workflows


def iter_steps(wf):
    for job_id, job in wf["jobs"].items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                yield job_id, step


def uses(step):
    return str(step.get("uses") or "")


def collect(workflows):
    uploads, consumers = [], []
    for wf in workflows:
        wr = wf["triggers"].get("workflow_run") if isinstance(wf["triggers"], dict) else None
        upstream = [str(w) for w in (wr or {}).get("workflows", [])] if isinstance(wr, dict) else []
        for job_id, step in iter_steps(wf):
            u, w = uses(step), step.get("with") or {}
            run = str(step.get("run") or "")
            if u.startswith(UPLOAD_ACTIONS) and "/merge" not in u:
                pages = u.startswith("actions/upload-pages-artifact")
                uploads.append({
                    "workflow_file": wf["file"], "workflow_name": wf["name"], "job": job_id,
                    "step": step.get("name") or u,
                    "artifact_name": w.get("name") or ("github-pages" if pages else "artifact"),
                    "path": str(w.get("path", "")).strip().replace("\n", " | "),
                    "if": str(step.get("if") or ""),
                    "retention_days": w.get("retention-days", ""),
                    "pages": pages,
                })
            if u.startswith("actions/download-artifact"):
                cross = bool(w.get("run-id") or w.get("github-token"))
                consumers.append({"kind": "download", "workflow_file": wf["file"], "job": job_id,
                                  "name": w.get("name"), "pattern": w.get("pattern"),
                                  "cross": cross, "upstream": upstream, "evidence": f"{wf['file']}:{job_id}: {u}"})
            elif u.startswith("actions/upload-artifact/merge"):
                consumers.append({"kind": "download", "workflow_file": wf["file"], "job": job_id,
                                  "name": None, "pattern": w.get("pattern"), "cross": False,
                                  "upstream": [], "evidence": f"{wf['file']}:{job_id}: {u}"})
            elif u.startswith("dawidd6/action-download-artifact"):
                consumers.append({"kind": "download", "workflow_file": wf["file"], "job": job_id,
                                  "name": w.get("name"), "pattern": w.get("name") if w.get("name_is_regexp") else None,
                                  "cross": True, "upstream": [str(w.get("workflow", ""))] + upstream,
                                  "evidence": f"{wf['file']}:{job_id}: {u}"})
            elif u.startswith(TEST_REPORT_ACTIONS) and w.get("artifact"):
                # Only reporters that fetch an artifact themselves (dorny/test-reporter's
                # `artifact:` input). Reporters that read files already on disk are
                # not consumers; the preceding download step is.
                consumers.append({"kind": "download", "workflow_file": wf["file"], "job": job_id,
                                  "name": w.get("artifact"), "pattern": None, "cross": bool(upstream),
                                  "upstream": upstream, "evidence": f"{wf['file']}:{job_id}: {u}"})
            elif u.startswith("actions/github-script") and "downloadArtifact" in str(w.get("script", "")):
                # JavaScript download via the REST API, usually filtered like
                #   artifacts.filter(a => a.name == "pr")
                script = str(w.get("script", ""))
                names = re.findall(r"\.name\s*===?\s*['\"]([^'\"]+)['\"]", script) or [None]
                for nm in names:
                    consumers.append({"kind": "download", "workflow_file": wf["file"], "job": job_id,
                                      "name": nm, "pattern": None, "cross": bool(upstream),
                                      "upstream": upstream,
                                      "evidence": f"{wf['file']}:{job_id}: {u} (script downloadArtifact name={nm})"})
            elif u.startswith("actions/deploy-pages"):
                consumers.append({"kind": "pages", "workflow_file": wf["file"], "job": job_id,
                                  "name": w.get("artifact_name", "github-pages"), "pattern": None,
                                  "cross": False, "upstream": [], "evidence": f"{wf['file']}:{job_id}: {u}"})
            if "gh run download" in run:
                consumers.append({"kind": "download", "workflow_file": wf["file"], "job": job_id,
                                  "name": None, "pattern": None, "cross": True, "upstream": upstream,
                                  "evidence": f"{wf['file']}:{job_id}: gh run download"})
    return uploads, consumers


def matches(upload, consumer, workflows_by_file):
    if consumer["kind"] == "pages":
        return upload["pages"] and names_compatible(upload["artifact_name"], consumer["name"])
    name, pattern = consumer["name"], consumer["pattern"]
    if pattern:
        name_ok = fnmatch.fnmatchcase(skeleton(upload["artifact_name"]), skeleton(pattern)) or \
                  bool(re.fullmatch(skeleton(pattern).replace("*", ".*"), skeleton(upload["artifact_name"])))
    elif name:
        name_ok = names_compatible(upload["artifact_name"], name)
    else:
        name_ok = True  # downloads every artifact of the run
    if not name_ok:
        return False
    if consumer["workflow_file"] == upload["workflow_file"]:
        return not consumer["cross"] or not consumer["upstream"]
    # different workflow: must point at the uploading workflow
    up_wf = workflows_by_file[upload["workflow_file"]]
    targets = {upload["workflow_file"], upload["workflow_file"].rsplit(".", 1)[0], str(up_wf["name"])}
    return consumer["cross"] and any(t in targets for t in consumer["upstream"])


def classify(upload, consumers, workflows_by_file):
    hits = [c for c in consumers if matches(upload, c, workflows_by_file)]
    if hits:
        if any(c["kind"] == "pages" for c in hits):
            cat = "consumed-pages"
        elif any(c["workflow_file"] == upload["workflow_file"] for c in hits):
            cat = "consumed-same-workflow"
        else:
            cat = "consumed-cross-workflow"
        return cat, "; ".join(c["evidence"] for c in hits)
    # No automated consumer. What matters for OptCD is whether the upload step
    # runs on a GREEN build (the kind OptCD analyzes):
    #   runs on green  -> the upload reads the files -> OptCD says "used"
    #                     although nothing consumes them (false negative)
    #   failure-only   -> skipped on green -> files unread -> OptCD may say
    #                     "unused" and remove diagnostics a failed build needs
    cond = upload["if"].replace(" ", "")
    failure_gate = any(k in cond for k in ("failure()", "cancelled()", "!success()"))
    green_too = "always()" in cond or "success()" in cond.replace("!success()", "")
    if failure_gate and not green_too:
        return "failure-only-diagnostic", f"if: {upload['if']}"
    return "stored-only", f"if: {upload['if']}" if upload["if"] else ""


def main():
    manifest = json.loads((WF_DIR / "manifest.json").read_text())
    RESULTS.mkdir(exist_ok=True)
    summary = {}
    fields = ["repo", "workflow_file", "workflow_name", "analyzed_by_paper", "job", "step",
              "artifact_name", "path", "if", "retention_days", "category", "consumer_evidence"]

    for snapshot in ("paper", "head"):
        rows = []
        for repo, meta in manifest.items():
            repo_dir = WF_DIR / snapshot / repo.replace("/", "__")
            if not repo_dir.exists():
                continue
            workflows = load_workflows(repo_dir)
            by_file = {w["file"]: w for w in workflows}
            uploads, consumers = collect(workflows)
            for up in uploads:
                cat, ev = classify(up, consumers, by_file)
                rows.append({
                    "repo": repo, "workflow_file": up["workflow_file"],
                    "workflow_name": up["workflow_name"],
                    "analyzed_by_paper": up["workflow_file"] in meta["analyzed_workflows"],
                    "job": up["job"], "step": up["step"], "artifact_name": up["artifact_name"],
                    "path": up["path"], "if": up["if"], "retention_days": up["retention_days"],
                    "category": cat, "consumer_evidence": ev,
                })
        with open(RESULTS / f"artifacts_{snapshot}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

        cats = {}
        for r in rows:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        analyzed = [r for r in rows if r["analyzed_by_paper"]]
        acats = {}
        for r in analyzed:
            acats[r["category"]] = acats.get(r["category"], 0) + 1
        summary[snapshot] = {
            "repos_scanned": sum(1 for m in manifest.values() if m[snapshot]["files"]),
            "repos_with_uploads": len({r["repo"] for r in rows}),
            "uploads_total": len(rows),
            "by_category": cats,
            "uploads_in_paper_analyzed_workflows": len(analyzed),
            "repos_with_uploads_in_analyzed_workflows": len({r["repo"] for r in analyzed}),
            "analyzed_by_category": acats,
        }
    (RESULTS / "artifact_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
