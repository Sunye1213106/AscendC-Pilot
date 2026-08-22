# AscendC-Pilot unified installer
#
# Usage:
#   ./install.sh opencode|cursor|codex
#   ./install.sh uninstall-opencode|uninstall-cursor|uninstall-codex
#   ./uninstall.sh opencode
#   SKIP_PIP=1 ./install.sh opencode
#   PYTHON=python3.12 ./install.sh opencode
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:-opencode}"
SKIP_PIP="${SKIP_PIP:-0}"

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

# Compose slash workflows (pilot_run). `/uo-query` is a Command + Action Skill, not a workflow shell.
WORKFLOW_SKILLS=(
  uo-init uo-update uo-investigate
  ce-review ce-plan ce-apply handoff
  tg-init tg-plan tg-solve
)
# Old installs left a workflow skill dir; unlink it. Uninstall still names it for cleanup.
STALE_WORKFLOW_SKILLS=(uo-query workflow-orchestration operator)
# Action Skills are discovered from generated/<host> after compose.
# Uninstall still names the old five families so leftover installs are cleaned.
LEGACY_COGNITIVE_SKILLS=(operator-analysis testcase-generation source-proof code-review code-engineering)
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

remove_owned_opencode_tabs() {
  local agents_dir="$1"
  local man="${2:-}"
  if [[ -n "$man" ]]; then
    "$PYTHON" "$BUNDLE_ROOT/scripts/install_manifest.py" \
      --host opencode \
      --prune-global-agents "$agents_dir" \
      --manifest "$man"
  else
    "$PYTHON" "$BUNDLE_ROOT/scripts/install_manifest.py" \
      --host opencode \
      --prune-global-agents "$agents_dir"
  fi
}

purge_legacy_ascendc_agent() {
  local plat="$1" skills="$2" agents="$3" plugins="$4"
  local name
  for name in "${LEGACY_SKILLS[@]}"; do
    if [[ -e "$skills/$name" || -L "$skills/$name" ]]; then
      rm -rf "$skills/$name"
      echo "Removed legacy skill → $skills/$name"
    fi
  done
  for name in "${LEGACY_AGENTS[@]}"; do
    if [[ -f "$agents/$name.md" || -L "$agents/$name.md" ]]; then
      rm -f "$agents/$name.md"
      echo "Removed legacy agent → $agents/$name.md"
    fi
  done
  if [[ "$plat" == "opencode" ]]; then
    local man=""
    if [[ -f "$BUNDLE_ROOT/generated/opencode/install-manifest.json" ]]; then
      man="$BUNDLE_ROOT/generated/opencode/install-manifest.json"
    elif [[ -f "$(plugin_dest opencode)/install-manifest.json" ]]; then
      man="$(plugin_dest opencode)/install-manifest.json"
    fi
    remove_owned_opencode_tabs "$agents" "$man"
    rm -rf "$(opencode_home)/ascendc-agent-plugin"
    if [[ -n "$plugins" ]]; then
      rm -f "$plugins/ascendc-harness.ts"
    fi
  fi
}

uninstall() {
  local plat="$1"
  exec "$BUNDLE_ROOT/uninstall.sh" "$plat"
}

