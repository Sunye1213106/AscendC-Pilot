#!/usr/bin/env bash
set -euo pipefail

# Repo root IS the plugin root.
PLUGIN_ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILLS_ROOT="$PLUGIN_ROOT/skills"
AGENTS_SRC="$PLUGIN_ROOT/agents"
PLATFORM="${1:-opencode}"
SKIP_PIP="${SKIP_PIP:-0}"

SKILL_NAMES=(tg-init tg-plan tg-solve)
RETIRED_SKILL_NAMES=(tg-contract tg-domain-review)
REQUIRED_AGENTS=(tg-csv-contract tg-init-audit)

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
    for name in "${SKILL_NAMES[@]}" "${RETIRED_SKILL_NAMES[@]}"; do
      rm -rf "$TARGET/$name"
      echo "Removed skill link: $TARGET/$name"
    done
    if [ "$PLATFORM" = "opencode" ] && [ -d "$HOME/.config/opencode/agents" ]; then
      rm -f "$HOME/.config/opencode/agents"/tg-*.md
      echo "Removed subagents: $HOME/.config/opencode/agents/tg-*.md"
    elif [ "$PLATFORM" = "cursor" ] && [ -d "$HOME/.cursor/agents" ]; then
      rm -f "$HOME/.cursor/agents"/tg-*.md
      echo "Removed subagents: $HOME/.cursor/agents/tg-*.md"
    fi
    rm -rf "$PLUGIN_LINK"
    echo "Removed plugin link: $PLUGIN_LINK"
    exit 0
    ;;
  *) echo "Unknown platform: $PLATFORM"; exit 1 ;;
esac

PLUGIN_LINK="$(dirname "$TARGET")/testcase-agent-plugin"

mkdir -p "$TARGET"
for name in "${RETIRED_SKILL_NAMES[@]}"; do
  dest="$TARGET/$name"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    rm -rf "$dest"
    echo "Removed retired skill link: $dest"
  fi
done
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

if [ "$PLATFORM" = "opencode" ] && [ -d "$AGENTS_SRC" ]; then
  AGENTS_DEST="$HOME/.config/opencode/agents"
elif [ "$PLATFORM" = "cursor" ] && [ -d "$AGENTS_SRC" ]; then
  AGENTS_DEST="$HOME/.cursor/agents"
else
  AGENTS_DEST=""
fi

if [ -n "$AGENTS_DEST" ]; then
  mkdir -p "$AGENTS_DEST"
  rm -f "$AGENTS_DEST"/tg-*.md
  for agent in "${REQUIRED_AGENTS[@]}"; do
    src_agent="$AGENTS_SRC/$agent.md"
    if [ ! -f "$src_agent" ]; then
      echo "REQUIRED_SUBAGENT_UNAVAILABLE: missing source $src_agent" >&2
      exit 1
    fi
    cp -f "$src_agent" "$AGENTS_DEST/$agent.md"
  done
  echo "Installed testcase-agent subagents (required only): ${REQUIRED_AGENTS[*]}"
  for agent in "${REQUIRED_AGENTS[@]}"; do
    path="$AGENTS_DEST/$agent.md"
    if [ ! -f "$path" ]; then
      echo "REQUIRED_SUBAGENT_UNAVAILABLE: $agent was not installed at $path" >&2
      exit 1
    fi
    grep -Eq "^name:[[:space:]]*$agent[[:space:]]*$" "$path" || {
      echo "REQUIRED_SUBAGENT_UNAVAILABLE: $agent missing matching frontmatter name" >&2
      exit 1
    }
    grep -Eq "^type:[[:space:]]*subagent[[:space:]]*$" "$path" || {
      echo "REQUIRED_SUBAGENT_UNAVAILABLE: $agent missing frontmatter type: subagent" >&2
      exit 1
    }
  done
  echo "Verified named subagents discoverable: ${REQUIRED_AGENTS[*]}"
fi

if [ "$SKIP_PIP" != "1" ]; then
  echo "Installing Python package (editable)..."
  if ! python -m pip install -e "${PLUGIN_ROOT}[solver]" -q; then
    echo "solver extra failed; falling back to base install..."
    python -m pip install -e "$PLUGIN_ROOT" -q
  fi
  echo "Python entrypoints: tg-init, tg-plan, tg-solve (tg-contract=compat CLI only)"
fi

echo "Commands: /tg-init  /tg-plan  /tg-solve"
echo "PLUGIN_ROOT: $PLUGIN_LINK"
echo "For Cursor: add this repository root as a local plugin, or rely on the installed skill links."
