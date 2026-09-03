#!/usr/bin/env python3
"""Single entrypoint for OptCD.

Usage:
    python optcd.py <input_yaml> <output_yaml> [owner] [repo] [output_file]

This replaces the old optcd.sh -> utils.sh -> find_plugins.py -> utils.sh ->
fixer/run_gemini_with_confirmation.py chain with one coherent flow in the
optcd/ package. See optcd/cli.py for the implementation.
"""
import sys

from optcd.cli import main

if __name__ == "__main__":
    sys.exit(main())
