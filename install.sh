#!/usr/bin/env bash
# Install both understand-operator and testcase-agent.
#
# Usage:
#   ./install.sh opencode
#   SKIP_PIP=1 ./install.sh cursor
#   ./install.sh uninstall-opencode
#   ONLY=understand-operator ./install.sh opencode
#   ONLY=testcase-agent ./install.sh opencode
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
UO_ROOT="$BUNDLE_ROOT/understand-operator"
TG_ROOT="$BUNDLE_ROOT/testcase-agent"
PLATFORM="${1:-opencode}"
ONLY="${ONLY:-all}"
SKIP_PIP="${SKIP_PIP:-0}"

if [[ ! -f "$UO_ROOT/install.sh" ]]; then
  echo "Missing understand-operator installer: $UO_ROOT/install.sh" >&2
  exit 1
fi
if [[ ! -f "$TG_ROOT/install.sh" ]]; then
  echo "Missing testcase-agent installer: $TG_ROOT/install.sh" >&2
  exit 1
fi

case "$ONLY" in
  all|understand-operator|testcase-agent) ;;
  *)
    echo "Unknown ONLY=$ONLY (expected: all|understand-operator|testcase-agent)" >&2
    exit 1
    ;;
esac

is_uninstall=0
case "$PLATFORM" in
  uninstall-opencode|uninstall-codex|uninstall-cursor) is_uninstall=1 ;;
  opencode|codex|cursor) ;;
  *)
    echo "Unknown platform: $PLATFORM" >&2
    echo "Supported: opencode|codex|cursor|uninstall-opencode|uninstall-codex|uninstall-cursor" >&2
    exit 1
    ;;
esac

run_agent() {
  local name="$1"
  local root="$2"
  echo ""
  echo "======== $name ========"
  if [[ "$name" == "testcase-agent" && "$SKIP_PIP" == "1" && "$is_uninstall" -eq 0 ]]; then
    SKIP_PIP=1 bash "$root/install.sh" "$PLATFORM"
  else
    bash "$root/install.sh" "$PLATFORM"
  fi
}

echo "Ascendc PR agents bundle install"
echo "  Bundle:   $BUNDLE_ROOT"
echo "  Platform: $PLATFORM"
echo "  Mode:     $([[ $is_uninstall -eq 1 ]] && echo uninstall || echo install)"
echo "  Agents:   $ONLY"

if [[ "$ONLY" == "all" || "$ONLY" == "understand-operator" ]]; then
  run_agent "understand-operator" "$UO_ROOT"
fi
if [[ "$ONLY" == "all" || "$ONLY" == "testcase-agent" ]]; then
  run_agent "testcase-agent" "$TG_ROOT"
fi

echo ""
echo "======== Done ========"
if [[ $is_uninstall -eq 1 ]]; then
  echo "Uninstalled: $ONLY ($PLATFORM)"
else
  echo "Installed: $ONLY ($PLATFORM)"
  echo "UO commands: /uo-init  /uo-query  /uo-update  /uo-diff"
  echo "TG commands: /tg-contract  /tg-plan  /tg-solve"
  if [[ "$PLATFORM" == "opencode" ]]; then
    echo 'OpenCode: ensure opencode.json has "permission": { "question": "allow" }'
  fi
fi
