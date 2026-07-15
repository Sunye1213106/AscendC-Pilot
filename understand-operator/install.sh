#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$REPO_ROOT/understand-operator-plugin"
SKILLS_ROOT="$PLUGIN_ROOT/skills"
AGENTS_SRC="$PLUGIN_ROOT/agents"
PLATFORM="${1:-opencode}"

SKILL_NAMES=(uo-init uo-query uo-update uo-diff understand-operator)
REQUIRED_AGENTS=(
  uo-boundary-agent
  uo-host-extraction
  uo-flow-extraction
  uo-kernel-overview-agent
  uo-kernel-slice-planner
  uo-kernel-slice-agent
  uo-step2-fact-review-agent
  uo-step3-fact-review-agent
  uo-behavior-abstraction-agent
  uo-graph-review-agent
)

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

if [ "$PLATFORM" = "opencode" ] && [ -d "$AGENTS_SRC" ]; then
  AGENTS_DEST="$HOME/.config/opencode/agents"
elif [ "$PLATFORM" = "cursor" ] && [ -d "$AGENTS_SRC" ]; then
  AGENTS_DEST="$HOME/.cursor/agents"
else
  AGENTS_DEST=""
fi

if [ -n "$AGENTS_DEST" ]; then
  mkdir -p "$AGENTS_DEST"
  rm -f "$AGENTS_DEST"/uo-*.md
  cp -f "$AGENTS_SRC"/uo-*.md "$AGENTS_DEST"/
  echo "Installed understand-operator subagents: $AGENTS_DEST/uo-*.md"
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
    if grep -Eq "^model:[[:space:]]*inherit[[:space:]]*$" "$path"; then
      echo "REQUIRED_SUBAGENT_UNAVAILABLE: $agent must omit model: inherit" >&2
      exit 1
    fi
  done
  echo "Verified named subagents discoverable: ${REQUIRED_AGENTS[*]}"
fi

echo "Commands: /uo-init  /uo-query  /uo-update  /uo-diff"
echo "For Cursor: add the repository root as a local plugin, or rely on the installed skill links."
