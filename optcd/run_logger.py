"""Persistent, structured logging for one OptCD invocation.

Every git command, every `gh` call, and every Gemini prompt/response gets
recorded here -- both as a human-readable transcript (run.log) and as
machine-readable JSONL (run.jsonl), one line per event. This exists because
an OptCD run touches three different systems (local git, GitHub's API, an
LLM) across multiple real CI round-trips, and reconstructing "what actually
happened" after the fact from stdout alone is unreliable -- especially
across the several push/poll/analyze cycles the Fixer's verification loop
does.

Call `init(base_dir)` once at the start of a run (optcd/cli.py does this).
Every other module in this package calls the module-level `log_*` functions,
which are no-ops until `init` has been called.
"""
import json
import os
import sys
from datetime import datetime, timezone

_run_dir: str | None = None
_jsonl_path: str | None = None
_text_path: str | None = None


def init(base_dir: str = "run-history") -> str:
    """Creates a fresh timestamped run directory under `base_dir` and makes
    it the active logging target. Returns the directory path."""
    global _run_dir, _jsonl_path, _text_path
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(base_dir, timestamp)
    os.makedirs(run_dir, exist_ok=True)
    _run_dir = run_dir
    _jsonl_path = os.path.join(run_dir, "run.jsonl")
    _text_path = os.path.join(run_dir, "run.log")
    return run_dir


def active_dir() -> str | None:
    return _run_dir


def _write(category: str, **fields) -> None:
    if _run_dir is None:
        return
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "category": category, **fields}
    with open(_jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with open(_text_path, "a", encoding="utf-8") as f:
        f.write(_render_text(category, fields) + "\n")


def _render_text(category: str, fields: dict) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    if category == "git":
        return f"[{timestamp}] git {' '.join(fields['args'])} (cwd={fields.get('cwd')}) -> exit {fields['returncode']}\n  stdout: {fields.get('stdout', '').strip()}\n  stderr: {fields.get('stderr', '').strip()}"
    if category == "gh":
        return f"[{timestamp}] gh {' '.join(fields['args'])} -> exit {fields['returncode']}\n  stdout: {fields.get('stdout', '').strip()}\n  stderr: {fields.get('stderr', '').strip()}"
    if category == "http":
        return f"[{timestamp}] {fields.get('method', 'GET')} {fields['url']} -> {fields.get('status')} ({fields.get('bytes', 0)} bytes)"
    if category == "gemini":
        return f"[{timestamp}] Gemini prompt:\n{fields['prompt']}\n---\nGemini response:\n{fields['response']}\n==="
    if category == "step":
        return f"[{timestamp}] {fields.get('message', '')}"
    return f"[{timestamp}] {category}: {fields}"


def log_git(args: list[str], cwd: str | None, returncode: int, stdout: str, stderr: str) -> None:
    _write("git", args=args, cwd=cwd, returncode=returncode, stdout=stdout, stderr=stderr)


def log_gh(args: list[str], returncode: int, stdout: str, stderr: str) -> None:
    _write("gh", args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def log_http(method: str, url: str, status: int, byte_count: int) -> None:
    _write("http", method=method, url=url, status=status, bytes=byte_count)


def log_gemini(prompt: str, response: str) -> None:
    _write("gemini", prompt=prompt, response=response)


def log_step(message: str) -> None:
    _write("step", message=message)
    print(message)
    sys.stdout.flush()
