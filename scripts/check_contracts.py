#!/usr/bin/env python3
"""Validate composed runtime + Pilot SSOT consistency (exit non-zero on failure)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


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

    # Ownership / identity auditor (Spec, Skill, lease ceilings, run-scoped contracts).
    try:
        from check_ownership_contracts import audit as ownership_audit  # noqa: WPS433

        errors.extend(ownership_audit(repo))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ownership auditor unavailable: {exc}")

    if errors:
        print({"ok": False, "error_count": len(errors), "errors": errors})
        return 1
    print({"ok": True, "errors": []})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
