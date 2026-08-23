"""Deterministic engine entrypoints invoked by Host `pilot_run` (internal run-action)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable


EngineFn = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _uo(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import uo_root

    return uo_root(project_root, arch=arch)


def _tg(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import tg_root

    return tg_root(project_root, arch=arch)


def _ctx_root(project_root: Path, *, arch: str | None = None):
    from ascendc_pilot.paths import context_root

    return context_root(project_root, arch=arch)


def _ce(project_root: Path, *, arch: str | None = None) -> Path:
    from ascendc_pilot.paths import agent_root

    return agent_root(project_root, arch) / "ce"


def _resolve_ce_arch(project_root: Path, ctx: dict[str, Any]) -> str:
    from ascendc_pilot.paths import discover_arch

    return str(ctx.get("architecture") or "").strip() or discover_arch(project_root)


def _dump_ce_yaml(path: Path, doc: Any) -> Path:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _write_run_receipt(
    project_root: Path,
    ctx: dict[str, Any] | None,
    filename: str,
    payload: dict[str, Any],
) -> Path:
    """Write a gate/check receipt under ``runs/<run_id>/receipts/``."""
    import yaml

    from ascendc_pilot.runs import receipts_dir

    ctx = dict(ctx or {})
    run_id = str(ctx.get("run_id") or "").strip()
    if not run_id:
        try:
            from ascendc_pilot.state import load_state

            st = load_state(project_root) or {}
            run_id = str(st.get("run_id") or "").strip()
            for key in ("workflow_id", "action_id", "architecture"):
                if not ctx.get(key) and st.get(key):
                    ctx[key] = st.get(key)
        except Exception:  # noqa: BLE001
            run_id = ""
    body = dict(payload)
    body.setdefault("kind", "receipt")
    if run_id:
        body.setdefault("run_id", run_id)
    for key in ("workflow_id", "action_id", "architecture"):
        val = ctx.get(key)
        if val and key not in body:
            body[key] = val
    out = receipts_dir(project_root, run_id or None) / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out



def _run_ce_kb_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.gates import run_named_gate

    arch = _resolve_ce_arch(project_root, ctx)
    gate = run_named_gate(
        project_root,
        "kb_ready",
        op_name=str(ctx.get("op_name") or "") or None,
        architecture=arch,
    )
    return {"ok": bool(gate.get("ok")), "engine": "kb_check", "gate": gate}


def _ce_state(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        from ascendc_pilot.state import load_state

        live = load_state(project_root) or {}
    except Exception:  # noqa: BLE001
        live = {}
    merged = dict(live)
    merged.update({k: v for k, v in ctx.items() if v not in (None, "")})
    return merged


def _run_ce_apply_gate(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.apply import apply_gate

    arch = _resolve_ce_arch(project_root, ctx)
    return apply_gate(project_root, architecture=arch, state=_ce_state(project_root, ctx))


def _run_ce_plan_revise_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.paths import runs_root
    from code_engineering.plan_md import resolve_active_plan, validate_plan_revision

    arch = _resolve_ce_arch(project_root, ctx)
    state = _ce_state(project_root, ctx)
    plan = resolve_active_plan(project_root, architecture=arch, state=state)
    run_id = str((state or {}).get("run_id") or ctx.get("run_id") or "")
    before: list[dict[str, Any]] = []
    if run_id:
        baseline_path = (
            runs_root(project_root, arch=arch or None)
            / run_id
            / "actions"
            / "plan_revise"
            / "baseline.yaml"
        )
        if baseline_path.is_file():
            import yaml

            doc = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) or {}
            if isinstance(doc, dict):
                before = [row for row in (doc.get("todos") or []) if isinstance(row, dict)]
    if plan is None:
        return {
            "ok": False,
            "engine": "plan_revise_check",
            "reason_code": "APPLY_PLAN_MISSING",
            "message_zh": "修订后仍没有当前计划 markdown。",
        }
    checked = validate_plan_revision(before=before, after_path=plan)
    checked["engine"] = "plan_revise_check"
    checked["plan"] = plan.as_posix()
    return checked


def _run_ce_patch_guard(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from code_engineering.apply import patch_guard

    arch = _resolve_ce_arch(project_root, ctx)
    return patch_guard(project_root, architecture=arch, state=_ce_state(project_root, ctx))


def _hunk_filename(path: str, line: int) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in path.replace("\\", "/"))
    return f"{safe}__{int(line)}.diff"


def _compact_uo_hint(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return str(payload)[:400]
    cards = payload.get("cards") or payload.get("entities") or payload.get("around") or []
    if isinstance(cards, dict):
        cards = [cards]
    bits: list[str] = []
    for card in list(cards)[:4]:
        if not isinstance(card, dict):
            continue
        name = str(card.get("name") or card.get("kind") or "").strip()
        loc = f"{card.get('file') or ''}:{card.get('line') or card.get('line_start') or ''}"
        snip = str(card.get("snippet") or "")[:240].replace("\n", " ")
        bits.append(f"- {name} `{loc}` {snip}".strip())
    if bits:
        return "\n".join(bits)
    for key in ("answer_zh", "message_zh", "error", "reason_code", "hint"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text[:600]
    if payload.get("ok") and (payload.get("count") or payload.get("cards")):
        return "ok"
    return "no card"


def _write_change_capture_artifacts(
    out_dir: Path,
    *,
    diff_text: str,
    project_root: Path,
    architecture: str,
    base_sha: str,
    head_sha: str,
) -> dict[str, str]:
    """Index + hunk windows + bounded uo-query hints. diff.md is forensic only."""
    from code_engineering.change.capture import (
        extract_added_identifiers,
        iter_hunk_windows,
        parse_diff_ranges,
        render_change_index,
        suggested_file_line_queries,
        suggested_ident_queries,
        operator_relative_path,
        _run_git,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = out_dir / "diff.md"
    diff_path.write_text(
        "# Change capture (forensic; do not linearly read)\n\n```diff\n"
        + diff_text.rstrip()
        + "\n```\n",
        encoding="utf-8",
    )
    ranges = parse_diff_ranges(diff_text)
    idents = extract_added_identifiers(diff_text)
    ident_queries = suggested_ident_queries(idents, limit=8)
    line_queries = suggested_file_line_queries(ranges, limit=4)
    queries = ident_queries + line_queries
    log_oneline = ""
    subject = ""
    try:
        if head_sha:
            subject = _run_git(project_root, "log", "-1", "--format=%s", head_sha).strip()
        if base_sha and head_sha:
            log_oneline = _run_git(
                project_root, "log", "--oneline", f"{base_sha}..{head_sha}"
            ).strip()
        elif not log_oneline:
            log_oneline = _run_git(project_root, "log", "--oneline", "-8").strip()
        if not subject and log_oneline:
            subject = log_oneline.splitlines()[0]
    except Exception:  # noqa: BLE001
        log_oneline = log_oneline or ""
    index_path = out_dir / "index.md"
    index_path.write_text(
        render_change_index(
            subject=subject,
            log_oneline=log_oneline,
            base_sha=base_sha,
            head_sha=head_sha,
            ranges={operator_relative_path(p): spans for p, spans in ranges.items()},
            identifiers=idents,
            queries=queries,
        ),
        encoding="utf-8",
    )
    hunk_dir = out_dir / "hunks"
    hunk_dir.mkdir(parents=True, exist_ok=True)
    hunk_paths: list[str] = []
    for path, start, body in iter_hunk_windows(diff_text):
        hp = hunk_dir / _hunk_filename(path, start)
        hp.write_text(f"# {path}:{start}\n\n```diff\n{body}\n```\n", encoding="utf-8")
        hunk_paths.append(hp.as_posix())
    hints_path = out_dir / "uo_hints.md"
    hint_lines = [
        "# UO hints (bounded prefetch)",
        "",
        "Prefer identifier cards from index.md; skip empty format-hunk around queries.",
        "",
    ]
    try:
        from uo_init.uo_query import open_query

        with open_query(project_root, architecture=architecture) as q:
            for item in queries[:8]:
                ident = str(item.get("ident") or "").strip()
                path = str(item.get("file") or "")
                line = int(item.get("line") or 0)
                if ident:
                    hint_lines.append(f"## `{ident}`")
                    hint_lines.append("")
                    try:
                        payload = q.agent_query(pattern=ident, limit=4)
                        hint_lines.append(_compact_uo_hint(payload if isinstance(payload, dict) else {}))
                    except Exception as exc:  # noqa: BLE001
                        hint_lines.append(f"prefetch failed: {exc}"[:400])
                elif path and line:
                    hint_lines.append(f"## `{path}:{line}`")
                    hint_lines.append("")
                    try:
                        payload = q.agent_query(pattern="", file=path, line=line, limit=4)
                        hint_lines.append(_compact_uo_hint(payload if isinstance(payload, dict) else {}))
                    except Exception as exc:  # noqa: BLE001
                        hint_lines.append(f"prefetch failed: {exc}"[:400])
                else:
                    continue
                hint_lines.append("")
    except Exception as exc:  # noqa: BLE001
        hint_lines.append(f"UO product unavailable ({exc}). Run suggested queries from index.md.")
        hint_lines.append("")
    hints_path.write_text("\n".join(hint_lines), encoding="utf-8")
    return {
        "diff": diff_path.as_posix(),
        "index": index_path.as_posix(),
        "uo_hints": hints_path.as_posix(),
        "hunks": str(len(hunk_paths)),
    }


def _run_ce_review_capture(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.paths import agent_root
    from code_engineering.git import capture_change

    arch = _resolve_ce_arch(project_root, ctx)
    pr_url = str(ctx.get("pr_url") or ctx.get("pr") or "").strip()
    intent = str(ctx.get("intent") or "")
    if not pr_url:
        try:
            from ascendc_pilot.intake import extract_pr_url_from_intent

            pr_url = extract_pr_url_from_intent(intent)
        except Exception:  # noqa: BLE001
            pr_url = ""
    capture_root = Path(project_root)
    if pr_url:
        try:
            import sys

            ws = Path(__file__).resolve().parents[3] / "engines" / "workspace"
            if str(ws) not in sys.path:
                sys.path.insert(0, str(ws))
            import pr_workspace as gw  # type: ignore[import-not-found]

            if not gw.is_isolated_pr_tree(capture_root):
                acquire = gw.acquire_pull_request(
                    pr_url,
                    run_id=str(ctx.get("run_id") or "").strip(),
                    workspace_root=capture_root,
                )
                if acquire.get("ok"):
                    resolved = gw.resolve_targets_or_ask(
                        acquire, workflow_id="ce-review", host_root=capture_root
                    )
                    if resolved.get("ok"):
                        capture_root = Path(str(resolved["project"]))
                        if resolved.get("architecture") and not arch:
                            arch = str(resolved["architecture"])
        except Exception:  # noqa: BLE001
            pass
    base = str(ctx.get("base") or "")
    head = str(ctx.get("head") or "")
    if pr_url and (not base or base == "HEAD"):
        try:
            from ascendc_pilot.user_goal import load_user_goal

            goal = load_user_goal(capture_root) or load_user_goal(project_root)
            cs = ((goal or {}).get("artifacts") or {}).get("changeset") or {}
            base = str(cs.get("base_sha") or base)
            head = str(cs.get("head_sha") or head)
        except Exception:  # noqa: BLE001
            pass
    payload = capture_change(
        capture_root,
        architecture=arch,
        base=base,
        head=head,
        pr_url=pr_url,
        intent=intent,
    )
    diff = str(payload.get("diff") or "")
    run_id = str(ctx.get("run_id") or "").strip()
    if run_id and diff.strip():
        out_dir = (
            agent_root(project_root, arch)
            / "runs"
            / run_id
            / "actions"
            / "change_capture"
        )
        artifacts = _write_change_capture_artifacts(
            out_dir,
            diff_text=diff,
            project_root=Path(capture_root),
            architecture=arch,
            base_sha=str(payload.get("base_sha") or base or ""),
            head_sha=str(payload.get("head_sha") or head or ""),
        )
        payload["artifact"] = artifacts.get("index") or artifacts.get("diff")
        payload["artifacts"] = artifacts
    payload.setdefault("engine", "change_capture")
    if not payload.get("ok"):
        payload["ok"] = False
        payload.setdefault("reason_code", "NO_CODE_CHANGE")
    return payload


def _run_ce_codemap_refresh(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Independent UO transaction: never write .uo under the CE apply lock alone."""
    from ascendc_pilot.occupancy import (
        acquire_exclusive_lock,
        live_exclusive_lock,
        live_resource_conflict,
        publish_uo_digest,
        release_exclusive_lock,
    )

    arch = _resolve_ce_arch(project_root, ctx)
    holder = live_exclusive_lock(project_root, "uo")
    if holder:
        return {
            "ok": False,
            "engine": "codemap_refresh",
            "error": "UO_PRODUCT_LOCKED",
            "holder": holder,
            "message_zh": "UO 产物锁被占用，禁止在 CE apply 内静默双写 .uo",
        }
    conflict = live_resource_conflict(
        project_root, "uo-update", ignore_run_id=str(ctx.get("run_id") or "")
    )
    if conflict:
        return {"ok": False, "engine": "codemap_refresh", "error": "UO_REFRESH_CONFLICT", **conflict}

    refresh_run = f"{ctx.get('run_id') or 'CE'}-uo-refresh"
    nested = False
    ok = False
    doc: dict[str, Any] = {}
    try:
        acquire_exclusive_lock(
            project_root,
            occupancy_group="uo",
            workflow_id="uo-update",
            run_id=refresh_run,
            architecture=arch,
            session_id=str(ctx.get("session_id") or ""),
        )
        nested = True
        detect = _run_detect_changes(project_root, ctx)
        plan = _run_plan_update(project_root, ctx)
        applied = _run_apply_update(project_root, ctx)
        export = _run_export_integrity(project_root, ctx)
        diff = _run_diff_summary(project_root, ctx)
        ok = all(bool(step.get("ok")) for step in (detect, plan, applied, export, diff))
        published: dict[str, Any] = {}
        try:
            published = publish_uo_digest(project_root, architecture=arch)
        except Exception as exc:  # noqa: BLE001
            published = {"ok": False, "error": str(exc)[:200]}
        doc = {
            "ok": ok,
            "engine": "codemap_refresh",
            "uo_transaction": refresh_run,
            "uo_digest": published.get("digest") or "",
            "detect": {k: detect.get(k) for k in ("ok", "engine", "error", "scoped_change_count") if k in detect},
            "plan": {k: plan.get(k) for k in ("ok", "engine", "error") if k in plan},
            "apply": {k: applied.get(k) for k in ("ok", "engine", "error") if k in applied},
            "export": {k: export.get(k) for k in ("ok", "engine", "error") if k in export},
            "diff": {k: diff.get(k) for k in ("ok", "engine", "error") if k in diff},
        }
    finally:
        if nested:
            release_exclusive_lock(project_root, "uo", run_id=refresh_run)
    return doc



