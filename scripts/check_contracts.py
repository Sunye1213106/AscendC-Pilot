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
            from compose_runtime import validate, validate_generated  # noqa: WPS433
        except ImportError as exc:
            errors.append(f"compose_runtime unavailable: {exc}")
        else:
            errors.extend(validate(repo))
            for host in ("opencode", "cursor", "codex"):
                errors.extend(validate_generated(repo, host=host))

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows.consistency import check_all  # noqa: WPS433

    errors.extend(check_all(repo))

    if errors:
        print({"ok": False, "error_count": len(errors), "errors": errors})
        return 1
    print({"ok": True, "errors": []})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
