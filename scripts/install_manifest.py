#!/usr/bin/env python3
"""Owned Host-install manifest for AscendC-Pilot.

Compose writes ``generated/<host>/install-manifest.json``. Install copies it to
the plugin dest. Uninstall / leftover-Tab cleanup / the OpenCode plugin may
delete or patch **only** names listed here.

Never infer ownership from filename prefixes such as ``tg-`` / ``uo-`` / ``ce-``.
User files like ``~/.config/opencode/agents/ce-helper.md`` are not ours.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

MANIFEST_NAME = "install-manifest.json"
MANIFEST_VERSION = 1
OWNER = "ascendc-pilot"

# Fallback when an older install has no manifest. Explicit identities only.
WORKFLOW_SKILLS: tuple[str, ...] = (
    "uo-init",
    "uo-update",
    "uo-query",
    "uo-investigate",
    "ce-review",
    "ce-plan",
    "ce-apply",
    "handoff",
    "tg-init",
    "tg-plan",
    "tg-solve",
    "workflow-orchestration",
)
from compose_runtime_legacy import listed_skill_ids

COGNITIVE_SKILLS: tuple[str, ...] = listed_skill_ids()
OPENCODE_COMMANDS: tuple[str, ...] = (
    "uo-init",
    "uo-update",
    "uo-query",
    "uo-investigate",
    "ce-review",
    "ce-plan",
    "ce-apply",
    "handoff",
    "tg-init",
    "tg-plan",
    "tg-solve",
)
CURRENT_AGENTS: tuple[str, ...] = (
    "ascendc-pilot",
    "uo-query",
    "uo-heal-analyst",
    "uo-gap-investigator",
    "ce-reviewer",
    "tg-analyst",
    "ce-applier",
    "ce-analyst",
)
CURRENT_PLUGINS: tuple[str, ...] = ("ascendc-pilot.ts",)

# Names we used to install and still own. Upgrade/uninstall may remove these.
# Do not add prefix globs here.
LEGACY_OWNED: dict[str, list[str]] = {
    "agents": [
        "ascendc-agent.md",
        "uo-semantic-resolve.md",
        "uo-semantic-resolver.md",
        "uo-gap-resolve.md",
        "uo-key-resolve.md",
        "uo-confidence-review.md",
        "uo-kb-review.md",
        "uo-code-reviewer.md",
        "tg-csv-contract.md",
        "tg-semantic-bind.md",
        "tg-init-audit.md",
        "tg-lemma-producer.md",
        "tg-closure-referee.md",
        "deterministic-uo-engine.md",
        "deterministic-tg-engine.md",
        "deterministic-ce-engine.md",
        "ce-change-referee.md",
        "README.md",
    ],
    "skills": [
        "uo-code-review",
        "understand-operator",
        "uo-diff",
        "ce-intent",
        "ce-impact",
        "ce-verify",
        "ce-handoff",
        "_policies",
        "operator",
    ],
    "plugins": [
        "zz-uo-query-return-value.ts",
        "uo-query-return-value.ts",
        "ascendc-harness.ts",
        "pilot-driver.ts",
    ],
    "plugin_trees": ["ascendc-agent-plugin"],
}


def _file_names(root: Path, pattern: str, *, skip: Iterable[str] = ()) -> list[str]:
    if not root.is_dir():
        return []
    skip_l = {s.lower() for s in skip}
    names = [
        p.name
        for p in sorted(root.glob(pattern))
        if p.is_file() and p.name.lower() not in skip_l
    ]
    return names


def _dir_names(root: Path, *, skip: Iterable[str] = ()) -> list[str]:
    if not root.is_dir():
        return []
    skip_l = {s.lower() for s in skip}
    return [
        p.name
        for p in sorted(root.iterdir())
        if p.is_dir() and p.name.lower() not in skip_l
    ]


def _as_md(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    return s if s.lower().endswith(".md") else f"{s}.md"


def _names(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def builtin_manifest(host: str) -> dict[str, Any]:
    """Explicit fallback for installs that predate the manifest file."""
    agents = [_as_md(n) for n in CURRENT_AGENTS]
    global_agents = ["ascendc-pilot.md"] if host == "opencode" else list(agents)
    commands = [_as_md(n) for n in OPENCODE_COMMANDS] if host == "opencode" else []
    plugins = list(CURRENT_PLUGINS) if host == "opencode" else []
    return {
        "version": MANIFEST_VERSION,
        "owner": OWNER,
        "host": host,
        "agents": agents,
        "global_agents": global_agents,
        "skills": list(WORKFLOW_SKILLS),
        "cognitive_skills": list(COGNITIVE_SKILLS),
        "commands": commands,
        "plugins": plugins,
        "legacy": {
            "agents": list(LEGACY_OWNED["agents"]),
            "skills": list(LEGACY_OWNED["skills"]),
            "plugins": list(LEGACY_OWNED["plugins"]),
            "plugin_trees": list(LEGACY_OWNED["plugin_trees"]),
        },
    }


def build_manifest(out_root: Path, host: str) -> dict[str, Any]:
    """Build ownership from a composed host runtime tree (post-prune)."""
    out_root = Path(out_root)
    agents = _file_names(out_root / "agents", "*.md", skip=("readme.md",))
    if "ascendc-pilot.md" not in agents:
        agents = ["ascendc-pilot.md", *agents]
    skills = _dir_names(out_root / "skills", skip=("_policies",))
    cognitive = _dir_names(out_root / "cognitive-skills")
    commands = _file_names(out_root / "commands", "*.md")
    if host == "opencode":
        global_agents = ["ascendc-pilot.md"]
        plugins = list(CURRENT_PLUGINS)
    else:
        global_agents = list(agents)
        plugins = []
    return {
        "version": MANIFEST_VERSION,
        "owner": OWNER,
        "host": host,
        "agents": agents,
        "global_agents": global_agents,
        "skills": skills,
        "cognitive_skills": cognitive,
        "commands": commands,
        "plugins": plugins,
        "legacy": {
            "agents": list(LEGACY_OWNED["agents"]),
            "skills": list(LEGACY_OWNED["skills"]),
            "plugins": list(LEGACY_OWNED["plugins"]),
            "plugin_trees": list(LEGACY_OWNED["plugin_trees"]),
        },
    }


def write_install_manifest(out_root: Path, host: str) -> Path:
    payload = build_manifest(out_root, host)
    path = Path(out_root) / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_install_manifest(path: Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def resolve_manifest(
    host: str,
    *,
    dest: Path | None = None,
    generated: Path | None = None,
) -> dict[str, Any]:
    candidates: list[Path] = []
    if dest is not None:
        candidates.append(Path(dest) / MANIFEST_NAME)
    if generated is not None:
        candidates.append(Path(generated) / MANIFEST_NAME)
    for path in candidates:
        data = load_install_manifest(path)
        if data:
            data.setdefault("host", host)
            return data
    return builtin_manifest(host)


def owned_agent_files(manifest: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    legacy = manifest.get("legacy") if isinstance(manifest.get("legacy"), dict) else {}
    for raw in (
        _names(manifest.get("agents")),
        _names(manifest.get("global_agents")),
        _names(legacy.get("agents") if isinstance(legacy, dict) else None),
    ):
        for item in raw:
            md = _as_md(item)
            key = md.lower()
            if md and key not in seen:
                seen.add(key)
                names.append(md)
    return names


def global_keep_agent_files(manifest: dict[str, Any]) -> list[str]:
    keep = [_as_md(n) for n in _names(manifest.get("global_agents"))]
    return keep or ["ascendc-pilot.md"]


def prune_global_agents(agents_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Remove owned leftover Tabs only. Never prefix-match user agents."""
    keep = {n.lower() for n in global_keep_agent_files(manifest)}
    owned = {n.lower() for n in owned_agent_files(manifest)}
    removed: list[str] = []
    root = Path(agents_dir)
    if not root.is_dir():
        return removed
    for path in root.glob("*.md"):
        key = path.name.lower()
        if key in keep:
            continue
        if key in owned:
            path.unlink()
            removed.append(str(path))
    return removed


