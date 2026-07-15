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
    "uo-boundary-agent",
    "uo-host-extraction",
    "uo-flow-extraction",
    "uo-kernel-overview-agent",
    "uo-kernel-slice-planner",
    "uo-kernel-slice-agent",
    "uo-step2-fact-review-agent",
    "uo-step3-fact-review-agent",
    "uo-behavior-abstraction-agent",
    "uo-graph-review-agent",
)


def default_agents_dir(platform: str) -> Path:
    home = Path.home()
    if platform == "opencode":
        return home / ".config" / "opencode" / "agents"
    if platform == "cursor":
        return home / ".cursor" / "agents"
    return Path(__file__).resolve().parents[2] / "agents"


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


def check_agents(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    for name in REQUIRED_SUBAGENTS:
        path = agents_dir / f"{name}.md"
        if not path.exists():
            problems.append(f"missing required subagent: {path}")
            continue
        try:
            meta = parse_frontmatter(path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{path}: invalid frontmatter: {exc}")
            continue
        if meta.get("name") != name:
            problems.append(f"{path}: frontmatter name must be {name!r}, got {meta.get('name')!r}")
        if meta.get("type") != "subagent":
            problems.append(f"{path}: frontmatter type must be 'subagent'")
        model = meta.get("model")
        if isinstance(model, str) and model.strip().lower() == "inherit":
            problems.append(f"{path}: frontmatter model must not be 'inherit'; omit model to use the runtime default")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify required Understand Operator subagents are installed and typed.")
    parser.add_argument("--platform", default="opencode", choices=("opencode", "cursor", "repo"))
    parser.add_argument("--agents-dir", type=Path, help="Override the agent directory to inspect.")
    args = parser.parse_args(argv)

    agents_dir = (args.agents_dir or default_agents_dir(args.platform)).expanduser().resolve()
    problems = check_agents(agents_dir)
    if problems:
        print("REQUIRED_SUBAGENT_UNAVAILABLE", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 2
    print(f"Required Understand Operator subagents verified in {agents_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