def _run_export_integrity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Delegate integrity to uo_init.pilot_engines.export_integrity."""
    try:
        from uo_init.pilot_engines import export_integrity

        return export_integrity(Path(project_root), ctx or {})
    except Exception as exc:  # noqa: BLE001
        uo = _uo(project_root)
        gate = uo / "checks" / "integrity.yaml"
        if not gate.is_file():
            gate.parent.mkdir(parents=True, exist_ok=True)
            gate.write_text("status: fail\nmessage: engine_invoke_failed\n", encoding="utf-8")
        return {"ok": False, "errors": [str(exc)[:200]]}


def _run_detect_changes(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_changes", "error": str(exc)[:300]}
    if not op_name:
        return {"ok": False, "engine": "detect_changes", "error": "op_name required"}
    try:
        from uo_init.update import detect_kb_changes

        payload = detect_kb_changes(project_root, op_name, write=True, architecture=arch)
        out = uo / "diff" / "change_set.yaml"
        return {
            "ok": out.is_file(),
            "engine": "detect_changes",
            "artifact": out.as_posix() if out.is_file() else "",
            "scoped_change_count": payload.get("scoped_change_count"),
            "detection": payload.get("detection"),
            "worktree_dirty": payload.get("worktree_dirty"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "detect_changes", "error": str(exc)[:300]}


def _run_plan_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_update", "error": str(exc)[:300]}
    if not op_name:
        return {"ok": False, "engine": "plan_update", "error": "op_name required"}
    try:
        from uo_init.update import detect_kb_changes, load_change_set_if_fresh, plan_kb_update

        change_set = load_change_set_if_fresh(uo, repo_root=project_root)
        reused = change_set is not None
        if change_set is None:
            change_set = detect_kb_changes(project_root, op_name, write=True, architecture=arch)
        plan_kb_update(project_root, op_name, change_set=change_set, write=True, architecture=arch)
        out = uo / "summary" / "update_plan.yaml"
        return {
            "ok": out.is_file(),
            "engine": "plan_update",
            "artifact": out.as_posix() if out.is_file() else "",
            "change_set_reused": reused,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_update", "error": str(exc)[:300]}


def _cann_not_ready(engine: str, ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fail closed with a user-facing CANN hint before clang work."""
    try:
        from uo_init.pilot_engines import _cann_env_block
    except Exception:  # noqa: BLE001
        return None
    return _cann_env_block(engine, ctx)


