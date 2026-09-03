#!/bin/bash
# Compatibility wrapper. The real implementation now lives in optcd.py /
# the optcd/ package -- this just keeps the documented `./optcd.sh ...`
# invocation working.
#
# Usage: ./optcd.sh <input_yaml> <output_yaml> [owner] [repo] [output_file]

if [ "$#" -le 1 ]; then
  echo "Usage: optcd.sh <input_yaml_filename> <output_yaml_filename> [owner] [repo] [output_file]"
  exit 1
fi

pip install -r requirements.txt > /dev/null 2>&1

python optcd.py "$@"
