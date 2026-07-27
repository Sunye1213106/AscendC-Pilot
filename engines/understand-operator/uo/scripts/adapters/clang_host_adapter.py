"""可选 Clang Host adapter。

仅当发现有效 compile_commands.json 或明确 CANN include/define 时启用。
只输出 function/call/assignment/return/if/template/macro expansion location/source span。
不得直接产生 AscendC 语义。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _find_compile_commands(repo_root: Path) -> Path | None:
    for candidate in (
        repo_root / "compile_commands.json",
        repo_root / "build" / "compile_commands.json",
        repo_root / ".cache" / "compile_commands.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def try_extract_host_ast_facts(
    repo_root: Path,
    source_files: list[Path],
    *,
    include_paths: list[str] | None = None,
    defines: dict[str, str] | None = None,
) -> dict[str, Any]:
    """尝试 Clang；不可用时返回 degraded，不抛异常阻断主链。"""
    del source_files  # 第一版仅探测环境，不跑全量 AST
    cc = _find_compile_commands(repo_root)
    has_cann = bool(include_paths) or bool(defines)
    if cc is None and not has_cann:
        return {
            "enabled": False,
            "status": "disabled",
            "reason": "未发现 compile_commands.json 且无显式 CANN include/define",
            "facts": [],
        }

    # 探测 libclang / clang.cindex 是否可用
    try:
        import clang.cindex  # type: ignore  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": False,
            "status": "degraded",
            "reason": f"libclang 不可用: {exc}"[:300],
            "facts": [],
            "compile_commands": str(cc) if cc else "",
        }

    # 第一版：仅记录探测成功，不强制跑全量 AST（避免强依赖与超时）
    meta: dict[str, Any] = {}
    if cc is not None:
        try:
            meta["compile_commands_entries"] = len(json.loads(cc.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            meta["compile_commands_entries"] = -1

    return {
        "enabled": True,
        "status": "ok",
        "reason": "clang_detected_probe_only",
        "facts": [],
        "compile_commands": str(cc) if cc else "",
        "meta": meta,
        "note": "Clang 结果不得直接产生 AscendC 语义，需经 macro contract 物化",
    }
