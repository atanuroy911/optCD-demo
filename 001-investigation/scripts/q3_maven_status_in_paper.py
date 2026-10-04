"""Q3: how did maven-status flow through the paper's OWN fixer experiment?

Reads eval/fixer/updated_prompt_result.json (the paper's 216-command fixer
experiment) and, for every command whose unused directories include a
maven-status path, records:
  - which maven-status dirs were sent to Gemini
  - the fix Gemini suggested (fix_suggested_new_updated_prompt)
  - whether maven-status dirs were still unused after applying the fix
    (unused_dirs_w_fix)

Also counts maven-status rows in eval/all_results (all unused dirs) and
eval/maven_only_results (the subset attributed to a Maven plugin, i.e. the
fixer's input).

Usage: python scripts/q3_maven_status_in_paper.py
Output: results/q3_maven_status_paper.csv, results/q3_summary.json
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT.parent / "eval"
RESULTS = ROOT / "results"


def ms(dirs):
    return [d for d in dirs if "maven-status" in d]


def count_rows(folder):
    files = rows = 0
    for p in (EVAL / folder).glob("*.json"):
        hits = [r for r in json.loads(p.read_text(encoding="utf-8")) if "maven-status" in r["Unused directory"]]
        if hits:
            files += 1
            rows += len(hits)
    return files, rows


def main():
    data = json.loads((EVAL / "fixer" / "updated_prompt_result.json").read_text(encoding="utf-8"))
    rows = []
    for key, e in data.items():
        sent = ms(e.get("unused_dirs") or [])
        if not sent:
            continue
        after = ms(e.get("unused_dirs_w_fix") or [])
        fix = e.get("fix_suggested_new_updated_prompt") or ""
        rows.append({
            "id": key, "repo": f"{e.get('owner')}/{e.get('repo')}", "job": e.get("job"),
            "command": (e.get("old_commands") or "").replace("\n", " \\n "),
            "maven_status_dirs_sent_to_gemini": len(sent),
            "other_dirs_sent": len(e.get("unused_dirs") or []) - len(sent),
            "only_maven_status": len(sent) == len(e.get("unused_dirs") or []),
            "gemini_fix": fix.replace("\n", " \\n "),
            "fix_given": bool(fix.strip()),
            "maven_status_still_unused_after_fix": len(after),
            "sent_dirs": "; ".join(sent),
        })

    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / "q3_maven_status_paper.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    all_files, all_rows = count_rows("all_results")
    mvn_files, mvn_rows = count_rows("maven_only_results")
    summary = {
        "paper_all_results": {"jobs_with_maven_status": all_files, "maven_status_rows": all_rows},
        "paper_maven_only_results_fixer_input": {"jobs_with_maven_status": mvn_files, "maven_status_rows": mvn_rows},
        "fixer_experiment_total_commands": len(data),
        "commands_whose_prompt_included_maven_status": len(rows),
        "commands_where_maven_status_was_the_only_unused_dir": sum(r["only_maven_status"] for r in rows),
        "of_those_with_maven_status_gemini_gave_a_fix": sum(r["fix_given"] for r in rows),
        "commands_where_maven_status_still_unused_after_fix": sum(1 for r in rows if r["maven_status_still_unused_after_fix"]),
    }
    (RESULTS / "q3_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
