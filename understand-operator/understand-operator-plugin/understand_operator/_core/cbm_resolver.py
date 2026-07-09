from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def _candidate_names() -> list[str]:
    return ["codebase-memory-mcp.exe", "codebase-memory-mcp"] if os.name == "nt" else ["codebase-memory-mcp"]


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)


def resolve_cbm_binary(config: dict[str, Any] | None = None) -> Path | None:
    """Find a codebase-memory-mcp binary without installing or downloading it."""
    scanner_cfg = (config or {}).get("scanner", {}) if isinstance(config, dict) else {}

    explicit = str(scanner_cfg.get("cbm_binary") or "").strip()
    env_path = os.environ.get("UNDERSTAND_OPERATOR_CBM_BIN", "").strip()
    for raw in (explicit, env_path):
        if raw:
            path = Path(raw).expanduser()
            if _is_executable(path):
                return path.resolve()

    search_dirs = [
        _package_root() / "thirdparty",
        _package_root() / "thirdparty" / "bin",
        Path.cwd() / "thirdparty",
        Path.cwd() / "thirdparty" / "bin",
    ]
    for directory in search_dirs:
        for name in _candidate_names():
            path = directory / name
            if _is_executable(path):
                return path.resolve()

    found = shutil.which("codebase-memory-mcp")
    return Path(found).resolve() if found else None


def cbm_install_hint() -> str:
    names = ", ".join(_candidate_names())
    return (
        "codebase-memory-mcp binary not found. Install it from "
        "https://github.com/DeusData/codebase-memory-mcp/releases and either put it in PATH, "
        "set UNDERSTAND_OPERATOR_CBM_BIN, configure [scanner].cbm_binary, or place it under "
        f"{_package_root() / 'thirdparty'} as {names}."
    )
