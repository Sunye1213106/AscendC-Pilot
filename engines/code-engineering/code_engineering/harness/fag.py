# -*- coding: utf-8 -*-
"""FlashAttentionScoreGrad adapter over fag_debug_tools CSV + run_fag.py."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path
from typing import Any

from code_engineering.harness import evidence_receipt

_FAG_COLUMNS = [
    "Testcase_Name", "enable", "is_deter", "Level", "Network_Type",
    "B", "N1", "N2", "S1", "S2", "D", "D_V", "Dtype", "out_dtype",
    "sparse_mode", "Layout", "PSE_type", "PSE_shape", "Atten_mask_Shape",
    "Drop_Out_Possibility", "tiling_key",
]


class FagHarnessAdapter:
    def __init__(
        self,
        project_root: Path,
        *,
        architecture: str = "",
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.architecture = architecture
        self.manifest = dict(manifest or {})
        root = self.manifest.get("root")
        self.harness_root = Path(root) if root else self._default_root()
        self.entry = str(self.manifest.get("entry") or "run_fag.py")

    def _default_root(self) -> Path:
        here = self.project_root
        for parent in [here, *here.parents]:
            candidate = parent / "TEST" / "fag_debug_tools"
            if candidate.is_dir():
                return candidate
            sibling = parent / "fag_debug_tools"
            if sibling.is_dir():
                return sibling
        return here / "fag_debug_tools"

    def identity(self) -> dict[str, Any]:
        return {
            "kind": "fag",
            "root": str(self.harness_root),
            "entry": self.entry,
            "architecture": self.architecture,
        }

    def case_schema(self) -> list[str]:
        return list(_FAG_COLUMNS)

    def _corpus_paths(self) -> list[Path]:
        rows = list(self.manifest.get("corpus") or [])
        if not rows:
            rows = [
                "data/fag_arch35_reachable_cases.csv",
                "data/FASG_PSE_cases.csv",
            ]
        return [self.harness_root / rel if not Path(rel).is_absolute() else Path(rel) for rel in rows]

    def load_corpus(self) -> list[dict[str, str]]:
        cases: list[dict[str, str]] = []
        for path in self._corpus_paths():
            if not path.is_file():
                continue
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    cases.append({str(k): "" if v is None else str(v) for k, v in row.items()})
        return cases

    def retrieve(self, scenario: dict[str, Any]) -> list[dict[str, str]]:
        knobs = scenario.get("knobs") if isinstance(scenario.get("knobs"), dict) else {}
        sid = str(scenario.get("id") or "")
        budget = int((scenario.get("budget") or {}).get("max_cases") or 4)
        if sid == "P-ILLEGAL":
            budget = max(budget, 4)
        hits: list[dict[str, str]] = []
        for row in self.load_corpus():
            if sid == "P-ILLEGAL":
                if str(row.get("enable") or row.get("Enable") or "").lower() == "disable":
                    hits.append(row)
            elif knobs.get("dtype") and str(row.get("Dtype") or row.get("dtype") or "").lower() not in {
                str(v).lower() for v in (knobs["dtype"] if isinstance(knobs["dtype"], list) else [knobs["dtype"]])
            }:
                continue
            else:
                hits.append(row)
            if len(hits) >= max(budget, 0):
                break
        return hits[: max(budget, 0)]

    def emit(self, cases: list[dict[str, Any]], dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(_FAG_COLUMNS)
        extra = sorted({key for row in cases for key in row} - set(fieldnames))
        fieldnames.extend(extra)
        with dest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for index, row in enumerate(cases, start=1):
                payload = {key: row.get(key, "") for key in fieldnames}
                payload.setdefault("Testcase_Name", f"scenario_{index}")
                payload.setdefault("enable", "enable")
                writer.writerow(payload)
        return dest

    def run(self, csv_path: Path, mode: str) -> dict[str, Any]:
        script = self.harness_root / self.entry
        if not script.is_file():
            return {"ok": False, "mode": mode, "reason": "harness_missing", "csv": str(csv_path)}
        pta = "only_grad" if mode in {"only_grad", "precision"} else "profiler"
        cmd = [
            sys.executable, "-u", str(script),
            "--case", str(csv_path),
            "--pta_mode", pta,
            "--golden-only" if pta == "only_grad" else "--pta",
        ]
        try:
            proc = subprocess.run(cmd, cwd=str(self.harness_root), capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ok": False,
                "mode": mode,
                "reason": "harness_run_failed",
                "error": str(exc)[:200],
                "csv": str(csv_path),
            }
        return {
            "ok": proc.returncode == 0,
            "mode": pta,
            "reason": "" if proc.returncode == 0 else "harness_run_failed",
            "returncode": proc.returncode,
            "csv": str(csv_path),
        }

    def to_evidence(
        self,
        result: dict[str, Any],
        *,
        change_head_sha: str,
        obligation_ids: list[str],
    ) -> dict[str, Any]:
        ok = bool(result.get("ok")) and str(result.get("reason") or "") not in {
            "harness_missing", "harness_run_failed",
        }
        kind = "precision_compare" if result.get("mode") in {"only_grad", "precision"} else "profiling"
        return evidence_receipt(
            change_head_sha=change_head_sha,
            obligation_ids=obligation_ids if ok else [],
            kind=kind,
            artifact=str(result.get("csv") or ""),
            ok=ok,
            reason=str(result.get("reason") or ""),
        )
