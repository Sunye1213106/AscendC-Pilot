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

uninstall() {
  local plat="$1"
  local plug skills agents
  plug="$(plugin_dest "$plat")"
  skills="$(skills_dest "$plat")"
  agents="$(agents_dest "$plat")"
  rm -rf "$plug"
  for name in uo-init uo-update uo-query uo-code-review uo-diff tg-init tg-plan tg-solve understand-operator; do
    rm -rf "$skills/$name"
  done
  for name in uo-semantic-resolve uo-key-resolve uo-confidence-review uo-kb-review uo-code-reviewer tg-csv-contract tg-init-audit; do
    rm -f "$agents/$name.md"
  done
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

DEST="$(plugin_dest "$PLATFORM")"
SKILLS="$(skills_dest "$PLATFORM")"
AGENTS="$(agents_dest "$PLATFORM")"
mkdir -p "$DEST" "$SKILLS" "$AGENTS"

rsync -a --delete \
  --exclude '.pytest_cache' --exclude '__pycache__' --exclude '*.egg-info' \
  "$BUNDLE_ROOT/skills" "$BUNDLE_ROOT/prompts" "$BUNDLE_ROOT/agents" "$BUNDLE_ROOT/docs" \
  "$BUNDLE_ROOT/engines" "$BUNDLE_ROOT/harness" "$BUNDLE_ROOT/templates" \
  "$DEST/" 2>/dev/null || {
  # Fallback without rsync
  rm -rf "$DEST"
  mkdir -p "$DEST"
  cp -R "$BUNDLE_ROOT/skills" "$BUNDLE_ROOT/prompts" "$BUNDLE_ROOT/agents" "$BUNDLE_ROOT/docs" \
    "$BUNDLE_ROOT/engines" "$BUNDLE_ROOT/harness" "$BUNDLE_ROOT/templates" "$DEST/"
}

# Symlink/copy user skills
for name in uo-init uo-update uo-query uo-code-review tg-init tg-plan tg-solve; do
  rm -rf "$SKILLS/$name"
  ln -sfn "$DEST/skills/$name" "$SKILLS/$name" 2>/dev/null || cp -R "$DEST/skills/$name" "$SKILLS/$name"
done

# Agents
for f in "$DEST/agents"/*.md; do
  base="$(basename "$f")"
  case "$base" in
    tg-domain-review.md) continue ;;
  esac
  ln -sfn "$f" "$AGENTS/$base" 2>/dev/null || cp "$f" "$AGENTS/$base"
done

# Host template stamp
mkdir -p "$DEST/templates/$PLATFORM"
echo "plugin_root=$DEST" > "$DEST/templates/$PLATFORM/install_stamp.txt"
echo "Installed AscendC Agent Harness → $DEST"
echo "Run: harness doctor"
