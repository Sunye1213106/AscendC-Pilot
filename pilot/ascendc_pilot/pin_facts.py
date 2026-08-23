"""This-run operator pin for host_step / complete payloads.

This module is NOT change_contract. It only carries next_project /
next_architecture / selected_by onto the live Host run state so
compactPilotRunPayload can keep the operator pin. PR changed_files
belong on operator clone_receipt.yaml (candidate) and change_contract.yaml
(SSOT after pin-facts promote). Host state must not persist changed_files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

DONE_ZH = "工作流已完成；已释放本产物族锁。"


def persist_pin_on_state(
    project_root: Path,
    *,
    next_project: str = "",
    next_architecture: str = "",
    selected_by: str = "",
    message_zh: str = "",
) -> None:
    from ascendc_pilot.state import load_state, save_state

    root = Path(project_root).expanduser().resolve()
    st = load_state(root)
    if not st:
        return
    if next_project:
        st["next_project"] = str(next_project)
    if next_architecture:
        st["next_architecture"] = str(next_architecture)
    if selected_by:
        st["selected_by"] = str(selected_by)
    if message_zh:
        st["pin_message_zh"] = str(message_zh)
    save_state(root, st)


def pin_view(*sources: Any) -> dict[str, Any]:
    """First nonempty pin field wins. ``architecture: goal`` is not a pin."""
    out: dict[str, Any] = {
        "project": "",
        "architecture": "",
        "selected_by": "",
        "changed_files": [],
        "changed_files_preview": [],
        "pin_message_zh": "",
    }
    for src in sources:
        if not isinstance(src, dict):
            continue
        project = str(
            src.get("next_project")
            or src.get("user_goal_next_project")
            or src.get("project")
            or ""
        ).strip()
        architecture = str(
            src.get("next_architecture")
            or src.get("user_goal_next_architecture")
            or ""
        ).strip()
        if not architecture:
            raw_arch = str(src.get("architecture") or "").strip()
            if raw_arch and raw_arch != "goal":
                architecture = raw_arch
        selected_by = str(src.get("selected_by") or "").strip()
        changed = [
            str(x).strip()
            for x in (src.get("changed_files") or src.get("changed_files_preview") or [])
            if str(x).strip()
        ]
        pin_zh = str(src.get("pin_message_zh") or "").strip()
        if project and not out["project"]:
            out["project"] = project
        if architecture and not out["architecture"]:
            out["architecture"] = architecture
        if selected_by and not out["selected_by"]:
            out["selected_by"] = selected_by
        if changed and not out["changed_files"]:
            out["changed_files"] = changed
        if pin_zh and not out["pin_message_zh"]:
            out["pin_message_zh"] = pin_zh
    out["changed_files_preview"] = list(out["changed_files"][:40])
    return out


def merge_pin_message(existing: str, pin_zh: str) -> str:
    facts = str(pin_zh or "").strip()
    current = str(existing or "").strip()
    if facts:
        if not current or current == DONE_ZH:
            current = facts
        elif facts not in current:
            current = f"{facts} {current}".strip()
    if DONE_ZH not in current:
        current = f"{current} {DONE_ZH}".strip() if current else DONE_ZH
    return current


def apply_pin_to_payload(payload: dict[str, Any], *sources: Any) -> dict[str, Any]:
    view = pin_view(*sources)
    if not str(payload.get("message_zh") or "").strip():
        for src in sources:
            if isinstance(src, dict) and str(src.get("message_zh") or "").strip():
                payload["message_zh"] = str(src.get("message_zh") or "")
                break
    if view["project"]:
        payload["project"] = view["project"]
        if not payload.get("user_goal_next_project"):
            payload["user_goal_next_project"] = view["project"]
    if view["architecture"]:
        payload["architecture"] = view["architecture"]
        if not payload.get("user_goal_next_architecture"):
            payload["user_goal_next_architecture"] = view["architecture"]
    if view["selected_by"]:
        payload["selected_by"] = view["selected_by"]
    if view["changed_files"]:
        payload["changed_files"] = list(view["changed_files"])
        payload["changed_files_preview"] = list(view["changed_files_preview"])
    pin_zh = view["pin_message_zh"]
    payload["message_zh"] = merge_pin_message(str(payload.get("message_zh") or ""), pin_zh)
    return payload


def host_step_pin_extra(payload: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key in (
        "project",
        "architecture",
        "selected_by",
        "changed_files",
        "changed_files_preview",
    ):
        value = payload.get(key)
        if value in (None, "", []):
            continue
        extra[key] = value
    return extra
