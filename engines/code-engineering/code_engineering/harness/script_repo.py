# -*- coding: utf-8 -*-
"""Generic adapter over an operator test-script repository.

Driven by ``tg-test-repo/v1`` (or a local harness manifest). No operator
name, column list, or runner flag is hardcoded here.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path
from typing import Any

from code_engineering.harness import evidence_receipt


class ScriptRepoAdapter:
    def __init__(
        self,
        project_root: Path,
        *,
        architecture: str = "",
        manifest: dict[str, Any] | None = None,
        contract: dict[str, Any] | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.architecture = architecture
        self.manifest = dict(manifest or {})
        self.contract = dict(contract or {})
        root = self.contract.get("root") or self.manifest.get("root") or ""
        self.harness_root = Path(root).expanduser() if root else self.project_root
        self.entry = str(
            self.contract.get("entry") or self.manifest.get("entry") or ""
        )
        self.case_arg = str(self.contract.get("case_arg") or self.manifest.get("case_arg") or "")
        modes = self.contract.get("modes") if isinstance(self.contract.get("modes"), dict) else {}
        man_modes = self.manifest.get("modes") if isinstance(self.manifest.get("modes"), dict) else {}
        self.modes = {
            "precision": list(modes.get("precision") or man_modes.get("precision") or []),
            "perf": list(modes.get("perf") or man_modes.get("perf") or []),
        }
        corpus = self.contract.get("corpus") or self.manifest.get("corpus") or []
        self.corpus = [str(item) for item in corpus if item]

    def identity(self) -> dict[str, Any]:
        return {
            "kind": "script_repo",
            "root": str(self.harness_root),
            "entry": self.entry,
            "architecture": self.architecture,
        }

    def case_schema(self) -> list[str]:
        cols = [str(c) for c in (self.contract.get("columns") or []) if str(c)]
        if cols:
            return cols
        man = [str(c) for c in (self.manifest.get("columns") or []) if str(c)]
        return man or ["Testcase_Name"]

    def _corpus_paths(self) -> list[Path]:
        out: list[Path] = []
        for rel in self.corpus:
            path = Path(rel)
            out.append(path if path.is_absolute() else self.harness_root / rel)
        return out

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
                if _enable_value(row).lower() == "disable":
                    hits.append(row)
            elif knobs and not _knob_match(row, knobs):
                continue
            else:
                hits.append(row)
            if len(hits) >= max(budget, 0):
                break
        return hits[: max(budget, 0)]

    def emit(self, cases: list[dict[str, Any]], dest: Path) -> Path:
        import sys

        tg_src = Path(__file__).resolve().parents[3] / "testcase-generation"
        if str(tg_src) not in sys.path:
            sys.path.insert(0, str(tg_src))
        from testcase_agent.test_repo import disable_illegal_row, fill_row

        dest.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(self.case_schema())
        rows: list[dict[str, str]] = []
        if not cases:
            rows.append(fill_row(self.contract, name="default_input"))
        for index, raw in enumerate(cases, start=1):
            payload = fill_row(
                self.contract,
                {str(k): v for k, v in dict(raw).items()},
                name=str(raw.get("Testcase_Name") or f"case_{index}"),
                extra=dict(raw),
            )
            if str(raw.get("enable") or "").lower() == "disable":
                payload = disable_illegal_row(self.contract, payload)
            rows.append(payload)
            for key in payload:
                if key not in fieldnames:
                    fieldnames.append(key)
        with dest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return dest

    def run(self, csv_path: Path, mode: str) -> dict[str, Any]:
        script = self.harness_root / self.entry if self.entry else Path()
        if not self.entry or not script.is_file():
            return {"ok": False, "mode": mode, "reason": "harness_missing", "csv": str(csv_path)}
        flags = self._flags_for(mode)
        cmd = [sys.executable, "-u", str(script)]
        if self.case_arg:
            cmd.extend([self.case_arg, str(csv_path)])
        else:
            cmd.append(str(csv_path))
        cmd.extend(str(part) for part in flags if part)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.harness_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
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
            "mode": mode,
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
            "harness_missing",
            "harness_run_failed",
        }
        raw_mode = str(result.get("mode") or "")
        kind = "precision_compare" if raw_mode in {"precision", "only_grad", "golden"} else "profiling"
        return evidence_receipt(
            change_head_sha=change_head_sha,
            obligation_ids=obligation_ids if ok else [],
            kind=kind,
            artifact=str(result.get("csv") or ""),
            ok=ok,
            reason=str(result.get("reason") or ""),
        )

    def _flags_for(self, mode: str) -> list[str]:
        key = "precision" if mode in {"precision", "only_grad", "golden", "auto_grad"} else "perf"
        if mode in {"profiler", "perf", "profiling"}:
            key = "perf"
        return [str(part) for part in (self.modes.get(key) or [])]


def _enable_value(row: dict[str, str]) -> str:
    for key in ("enable", "Enable", "ENABLE"):
        if key in row:
            return str(row.get(key) or "")
    return ""


def _knob_match(row: dict[str, str], knobs: dict[str, Any]) -> bool:
    folded = {"".join(ch for ch in str(k).lower() if ch.isalnum()): str(v) for k, v in row.items()}
    for name, raw in knobs.items():
        want = {str(v).lower() for v in (raw if isinstance(raw, list) else [raw])}
        key = "".join(ch for ch in str(name).lower() if ch.isalnum())
        got = folded.get(key)
        if got is None:
            continue
        if got.lower() not in want:
            return False
    return True