def _rebuild_failure_from_update(result: dict[str, Any] | None) -> dict[str, Any]:
    """Copy nested prepare_layout / clang errors out of update_operator status=fail."""
    from ascendc_pilot.actions.failure_text import preferred_failure_text

    payload = result if isinstance(result, dict) else {}
    for row in payload.get("action_results") or []:
        if not isinstance(row, dict) or row.get("ok"):
            continue
        inner = row.get("result") if isinstance(row.get("result"), dict) else {}
        merged = {**inner, "error": inner.get("error") or row.get("error")}
        return {
            "ok": False,
            "failed_rebuild_action": row.get("action"),
            "error": str(inner.get("error") or row.get("error") or "rebuild_action_failed"),
            "message_zh": preferred_failure_text(merged, fallback=str(row.get("error") or "")),
            "issues": list(inner.get("issues") or []),
        }
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    msg = str(receipt.get("message") or "")
    return {
        "ok": False,
        "error": msg or "APPLY_UPDATE_FAILED",
        "message_zh": msg,
        "issues": [],
    }


def _run_apply_update(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    blocked = _cann_not_ready("apply_update", ctx)
    if blocked is not None:
        return blocked
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_update", "error": str(exc)[:800]}
    if not op_name:
        return {"ok": False, "engine": "apply_update", "error": "op_name required"}
    run_id = str((ctx or {}).get("run_id") or "").strip()
    try:
        from uo_init.update import update_operator

        result = update_operator(
            project_root,
            op_name,
            architecture=arch,
            run_id=run_id or None,
            reuse_artifacts=True,
            cann_root=str((ctx or {}).get("cann_root") or "") or None,
            ops_root=str((ctx or {}).get("ops_root") or "") or None,
        )
        status = str((result or {}).get("status") or "")
        receipt_ok = any((uo / "runs").glob("*/update/receipt.yaml")) if (uo / "runs").is_dir() else False
        diff_ok = (uo / "diff" / "index.yaml").is_file() and (uo / "diff" / "change_set.yaml").is_file()
        eng_ok = status in {"pass", "blocked", "noop"} or status == "pass"
        if status == "fail":
            eng_ok = False
        payload = {
            "ok": eng_ok and (diff_ok or status == "blocked"),
            "engine": "apply_update",
            "receipt_present": receipt_ok,
            "diff_present": diff_ok,
            "publish_deferred": bool((result or {}).get("publish_deferred")),
            "run_id": (result.get("run_id") if isinstance(result, dict) else None) or run_id,
            "result_keys": list(result.keys())[:12] if isinstance(result, dict) else [],
            "status": status,
        }
        if not payload["ok"]:
            nested = _rebuild_failure_from_update(result if isinstance(result, dict) else {})
            payload["error"] = nested.get("error") or "APPLY_UPDATE_FAILED"
            payload["message_zh"] = nested.get("message_zh") or nested.get("error")
            payload["issues"] = nested.get("issues") or []
            payload["failed_rebuild_action"] = nested.get("failed_rebuild_action") or ""
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "apply_update", "error": str(exc)[:800]}


