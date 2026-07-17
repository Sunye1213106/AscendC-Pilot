#!/usr/bin/env bash
set -euo pipefail

# Repo root IS the plugin root.
PLUGIN_ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILLS_ROOT="$PLUGIN_ROOT/skills"
PLATFORM="${1:-opencode}"
SKIP_PIP="${SKIP_PIP:-0}"

SKILL_NAMES=(tg-plan tg-solve tg-init)

case "$PLATFORM" in
  opencode) TARGET="$HOME/.config/opencode/skills" ;;
  codex) TARGET="$HOME/.agents/skills" ;;
  cursor) TARGET="$HOME/.cursor/skills" ;;
  uninstall-opencode|uninstall-codex|uninstall-cursor)
    case "$PLATFORM" in
      uninstall-opencode) TARGET="$HOME/.config/opencode/skills"; PLATFORM=opencode ;;
      uninstall-codex) TARGET="$HOME/.agents/skills"; PLATFORM=codex ;;
      uninstall-cursor) TARGET="$HOME/.cursor/skills"; PLATFORM=cursor ;;
    esac
    PLUGIN_LINK="$(dirname "$TARGET")/testcase-agent-plugin"
    for name in "${SKILL_NAMES[@]}"; do
      rm -rf "$TARGET/$name"
      echo "Removed skill link: $TARGET/$name"
    done
    rm -rf "$PLUGIN_LINK"
    echo "Removed plugin link: $PLUGIN_LINK"
    exit 0
    ;;
  *) echo "Unknown platform: $PLATFORM"; exit 1 ;;
esac

PLUGIN_LINK="$(dirname "$TARGET")/testcase-agent-plugin"

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

if [ "$SKIP_PIP" != "1" ]; then
  echo "Installing Python package (editable)..."
  if ! python -m pip install -e "${PLUGIN_ROOT}[solver]" -q; then
    echo "solver extra failed; falling back to base install..."
    python -m pip install -e "$PLUGIN_ROOT" -q
  fi
  echo "Python entrypoints: tg-plan, tg-solve (tg-init deprecated)"
fi

echo "Commands: /tg-plan  /tg-solve  (/tg-init deprecated)"
echo "PLUGIN_ROOT: $PLUGIN_LINK"
echo "For Cursor: add this repository root as a local plugin, or rely on the installed skill links."
