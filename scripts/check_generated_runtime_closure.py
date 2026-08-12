#!/usr/bin/env python3
"""Validate an already-composed host runtime against the exact host pipeline.

Unlike the older ``compose_runtime.check_generated_drift`` helper, this checker
models the product that OpenCode actually installs:

    compose_host -> prune_runtime_context -> compose_opencode_commands

It is intended to run after CI has regenerated ``generated/opencode`` in the
workspace.  The candidate is built in a temporary directory and compared by
content, so pruning/command generation cannot appear as false drift.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from compose_opencode_commands import compose as compose_opencode_commands
from compose_runtime import _normalize_generated_text, compose_host
from prune_runtime_context import prune


def _files(root: Path) -> set[str]:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
    }


def check(repo: Path, *, host: str = "opencode") -> list[str]:
    repo = repo.expanduser().resolve()
    actual = repo / "generated" / host
    if not actual.is_dir():
        return [f"GENERATED_RUNTIME_CLOSURE: missing generated/{host}/"]

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="acp-host-closure-") as tmp:
        tmp_root = Path(tmp)
        candidate = tmp_root / host
        compose_host(repo, host, out_root=candidate)
        pruned = prune(repo, host, generated_root=candidate)
        if not pruned.get("ok"):
            return [
                "GENERATED_RUNTIME_CLOSURE: prune failed: "
                + str(
                    {
                        "missing_agents": pruned.get("missing_agents"),
                        "missing_prompts": pruned.get("missing_prompts"),
                    }
                )
            ]
        if host == "opencode":
            compose_opencode_commands(repo, out_root=candidate)

        expected_files = _files(candidate)
        actual_files = _files(actual)
        for rel in sorted(expected_files - actual_files)[:30]:
            errors.append(f"GENERATED_RUNTIME_CLOSURE: generated/{host}/{rel} missing")
        for rel in sorted(actual_files - expected_files)[:30]:
            errors.append(f"GENERATED_RUNTIME_CLOSURE: generated/{host}/{rel} unexpected")
        for rel in sorted(expected_files & actual_files):
            expected = _normalize_generated_text(
                (candidate / rel).read_text(encoding="utf-8", errors="replace"),
                tmp_root=str(tmp_root),
                repo_root=str(repo),
            )
            current = _normalize_generated_text(
                (actual / rel).read_text(encoding="utf-8", errors="replace"),
                tmp_root=str(tmp_root),
                repo_root=str(repo),
            )
            if expected != current:
                errors.append(f"GENERATED_RUNTIME_CLOSURE: generated/{host}/{rel}")
                if len(errors) >= 50:
                    break
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate composed host runtime closure")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--host", default="opencode")
    args = parser.parse_args(argv)
    errors = check(args.repo, host=str(args.host))
    if errors:
        print("\n".join(errors))
        return 1
    print(f"generated runtime closure ({args.host}): ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