def _run_diff_summary(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Emit canonical diff/ product from existing change_set/update_plan when fresh."""
    try:
        uo, op_name, arch = _uo_op_ctx(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "diff_summary", "error": str(exc)[:300]}
    if not op_name:
        return {"ok": False, "engine": "diff_summary", "error": "op_name required"}
    try:
        from uo_init.update import (
            detect_kb_changes,
            export_diff_product,
            load_change_set_if_fresh,
            load_update_plan_if_fresh,
            plan_kb_update,
        )

        change_set = load_change_set_if_fresh(uo, repo_root=project_root)
        plan = load_update_plan_if_fresh(uo, change_set=change_set) if change_set else None
        reused = change_set is not None and plan is not None
        if change_set is None:
            change_set = detect_kb_changes(project_root, op_name, write=True, architecture=arch)
        if plan is None:
            plan = plan_kb_update(
                project_root, op_name, change_set=change_set, write=True, architecture=arch
            )
        product = export_diff_product(
            project_root,
            op_name,
            change_set=change_set,
            update_plan=plan,
            write=True,
            architecture=arch,
        )
        return {"ok": True, "engine": "diff_summary", "product": product, "artifacts_reused": reused}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "diff_summary", "error": str(exc)[:300]}


def _run_tg_kb_check(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Require CodeMap ``.uo`` with TG view blobs (D / host_view / graph)."""
    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    ready = _ensure_uo_tg_views(project_root, tg_ctx)
    ok = bool(ready.get("ok")) and int(ready.get("legal_key_count") or 0) > 0
    receipt = {
        "schema": "tg-uo-ready/v1",
        "kind": "receipt",
        "ok": ok,
        "mode": str(tg_ctx.get("mode") or ""),
        "op_name": str(tg_ctx.get("op_name") or ""),
        "architecture": str(tg_ctx.get("architecture") or ""),
        "uo_product": str(ready.get("path") or ""),
        "legal_key_count": int(ready.get("legal_key_count") or 0),
        "error": "" if ok else str(ready.get("error") or "UO TG views not ready"),
    }
    out = _write_run_receipt(project_root, ctx, "uo_ready.yaml", receipt)
    return {
        "ok": ok,
        "engine": "kb_check",
        "mode": receipt["mode"],
        "gate": {
            "gate": "uo_ready",
            "ok": ok,
            "message": "ok" if ok else receipt["error"],
            "detail": ready,
        },
        "uo": ready,
        "receipt_path": out.as_posix(),
    }


def _ensure_uo_tg_views(project_root: Path, tg_ctx: dict[str, Any]) -> dict[str, Any]:
    """Locate ``.uo`` and confirm TPL/D + host/graph view_blobs are readable."""
    try:
        from uo_init.tg_projection import ensure_tg_views

        return ensure_tg_views(
            project_root,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:400]}


