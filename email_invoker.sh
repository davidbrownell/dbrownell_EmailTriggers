#!/bin/bash

script_dir="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

cd "$script_dir" || exit 1
. ./.venv/bin/activate
python main.py --verbose