def uninstall_plan(
    host: str,
    *,
    dest: Path,
    generated: Path | None = None,
) -> dict[str, Any]:
    """Names the uninstallers may delete. Never a prefix glob."""
    manifest = resolve_manifest(host, dest=dest, generated=generated)
    legacy = manifest.get("legacy") if isinstance(manifest.get("legacy"), dict) else {}
    skills = []
    seen_s: set[str] = set()
    for item in (
        _names(manifest.get("skills"))
        + _names(manifest.get("cognitive_skills"))
        + _names(legacy.get("skills") if isinstance(legacy, dict) else None)
        + ["_shared"]
    ):
        if item and item.lower() not in seen_s:
            seen_s.add(item.lower())
            skills.append(item)
    plugins = []
    seen_p: set[str] = set()
    for item in _names(manifest.get("plugins")) + _names(
        legacy.get("plugins") if isinstance(legacy, dict) else None
    ):
        if item and item.lower() not in seen_p:
            seen_p.add(item.lower())
            plugins.append(item)
    trees = _names(legacy.get("plugin_trees") if isinstance(legacy, dict) else None)
    commands = [_as_md(n) for n in _names(manifest.get("commands"))]
    return {
        "host": host,
        "dest": str(Path(dest)),
        "agents": owned_agent_files(manifest),
        "global_keep_agents": global_keep_agent_files(manifest),
        "skills": skills,
        "commands": commands,
        "plugins": plugins,
        "plugin_trees": trees,
        "manifest": MANIFEST_NAME,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write or inspect AscendC-Pilot install ownership")
    parser.add_argument("--write", metavar="OUT_ROOT", help="Write install-manifest.json under OUT_ROOT")
    parser.add_argument("--host", default="opencode")
    parser.add_argument("--plan", action="store_true", help="Print uninstall name plan as JSON")
    parser.add_argument("--dest", type=Path, default=None)
    parser.add_argument("--generated", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--prune-global-agents", type=Path, default=None, help="Delete owned leftover Tabs in this agents dir")
    args = parser.parse_args(argv)
    if args.write:
        path = write_install_manifest(Path(args.write), args.host)
        print(path.as_posix())
        return 0
    if args.prune_global_agents is not None:
        man = None
        if args.manifest:
            man = load_install_manifest(args.manifest)
        if man is None:
            man = resolve_manifest(args.host, dest=args.dest, generated=args.generated)
        removed = prune_global_agents(args.prune_global_agents, man)
        for path in removed:
            print(f"Removed leftover OpenCode Tab → {path}")
        return 0
    if args.plan:
        host = str(args.host)
        dest = args.dest
        if dest is None:
            home = Path.home() / ".config" / "opencode"
            dest = {
                "opencode": home / "ascendc-pilot-plugin",
                "cursor": Path.home() / ".cursor" / "ascendc-pilot-plugin",
                "codex": Path.home() / ".agents" / "ascendc-pilot-plugin",
            }.get(host)
            if dest is None:
                print(f"unknown host {host}", file=sys.stderr)
                return 2
        print(json.dumps(uninstall_plan(host, dest=dest, generated=args.generated), indent=2))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
