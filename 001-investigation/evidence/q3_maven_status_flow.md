# Q3: Why does `maven-status` still reach Gemini?

## Short answer

The only `maven-status` handling in the entire original pipeline is one line
in the fixer's *post-verification* reporting step. Detection (classifier,
clusterer), attribution (mapper) and prompt construction contain no
`maven-status` check at all. By the time that line runs, Gemini has already
been asked about the directory, its suggested flags have been merged into
the workflow, and the build has been re-run.

The filter is only applied in one of the two reporting branches, so in the
other branch `maven-status` is reported as "fixed".

## Code trace (original implementation, `legacy/fixer/run_gemini_with_confirmation.py`)

`grep -rn "maven-status" legacy/ classifier/ clusterer/ mapper/ logger/`
returns exactly two lines, both in this file (213 is a comment, 214 the
filter). Every stage before them is unfiltered:

| Stage | Location | `maven-status` check? |
|---|---|---|
| Classify created vs accessed files | `classifier/utils.py` | none |
| Cluster files into unused dirs | `clusterer/utils.py` | none |
| Attribute dir to plugin | `mapper/utils.py` | none |
| Loop over unused dirs per command | legacy fixer, L137 | none |
| Build Gemini prompt with the dir path | legacy fixer, L154-162 | none |
| **Call Gemini** | legacy fixer, **L164** | none |
| Merge suggested flags into the command | legacy fixer, L177-182 | none |
| **Rewrite workflow YAML** | legacy fixer, **L187** | none |
| **Re-run the build** | legacy fixer, **L191** | none |
| Diff old vs new unused dirs (`try` branch) | legacy fixer, **L214** | **yes: drops maven-status from the "fixed" list** |
| Report when re-run finds zero unused dirs (`except FileNotFoundError` branch) | legacy fixer, L227-238 | **none: writes `all_unused_old`, maven-status included, as "fixed"** |

Excerpt, L208-214 (`try` branch):

```python
diff_only_in_old = all_unused_old - all_unused_new
diff_only_in_old = list(dict.fromkeys(diff_only_in_old))
# if any content in the diff_only_in_old list contains "maven-status" then remove it
diff_only_in_old = [x for x in diff_only_in_old if "maven-status" not in x]
```

Excerpt, L227-234 (`except` branch, no filter):

```python
except FileNotFoundError:
    # in this case, the fixes successfully removed all the unused directories, therefore new json file is empty
    with open(initial_output_file, 'a') as f:
        ...
        f.write(f"following directories are fixed:\n")
        for dir in all_unused_old:
            f.write(f"{dir}\n")
```

Our rewrite (`optcd/fixer.py` L150) kept the same placement, after the
Gemini call, YAML rewrite and re-run. That is why the live `gson` run sent
`gson/target/maven-status/.../testCompile/` to Gemini and got
`-Dmaven.compiler.useIncrementalCompilation=false` back
(`000-research/evidence/incremental-compilation-gemini-exchange.txt`).

## How often this happened in the paper's own experiment

Script: `scripts/q3_maven_status_in_paper.py`. Output:
`results/q3_maven_status_paper.csv`, `results/q3_summary.json`.

| Measure | Value |
|---|---|
| Paper jobs with a `maven-status` unused dir (`eval/all_results`) | 30 of 614 |
| `maven-status` rows attributed to a Maven plugin (`eval/maven_only_results`, the fixer's input) | 47 rows in 29 jobs |
| Commands in the paper's fixer experiment (`eval/fixer/updated_prompt_result.json`) | 216 |
| ...whose Gemini input included a `maven-status` dir | **29 (13%)** |
| ...where `maven-status` was the **only** unused dir | **5** |
| ...where `maven-status` was still unused after the fix | 6 |

## Why the filter probably exists: `maven-status` is unstable between runs

For the 5 commands where `maven-status` was the only unused directory:

| id | repo | Gemini "fix" | maven-status unused after fix? |
|---|---|---|---|
| 112 | rocketmq | **identical to the original command** (no change at all) | no |
| 395 | litemall | adds `-Dmaven.compiler.showWarnings=false` (unrelated to output dirs) | no |
| 230, 470, 510 | shenyu | no fix suggested | no |

In every case `maven-status` stopped being "unused" on the re-run, including
where the command was not changed at all (rocketmq) and where the added
flag cannot affect which directories are written (litemall). Whether
`maven-status` is classified as unused therefore varies between runs,
independent of any fix.

Our interpretation: the authors saw `maven-status` "disappear" after
irrelevant fixes and added L214 so this noise would not be counted as a
successful fix. That guards the *success tally*. It does not stop the
directory from being detected, sent to Gemini, or patched. It also does not
cover the `except` branch, where such noise is reported as fixed.

## Related detail noticed while tracing (not yet investigated)

Legacy L140 deduplicates unused dirs per command by **basename**
(`os.path.basename(unused_dir) in fixed_dirs`). In a multi-module build,
`moduleA/target/surefire-reports` and `moduleB/target/surefire-reports`
share the basename `surefire-reports`, so only the first is ever sent to
Gemini. The same applies to `.../maven-status/maven-compiler-plugin/compile`
across modules (basename `compile`).
