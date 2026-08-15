# -*- coding: utf-8 -*-
"""Fallback adapter when no operator test-script repository is configured.

Generated cases use InputSemantics / knob defaults (or a tiling_key column)
instead of a harness CSV schema.
"""

from __future__ import annotations

import csv
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
        return {"kind": "default_input", "architecture": self.architecture}

    def _defaults(self) -> dict[str, Any]:
        try:
            from replay import inputs as I

            sem = getattr(I, "SEMANTICS", None)
            if sem is None or not hasattr(sem, "knob_schema"):
                return {}
            out: dict[str, Any] = {}
            for name, meta in (sem.knob_schema() or {}).items():
                if isinstance(meta, dict) and "default" in meta:
                    out[str(name)] = meta["default"]
            return out
        except Exception:
            return {}

    def case_schema(self) -> list[str]:
        knobs = list(self._defaults())
        cols = ["Testcase_Name"]
        if "tiling_key" not in knobs:
            cols.append("tiling_key")
        cols.extend(knobs)
        return cols

    def load_corpus(self) -> list[dict[str, str]]:
        return []

    def retrieve(self, scenario: dict[str, Any]) -> list[dict[str, str]]:
        del scenario
        return []

    def emit(self, cases: list[dict[str, Any]], dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        defaults = self._defaults()
        fieldnames = list(self.case_schema())
        rows = list(cases) or [{}]
        extra = sorted({key for row in rows for key in row} - set(fieldnames))
        fieldnames.extend(str(k) for k in extra)
        with dest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for index, raw in enumerate(rows, start=1):
                payload = {key: defaults.get(key, "") for key in fieldnames}
                payload.update({str(k): "" if v is None else str(v) for k, v in dict(raw).items()})
                payload.setdefault("Testcase_Name", f"default_{index}")
                payload.setdefault("tiling_key", payload.get("tiling_key") or "")
                writer.writerow(payload)
        return dest

    def run(self, csv_path: Path, mode: str) -> dict[str, Any]:
        if mode in {"only_grad", "precision", "profiler", "perf", "golden"}:
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
