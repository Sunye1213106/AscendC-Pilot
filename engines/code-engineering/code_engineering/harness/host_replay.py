# -*- coding: utf-8 -*-
"""Fallback adapter when no operator test harness is configured."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from code_engineering.harness import evidence_receipt


class HostReplayAdapter:
    def __init__(
        self,
        project_root: Path,
        *,
        architecture: str = "",
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.architecture = architecture
        self.manifest = dict(manifest or {})

    def identity(self) -> dict[str, Any]:
        return {"kind": "host_replay", "architecture": self.architecture}

    def case_schema(self) -> list[str]:
        return ["Testcase_Name", "tiling_key"]

    def load_corpus(self) -> list[dict[str, str]]:
        return []

    def retrieve(self, scenario: dict[str, Any]) -> list[dict[str, str]]:
        return []

    def emit(self, cases: list[dict[str, Any]], dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("Testcase_Name,tiling_key\n", encoding="utf-8")
        return dest

    def run(self, csv_path: Path, mode: str) -> dict[str, Any]:
        if mode in {"only_grad", "precision", "profiler", "perf"}:
            return {
                "ok": False,
                "mode": mode,
                "reason": "harness_missing",
                "csv": str(csv_path),
            }
        return {"ok": True, "mode": "host_replay", "reason": "", "csv": str(csv_path)}

    def to_evidence(
        self,
        result: dict[str, Any],
        *,
        change_head_sha: str,
        obligation_ids: list[str],
    ) -> dict[str, Any]:
        reason = str(result.get("reason") or "")
        ok = bool(result.get("ok")) and reason != "harness_missing"
        return evidence_receipt(
            change_head_sha=change_head_sha,
            obligation_ids=obligation_ids if ok else [],
            kind="host_replay",
            artifact=str(result.get("csv") or ""),
            ok=ok,
            reason=reason or ("harness_missing" if not ok else ""),
        )
