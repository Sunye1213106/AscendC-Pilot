# AscendC Agent unified installer
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
    opencode) echo "$HOME/.config/opencode/ascendc-agent-plugin" ;;
    cursor) echo "$HOME/.cursor/ascendc-agent-plugin" ;;
    codex) echo "$HOME/.agents/ascendc-agent-plugin" ;;
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

uninstall() {
  local plat="$1"
  local plug skills agents plugins
  plug="$(plugin_dest "$plat")"
  skills="$(skills_dest "$plat")"
  agents="$(agents_dest "$plat")"
  plugins="$(plugins_dest "$plat")"
  rm -rf "$plug"
  for name in uo-init uo-update uo-query uo-code-review tg-init tg-plan tg-solve operator _policies; do
    rm -rf "$skills/$name"
  done
  for name in ascendc-agent uo-semantic-resolve uo-key-resolve uo-confidence-review uo-kb-review uo-code-reviewer uo-query tg-csv-contract tg-semantic-bind tg-init-audit deterministic-uo-engine deterministic-tg-engine; do
    rm -f "$agents/$name.md"
  done
  if [[ "$plat" == "opencode" && -n "$plugins" ]]; then
    rm -f "$plugins/ascendc-harness.ts"
  fi
  echo "Uninstalled $plat ascendc-agent plugin"
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
  python -m pip install -e "$BUNDLE_ROOT/harness" -e "$BUNDLE_ROOT/engines/uo" -e "$BUNDLE_ROOT/engines/tg[solver]"
fi

python "$BUNDLE_ROOT/scripts/compose_runtime.py" --repo "$BUNDLE_ROOT" --host "$PLATFORM"

DEST="$(plugin_dest "$PLATFORM")"
SKILLS="$(skills_dest "$PLATFORM")"
AGENTS="$(agents_dest "$PLATFORM")"
mkdir -p "$DEST" "$SKILLS" "$AGENTS"
rm -rf "$DEST"
mkdir -p "$DEST"

for name in skills-src prompts-src agents-src docs engines harness templates scripts opencode-plugin; do
  if [[ -d "$BUNDLE_ROOT/$name" ]]; then
    cp -R "$BUNDLE_ROOT/$name" "$DEST/"
  fi
done

GEN="$BUNDLE_ROOT/generated/$PLATFORM"
cp -R "$GEN/skills" "$DEST/skills"
cp -R "$GEN/agents" "$DEST/agents"
if [[ -d "$GEN/prompts" ]]; then
  cp -R "$GEN/prompts" "$DEST/prompts"
fi

# Purge pre-harness legacy skills (free-form LLM KB builds; not Tab→ascendc-agent).
for legacy in understand-operator uo-diff; do
  if [[ -e "$SKILLS/$legacy" || -L "$SKILLS/$legacy" ]]; then
    rm -rf "$SKILLS/$legacy"
    echo "Removed legacy skill → $SKILLS/$legacy"
  fi
done

for name in uo-init uo-update uo-query uo-code-review tg-init tg-plan tg-solve operator; do
  [[ -d "$DEST/skills/$name" ]] || continue
  rm -rf "$SKILLS/$name"
  ln -sfn "$DEST/skills/$name" "$SKILLS/$name" 2>/dev/null || cp -R "$DEST/skills/$name" "$SKILLS/$name"
done

for f in "$DEST/agents"/*.md; do
  [[ -f "$f" ]] || continue
  base="$(basename "$f")"
  ln -sfn "$f" "$AGENTS/$base" 2>/dev/null || cp "$f" "$AGENTS/$base"
done

if [[ "$PLATFORM" == "opencode" ]]; then
  PLUGINS="$(plugins_dest opencode)"
  mkdir -p "$PLUGINS"
  if [[ -f "$BUNDLE_ROOT/opencode-plugin/ascendc-harness.ts" ]]; then
    cp "$BUNDLE_ROOT/opencode-plugin/ascendc-harness.ts" "$PLUGINS/ascendc-harness.ts"
    echo "Installed plugin → $PLUGINS/ascendc-harness.ts"
  fi
  echo "Primary agent → $AGENTS/ascendc-agent.md (Tab switch; opencode.json untouched)"
fi

mkdir -p "$DEST/templates/$PLATFORM"
echo "plugin_root=$DEST" > "$DEST/templates/$PLATFORM/install_stamp.txt"
echo "Installed AscendC Agent Harness → $DEST"
echo "Run: harness doctor"
