# Legacy implementation

This is the original OptCD implementation: a chain of `optcd.sh` ->
`utils.sh` -> `find_plugins.py` -> `utils.sh` (again) ->
`fixer/run_gemini_with_confirmation.py`, passing state between shell and
Python via files, env vars, and positional CLI arguments.

Its logic has been reimplemented as a single Python flow in the `optcd/`
package (see `optcd.py` / `optcd/cli.py` at the repo root). Nothing here is
dead weight to be deleted casually -- it's kept as a reference for exactly
what the original tool did, including two bugs found and fixed during a
Windows run (a missing `rev` dependency in the owner/repo parsing, and a
`UnicodeEncodeError` when writing the Unicode report table) and one race
condition in `cancel_runs` (it could cancel the *wrong* GitHub Actions run
because it wasn't scoped to the run's own head commit).

- `utils.sh` -- push the modified workflow, poll for the run, download
  artifacts, fetch job logs, call `find_plugins.py` per job.
- `find_plugins.py` -- classifier -> clusterer -> mapper glue for one job.
- `modify_yaml.py` -- CLI wrapper around `logger/utils.py`'s YAML
  instrumentation.
- `fixer/run_gemini_with_confirmation.py` -- the Gemini-driven fix/verify
  loop, re-invoking `utils.sh` as a subprocess to re-run the build after each
  patch.
