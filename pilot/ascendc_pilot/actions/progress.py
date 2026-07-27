"""Action 阶段进度与 heartbeat（CLI stdout + progress.yaml + events.jsonl）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import yaml

from ascendc_pilot.paths import agent_root
from ascendc_pilot.runs import append_event


def _now_ms() -> int:
    return int(time.time() * 1000)


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


class ActionProgressReporter:
    """统一进度报告；禁止在各脚本里散落 print。"""

    def __init__(
        self,
        project_root: Path,
        *,
        run_id: str,
        action_id: str,
        phase: str = "prepare",
        heartbeat_interval_s: float = 8.0,
    ) -> None:
        self.project_root = Path(project_root)
        self.run_id = str(run_id or "")
        self.action_id = str(action_id or "")
        self.phase = str(phase or "prepare")
        self.heartbeat_interval_s = float(heartbeat_interval_s)
        self._stage_id = ""
        self._stage_started_ms = 0
        self._last_heartbeat_ms = 0
        self._stages: list[dict[str, Any]] = []
        self._progress_path = (
            agent_root(self.project_root)
            / "runs"
            / self.run_id
            / "actions"
            / self.action_id
            / "progress.yaml"
        )

    def _emit(self, line: str) -> None:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass

    def _prefix(self, stage_id: str | None = None) -> str:
        sid = stage_id or self._stage_id or "-"
        return f"[{self.action_id}][{self.phase}][{sid}]"

    def _flush_progress(self, extra: dict[str, Any] | None = None) -> None:
        doc: dict[str, Any] = {
            "version": 1,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "phase": self.phase,
            "current_stage": self._stage_id or None,
            "stages": list(self._stages),
            "updated_at_ms": _now_ms(),
        }
        if extra:
            doc.update(extra)
        try:
            self._progress_path.parent.mkdir(parents=True, exist_ok=True)
            _dump_yaml(self._progress_path, doc)
        except OSError:
            pass

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.run_id:
            return
        try:
            append_event(
                self.project_root,
                {
                    "type": event_type,
                    "action_id": self.action_id,
                    "phase": self.phase,
                    **payload,
                },
                run_id=self.run_id,
            )
        except Exception:  # noqa: BLE001
            pass

    def start_stage(
        self,
        stage_id: str,
        total: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._stage_id = str(stage_id)
        self._stage_started_ms = _now_ms()
        self._last_heartbeat_ms = self._stage_started_ms
        row: dict[str, Any] = {
            "stage_id": self._stage_id,
            "status": "running",
            "started_at_ms": self._stage_started_ms,
            "total": total,
            "current": 0,
            "metadata": dict(metadata or {}),
        }
        self._stages.append(row)
        self._emit(f"{self._prefix()} started")
        self._flush_progress()
        self._event(
            "action_stage_started",
            {"stage_id": self._stage_id, "total": total, "metadata": dict(metadata or {})},
        )

    def update(
        self,
        current: int | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._stages:
            row = self._stages[-1]
            if current is not None:
                row["current"] = int(current)
            if message:
                row["message"] = message
            if metadata:
                row.setdefault("metadata", {}).update(metadata)
        msg = message or (f"current={current}" if current is not None else "update")
        self._emit(f"{self._prefix()} {msg}")
        self._flush_progress()
        self.maybe_heartbeat(message=message)

    def heartbeat(self, message: str | None = None) -> None:
        self._last_heartbeat_ms = _now_ms()
        elapsed = self._last_heartbeat_ms - self._stage_started_ms
        text = message or "heartbeat"
        self._emit(f"{self._prefix()} heartbeat elapsed_ms={elapsed} {text}")
        self._flush_progress({"last_heartbeat_ms": self._last_heartbeat_ms})
        self._event(
            "action_stage_heartbeat",
            {"stage_id": self._stage_id, "elapsed_ms": elapsed, "message": text},
        )

    def maybe_heartbeat(self, message: str | None = None) -> None:
        now = _now_ms()
        if (now - self._last_heartbeat_ms) >= int(self.heartbeat_interval_s * 1000):
            self.heartbeat(message=message)

    def complete_stage(self, metadata: dict[str, Any] | None = None) -> None:
        elapsed = _now_ms() - self._stage_started_ms
        if self._stages:
            row = self._stages[-1]
            row["status"] = "completed"
            row["elapsed_ms"] = elapsed
            if metadata:
                row.setdefault("metadata", {}).update(metadata)
        self._emit(f"{self._prefix()} completed elapsed_ms={elapsed}")
        self._flush_progress()
        self._event(
            "action_stage_completed",
            {"stage_id": self._stage_id, "elapsed_ms": elapsed, "metadata": dict(metadata or {})},
        )
        self._stage_id = ""

    def fail_stage(
        self,
        error_code: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        elapsed = _now_ms() - self._stage_started_ms if self._stage_started_ms else 0
        if self._stages:
            row = self._stages[-1]
            row["status"] = "failed"
            row["elapsed_ms"] = elapsed
            row["error_code"] = error_code
            row["message"] = message
            if metadata:
                row.setdefault("metadata", {}).update(metadata)
        self._emit(f"{self._prefix()} FAILED error={error_code} {message}")
        self._flush_progress()
        self._event(
            "action_stage_failed",
            {
                "stage_id": self._stage_id,
                "error_code": error_code,
                "message": message,
                "elapsed_ms": elapsed,
            },
        )
        payload = {
            "ok": False,
            "error": "EXTRACT_PLAN_STAGE_FAILED",
            "stage": self._stage_id or self.phase,
            "error_code": error_code,
            "message": message,
            "elapsed_ms": elapsed,
            "retryable": True,
            "metadata": dict(metadata or {}),
        }
        self._stage_id = ""
        return payload


__all__ = ["ActionProgressReporter"]
