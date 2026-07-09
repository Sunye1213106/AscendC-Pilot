#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILLS_ROOT="$REPO_ROOT/understand-operator-plugin/skills"
AGENTS_SRC="$REPO_ROOT/understand-operator-plugin/agents"
PLATFORM="${1:-opencode}"

SKILL_NAMES=(uo-init uo-query uo-update uo-diff understand-operator)

case "$PLATFORM" in
  opencode) TARGET="$HOME/.config/opencode/skills" ;;
  codex) TARGET="$HOME/.agents/skills" ;;
  cursor) TARGET="$HOME/.cursor/skills" ;;
  *) echo "Unknown platform: $PLATFORM"; exit 1 ;;
esac

mkdir -p "$TARGET"
for name in "${SKILL_NAMES[@]}"; do
  src="$SKILLS_ROOT/$name"
  dest="$TARGET/$name"
  if [ ! -d "$src" ]; then
    echo "Missing skill source: $src" >&2
    exit 1
  fi
  rm -rf "$dest"
  ln -s "$src" "$dest"
  echo "Installed skill: $dest -> $src"
done

if [ "$PLATFORM" = "cursor" ] && [ -d "$AGENTS_SRC" ]; then
  AGENTS_DEST="$HOME/.cursor/agents"
  mkdir -p "$AGENTS_DEST"
  rm -f "$AGENTS_DEST"/uo-*.md
  cp -f "$AGENTS_SRC"/uo-*.md "$AGENTS_DEST"/
  echo "Installed understand-operator subagents: $AGENTS_DEST/uo-*.md"
fi

echo "Commands: /uo-init  /uo-query  /uo-update  /uo-diff"
echo "For Cursor: add the repository root as a local plugin, or rely on the installed skill links."
