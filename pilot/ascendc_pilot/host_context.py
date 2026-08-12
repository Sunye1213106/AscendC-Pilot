"""Host adapter context resolver — single authority for OpenCode plugin paths.

Returns arch-scoped workflow/active_action paths so the Host must not hardcode
``.ascendc-pilot/state/...`` flat layout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ascendc_pilot.paths import AGENT_DIR, STATE_SUBDIR, agent_root, state_root


def _list_arch_candidates(project_root: Path) -> list[str]:
    root = Path(project_root).expanduser().resolve() / AGENT_DIR
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / STATE_SUBDIR / "workflow.yaml").is_file()
    )


def _active_action_payload(project_root: Path, *, arch: str | None) -> dict[str, Any]:
    path = state_root(project_root, arch=arch) / "active_action.yaml"
    if not path.is_file():
        return {"path": str(path), "action_id": "", "actor_id": ""}
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    return {
        "path": str(path),
        "action_id": str(doc.get("action_id") or "").strip(),
        "actor_id": str(doc.get("actor_id") or "").strip(),
    }


def build_host_context(
    project_root: Path | str,
    *,
    architecture: str = "",
) -> dict[str, Any]:
    """Resolve Host-facing paths and active action identity.

    Fail-closed on architecture ambiguity / missing state, but always returns
    ``project_root`` and ``architectures`` so the Host can render AskQuestion.
    """
    from ascendc_pilot.human_interaction import pending_path
    from ascendc_pilot.intake import discover_architectures
    from ascendc_pilot.state import load_state, workflow_state_path

    root = Path(project_root).expanduser().resolve()
    tree_arches = discover_architectures(root)
    state_arches = _list_arch_candidates(root)
    architectures = sorted(set(tree_arches) | set(state_arches))

    pending = pending_path(root)
    base: dict[str, Any] = {
        "ok": False,
        "project_root": str(root),
        "architectures": architectures,
        "pending_interaction_path": str(pending),
        "architecture": "",
        "workflow_state_path": "",
        "active_action_path": "",
        "run_id": "",
        "workflow_id": "",
        "phase": "",
        "status": "",
        "action_id": "",
        "actor_id": "",
    }

    arch = str(architecture or "").strip()
    if not arch:
        try:
            from ascendc_pilot.paths import discover_arch

            arch = discover_arch(root)
        except ValueError as exc:
            msg = str(exc)
            code = "ARCHITECTURE_MISSING_IN_RUN_STATE"
            if "ARCHITECTURE_AMBIGUOUS" in msg or "multiple architectures" in msg:
                code = "ARCHITECTURE_AMBIGUOUS"
            base["error"] = code
            base["message_zh"] = msg
            return base

    base["architecture"] = arch
    try:
        wf_path = workflow_state_path(root, arch=arch)
        aa = _active_action_payload(root, arch=arch)
    except ValueError as exc:
        base["error"] = "ARCHITECTURE_MISSING_IN_RUN_STATE"
        base["message_zh"] = str(exc)
        return base

    base["workflow_state_path"] = str(wf_path)
    base["active_action_path"] = str(aa["path"])
    base["action_id"] = str(aa.get("action_id") or "")
    base["actor_id"] = str(aa.get("actor_id") or "")

    state = load_state(root, arch=arch) or {}
    if not state:
        base["error"] = "NO_ACTIVE_WORKFLOW"
        base["message_zh"] = f"no workflow.yaml under .ascendc-pilot/{arch}/state"
        return base

    base["ok"] = True
    base["run_id"] = str(state.get("run_id") or "")
    base["workflow_id"] = str(state.get("workflow_id") or "")
    base["phase"] = str(state.get("phase") or "")
    base["status"] = str(state.get("status") or "")
    # Prefer active_action.yaml identity; fall back to state fields if present.
    if not base["action_id"]:
        base["action_id"] = str(state.get("active_action_id") or "")
    if not base["actor_id"]:
        base["actor_id"] = str(state.get("active_actor_id") or "")
    try:
        from ascendc_pilot.active_run import active_run_path

        base["active_run_path"] = str(active_run_path(root))
    except Exception:  # noqa: BLE001
        base["active_run_path"] = ""
    return base