def _load_uo_tg_doc(project_root: Path, tg_ctx: dict[str, Any], name: str) -> dict[str, Any]:
    """Load a TG view exclusively from the CodeMap ``.uo`` view_blob."""
    try:
        from testcase_agent import product_uo

        blob = product_uo.view(
            project_root,
            name,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
        return blob if isinstance(blob, dict) else {}
    except Exception:
        return {}


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return None
    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _resolve_tg_ctx(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Resolve op_name / architecture / consumer root / level / focus / mode for TG engines."""
    import os

    from ascendc_pilot.paths import discover_arch, resolve_arch
    from ascendc_pilot.state import load_state

    # Prefer ctx.architecture; otherwise discover (env → active_run → sole workflow).
    # Do not call resolve_arch(None): that only reads env and breaks fresh acp
    # subprocesses after start already pinned active_run.yaml.
    arch_explicit = str(ctx.get("architecture") or "").strip() or None
    try:
        arch_hint = (
            resolve_arch(arch_explicit)
            if arch_explicit
            else discover_arch(project_root)
        )
    except ValueError as exc:
        text = str(exc)
        if "ARCHITECTURE_AMBIGUOUS" in text:
            raise
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE") from exc
    state = load_state(project_root) or {}
    params = _load_yaml(_ctx_root(project_root, arch=arch_hint) / "pilot_params.yaml") or {}
    if not isinstance(params, dict):
        params = {}
    run_ctx = _load_yaml(_tg(project_root, arch=arch_hint) / "init.yaml") or {}
    if not isinstance(run_ctx, dict):
        run_ctx = {}
    init_intent = run_ctx
    plan_md = _tg(project_root, arch=arch_hint) / "plan.md"
    plan_intent: dict[str, Any] = {}
    if plan_md.is_file():
        try:
            from testcase_agent.products import parse_plan_fence

            plan_intent = parse_plan_fence(plan_md.read_text(encoding="utf-8"))
        except Exception:
            plan_intent = {}
    man = _load_yaml(_uo(project_root, arch=arch_hint) / "manifest.yaml") or {}
    if not isinstance(man, dict):
        man = {}

    def _pick(*vals: Any, default: str = "") -> str:
        for v in vals:
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
        return default

    op_name = _pick(
        ctx.get("op_name"),
        state.get("op_name"),
        params.get("op_name"),
        run_ctx.get("op_name"),
        man.get("op_name"),
        project_root.name,
    )
    architecture = _pick(
        ctx.get("architecture"),
        state.get("architecture"),
        params.get("architecture"),
        man.get("architecture"),
        default=arch_hint,
    )
    if not architecture:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    level = _pick(ctx.get("level"), state.get("level"), params.get("level"), default="L0")
    focus = _pick(ctx.get("focus"), state.get("focus"), params.get("focus"))
    test_script_root = _pick(
        ctx.get("test_script_root"),
        state.get("test_script_root"),
        params.get("test_script_root"),
        run_ctx.get("test_script_root"),
        os.environ.get("ASCENDC_TEST_SCRIPT_ROOT"),
        init_intent.get("consumer_root"),
    )
    from ascendc_pilot.human_interaction import resolved_test_script_root

    test_script_root = resolved_test_script_root(project_root, test_script_root)
    mode = _pick(
        ctx.get("mode"),
        ctx.get("tg_mode"),
        state.get("mode"),
        params.get("mode"),
        init_intent.get("mode"),
        plan_intent.get("mode"),
        default="",
    )
    return {
        "op_name": op_name,
        "architecture": architecture,
        "level": level,
        "focus": focus,
        "test_script_root": test_script_root,
        "mode": mode,
    }



def _uo_op_ctx(project_root: Path, ctx: dict[str, Any]) -> tuple[Path, str, str]:
    architecture = str(ctx.get("architecture") or "").strip()
    if not architecture:
        raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE")
    uo = _uo(project_root, arch=architecture)
    op_name = str(ctx.get("op_name") or "").strip()
    if not op_name:
        try:
            from ascendc_pilot.uo_artifacts import read_yaml

            man = read_yaml(uo / "manifest.yaml") or {}
            op_name = str(man.get("op_name") or "").strip()
        except Exception:  # noqa: BLE001
            op_name = ""
    return uo, op_name, architecture


def _uo_init_engine(action_id: str) -> EngineFn:
    def _run(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
        from uo_init.pilot_engines import ENGINES

        fn = ENGINES[action_id]
        return fn(Path(project_root), ctx or {})

    _run.__name__ = f"_run_uo_init_{action_id}"
    return _run


ENGINE_REGISTRY: dict[tuple[str, str], EngineFn] = {
    # CodeMap compiler public surface (5 Actions).
    ("uo-init", "prepare"): _uo_init_engine("prepare"),
    ("uo-init", "extract"): _uo_init_engine("extract"),
    ("uo-init", "analyze"): _uo_init_engine("analyze"),
    ("uo-init", "commit"): _uo_init_engine("commit"),
    ("uo-init", "verify"): _uo_init_engine("verify"),
    ("uo-init", "heal_promote"): _uo_init_engine("heal_promote"),
    ("uo-update", "detect_changes"): _run_detect_changes,
    ("uo-update", "plan_update"): _run_plan_update,
    ("uo-update", "apply_update"): _run_apply_update,
    ("uo-update", "export_integrity"): _run_export_integrity,
    ("uo-update", "diff_summary"): _run_diff_summary,
    ("uo-update", "diff_only"): _run_diff_summary,
    ("ce-plan", "kb_check"): _run_ce_kb_check,
    ("ce-apply", "apply_gate"): _run_ce_apply_gate,
    ("ce-apply", "patch_guard"): _run_ce_patch_guard,
    ("ce-apply", "plan_revise_check"): _run_ce_plan_revise_check,
    ("ce-apply", "codemap_refresh"): _run_ce_codemap_refresh,
    ("ce-review", "change_capture"): _run_ce_review_capture,
    ("tg-init", "kb_check"): _run_tg_kb_check,
}

from ascendc_pilot.actions.tg_product import install as _install_tg_product

_install_tg_product(ENGINE_REGISTRY)

from ascendc_pilot.actions.goal_engines import install as _install_goal

_install_goal(ENGINE_REGISTRY)



# Output contract id → relative paths under .ascendc-pilot (existence + nonempty where applicable)
OUTPUT_CONTRACT_PATHS: dict[str, list[str]] = {
    # Layout artifacts + machine scope receipt (SSOT; composite overlay must match).
    "uo-prepare-v1": [
        "uo/manifest.yaml",
        "uo/operator.yaml",
        "uo/ir/build_variant.yaml",
        "uo/runs/{run_id}/scope/scope_validated.yaml",
        "uo/runs/{run_id}/scope/receipt.yaml",
    ],
    "uo-extract-v1": [
        "uo/ir/host_extract_receipt.yaml",
        "uo/ir/kernel_ir.yaml",
    ],
    "uo-analyze-v1": [
        "uo/ir/unresolved.yaml",
        "uo/ir/codemap_analyze_receipt.yaml",
    ],
    "uo-commit-v1": ["uo/*.uo"],
    # verify audits the committed .uo; receipts live under uo/checks/
    "uo-verify-v1": ["uo/checks/integrity.yaml", "uo/checks/quality.yaml"],
    "include-heal-staging-v1": [
        "runs/{run_id}/actions/propose_include_heal/parts/**",
        "runs/{run_id}/actions/propose_include_heal/staging.yaml",
    ],
    "include-heal-extras-v1": ["uo/summary/build_context_extras.yaml"],
    "integrity-v1": ["uo/checks/integrity.yaml"],
    "change-detect-v1": ["uo/diff/change_set.yaml"],
    "update-plan-v1": ["uo/summary/update_plan.yaml"],
    "update-apply-v1": [
        "uo/runs/{run_id}/update/receipt.yaml",
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
    ],
    "diff-summary-v1": [
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
        "uo/diff/impact.yaml",
        "uo/diff/unresolved.yaml",
    ],
    # kb-answer-v1: dialogue contract (Task/stdout body); no disk payload.
    "kb-answer-v1": [],
    "code-review-v1": [],
    "ce-kb-check-v1": [],
    "ce-plan-v1": ["ce/plan/*_plan.md"],
    "ce-plan-confirmed-v1": [],
    "apply-gate-v1": [],
    "apply-patch-v1": ["ce/plan/*_plan.md"],
    "apply-plan-revise-v1": ["ce/plan/*_plan.md"],
    "apply-plan-revise-check-v1": [],
    "apply-patch-guard-v1": [],
    "codemap-refresh-v1": [],
    "apply-report-v1": [],
    "review-capture-v1": [],
    "review-report-v1": [],
    "session-handoff-v1": ["session_handoff.md"],
    # tg-init kb_check receipt: proves CodeMap .uo TG views are readable.
    "uo-ready-v1": ["runs/{run_id}/receipts/uo_ready.yaml"],
    "tg-init-v1": ["tg/init.yaml"],
    "tg-init-validate-v1": ["runs/{run_id}/receipts/validate_init.yaml"],
    "tg-repo-scan-v1": ["runs/{run_id}/receipts/repo_scan.yaml"],
    "tg-bind-staging-v1": [
        "runs/{run_id}/actions/bind_init/parts/harness.yaml",
        "runs/{run_id}/actions/bind_init/parts/bind.yaml",
    ],
    "tg-bind-review-v1": [],
    "plan-precheck-v1": [],
    "tg-plan-scope-v1": [],
    "tg-plan-fuse-v1": [],
    "tg-plan-v1": ["tg/plan.md"],
    "tg-plan-validate-v1": ["runs/{run_id}/receipts/plan_validate.yaml"],
    "tg-plan-approved-v1": ["tg/plan.md"],
    "solve-precheck-v1": [],
    "tg-construct-v1": [],
    "tg-construct-capture-v1": ["runs/{run_id}/receipts/construct_promote.yaml"],
    "tg-replay-v1": ["runs/{run_id}/receipts/replay_round.yaml"],
    "tg-worklog-v1": ["tg/worklog.md"],
    "tg-analyze-v1": [],
    "tg-certify-v1": ["runs/{run_id}/receipts/solve_certify.yaml"],
    "intent-promoted-v1": ["runs/{run_id}/receipts/intent_promoted.yaml"],
}

# Alternative draft locations: any one nonempty path satisfies the contract.
OUTPUT_CONTRACT_MATCH_ANY: frozenset[str] = frozenset()

# Contracts that must contain at least one nonempty concrete artifact (not empty dir / empty file)
OUTPUT_CONTRACT_NONEMPTY_GLOBS: dict[str, list[str]] = {
    "change-detect-v1": [
        "uo/diff/change_set.yaml",
    ],
    "update-plan-v1": [
        "uo/summary/update_plan.yaml",
    ],
    "update-apply-v1": [
        "uo/runs/{run_id}/update/receipt.yaml",
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
    ],
    "diff-summary-v1": [
        "uo/diff/index.yaml",
        "uo/diff/change_set.yaml",
        "uo/diff/impact.yaml",
        "uo/diff/unresolved.yaml",
    ],
}


def invoke_engine(project_root: Path, workflow_id: str, action_id: str, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    from ascendc_pilot.progress import engine_span

    key = (workflow_id, action_id)
    fn = ENGINE_REGISTRY.get(key)
    if fn is None:
        return {"ok": False, "error": f"no deterministic engine for {workflow_id}/{action_id}"}
    payload = dict(ctx or {})
    payload["action_id"] = action_id
    payload["workflow_id"] = workflow_id
    if not str(payload.get("run_id") or "").strip():
        try:
            from ascendc_pilot.state import load_state

            payload["run_id"] = str(load_state(project_root).get("run_id") or "").strip()
        except Exception:  # noqa: BLE001
            pass
    with engine_span(workflow_id, action_id):
        try:
            return fn(project_root, payload)
        except Exception as exc:  # noqa: BLE001
            from ascendc_pilot.local_extension import LocalCapabilityRequired

            if isinstance(exc, LocalCapabilityRequired):
                payload = exc.as_dict()
                payload["reason_code"] = "LOCAL_CAPABILITY_REQUIRED"
                payload["error"] = "LOCAL_CAPABILITY_REQUIRED"
                payload["recovery_action"] = "local_capability_bootstrap"
                return payload
            raise
