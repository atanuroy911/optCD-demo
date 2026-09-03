# Evaluation scripts

This directory holds the one-off scripts and result artifacts used to produce
the paper's evaluation (Tables I-III: the 1,020 -> 89 project filtering
pipeline, and the per-job/per-project unused-directory counts). They are not
part of running the OptCD tool itself -- see the root `optcd.sh` / `optcd.py`
for that.

Run these with `eval/` as the working directory; they reference relative
filenames like `repos.csv` and `all_results/`.

- `find_repos.py` -- searches GitHub for the top starred Java/Maven projects
  and filters to those using GitHub Actions with passing Maven workflows.
- `find_commit_counts.py` -- annotates `repos.csv` with each repo's commit
  count, producing `repos-with-commit-counts.csv`.
- `experiment.py` -- drives the old `run.sh`-based flow across every repo in
  `repos-with-commit-counts.csv`, writing one result file per job into
  `table_results/`.
- `create_summary.py` -- aggregates `all_results/` and `maven_only_results/`
  (per-job JSON dumps of detected unused directories) into
  `job-based-results.csv` and `project-based-results.csv`.
- `calculate_used_unused_dir_with_fix.py` -- summarizes
  `fixer/updated_prompt_result.json` (unused dirs before/after the Gemini fix)
  into a CSV.
- `x.sh` -- an earlier, superseded version of the push/poll/analyze flow
  (no fixer step). Kept for reference.
- `fixer/` -- earlier fixer experiments (`run_gemini_legacy.py`,
  `experiment_gemini.py`) and their result dumps.
