import os
import posixpath
import time
import warnings
from typing import Callable

import google.generativeai as genai
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import PlainScalarString

from optcd import run_logger

warnings.filterwarnings("ignore")

PROMPT_TEMPLATE = (
    "The command `{command}` creates the following unused directory:"
    "{unused_dir}\n"
    "while running the plugin `{plugin}`:\n"
    "We can skip creating any files that are being created in this directory by updating the command. "
    "The fix normally include skipping the execution of the plugin responsible.\n"
    "Please suggest an updated command to avoid creating this unnecessary directory. Note that your command "
    "should not stop the test runs. For example, using -DskipTests would prevent Maven tests from running, "
    "which is not acceptable. Therefore, your solution should not include such options.\n"
    "A valid fix would disable the generation of the unused directory without affecting the test runs. "
    "For example `-DdisableXmlReport=true` would disable generation of surefire reports directory without "
    "affecting test runs and is considered a valid fix if unused directory is surefire-reports.\n"
    "Provide only the new command without additional explanation, code formatting, or backticks."
)


class GeminiAPI:
    def __init__(self):
        api_key = os.environ["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-3.6-flash")

    def ask_prompt(self, prompt: str) -> str:
        response = self.model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.0),
        )
        text = "".join(part.text for part in response.parts)
        result = text.replace("```", "").replace("\n", "")
        run_logger.log_gemini(prompt, result)
        return result


def extract_unique_commands(responsible_plugins_maven: list[dict]) -> dict:
    unique_commands: dict = {}
    for instance in responsible_plugins_maven:
        command = instance["Responsible command"]
        unused_dir = instance["Unused directory"]
        plugin = instance["Responsible plugin"]

        entry = unique_commands.setdefault(command, {
            "command": command, "unused_dirs": [], "responsible_plugin": [], "fixes": [],
        })
        if unused_dir not in entry["unused_dirs"]:
            entry["unused_dirs"].append(unused_dir)
        if plugin not in entry["responsible_plugin"]:
            entry["responsible_plugin"].append(plugin)
    return unique_commands


def update_mvn_command_in_workflow(workflow_path: str, old_command: str, new_command: str) -> None:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    new_command = new_command.strip()

    with open(workflow_path, "r") as f:
        yml_data = yaml.load(f)

    for job in yml_data.get("jobs", {}).values():
        for step in job.get("steps", []) or []:
            if isinstance(step, dict) and step.get("run", "").strip() == old_command.strip():
                step["run"] = PlainScalarString(new_command)

    with open(workflow_path, "w") as f:
        yaml.dump(yml_data, f)


def run_fixer(
    responsible_plugins_maven: list[dict],
    modified_workflow_path: str,
    rerun_and_analyze: Callable[[], list[dict]],
    initial_output_file: str,
) -> None:
    """For each distinct Maven command responsible for unused directories:
    ask Gemini for a fix, apply it to the workflow file, re-run the build via
    `rerun_and_analyze`, and record which unused directories disappeared.
    """
    gemini = GeminiAPI()
    unique_commands = extract_unique_commands(responsible_plugins_maven)

    for original_command, info in unique_commands.items():
        unused_dirs = info["unused_dirs"]
        fixes = info["fixes"]
        fix_args: set[str] = set()
        fixed_dir_basenames: set[str] = set()

        for unused_dir in unused_dirs:
            normalized = posixpath.normpath(unused_dir)
            if posixpath.basename(normalized) in fixed_dir_basenames:
                continue

            plugin = next(
                (item["Responsible plugin"] for item in responsible_plugins_maven
                 if posixpath.normpath(item["Unused directory"]) == normalized),
                None,
            )
            if not plugin:
                run_logger.log_step(f"No responsible plugin found for unused directory: {unused_dir}")
                continue

            prompt = PROMPT_TEMPLATE.format(command=original_command, unused_dir=unused_dir, plugin=plugin)
            fix_suggestion = gemini.ask_prompt(prompt)
            run_logger.log_step(f"Fix suggestion for the command '{original_command}' is:\n{fix_suggestion}")
            time.sleep(12)  # avoid rate limiting

            fixed_dir_basenames.add(posixpath.basename(normalized))

            if not fix_suggestion or fix_suggestion == original_command:
                with open(initial_output_file, "a", encoding="utf-8") as f:
                    f.write(f"[FIXER ERROR] There is no fix suggestion found for the unused directory: {unused_dir}\n")
                continue

            new_args = [x for x in fix_suggestion.split() if x not in original_command.split()]
            fixes.extend(new_args)
            fix_args.update(new_args)

        fixed_command = original_command + " " + " ".join(sorted(fix_args))
        run_logger.log_step(f"Fix suggestion for the command '{original_command}' is: '{fixed_command}'")

        update_mvn_command_in_workflow(modified_workflow_path, original_command, fixed_command)

        old_unused = {
            posixpath.normpath(item["Unused directory"]).rstrip("/")
            for item in responsible_plugins_maven
            if item["Responsible command"] == original_command
        }

        new_responsible_plugins_maven = rerun_and_analyze()
        new_unused = {
            posixpath.normpath(item["Unused directory"]).rstrip("/")
            for item in new_responsible_plugins_maven
        }

        fixed_dirs = [d for d in (old_unused - new_unused) if "maven-status" not in d]

        with open(initial_output_file, "a", encoding="utf-8") as f:
            f.write(f"Command: {original_command}\n")
            f.write(f"Fixes: {fixes}\n")
            f.write("following directories are fixed:\n")
            for d in fixed_dirs:
                f.write(f"{d}\n")
            f.write("-" * 10 + "\n")
            f.write(f"fixed command: {fixed_command}\n")
            f.write("-" * 10 + "\n\n")
