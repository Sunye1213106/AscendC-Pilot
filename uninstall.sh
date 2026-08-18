#!/usr/bin/env bash
# AscendC-Pilot uninstaller
#
# Usage:
#   ./uninstall.sh                 # OpenCode (default)
#   ./uninstall.sh opencode|cursor|codex
#
# Deletes only files listed in the installed install-manifest.json (or the
# explicit builtin fallback). Never globs tg-* / uo-* / ce-* in the user's
# ~/.config/opencode/agents.
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:-opencode}"
PLATFORM="${PLATFORM#uninstall-}"

case "$PLATFORM" in
  opencode|cursor|codex) ;;
  *)
    echo "Usage: $0 opencode|cursor|codex" >&2
    exit 2
    ;;
esac

resolve_python() {
  if [[ -n "${PYTHON:-}" ]] && command -v "$PYTHON" >/dev/null 2>&1; then
    command -v "$PYTHON"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  echo "ERROR: python3 or python >= 3.10 required" >&2
  exit 1
}

PYTHON="$(resolve_python)"

opencode_home() {
  echo "${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
}

plugin_dest() {
  case "$1" in
    opencode) echo "$(opencode_home)/ascendc-pilot-plugin" ;;
    cursor) echo "$HOME/.cursor/ascendc-pilot-plugin" ;;
    codex) echo "$HOME/.agents/ascendc-pilot-plugin" ;;
    *) return 1 ;;
  esac
}

skills_dest() {
  case "$1" in
    opencode) echo "$(opencode_home)/skills" ;;
    cursor) echo "$HOME/.cursor/skills" ;;
    codex) echo "$HOME/.agents/skills" ;;
  esac
}

agents_dest() {
  case "$1" in
    opencode) echo "$(opencode_home)/agents" ;;
    cursor) echo "$HOME/.cursor/agents" ;;
    codex) echo "$HOME/.agents/agents" ;;
  esac
}

commands_dest() {
  case "$1" in
    opencode) echo "$(opencode_home)/commands" ;;
    *) echo "" ;;
  esac
}

plugins_dest() {
  case "$1" in
    opencode) echo "$(opencode_home)/plugins" ;;
    *) echo "" ;;
  esac
}

WORKFLOW_SKILLS=(
  uo-init uo-update uo-query uo-investigate
  ce-review ce-plan ce-apply handoff
  tg-init tg-plan tg-solve
)
COGNITIVE_SKILLS=(operator-analysis testcase-generation source-proof code-review code-engineering)
OPENCODE_COMMANDS=(
  uo-init uo-update uo-query uo-investigate
  ce-review ce-plan ce-apply handoff
  tg-init tg-plan tg-solve
)
CURRENT_AGENTS=(
  ascendc-pilot uo-query uo-heal-analyst uo-gap-investigator ce-reviewer tg-analyst
  ce-applier ce-analyst
)
LEGACY_SKILLS=(uo-code-review understand-operator uo-diff _policies ce-intent ce-impact ce-verify ce-handoff operator)
LEGACY_AGENTS=(
  ascendc-agent uo-semantic-resolve uo-semantic-resolver uo-gap-resolve
  uo-key-resolve uo-confidence-review uo-kb-review uo-code-reviewer
  tg-csv-contract tg-semantic-bind tg-init-audit tg-lemma-producer
  tg-closure-referee deterministic-uo-engine deterministic-tg-engine
  deterministic-ce-engine ce-change-referee README
)
LEGACY_PLUGINS=(ascendc-pilot.ts zz-uo-query-return-value.ts uo-query-return-value.ts ascendc-harness.ts pilot-driver.ts)

DEST="$(plugin_dest "$PLATFORM")"
SKILLS="$(skills_dest "$PLATFORM")"
AGENTS="$(agents_dest "$PLATFORM")"
PLUGINS="$(plugins_dest "$PLATFORM")"
COMMANDS="$(commands_dest "$PLATFORM")"
MAN="${DEST}/install-manifest.json"
if [[ ! -f "$MAN" && -f "$BUNDLE_ROOT/generated/${PLATFORM}/install-manifest.json" ]]; then
  MAN="$BUNDLE_ROOT/generated/${PLATFORM}/install-manifest.json"
fi

mapfile_from_manifest() {
  local field="$1"
  if [[ -f "$MAN" ]]; then
    "$PYTHON" - "$MAN" "$field" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
field = sys.argv[2]
if field.startswith("legacy."):
    data = data.get("legacy") or {}
    field = field.split(".", 1)[1]
vals = data.get(field) or []
if not isinstance(vals, list):
    vals = [vals]
for v in vals:
    s = str(v or "").strip()
    if s:
        print(Path(s).name)
PY
  fi
}

echo "Uninstalling AscendC-Pilot ($PLATFORM) from owned manifest only"

if [[ -f "$MAN" ]]; then
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    rm -rf "$SKILLS/$name"
  done < <(mapfile_from_manifest skills; mapfile_from_manifest cognitive_skills; mapfile_from_manifest legacy.skills; echo _shared)
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    [[ "$name" == *.md ]] || name="${name}.md"
    rm -f "$AGENTS/$name"
  done < <(mapfile_from_manifest agents; mapfile_from_manifest global_agents; mapfile_from_manifest legacy.agents)
  if [[ "$PLATFORM" == "opencode" ]]; then
    if [[ -n "$COMMANDS" ]]; then
      while IFS= read -r name; do
        [[ -n "$name" ]] || continue
        [[ "$name" == *.md ]] || name="${name}.md"
        rm -f "$COMMANDS/$name"
      done < <(mapfile_from_manifest commands)
    fi
    if [[ -n "$PLUGINS" ]]; then
      while IFS= read -r name; do
        [[ -n "$name" ]] || continue
        rm -f "$PLUGINS/$name"
      done < <(mapfile_from_manifest plugins; mapfile_from_manifest legacy.plugins)
    fi
    while IFS= read -r name; do
      [[ -n "$name" ]] || continue
      rm -rf "$(opencode_home)/$name"
    done < <(mapfile_from_manifest legacy.plugin_trees)
  fi
else
  for name in "${WORKFLOW_SKILLS[@]}" "${LEGACY_SKILLS[@]}" "${COGNITIVE_SKILLS[@]}" _shared; do
    rm -rf "$SKILLS/$name"
  done
  for name in "${CURRENT_AGENTS[@]}" "${LEGACY_AGENTS[@]}"; do
    rm -f "$AGENTS/$name.md"
  done
  if [[ "$PLATFORM" == "opencode" ]]; then
    if [[ -n "$COMMANDS" ]]; then
      for name in "${OPENCODE_COMMANDS[@]}"; do
        rm -f "$COMMANDS/$name.md"
      done
    fi
    if [[ -n "$PLUGINS" ]]; then
      for name in "${LEGACY_PLUGINS[@]}"; do
        rm -f "$PLUGINS/$name"
      done
    fi
    rm -rf "$(opencode_home)/ascendc-agent-plugin"
  fi
fi

rm -rf "$DEST"
echo "Uninstalled $PLATFORM"