resolve_acp_bin() {
  if command -v acp >/dev/null 2>&1; then
    command -v acp
    return 0
  fi
  "$PYTHON" -c "
import pathlib, sysconfig
scripts = pathlib.Path(sysconfig.get_path('scripts'))
for name in ('acp', 'acp.exe'):
    p = scripts / name
    if p.is_file():
        print(p)
        break
" 2>/dev/null || true
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
  "$PYTHON" -m pip install -r "$BUNDLE_ROOT/requirements.txt"
fi

# Fail installation before composing a Host runtime when execution ownership is
# internally inconsistent.
"$PYTHON" "$BUNDLE_ROOT/scripts/check_execution_contracts.py"

# Compose sources, then retain only model-reachable runtime context.
"$PYTHON" "$BUNDLE_ROOT/scripts/compose_runtime.py" --repo "$BUNDLE_ROOT" --host "$PLATFORM"
"$PYTHON" "$BUNDLE_ROOT/scripts/prune_runtime_context.py" --repo "$BUNDLE_ROOT" --host "$PLATFORM"
if [[ "$PLATFORM" == "opencode" ]]; then
  "$PYTHON" "$BUNDLE_ROOT/scripts/compose_opencode_commands.py"
fi

DEST="$(plugin_dest "$PLATFORM")"
SKILLS="$(skills_dest "$PLATFORM")"
AGENTS="$(agents_dest "$PLATFORM")"
mkdir -p "$DEST" "$SKILLS" "$AGENTS"
rm -rf "$DEST"
mkdir -p "$DEST"

# Bundle runtime implementation only. Agent-facing assets come exclusively
# from generated/<host>; docs/templates/source prompts are not runtime context.
for name in pilot acp scripts opencode-plugin; do
  if [[ -d "$BUNDLE_ROOT/$name" ]]; then
    cp -R "$BUNDLE_ROOT/$name" "$DEST/"
  fi
done
mkdir -p "$DEST/engines"
for eng in common understand-operator testcase-generation code-engineering; do
  if [[ -d "$BUNDLE_ROOT/engines/$eng" ]]; then
    cp -R "$BUNDLE_ROOT/engines/$eng" "$DEST/engines/"
  fi
done

GEN="$BUNDLE_ROOT/generated/$PLATFORM"
for name in skills agents prompts commands knowledge; do
  rm -rf "$DEST/$name"
done
cp -R "$GEN/skills" "$DEST/skills"
cp -R "$GEN/agents" "$DEST/agents"
if [[ -d "$GEN/prompts" ]]; then
  cp -R "$GEN/prompts" "$DEST/prompts"
fi
if [[ -d "$GEN/commands" ]]; then
  cp -R "$GEN/commands" "$DEST/commands"
fi
if [[ ! -d "$GEN/knowledge" ]]; then
  echo "generated knowledge missing: $GEN/knowledge (compose/copy failed)" >&2
  exit 1
fi
cp -R "$GEN/knowledge" "$DEST/knowledge"
if [[ -f "$GEN/install-manifest.json" ]]; then
  cp "$GEN/install-manifest.json" "$DEST/install-manifest.json"
fi

# Purge leftovers from earlier installs before linking the current closure.
purge_legacy_ascendc_agent "$PLATFORM" "$SKILLS" "$AGENTS" "$(plugins_dest "$PLATFORM")"

for name in "${WORKFLOW_SKILLS[@]}"; do
  [[ -d "$DEST/skills/$name" ]] || continue
  rm -rf "$SKILLS/$name"
  # OpenCode: plugin-internal only. Global skills/ is native Build/Plan discovery.
  if [[ "$PLATFORM" != "opencode" ]]; then
    ln -sfn "$DEST/skills/$name" "$SKILLS/$name" 2>/dev/null || cp -R "$DEST/skills/$name" "$SKILLS/$name"
  fi
done
for name in "${STALE_WORKFLOW_SKILLS[@]}"; do
  rm -rf "$SKILLS/$name"
done

# Action Skills: Cursor/Codex install into skill discovery with
# disable-model-invocation; OpenCode keeps them plugin-internal only.
if [[ "$PLATFORM" == "opencode" ]]; then
  for name in "${LEGACY_COGNITIVE_SKILLS[@]}" _shared; do
    rm -rf "$SKILLS/$name"
  done
  if [[ -d "$BUNDLE_ROOT/generated/opencode/cognitive-skills" ]]; then
    rm -rf "$DEST/cognitive-skills"
    cp -R "$BUNDLE_ROOT/generated/opencode/cognitive-skills" "$DEST/cognitive-skills"
    for name in "$BUNDLE_ROOT/generated/opencode/cognitive-skills"/*; do
      [[ -d "$name" ]] || continue
      rm -rf "$SKILLS/$(basename "$name")"
    done
  fi
else
  if [[ -d "$DEST/skills" ]]; then
    for dir in "$DEST/skills"/*; do
      [[ -d "$dir" ]] || continue
      name="$(basename "$dir")"
      case "$name" in
        _policies|_shared|uo-init|uo-update|uo-investigate|ce-review|ce-plan|ce-apply|handoff|tg-init|tg-plan|tg-solve) continue ;;
      esac
      rm -rf "$SKILLS/$name"
      ln -sfn "$DEST/skills/$name" "$SKILLS/$name" 2>/dev/null || cp -R "$DEST/skills/$name" "$SKILLS/$name"
    done
  fi
  rm -rf "$SKILLS/_shared"
fi

# OpenCode treats every .md under agents/ as a Tab. Only expose AscendC-Pilot.
if [[ "$PLATFORM" == "opencode" ]]; then
  ln -sfn "$DEST/agents/ascendc-pilot.md" "$AGENTS/ascendc-pilot.md" 2>/dev/null || cp "$DEST/agents/ascendc-pilot.md" "$AGENTS/ascendc-pilot.md"
  remove_owned_opencode_tabs "$AGENTS" "$DEST/install-manifest.json"
else
  for f in "$DEST/agents"/*.md; do
    [[ -f "$f" ]] || continue
    base="$(basename "$f")"
    [[ "$base" == "README.md" ]] && continue
    ln -sfn "$f" "$AGENTS/$base" 2>/dev/null || cp "$f" "$AGENTS/$base"
  done
fi

if [[ "$PLATFORM" == "opencode" ]]; then
  PLUGINS="$(plugins_dest opencode)"
  COMMANDS="$(commands_dest opencode)"
  mkdir -p "$PLUGINS" "$COMMANDS"
  # OpenCode autoloads every *.ts in this directory as a plugin factory.
  # Copy only real plugins. pilot-driver.ts is a library loaded from $DEST.
  for f in "$BUNDLE_ROOT"/opencode-plugin/ascendc-pilot.ts; do
    [[ -f "$f" ]] || continue
    base="$(basename "$f")"
    cp "$f" "$PLUGINS/$base"
    echo "Installed plugin → $PLUGINS/$base"
  done
  rm -f "$PLUGINS/pilot-driver.ts" "$PLUGINS/zz-uo-query-return-value.ts" "$PLUGINS/uo-query-return-value.ts"
  # OpenCode 1.18 RipgrepBinary uses $XDG_CACHE_HOME/opencode/bin (default
  # ~/.cache/opencode/bin), not only ~/.local/share/opencode/bin.
  RG_SRC=""
  if command -v rg >/dev/null 2>&1; then
    RG_SRC="$(command -v rg)"
  fi
  OC_BINS=(
    "$HOME/.local/share/opencode/bin"
    "${XDG_CACHE_HOME:-$HOME/.cache}/opencode/bin"
    "$HOME/.cache/opencode/bin"
  )
  SEEDED=0
  for OC_BIN in "${OC_BINS[@]}"; do
    mkdir -p "$OC_BIN"
    if [[ -x "$OC_BIN/rg" ]]; then
      SEEDED=1
      continue
    fi
    if [[ -n "$RG_SRC" ]]; then
      cp "$RG_SRC" "$OC_BIN/rg"
      chmod +x "$OC_BIN/rg"
      echo "Seeded OpenCode rg → $OC_BIN/rg"
      SEEDED=1
    fi
  done
  if [[ "$SEEDED" -eq 0 ]]; then
    echo "WARN: no rg to seed; Pilot after-hook still loads plugin-internal SKILL.md without rg"
  fi
  if [[ -d "$DEST/commands" ]]; then
    for f in "$DEST/commands"/*.md; do
      [[ -f "$f" ]] || continue
      cp "$f" "$COMMANDS/$(basename "$f")"
    done
    echo "Workflow commands → $COMMANDS/{uo-*,tg-*,ce-*}.md"
  fi
  echo "Primary agent → $AGENTS/ascendc-pilot.md (Tab: AscendC-Pilot; opencode.json untouched)"
fi

mkdir -p "$DEST/templates/$PLATFORM"
echo "plugin_root=$DEST" > "$DEST/templates/$PLATFORM/install_stamp.txt"

# Cache absolute acp path for OpenCode plugin (Node often has a thinner PATH).
OC_HOME="$(opencode_home)"
ACP_BIN="$(resolve_acp_bin || true)"
mkdir -p "$OC_HOME"
if [[ -n "${ACP_BIN:-}" && -e "$ACP_BIN" ]]; then
  printf '%s\n' "$ACP_BIN" > "$OC_HOME/ascendc-harness-bin"
  echo "Cached acp bin → $ACP_BIN"
else
  echo "WARN: acp not on PATH after pip install; OpenCode may fail to find harness"
fi

cann_pkg="$BUNDLE_ROOT/_cann/pkg"
cann_root_to_cache=""
if [[ -n "${UO_CANN_ROOT:-}" && -d "$UO_CANN_ROOT" ]]; then
  cann_root_to_cache="$UO_CANN_ROOT"
elif [[ -d "$cann_pkg/cann-asc-devkit" || -d "$cann_pkg/cann-metadef" ]]; then
  cann_root_to_cache="$cann_pkg"
fi
if [[ -n "$cann_root_to_cache" ]]; then
  printf '%s\n' "$cann_root_to_cache" > "$OC_HOME/ascendc-cann-root"
  echo "Cached CANN root → $cann_root_to_cache"
fi

echo "Installed AscendC-Pilot → $DEST"
cann_pkg="$BUNDLE_ROOT/_cann/pkg"
if [[ -n "${UO_CANN_ROOT:-}" && -d "$UO_CANN_ROOT" ]]; then
  echo "UO_CANN_ROOT=$UO_CANN_ROOT"
elif [[ -d "$cann_pkg/cann-asc-devkit" || -d "$cann_pkg/cann-metadef" ]]; then
  echo "CANN headers auto-discovered at $cann_pkg (no env var needed)"
else
  echo "WARN: CANN headers not found. Extract into the checkout so doctor can discover it:"
  echo "  $PYTHON \"$BUNDLE_ROOT/scripts/cann_extract.py\" <toolkit.run> --dest \"$cann_pkg\""
  echo "  $PYTHON \"$BUNDLE_ROOT/scripts/cann_extract.py\" --fixup --dest \"$cann_pkg\""
  echo "If already extracted elsewhere: export UO_CANN_ROOT=<abs-pkg> (put it in your shell profile)"
fi
if [[ "$PLATFORM" == "opencode" ]]; then
  echo "Run: $PYTHON -m ascendc_pilot doctor --host opencode"
else
  echo "Run: $PYTHON -m ascendc_pilot doctor"
fi
echo "Keep this checkout; pip -e installs point at it. Fully quit and reopen the Host."
