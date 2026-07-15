#!/usr/bin/env sh
set -eu

PLUGIN_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python "$PLUGIN_ROOT/skills/understand-operator/verify_required_scripts.py" --plugin-root "$PLUGIN_ROOT"
