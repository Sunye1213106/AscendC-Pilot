# -*- coding: utf-8 -*-
"""Generic test-harness adapter protocol and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

SCHEMA = "ce-external-evidence/v1"


@runtime_checkable
class TestHarnessAdapter(Protocol):
    def identity(self) -> dict[str, Any]:
        ...

    def case_schema(self) -> list[str]:
        ...

    def load_corpus(self) -> list[dict[str, str]]:
        ...

    def retrieve(self, scenario: dict[str, Any]) -> list[dict[str, str]]:
        ...

    def emit(self, cases: list[dict[str, Any]], dest: Path) -> Path:
        ...

    def run(self, csv_path: Path, mode: str) -> dict[str, Any]:
        ...

    def to_evidence(
        self,
        result: dict[str, Any],
        *,
        change_head_sha: str,
        obligation_ids: list[str],
    ) -> dict[str, Any]:
        ...


def load_manifest(project_root: Path | str, architecture: str = "") -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    pilot = root / ".ascendc-pilot"
    scoped = pilot / architecture if architecture else pilot
    path = scoped / "local" / "harness" / "manifest.yaml"
    if not path.is_file():
        fallback = root / "local" / "harness" / "manifest.yaml"
        path = fallback if fallback.is_file() else path
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def load_adapter(project_root: Path | str, architecture: str = "") -> TestHarnessAdapter:
    manifest = load_manifest(project_root, architecture)
    kind = str(manifest.get("kind") or "").strip().lower()
    if kind == "fag":
        from code_engineering.harness.fag import FagHarnessAdapter

        return FagHarnessAdapter(Path(project_root), architecture=architecture, manifest=manifest)
    from code_engineering.harness.host_replay import HostReplayAdapter

    return HostReplayAdapter(Path(project_root), architecture=architecture, manifest=manifest)


def evidence_receipt(
    *,
    change_head_sha: str,
    obligation_ids: list[str],
    kind: str,
    artifact: str,
    ok: bool,
    reason: str = "",
) -> dict[str, Any]:
    verified = list(obligation_ids) if ok and obligation_ids else []
    return {
        "schema": SCHEMA,
        "change_head_sha": change_head_sha,
        "verified_obligations": verified,
        "kind": kind,
        "artifact": artifact,
        "ok": ok,
        "reason": reason,
    }
