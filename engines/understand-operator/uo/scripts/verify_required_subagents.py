from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))


REQUIRED_SUBAGENTS = (
    "uo-semantic-resolve",
    "uo-key-resolve",
    "uo-confidence-review",
    "uo-kb-review",
    "ce-reviewer",
)


def default_agents_dir(platform: str) -> Path:
    home = Path.home()
    if platform == "opencode":
        return home / ".config" / "opencode" / "agents"
    if platform == "cursor":
        return home / ".cursor" / "agents"
    # source checkout: composed agents
    return Path(__file__).resolve().parents[4] / "generated" / "opencode" / "agents"


def parse_frontmatter(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required")
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return {}
    data = yaml.safe_load("\n".join(lines[1:end])) or {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify required AscendC subagents are installed.")
    parser.add_argument("--platform", choices=("cursor", "opencode", "plugin"), default="plugin")
    parser.add_argument("--agents-dir", default="")
    args = parser.parse_args(argv)
    agents_dir = Path(args.agents_dir) if args.agents_dir else default_agents_dir(args.platform)
    repo = Path(__file__).resolve().parents[4]
    bundle_agents = repo / "generated" / "opencode" / "agents"
    plugin_agents = Path(__file__).resolve().parents[2] / "agents"
    search_dirs = [agents_dir]
    for extra in (bundle_agents, plugin_agents):
        if extra.resolve() != agents_dir.resolve() and extra not in search_dirs:
            search_dirs.append(extra)

    missing: list[str] = []
    for name in REQUIRED_SUBAGENTS:
        found = False
        for directory in search_dirs:
            path = directory / f"{name}.md"
            if not path.exists():
                continue
            parse_frontmatter(path)
            found = True
            break
        if not found:
            missing.append(name)

    if missing:
        print("REQUIRED_SUBAGENT_UNAVAILABLE", file=sys.stderr)
        for name in missing:
            print(f"missing: {name}", file=sys.stderr)
        return 2
    print("required_subagents_ok", ",".join(REQUIRED_SUBAGENTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
