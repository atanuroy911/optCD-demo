"""Print the headline numbers of the investigation, for presenting.

Reads only saved results (no network, no CI). Run the analysis scripts
first if you want to regenerate those results from the raw data.

Usage: python 001-investigation/scripts/show_headlines.py [q1|q2|q3|e1|e2|all]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"


def load(name):
    return json.loads((RES / name).read_text())


def q1():
    s = load("artifact_summary.json")["paper"]
    c = s["by_category"]
    consumed = c.get("consumed-same-workflow", 0) + c.get("consumed-cross-workflow", 0) + c.get("consumed-pages", 0)
    total = s["uploads_total"]
    print("Q1  Uploaded artifacts (paper's 110 repos, workflows as of 2024-11-01)")
    print(f"    repos that upload artifacts : {s['repos_with_uploads']} / {s['repos_scanned']}")
    print(f"    total uploads               : {total}")
    print(f"    consumed by a workflow      : {consumed:4}  ({consumed / total:.0%})")
    print(f"    failure-only diagnostics    : {c.get('failure-only-diagnostic', 0):4}  ({c.get('failure-only-diagnostic', 0) / total:.0%})")
    print(f"    STORED-ONLY (never read back): {c.get('stored-only', 0):4}  ({c.get('stored-only', 0) / total:.0%})")
    v = load("q1_optcd_verdict_by_category.json")
    print("    OptCD's published verdict on uploads in analyzed workflows:")
    for cat in ("consumed-same-workflow", "consumed-cross-workflow", "stored-only", "failure-only-diagnostic"):
        if cat in v:
            d = v[cat]
            print(f"      {cat:26} treated as used: {d.get('not flagged (used)', 0):3}   flagged unused: {d.get('flagged unused', 0)}")


def q2():
    s = load("q2_attribution_summary.json")["paper"]
    p = load("q2_error_patterns_summary.json")
    print("Q2  Plugin attribution (paper's own 614 jobs, original OptCD code)")
    print(f"    attributions checkable from folder names : {s['verifiable_by_path_convention']}")
    print(f"    correct                                  : {s['correct']}")
    print(f"    WRONG                                    : {s['wrong']} ({s['wrong_rate_of_verifiable']:.1%})  in {s['jobs_with_a_wrong_attribution']} jobs / {s['repos_with_a_wrong_attribution']} repos")
    print("    why they are wrong:")
    names = {"H1-parallel-cross-module": "parallel build, blamed another module",
             "H2-nested-build": "nested build (invoker)",
             "H3-predecessor": "boundary timing, blamed the plugin before",
             "successor": "boundary timing, blamed the plugin after"}
    for k, n in p["mechanisms_of_wrong_rows"].items():
        print(f"      {names.get(k, k):42} {n}")
    par, seq = p["H1_wrong_rate_parallel_builds"], p["H1_wrong_rate_sequential_builds"]
    print(f"    wrong rate, parallel builds   : {par['wrong_rate']:.1%}  ({par['wrong']}/{par['verifiable']})")
    print(f"    wrong rate, sequential builds : {seq['wrong_rate']:.1%}  ({seq['wrong']}/{seq['verifiable']})")


def q3():
    s = load("q3_summary.json")
    print("Q3  maven-status reaching Gemini (paper's own fixer experiment)")
    print(f"    commands sent to Gemini                  : {s['fixer_experiment_total_commands']}")
    print(f"    ...whose prompt included maven-status    : {s['commands_whose_prompt_included_maven_status']}")
    print(f"    ...where maven-status was the ONLY dir   : {s['commands_where_maven_status_was_the_only_unused_dir']}")
    print("    filter location: legacy/fixer/run_gemini_with_confirmation.py line 214,")
    print("    AFTER Gemini (line 164), workflow rewrite (187) and re-run (191)")


def e1():
    print("E1  JSON-java, same job with vs without its 3 upload steps")
    print("    (from logs/E1_flagged_comparison.log and the access_by_step logs)")
    print(ROOT.joinpath("logs", "E1_flagged_comparison.log").read_text().rstrip())
    print("    reads of target/site/: with-upload 15 (all in the upload step), no-upload 0")


def e2():
    print("E2  gson, same job: mvn verify  vs  mvn -T 4 verify  (who made surefire-reports?)")
    for run, label in (("gson-37208820120", "sequential"), ("gson-37209217089", "parallel -T 4")):
        d = load(f"q2_timing_and_compare_{run}.json")["nearest_rule_on_first_file_event"]["surefire:test"]
        print(f"    {label:14} correct {d['correct']} / {d['correct'] + d['wrong']}")
    print("    every parallel error blamed a plugin from a DIFFERENT module (logs/E2_surefire_picks.log)")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, fn in (("q1", q1), ("q2", q2), ("q3", q3), ("e1", e1), ("e2", e2)):
        if which in (name, "all"):
            fn()
            print()
