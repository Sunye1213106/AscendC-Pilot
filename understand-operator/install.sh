#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$REPO_ROOT/understand-operator-plugin"
SKILLS_ROOT="$PLUGIN_ROOT/skills"
AGENTS_SRC="$PLUGIN_ROOT/agents"
PLATFORM="${1:-opencode}"

SKILL_NAMES=(uo-init uo-query uo-update uo-diff understand-operator)

case "$PLATFORM" in
  opencode) TARGET="$HOME/.config/opencode/skills" ;;
  codex) TARGET="$HOME/.agents/skills" ;;
  cursor) TARGET="$HOME/.cursor/skills" ;;
  *) echo "Unknown platform: $PLATFORM"; exit 1 ;;
esac

PLUGIN_LINK="$(dirname "$TARGET")/understand-operator-plugin"

mkdir -p "$TARGET"
for name in "${SKILL_NAMES[@]}"; do
  src="$SKILLS_ROOT/$name"
  dest="$TARGET/$name"
  if [ ! -d "$src" ]; then
    echo "Missing skill source: $src" >&2
    exit 1
  fi
  rm -rf "$dest"
  if [ -e "$dest" ]; then
    echo "Cleanup failed: $dest still exists" >&2
    exit 1
  fi
  ln -s "$src" "$dest"
  echo "Installed skill: $dest -> $src"
done

if [ -d "$PLUGIN_ROOT" ]; then
  rm -rf "$PLUGIN_LINK"
  if [ -e "$PLUGIN_LINK" ]; then
    echo "Cleanup failed: $PLUGIN_LINK still exists" >&2
    exit 1
  fi
  ln -s "$PLUGIN_ROOT" "$PLUGIN_LINK"
  echo "Installed plugin: $PLUGIN_LINK -> $PLUGIN_ROOT"
fi

if [ "$PLATFORM" = "cursor" ] && [ -d "$AGENTS_SRC" ]; then
  AGENTS_DEST="$HOME/.cursor/agents"
  mkdir -p "$AGENTS_DEST"
  rm -f "$AGENTS_DEST"/uo-*.md
  cp -f "$AGENTS_SRC"/uo-*.md "$AGENTS_DEST"/
  echo "Installed understand-operator subagents: $AGENTS_DEST/uo-*.md"
fi

echo "Commands: /uo-init  /uo-query  /uo-update  /uo-diff"
echo "For Cursor: add the repository root as a local plugin, or rely on the installed skill links."
