#!/usr/bin/env python3
"""Validate composed runtime + Pilot SSOT consistency (exit non-zero on failure)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Parenthesized backtick lists of capability-like ids in task prompts.
_CAP_LIST_RE = re.compile(
    r"\((?:\s*`([a-z][a-z0-9-]*)`\s*,\s*)+`([a-z][a-z0-9-]*)`\s*\)"
)


def check_prompt_capability_drift(repo: Path) -> list[str]:
    """Fail when a task prompt hardcodes a capability list that ≠ Action Spec."""
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows.specs import WORKFLOWS  # noqa: WPS433

    known_caps = {
        p.name
        for p in (repo / "skills" / "capabilities").iterdir()
        if p.is_dir() and (p / "capability.yaml").is_file()
    }
    # task_prompt_id -> expected capability_ids (first writer wins; warn on conflict)
    expected: dict[str, list[str]] = {}
    owners: dict[str, str] = {}
    errors: list[str] = []
    for wid, wf in WORKFLOWS.items():
        if wf.get("reserved") or wf.get("alias_of"):
            continue
        for action in wf.get("actions") or []:
            tpid = action.get("task_prompt_id")
            if not tpid:
                continue
            caps = list(action.get("capability_ids") or [])
            key = str(tpid)
            if key in expected and expected[key] != caps:
                errors.append(
                    f"prompt-cap-drift: task_prompt_id {key!r} used by "
                    f"{owners[key]} and {wid}/{action.get('id')} with different capability_ids"
                )
                continue
            expected[key] = caps
            owners[key] = f"{wid}/{action.get('id')}"

    tasks_root = repo / "prompts" / "tasks"
    if not tasks_root.is_dir():
        return errors

    for path in sorted(tasks_root.rglob("*.md")):
        rel = path.relative_to(tasks_root).as_posix()
        tpid = rel[:-3] if rel.endswith(".md") else rel
        text = path.read_text(encoding="utf-8")
        for match in _CAP_LIST_RE.finditer(text):
            # Re-parse span: repeating groups only keep the last capture.
            listed = re.findall(r"`([a-z][a-z0-9-]*)`", match.group(0))
            if not listed or not all(cid in known_caps for cid in listed):
                continue
            want = expected.get(tpid)
            if want is None:
                errors.append(
                    f"prompt-cap-drift: {path.as_posix()} hardcodes capabilities "
                    f"{listed} but no Action owns task_prompt_id={tpid!r}"
                )
                continue
            if set(listed) != set(want):
                errors.append(
                    f"prompt-cap-drift: {path.as_posix()} hardcodes {listed} "
                    f"but Action {owners.get(tpid)} expects {want}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AscendC-Pilot contract / SSOT checker")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (default: parent of scripts/)")
    parser.add_argument(
        "--skip-compose",
        action="store_true",
        help="Skip compose_runtime validation (consistency checks only)",
    )
    args = parser.parse_args(argv)

    repo = (args.repo or Path(__file__).resolve().parents[1]).expanduser().resolve()
    errors: list[str] = []

    if not args.skip_compose:
        sys.path.insert(0, str(repo / "scripts"))
        try:
            from compose_runtime import (  # noqa: WPS433
                compose_host,
                validate,
                validate_generated,
            )
        except ImportError as exc:
            errors.append(f"compose_runtime unavailable: {exc}")
        else:
            errors.extend(validate(repo))
            # generated/ is gitignored — always recompose, then validate the
            # fresh tree. Do not compare against a committed golden copy.
            for host in ("opencode", "cursor", "codex"):
                try:
                    result = compose_host(repo, host)
                    if not result.get("ok", True) and result.get("errors"):
                        errors.extend(str(e) for e in result["errors"])
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"compose/{host} failed: {exc}")
                    continue
                errors.extend(validate_generated(repo, host=host))

    sys.path.insert(0, str(repo / "pilot"))
    sys.path.insert(0, str(repo / "engines" / "understand-operator"))
    from ascendc_pilot.workflows.consistency import check_all  # noqa: WPS433

    errors.extend(check_all(repo))
    errors.extend(check_prompt_capability_drift(repo))

    # Ownership / identity auditor (Spec, Skill, lease ceilings, run-scoped contracts).
    try:
        from check_ownership_contracts import audit as ownership_audit  # noqa: WPS433

        errors.extend(ownership_audit(repo))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ownership auditor unavailable: {exc}")

    try:
        from check_skill_architecture import _errors as skill_arch_errors  # noqa: WPS433

        errors.extend(skill_arch_errors())
    except Exception as exc:  # noqa: BLE001
        errors.append(f"skill architecture lint unavailable: {exc}")

    import json

    payload = (
        {"ok": False, "error_count": len(errors), "errors": errors}
        if errors
        else {"ok": True, "errors": []}
    )
    # Windows consoles often default to GBK; avoid UnicodeEncodeError on symbols.
    text = json.dumps(payload, ensure_ascii=True)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
