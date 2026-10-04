"""Q2: check OptCD's producer (plugin) attribution against ground truth.

Ground truth comes from Maven's own directory conventions: many output
directories are written by exactly one plugin, and the path says which.
E.g. target/maven-status/maven-compiler-plugin/compile/ is written by
maven-compiler-plugin's compile goal, target/surefire-reports/ by
surefire:test. Rows whose path has no unambiguous convention are labelled
"unverifiable" rather than guessed.

A second, independent check compares the module in the path
(<module>/target/...) with the module in OptCD's attribution
("plugin:version:goal (execution) @ <artifactId>").

Inputs:
  paper  - eval/all_results/*.json  (614 jobs, produced by the paper's
           ORIGINAL mapper, so any error here is the paper's algorithm,
           not our rewrite)
  ours   - "Analysis for job" entries in run-history/*/run.jsonl
           (produced by our rewrite, for comparison)

Usage: python scripts/q2_attribution_check.py
Output: results/q2_attribution_rows.csv, results/q2_attribution_summary.json
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
RESULTS = ROOT / "results"

# (path regex, expected plugin prefixes, acceptable goals or None for any, label)
RULES = [
    (r"/target/maven-status/maven-compiler-plugin/compile(/|$)", {"compiler"}, {"compile"}, "compiler:compile state"),
    (r"/target/maven-status/maven-compiler-plugin/testCompile(/|$)", {"compiler"}, {"testCompile"}, "compiler:testCompile state"),
    (r"/target/maven-status(/maven-compiler-plugin)?/?$", {"compiler"}, None, "compiler state (parent dir)"),
    (r"/target/surefire-reports(/|$)", {"surefire"}, {"test"}, "surefire test reports"),
    (r"/target/failsafe-reports(/|$)", {"failsafe"}, None, "failsafe IT reports"),
    (r"/target/japicmp(/|$)", {"japicmp"}, None, "japicmp report"),
    (r"/target/generated-sources/annotations(/|$)", {"compiler"}, {"compile"}, "annotation-processor output"),
    (r"/target/generated-test-sources/test-annotations(/|$)", {"compiler"}, {"testCompile"}, "test annotation-processor output"),
    (r"/target/javadoc-bundle-options(/|$)", {"javadoc"}, None, "javadoc options bundle"),
    (r"/target/(site/)?apidocs(/|$)", {"javadoc"}, None, "javadoc html"),
    (r"/target/(site/)?jacoco[^/]*(/|$)", {"jacoco"}, None, "jacoco report"),
    (r"/target/checkstyle[^/]*(/|$)", {"checkstyle"}, None, "checkstyle output"),
    (r"/target/spotbugs[^/]*(/|$)", {"spotbugs"}, None, "spotbugs output"),
    (r"/target/pmd(/|$)", {"pmd"}, None, "pmd output"),
    (r"/target/rat\.txt$|/target/rat(/|$)", {"apache-rat", "rat"}, None, "apache-rat output"),
    (r"/target/antrun(/|$)", {"antrun"}, None, "antrun output"),
    (r"/target/native-test-reports(/|$)", {"native"}, None, "graalvm native test reports"),
    (r"/target/generated-sources/java-templates(/|$)", {"templating"}, None, "templating output"),
    (r"/target/test-classes(/|$)", {"compiler", "resources"}, {"testCompile", "testResources"}, "test classes"),
    (r"/target/classes(/|$)", {"compiler", "resources"}, {"compile", "resources"}, "main classes"),
]
RULES = [(re.compile(p), plugins, goals, label) for p, plugins, goals, label in RULES]

ATTR = re.compile(r"^(?P<plugin>[^:\s]+):(?P<version>[^:\s]+):(?P<goal>[^\s]+)\s*(\((?P<exec>[^)]*)\))?\s*@\s*(?P<module>\S+)")
RUNNER = re.compile(r"^/home/runner/work/(?P<repo>[^/]+)/[^/]+/(?P<rel>.*)$")


def normalize_plugin(name):
    """Maven logs print either the prefix ('surefire') or, in older versions,
    the full artifactId ('maven-surefire-plugin', 'jacoco-maven-plugin').
    Reduce both to the prefix so they compare equal."""
    n = name.lower()
    if n.startswith("maven-") and n.endswith("-plugin"):
        n = n[len("maven-"):-len("-plugin")]
    elif n.endswith("-maven-plugin"):
        n = n[:-len("-maven-plugin")]
    return n


def path_module(rel):
    """Directory of the module owning this target/ dir ('' for the root module)."""
    if "/target" not in "/" + rel:
        return None
    head = ("/" + rel).split("/target")[0].strip("/")
    return head.split("/")[-1] if head else ""


def module_matches(dir_module, artifact_id, repo):
    if dir_module is None:
        return None
    if dir_module == "":
        return None  # root module: artifactId (often *-parent) not derivable from path
    a, d = artifact_id.lower(), dir_module.lower()
    return d == a or d in a or a in d


def check_row(unused_dir, attribution, repo_hint=""):
    m = RUNNER.match(unused_dir)
    rel = m.group("rel") if m else unused_dir
    repo = m.group("repo") if m else repo_hint
    rule = next(((p, pl, g, lab) for p, pl, g, lab in RULES if p.search("/" + rel.rstrip("/"))), None)
    am = ATTR.match(attribution or "")
    out = {"rel_path": rel, "attribution": attribution, "expected": "", "rule": "",
           "verdict": "", "module_check": ""}
    if not am:
        out["verdict"] = "not-attributed-to-maven"
        return out
    plugin, goal, module = normalize_plugin(am.group("plugin")), am.group("goal"), am.group("module")
    mm = module_matches(path_module(rel), module, repo)
    out["module_check"] = {True: "same-module", False: "different-module", None: "n/a"}[mm]
    if not rule:
        out["verdict"] = "unverifiable"
        return out
    _, plugins, goals, label = rule
    out["rule"] = label
    out["expected"] = "/".join(sorted(plugins)) + (":" + "|".join(sorted(goals)) if goals else "")
    plugin_ok = plugin in plugins
    goal_ok = goals is None or goal in goals
    out["verdict"] = "correct" if plugin_ok and goal_ok else ("wrong-goal" if plugin_ok else "wrong-plugin")
    return out


def paper_rows():
    for p in sorted((REPO_ROOT / "eval" / "all_results").glob("*.json")):
        for r in json.loads(p.read_text(encoding="utf-8")):
            yield "paper", p.name, r["Unused directory"], r["Responsible plugin"]


def our_rows():
    for jsonl in sorted((REPO_ROOT / "run-history").glob("*/run.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            msg = e.get("message", "") if e.get("category") == "step" else ""
            if not msg.startswith("Analysis for job "):
                continue
            job, _, payload = msg[len("Analysis for job "):].partition(": ")
            try:
                rows = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for unused_dir, plugin, _cmd, _step in rows:
                yield "ours", f"{jsonl.parent.name} | {job}", unused_dir, plugin


def main():
    out_rows = []
    for source, job, unused_dir, attribution in list(paper_rows()) + list(our_rows()):
        r = check_row(unused_dir, attribution)
        out_rows.append({"source": source, "job": job, **r})

    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / "q2_attribution_rows.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    summary = {}
    for source in ("paper", "ours"):
        rows = [r for r in out_rows if r["source"] == source]
        attributed = [r for r in rows if r["verdict"] != "not-attributed-to-maven"]
        verifiable = [r for r in attributed if r["verdict"] != "unverifiable"]
        wrong = [r for r in verifiable if r["verdict"] != "correct"]
        by_rule = defaultdict(Counter)
        for r in verifiable:
            by_rule[r["rule"]][r["verdict"]] += 1
        wrong_attr = Counter(re.sub(r":[^:]+:", ":*:", r["attribution"].split(" @")[0]) for r in wrong)
        summary[source] = {
            "rows_total": len(rows),
            "attributed_to_a_maven_plugin": len(attributed),
            "verifiable_by_path_convention": len(verifiable),
            "correct": len(verifiable) - len(wrong),
            "wrong": len(wrong),
            "wrong_rate_of_verifiable": round(len(wrong) / len(verifiable), 3) if verifiable else None,
            "verdicts": dict(Counter(r["verdict"] for r in rows)),
            "module_check_on_attributed": dict(Counter(r["module_check"] for r in attributed)),
            "by_rule": {k: dict(v) for k, v in sorted(by_rule.items())},
            "most_common_wrong_attributions": wrong_attr.most_common(15),
            "jobs_with_a_wrong_attribution": len({r["job"] for r in wrong}),
            "repos_with_a_wrong_attribution": len({r["job"].split("_")[0] + "_" + r["job"].split("_")[1] for r in wrong}) if source == "paper" else None,
        }
    (RESULTS / "q2_attribution_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
