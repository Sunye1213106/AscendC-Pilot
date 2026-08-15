#!/usr/bin/env bash
# Fast path: Aliyun PyPI + PYTHONPATH. Prefer venv; fallback to system python.
set -euo pipefail

REPO="/mnt/d/TEST/AscendC-Pilot"
OP="/mnt/d/TEST/ops-transformer/attention/flash_attention_score_grad"
ARCH="arch35"
LOG="$REPO/_uo_init_full_run.log"
VENV="${HOME}/.cache/ascendc-pilot-venv"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-mirrors.aliyun.com}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
export PIP_ROOT_USER_ACTION=ignore

exec > >(tee "$LOG") 2>&1

echo "===== $(date -Iseconds) uo-init FAST run ====="
echo "REPO=$REPO OP=$OP"
echo "PIP_INDEX_URL=$PIP_INDEX_URL"

cd "$REPO"

echo
echo "===== 1) Clear products ====="
rm -rf \
  "$REPO/.ascendc-pilot" \
  "$REPO/.probe_cache" \
  "$OP/.ascendc-pilot" \
  "$OP/.probe_cache" \
  "$REPO/engines/testcase-generation/.ascendc-pilot" \
  "$REPO/engines/understand-operator/.ascendc-pilot" \
  2>/dev/null || true
echo "cleared"

echo
echo "===== 2) Python env ====="
PY=python3
if [[ -x "$VENV/bin/python" ]]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  PY=python
elif python3 -m venv "$VENV" 2>/tmp/venv.err; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  PY=python
else
  echo "venv unavailable; using system python3"
  cat /tmp/venv.err || true
fi

$PY -V
$PY -m pip install -U pip setuptools wheel

echo "check imports before install:"
$PY "$REPO/_check_env.py" || true

if ! $PY -c "import yaml"; then
  echo "install PyYAML/jsonschema via Aliyun..."
  $PY -m pip install "PyYAML>=6.0" "jsonschema>=4.0"
fi
if ! $PY -c "import clang.cindex"; then
  echo "install libclang via Aliyun..."
  $PY -m pip install libclang || true
fi

export PYTHONPATH="$REPO/engines/understand-operator/src:$REPO/engines/common:$REPO/pilot:${PYTHONPATH:-}"
echo "check imports after setup:"
$PY "$REPO/_check_env.py"

echo
echo "===== 3) Drive uo-init stages ====="
$PY "$REPO/engines/understand-operator/tools/experiments/drive_uo_init.py"

echo "===== finished $(date -Iseconds) ====="
