---
title: How it works
---

[← Back to overview](index.md)

# How it works

## The problem, in one sentence

Every time your project builds on GitHub Actions, plugins can leave behind
files nobody ever reads again — and generating those files still costs real
time and disk space on every single build.

## A concrete example

Say your Maven build runs:

```
mvn -X verify -B --file pom.xml
```

Two plugins configured in your `pom.xml` fire during that command:

- `surefire` writes test results into `target/surefire-reports/` as XML.
- `japicmp` compares your API against a previous release and writes a report into `target/japicmp/`.

If nothing later in the build reads either folder — no step uploads them, no
later plugin consumes them — then every single CI run pays the cost of
generating files that go straight into the trash when the runner is torn
down. That's the waste OptCD targets.

## The five-step mechanism

```
 1. LOGGER        instrument the workflow to watch every file event
        |
 2. CLASSIFIER    created-but-never-opened  =>  "unused file"
        |
 3. CLUSTERER     group unused files into whole unused directories
        |
 4. MAPPER        trace each directory back to the plugin + command that made it
        |
 5. FIXER         ask an LLM for a command flag that disables that plugin's
                   output, apply it, and verify the directory stops appearing
```

### 1. Logger

Before the real build runs, OptCD inserts a Python step at the start of every
job that uses the [`inotify`](https://pypi.org/project/inotify/) Linux kernel
feature to watch the entire working directory for two kinds of events:
`IN_CREATE` (a file was made) and `IN_ACCESS` (a file was opened/read). Every
event is appended to a CSV log, uploaded as a build artifact at the end of
the job.

This step only runs *on GitHub's own Linux runner*, in the cloud — never on
your machine. See [`logger/utils.py`](../logger/utils.py), function
`modify_file_content`.

### 2. Classifier

Once the build finishes, OptCD downloads that CSV and replays it:

| Created? | Modified? | Accessed after creation? | Verdict |
|---|---|---|---|
| ✅ | either | ✅ | **used** |
| ✅ | either | ❌ | **unused** |

A file that's created and later opened (even just to read it) is "used." A
file that's created and never touched again is "unused." See
[`classifier/utils.py`](../classifier/utils.py), function `classify_files`.

### 3. Clusterer

Individual unused *files* aren't that actionable — a build can produce
hundreds of them under one report folder. The Clusterer walks up from each
unused file to find the shallowest directory where **every** file underneath
is unused (and no used file lives there too). That whole directory becomes
one "unused directory" finding. See
[`clusterer/utils.py`](../clusterer/utils.py), function `cluster_files`.

### 4. Mapper

For each unused directory, OptCD needs to know *which Maven plugin* created
it and *which command* ran that plugin. It does this by comparing timestamps:
the build log records exactly when each Maven plugin execution started
(`[INFO] --- pluginname:version:goal ...`), and the Classifier already
recorded when the unused directory's first file was created. Whichever
plugin was executing at that moment is the culprit. See
[`mapper/utils.py`](../mapper/utils.py), function `get_responsible_plugins`.

### 5. Fixer

For each distinct Maven command responsible for at least one unused
directory, OptCD asks Google's Gemini model for a command-line flag that
would stop that specific plugin from generating output — explicitly
instructing it not to suggest anything that would skip tests. It applies the
suggested flag to the workflow file, re-runs the build, and checks whether
the unused directory actually disappeared. Only confirmed fixes are kept.

## Why this can only run against real GitHub Actions

OptCD doesn't simulate a build locally — it pushes an instrumented copy of
your workflow file to your actual repository and watches a real GitHub
Actions run happen in the cloud. That's the only place `inotify` needs to
work (a genuine Linux VM), which is why the orchestration script itself can
run from Windows, macOS, or Linux — see [Running it](running-it.md).
