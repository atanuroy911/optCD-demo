"""Q2: categorize the paper's attribution errors into mechanisms.

Runs on results/q2_attribution_rows.csv (from q2_attribution_check.py),
joined with the Maven command recorded for each row in eval/all_results.

Hypotheses tested:
  H1 parallel builds   - with `mvn -T N`, modules build concurrently and
                         their log lines interleave; nearest-timestamp
                         attribution then blames a plugin from another
                         module. Expect a higher wrong rate in -T builds,
                         and wrong rows marked different-module.
  H2 nested builds     - maven-invoker-plugin runs nested Maven builds whose
                         plugin lines never reach the main log, so their
                         outputs are all blamed on invoker:run.
  H3 lifecycle offset  - in the same module, the blamed plugin is one that
                         runs just BEFORE the true producer in Maven's
                         lifecycle, consistent with a small timing offset
                         between log-line timestamps and file-event
                         timestamps.

Usage: python scripts/q2_error_patterns.py
Output: results/q2_error_patterns.csv, results/q2_error_patterns_summary.json
"""
import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent
RESULTS = ROOT / "results"

# Maven default lifecycle order, with the phase each common goal binds to.
PHASES = ["validate", "initialize", "generate-sources", "process-sources", "generate-resources",
          "process-resources", "compile", "process-classes", "generate-test-sources",
          "process-test-sources", "generate-test-resources", "process-test-resources",
          "test-compile", "process-test-classes", "test", "prepare-package", "package",
          "pre-integration-test", "integration-test", "post-integration-test", "verify",
          "install", "deploy"]
GOAL_PHASE = {
    "enforcer:enforce": "validate", "checkstyle:check": "validate",
    "jacoco:prepare-agent": "initialize", "buildnumber:create": "initialize",
    "antlr4:antlr4": "generate-sources", "protobuf:compile": "generate-sources",
    "protobuf:generate-test": "generate-test-sources", "templating:filter-sources": "generate-sources",
    "build-helper:add-source": "generate-sources", "remote-resources:process": "generate-resources",
    "resources:resources": "process-resources", "resources:copy-resources": "process-resources",
    "compiler:compile": "compile", "bnd:bnd-process": "process-classes",
    "resources:testResources": "process-test-resources", "compiler:testCompile": "test-compile",
    "proguard:proguard": "process-test-classes", "surefire:test": "test",
    "jar:jar": "package", "jar:test-jar": "package", "javadoc:jar": "package", "source:jar-no-fork": "package",
    "invoker:run": "integration-test", "failsafe:integration-test": "integration-test",
    "jacoco:report": "verify", "japicmp:cmp": "verify", "pmd:pmd": "verify", "pmd:check": "verify",
    "antrun:run": "package",
}
EXPECTED_PHASE = {
    "compiler:compile state": "compile", "compiler:testCompile state": "test-compile",
    "compiler state (parent dir)": "compile", "surefire test reports": "test",
    "main classes": "compile", "test classes": "test-compile", "jacoco report": "verify",
    "javadoc options bundle": "package", "japicmp report": "verify", "failsafe IT reports": "integration-test",
}


def norm_plugin(name):
    n = name.lower()
    if n.startswith("maven-") and n.endswith("-plugin"):
        n = n[6:-7]
    elif n.endswith("-maven-plugin"):
        n = n[:-13]
    return n


def blamed_goal(attribution):
    m = re.match(r"^([^:\s]+):[^:\s]+:(\S+)", attribution)
    return f"{norm_plugin(m.group(1))}:{m.group(2)}" if m else None


def commands_by_row():
    """(job file, unused dir) -> Maven command, from the paper's raw results."""
    out = {}
    for p in (REPO_ROOT / "eval" / "all_results").glob("*.json"):
        for r in json.loads(p.read_text(encoding="utf-8")):
            out[(p.name, r["Unused directory"].split("/home/runner/work/", 1)[-1].split("/", 2)[-1])] = r["Responsible command"]
    return out


def is_parallel(cmd):
    return bool(re.search(r"(^|\s)(-T|--threads)(\s|=)\S+", cmd or ""))


def main():
    cmds = commands_by_row()
    rows = [r for r in csv.DictReader(open(RESULTS / "q2_attribution_rows.csv", encoding="utf-8"))
            if r["source"] == "paper" and r["verdict"] not in ("unverifiable", "not-attributed-to-maven")]

    out = []
    for r in rows:
        cmd = cmds.get((r["job"], r["rel_path"]), "")
        wrong = r["verdict"] != "correct"
        goal = blamed_goal(r["attribution"])
        mechanism = ""
        if wrong:
            exp_phase, got_phase = EXPECTED_PHASE.get(r["rule"]), GOAL_PHASE.get(goal)
            if goal and goal.startswith("invoker:") or "/target/it/" in r["rel_path"]:
                mechanism = "H2-nested-build"
            elif is_parallel(cmd) and r["module_check"] == "different-module":
                mechanism = "H1-parallel-cross-module"
            elif r["module_check"] == "different-module":
                mechanism = "cross-module-sequential"
            elif exp_phase and got_phase:
                d = PHASES.index(got_phase) - PHASES.index(exp_phase)
                mechanism = "H3-predecessor" if d < 0 else ("same-phase" if d == 0 else "successor")
            else:
                mechanism = "unclassified"
        out.append({**r, "parallel_build": is_parallel(cmd), "blamed_goal": goal,
                    "mechanism": mechanism, "command": cmd.replace("\n", " ")[:200]})

    with open(RESULTS / "q2_error_patterns.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    def rate(subset):
        wrong = sum(r["verdict"] != "correct" for r in subset)
        return {"verifiable": len(subset), "wrong": wrong,
                "wrong_rate": round(wrong / len(subset), 3) if subset else None}

    par = [r for r in out if r["parallel_build"]]
    seq = [r for r in out if not r["parallel_build"]]
    summary = {
        "H1_wrong_rate_parallel_builds": rate(par),
        "H1_wrong_rate_sequential_builds": rate(seq),
        "H1_parallel_repos": sorted({"_".join(r["job"].split("_")[:2]) for r in par}),
        "mechanisms_of_wrong_rows": dict(Counter(r["mechanism"] for r in out if r["mechanism"])),
        "H3_predecessor_examples": sorted({f"{r['rule']}: blamed {r['blamed_goal']}" for r in out if r["mechanism"] == "H3-predecessor"}),
        "non_H3_same_module_examples": sorted({f"{r['rule']}: blamed {r['blamed_goal']} ({r['mechanism']})" for r in out
                                               if r["mechanism"] in ("successor", "same-phase", "unclassified")}),
    }
    (RESULTS / "q2_error_patterns_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
