from __future__ import annotations

import argparse
import importlib
import re
import subprocess
import sys
from pathlib import Path


SCRIPT_RE = re.compile(r"\$SCRIPT_DIR/([A-Za-z0-9_]+\.py)")


def referenced_scripts(plugin_root: Path) -> list[str]:
    roots = [
        plugin_root / "skills" / "uo-init" / "SKILL.md",
        plugin_root / "prompts" / "01_workflow_orchestrator.md",
    ]
    agents = plugin_root / "agents"
    if agents.exists():
        roots.extend(sorted(agents.glob("*.md")))
    found: set[str] = set()
    for path in roots:
        if not path.exists():
            continue
        found.update(SCRIPT_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
    return sorted(found)


def verify_required_scripts(plugin_root: Path) -> list[str]:
    script_dir = plugin_root / "skills" / "understand-operator"
    errors: list[str] = []
    for name in referenced_scripts(plugin_root):
        path = script_dir / name
        if not path.exists():
            errors.append(f"{name}: missing wrapper at {path}")
            continue
        module = f"understand_operator.scripts.{path.stem}"
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: cannot import {module}: {exc}")
            continue
        result = subprocess.run([sys.executable, str(path), "--help"], cwd=plugin_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            errors.append(f"{name}: --help returned {result.returncode}: {result.stderr.strip()}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify every $SCRIPT_DIR/*.py referenced by /uo-init exists and supports --help.")
    parser.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    errors = verify_required_scripts(args.plugin_root.resolve())
    for error in errors:
        print(error, file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
