from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def step2_fact_paths(uo_root: Path) -> list[Path]:
    return [
        uo_root / "facts" / "host.yaml",
        uo_root / "facts" / "compute.yaml",
        uo_root / "facts" / "kernel" / "overview.yaml",
    ]


def step2_fact_hashes(uo_root: Path) -> dict[str, str]:
    return _hash_existing(uo_root, step2_fact_paths(uo_root))


def all_fact_hashes(uo_root: Path) -> dict[str, str]:
    facts = uo_root / "facts"
    if not facts.exists():
        return {}
    return _hash_existing(uo_root, sorted(path for path in facts.rglob("*.yaml") if path.is_file()))


def _hash_existing(uo_root: Path, paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        if path.is_file():
            result[path.relative_to(uo_root).as_posix()] = file_hash(path)
    return result
