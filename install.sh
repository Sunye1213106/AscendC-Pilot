# AscendC-Pilot unified installer
#
# Usage:
#   ./install.sh opencode|cursor|codex
#   ./install.sh uninstall-opencode|uninstall-cursor|uninstall-codex
#   SKIP_PIP=1 ./install.sh cursor
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:-opencode}"
SKIP_PIP="${SKIP_PIP:-0}"

plugin_dest() {
  case "$1" in
    opencode) echo "$HOME/.config/opencode/ascendc-pilot-plugin" ;;
    cursor) echo "$HOME/.cursor/ascendc-pilot-plugin" ;;
    codex) echo "$HOME/.agents/ascendc-pilot-plugin" ;;
    *) return 1 ;;
  esac
}

skills_dest() {
  case "$1" in
    opencode) echo "$HOME/.config/opencode/skills" ;;
    cursor) echo "$HOME/.cursor/skills" ;;
    codex) echo "$HOME/.agents/skills" ;;
  esac
}

agents_dest() {
  case "$1" in
    opencode) echo "$HOME/.config/opencode/agents" ;;
    cursor) echo "$HOME/.cursor/agents" ;;
    codex) echo "$HOME/.agents/agents" ;;
  esac
}

plugins_dest() {
  case "$1" in
    opencode) echo "$HOME/.config/opencode/plugins" ;;
    *) echo "" ;;
  esac
}

purge_legacy_ascendc_agent() {
  local plat="$1" skills="$2" agents="$3" plugins="$4"
  local name p
  for name in uo-code-review understand-operator uo-diff; do
    if [[ -e "$skills/$name" || -L "$skills/$name" ]]; then
      rm -rf "$skills/$name"
      echo "Removed legacy skill → $skills/$name"
    fi
  done
  for name in ascendc-agent uo-code-reviewer README; do
    if [[ -f "$agents/$name.md" || -L "$agents/$name.md" ]]; then
      rm -f "$agents/$name.md"
      echo "Removed legacy agent → $agents/$name.md"
    fi
  done
  if [[ "$plat" == "opencode" ]]; then
    rm -rf "$HOME/.config/opencode/ascendc-agent-plugin"
    if [[ -n "$plugins" ]]; then
      rm -f "$plugins/ascendc-harness.ts"
    fi
  fi
}

uninstall() {
  local plat="$1"
  local plug skills agents plugins
  plug="$(plugin_dest "$plat")"
  skills="$(skills_dest "$plat")"
  agents="$(agents_dest "$plat")"
  plugins="$(plugins_dest "$plat")"
  rm -rf "$plug"
  for name in uo-init uo-update uo-query ce-review tg-init tg-plan tg-solve operator _policies uo-code-review; do
    rm -rf "$skills/$name"
  done
  for name in ascendc-pilot ascendc-agent uo-semantic-resolve uo-key-resolve uo-confidence-review uo-kb-review ce-reviewer uo-query uo-code-reviewer tg-csv-contract tg-semantic-bind tg-init-audit deterministic-uo-engine deterministic-tg-engine README; do
    rm -f "$agents/$name.md"
  done
  if [[ "$plat" == "opencode" && -n "$plugins" ]]; then
    rm -f "$plugins/ascendc-pilot.ts" "$plugins/ascendc-harness.ts"
    rm -rf "$HOME/.config/opencode/ascendc-agent-plugin"
  fi
  echo "Uninstalled $plat ascendc-pilot plugin"
}

case "$PLATFORM" in
  uninstall-opencode) uninstall opencode; exit 0 ;;
  uninstall-cursor) uninstall cursor; exit 0 ;;
  uninstall-codex) uninstall codex; exit 0 ;;
  opencode|cursor|codex) ;;
  *)
    echo "Usage: $0 opencode|cursor|codex|uninstall-*" >&2
    exit 2
    ;;
esac

if [[ "$SKIP_PIP" != "1" ]]; then
  python -m pip install -e "$BUNDLE_ROOT/pilot" -e "$BUNDLE_ROOT/engines/understand-operator" -e "$BUNDLE_ROOT/engines/testcase-generation[solver]"
fi

python "$BUNDLE_ROOT/scripts/compose_runtime.py" --repo "$BUNDLE_ROOT" --host "$PLATFORM"

DEST="$(plugin_dest "$PLATFORM")"
SKILLS="$(skills_dest "$PLATFORM")"
AGENTS="$(agents_dest "$PLATFORM")"
mkdir -p "$DEST" "$SKILLS" "$AGENTS"
rm -rf "$DEST"
mkdir -p "$DEST"

for name in skills prompts agents docs engines acp templates scripts opencode-plugin; do
  if [[ -d "$BUNDLE_ROOT/$name" ]]; then
    cp -R "$BUNDLE_ROOT/$name" "$DEST/"
  fi
done

GEN="$BUNDLE_ROOT/generated/$PLATFORM"
# Remove source-bundled trees first — otherwise cp -R nests as dest/skills/skills
# when dest/skills already exists, and skill junctions silently skip.
for name in skills agents prompts; do
  rm -rf "$DEST/$name"
done
cp -R "$GEN/skills" "$DEST/skills"
cp -R "$GEN/agents" "$DEST/agents"
if [[ -d "$GEN/prompts" ]]; then
  cp -R "$GEN/prompts" "$DEST/prompts"
fi

# Purge pre-pilot leftovers (wrong Tab agents / free-form LLM KB skills).
purge_legacy_ascendc_agent "$PLATFORM" "$SKILLS" "$AGENTS" "$(plugins_dest "$PLATFORM")"

for name in uo-init uo-update uo-query ce-review tg-init tg-plan tg-solve operator; do
  [[ -d "$DEST/skills/$name" ]] || continue
  rm -rf "$SKILLS/$name"
  ln -sfn "$DEST/skills/$name" "$SKILLS/$name" 2>/dev/null || cp -R "$DEST/skills/$name" "$SKILLS/$name"
done

# OpenCode treats every .md under agents/ as a Tab entry — never install README.md.
for f in "$DEST/agents"/*.md; do
  [[ -f "$f" ]] || continue
  base="$(basename "$f")"
  [[ "$base" == "README.md" ]] && continue
  ln -sfn "$f" "$AGENTS/$base" 2>/dev/null || cp "$f" "$AGENTS/$base"
done

if [[ "$PLATFORM" == "opencode" ]]; then
  PLUGINS="$(plugins_dest opencode)"
  mkdir -p "$PLUGINS"
  if [[ -f "$BUNDLE_ROOT/opencode-plugin/ascendc-pilot.ts" ]]; then
    cp "$BUNDLE_ROOT/opencode-plugin/ascendc-pilot.ts" "$PLUGINS/ascendc-pilot.ts"
    echo "Installed plugin → $PLUGINS/ascendc-pilot.ts"
  fi
  echo "Primary agent → $AGENTS/ascendc-pilot.md (Tab switch; opencode.json untouched)"
fi

mkdir -p "$DEST/templates/$PLATFORM"
echo "plugin_root=$DEST" > "$DEST/templates/$PLATFORM/install_stamp.txt"
echo "Installed AscendC-Pilot → $DEST"
echo "Run: acp doctor"
