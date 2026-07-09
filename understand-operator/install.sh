#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILL_SRC="$REPO_ROOT/understand-operator-plugin/skills/understand-operator"
AGENTS_SRC="$REPO_ROOT/understand-operator-plugin/agents"
PLATFORM="${1:-opencode}"

case "$PLATFORM" in
  opencode|codex) TARGET="$HOME/.agents/skills" ;;
  cursor) TARGET="$HOME/.cursor/skills" ;;
  *) echo "Unknown platform: $PLATFORM"; exit 1 ;;
esac

SKILL_DEST="$TARGET/understand-operator"
mkdir -p "$TARGET"
rm -rf "$SKILL_DEST"
ln -s "$SKILL_SRC" "$SKILL_DEST"

if [ "$PLATFORM" = "cursor" ] && [ -d "$AGENTS_SRC" ]; then
  AGENTS_DEST="$HOME/.cursor/agents"
  mkdir -p "$AGENTS_DEST"
  rm -f "$AGENTS_DEST"/uo-*.md
  cp -f "$AGENTS_SRC"/uo-*.md "$AGENTS_DEST"/
  echo "Installed understand-operator subagents: $AGENTS_DEST/uo-*.md"
fi

echo "Installed understand-operator skill: $SKILL_DEST -> $SKILL_SRC"
echo "For Cursor: add the repository root as a local plugin, or rely on the installed ~/.cursor/agents links."
