# -*- coding: utf-8 -*-
"""Deterministic TG engines for init.yaml / plan.md / worklog.md / cases."""

from __future__ import annotations

import csv
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from testcase_agent import isolation, products, test_repo
from testcase_agent.init_status import InitGateError


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tg(project_root: Path, ctx: dict[str, Any] | None = None) -> Path:
    from ascendc_pilot.paths import tg_root

    arch = str((ctx or {}).get("architecture") or "").strip() or None
    return tg_root(project_root, arch=arch)


def _run_id(ctx: dict[str, Any]) -> str:
    return str(ctx.get("run_id") or "").strip()


def _action_dir(project_root: Path, ctx: dict[str, Any], action_id: str) -> Path:
    from ascendc_pilot.paths import agent_root

    arch = str(ctx.get("architecture") or "").strip() or None
    rid = _run_id(ctx)
    return agent_root(project_root, arch) / "runs" / rid / "actions" / action_id


def _dump_yaml(path: Path, doc: Any) -> Path:
    isolation.assert_tg_write_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data


def _receipt(project_root: Path, ctx: dict[str, Any], name: str, payload: dict[str, Any]) -> Path:
    from ascendc_pilot.runs import receipts_dir

    body = dict(payload)
    body.setdefault("kind", "receipt")
    body.setdefault("written_at", _now())
    rid = _run_id(ctx)
    if rid:
        body.setdefault("run_id", rid)
    for key in ("workflow_id", "action_id", "architecture"):
        if ctx.get(key) and key not in body:
            body[key] = ctx[key]
    out = receipts_dir(project_root, rid or None) / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


_DEFAULT_INPUT_MARKERS = frozenset(
    {
        "no_repo_uo_query",
        "default_input",
        "none",
        "null",
        "-",
        "__default_input__",
    }
)


def _choice_from_raw(raw: str, project_root: Path | None = None) -> tuple[str, str]:
    from ascendc_pilot.human_interaction import (
        adopt_test_script_root,
        extract_existing_directory,
        extract_harness_git_url,
    )

    text = str(raw or "").strip()
    if text.lower() in _DEFAULT_INPUT_MARKERS:
        return "default_input", ""
    if text.lower() in {"have_repo", "custom", "stop"}:
        return "unset", ""
    extracted = extract_existing_directory(text) if text else ""
    if extracted:
        return "script_repo", extracted
    git_url = extract_harness_git_url(text) if text else ""
    if git_url and project_root is not None:
        adopted = adopt_test_script_root(project_root, git_url)
        stored = str(adopted.get("test_script_root") or "").strip()
        if adopted.get("ok") and stored:
            return "script_repo", stored
        err = str(adopted.get("message_zh") or adopted.get("error") or "HARNESS_CLONE_FAILED")
        return "clone_failed", err
    if text:
        try:
            path = Path(text).expanduser()
            if path.is_dir():
                return "script_repo", str(path.resolve())
        except OSError:
            pass
    return "unset", ""


def _test_script_root(project_root: Path, ctx: dict[str, Any]) -> str:
    from ascendc_pilot.actions.engines import _resolve_tg_ctx
    from ascendc_pilot.human_interaction import resolved_test_script_root

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    raw = str(tg_ctx.get("test_script_root") or ctx.get("test_script_root") or "").strip()
    raw = resolved_test_script_root(project_root, raw)
    if raw.lower() in _DEFAULT_INPUT_MARKERS or raw.lower() in {"have_repo", "custom", "stop"}:
        return ""
    return raw


def _harness_choice(project_root: Path, ctx: dict[str, Any]) -> tuple[str, str]:
    from ascendc_pilot.actions.engines import _resolve_tg_ctx
    from ascendc_pilot.human_interaction import (
        adopt_test_script_root,
        extract_existing_directory,
        is_in_tree_operator_tests,
        resolved_test_script_root,
    )
    from ascendc_pilot.state import load_state

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    picked = str(tg_ctx.get("test_script_root") or ctx.get("test_script_root") or "").strip()
    st = load_state(project_root) or {}
    live = str(st.get("workflow_id") or "") == "tg-init"
    if live:
        raw = resolved_test_script_root(project_root, picked)
        if st.get("test_script_confirmed"):
            return _choice_from_raw(raw, project_root)
        # Unconfirmed live run: operator-external directory or git URL is a user fact.
        # In-tree tests/ and default_input markers from pack overlay are guesses.
        if raw.lower() in _DEFAULT_INPUT_MARKERS or raw.lower() in {"have_repo", "custom", "stop"}:
            return "unset", ""
        extracted = extract_existing_directory(raw) if raw else ""
        if extracted and not is_in_tree_operator_tests(project_root, extracted):
            adopt_test_script_root(project_root, extracted)
            return "script_repo", extracted
        return _choice_from_raw(raw, project_root)
    return _choice_from_raw(picked, project_root)


def _discover_in_tree_tests(project_root: Path) -> str:
    for name in ("tests", "test"):
        candidate = Path(project_root) / name
        if candidate.is_dir():
            return str(candidate.resolve())
    return ""


def _uo_identity(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent import product_uo

    from ascendc_pilot.actions.engines import _resolve_tg_ctx

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    return product_uo.identity(
        project_root,
        op_name=str(tg_ctx.get("op_name") or ""),
        architecture=str(tg_ctx.get("architecture") or ""),
    )


def _legal_key_count(project_root: Path, ctx: dict[str, Any]) -> int:
    from testcase_agent import product_uo

    from ascendc_pilot.actions.engines import _resolve_tg_ctx

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    try:
        rows = product_uo.legal_key_rows(
            project_root,
            op_name=str(tg_ctx.get("op_name") or ""),
            architecture=str(tg_ctx.get("architecture") or ""),
        )
    except Exception:
        return 0
    return len(rows)


def _collect_staging_mapping(root: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    staging = _load_yaml(root / "staging.yaml")
    if isinstance(staging, dict):
        merged.update(staging)
    for part in sorted((root / "parts").glob("*.yaml")) if (root / "parts").is_dir() else []:
        doc = _load_yaml(part)
        if isinstance(doc, dict):
            for key, value in doc.items():
                if key not in merged or merged[key] in (None, "", {}, []):
                    merged[key] = value
                elif isinstance(merged.get(key), dict) and isinstance(value, dict):
                    merged[key] = {**merged[key], **value}
    return merged


def _collect_staging_text(root: Path, *, names: tuple[str, ...] = ("plan.md", "worklog.md", "staging.md")) -> str:
    """Prefer nonempty parts/<name>, then nonempty action-root <name>, then parts/*.md."""
    parts = root / "parts"
    for name in names:
        path = parts / name
        if path.is_file() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8")
    for name in names:
        path = root / name
        if path.is_file() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8")
    staging = _load_yaml(root / "staging.yaml")
    if isinstance(staging, dict):
        for key in ("text", "markdown", "plan_md", "worklog_md"):
            if staging.get(key):
                return str(staging[key])
    if parts.is_dir():
        chunks: list[str] = []
        for part in sorted(parts.glob("*.md")):
            if part.stat().st_size > 0:
                chunks.append(part.read_text(encoding="utf-8"))
        if chunks:
            return "\n\n".join(chunks)
    return ""


def _goal_wants_test_generation(project_root: Path) -> bool:
    try:
        from ascendc_pilot.human_confirm import _auto_goal_wants_tests
        from ascendc_pilot.user_goal import load_user_goal
    except Exception:  # noqa: BLE001
        return False
    if _auto_goal_wants_tests(project_root):
        return True
    goal = load_user_goal(project_root) or {}
    for item in goal.get("public_plan") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") in {"bind_harness", "generate_cases", "validate_cases"}:
            return True
    return False


def run_repo_scan(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from ascendc_pilot.human_interaction import (
        adopt_test_script_root,
        extract_existing_directory,
        load_pending,
        pending_field,
    )

    pending = load_pending(project_root)
    if str(pending.get("status") or "") == "answered":
        field = pending_field(pending)
        answered = str(pending.get("answered_value") or "").strip()
        if field == "test_script_root" or extract_existing_directory(answered):
            adopt_test_script_root(project_root, answered)
    kind, root = _harness_choice(project_root, ctx)
    if kind == "clone_failed":
        return {
            "ok": False,
            "engine": "repo_scan",
            "error": "HARNESS_CLONE_FAILED",
            "message_zh": root or "测试仓 git URL 克隆失败。",
            "needs_human_decision": False,
            "test_script_root": "",
        }
    if kind == "unset":
        discovered = _discover_in_tree_tests(project_root)
        options: list[dict[str, str]] = [
            {
                "label": "没有测试仓，由 Agent 按算子约束生成",
                "value": "no_repo_uo_query",
                "description": "不扫描测试仓，按算子 UO 约束手写 init（default_input）",
            },
        ]
        if discovered:
            options.append(
                {
                    "label": f"使用已发现的仓内目录 {discovered}",
                    "value": discovered,
                    "description": "只有点选此项才把算子仓 tests/ 当作 harness；禁止代答",
                },
            )
        options.append(
            {
                "label": "有外部测试仓，或其他想法：在下面输入",
                "value": "custom",
                "description": "输入本地绝对路径、git 仓 URL，或其它说明（会打断当前确认）",
            }
        )
        question = (
            "尚未确认 test_script_root。"
            "请选择：没有测试仓则由 Agent 生成；"
            "确认仓内 tests/（若已发现）；"
            "或在最后一项输入外部仓路径 / git URL / 其它想法。"
            "未点选仓内项不得把 tests/ 当作 harness；不要静默 default_input。"
        )
        ask = {
            "header": "选择测试仓",
            "question": question,
            "prompt": question,
            "options": options,
            "allow_free_text": True,
            "field": "test_script_root",
        }
        return {
            "ok": False,
            "engine": "repo_scan",
            "needs_human_decision": True,
            "ask_question": ask,
            "message_zh": ask["question"],
            "test_script_root": "",
            "discovered_in_tree_tests": discovered,
        }
    inventory = test_repo.scan(root or None)
    ident = {}
    try:
        ident = _uo_identity(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        ident = {"error": str(exc)[:200]}
    declared = _legal_key_count(project_root, ctx)
    contract = test_repo.contract_from_inventory(inventory)
    doc = {
        "schema": "tg-repo-scan/v1",
        "ok": not str(inventory.get("error") or ""),
        "kind": kind,
        "test_script_root": root,
        "inventory": inventory,
        "contract": contract,
        "uo_digest": str(ident.get("sha256") or ident.get("digest") or ""),
        "uo_product": str(ident.get("path") or ""),
        "declared_key_count": declared,
        "declared_source": "product_uo.legal_key_rows",
    }
    out = _receipt(project_root, ctx, "repo_scan.yaml", doc)
    return {"ok": True, "engine": "repo_scan", "artifact": out.as_posix(), **doc}


def run_bind_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    action_root = _action_dir(project_root, ctx, "bind_init")
    review_root = _action_dir(project_root, ctx, "bind_review")
    verdict = _load_yaml(review_root / "verdict.yaml")
    if verdict.get("ok") is not True:
        receipt = _receipt(
            project_root,
            ctx,
            "bind_promote.yaml",
            {"ok": False, "error": "REFEREE_REJECTED", "verdict": verdict},
        )
        return {
            "ok": False,
            "engine": "bind_promote",
            "error": "REFEREE_REJECTED",
            "message_zh": "没有引擎 verdict ok: true，禁止写入 tg/init.yaml。",
            "receipt": receipt.as_posix(),
        }
    from ascendc_pilot.yaml_check import format_yaml_error_zh, parse_yaml_mapping

    harness_path = action_root / "parts" / "harness.yaml"
    bind_path = action_root / "parts" / "bind.yaml"
    harness, harness_err = parse_yaml_mapping(harness_path)
    bind, bind_err = parse_yaml_mapping(bind_path)
    part_err = harness_err or bind_err
    if part_err:
        receipt = _receipt(
            project_root,
            ctx,
            "bind_promote.yaml",
            {"ok": False, **part_err},
        )
        return {
            "ok": False,
            "engine": "bind_promote",
            "error": str(part_err.get("error") or "BIND_PART_YAML_INVALID"),
            "reason_code": "BIND_PART_YAML_INVALID",
            "message_zh": format_yaml_error_zh(part_err),
            "path": part_err.get("path"),
            "line": part_err.get("line"),
            "column": part_err.get("column"),
            "receipt": receipt.as_posix(),
        }
    if not harness or not bind:
        receipt = _receipt(
            project_root,
            ctx,
            "bind_promote.yaml",
            {"ok": False, "error": "BIND_PARTS_MISSING", "harness": bool(harness), "bind": bool(bind)},
        )
        return {
            "ok": False,
            "engine": "bind_promote",
            "error": "BIND_PARTS_MISSING",
            "message_zh": "缺少 parts/harness.yaml 或 parts/bind.yaml，禁止 promote。",
            "receipt": receipt.as_posix(),
        }
    staged = _collect_staging_mapping(action_root)
    from ascendc_pilot.runs import receipts_dir

    scan = _load_yaml(receipts_dir(project_root, _run_id(ctx) or None) / "repo_scan.yaml")
    inventory = scan.get("inventory") if isinstance(scan.get("inventory"), dict) else {}
    contract = scan.get("contract") if isinstance(scan.get("contract"), dict) else test_repo.contract_from_inventory(inventory)
    ident = {}
    try:
        ident = _uo_identity(project_root, ctx)
    except Exception as exc:  # noqa: BLE001
        ident = {"error": str(exc)[:200]}

    scan_kind = str(scan.get("kind") or contract.get("kind") or "")
    kind = str(
        scan_kind
        or staged.get("kind")
        or bind.get("kind")
        or harness.get("kind")
        or ("script_repo" if inventory.get("kind") == "script_repo" else "default_input")
    )
    if not str(scan.get("test_script_root") or "").strip():
        kind = "default_input"
    table_kind = str(bind.get("table_kind") or staged.get("table_kind") or "csv").strip().lower()
    if table_kind not in {"csv", "xls", "xlsx"}:
        tables = inventory.get("tables") or []
        kinds = [str(t.get("kind") or "") for t in tables if isinstance(t, dict)]
        if "xlsx" in kinds:
            table_kind = "xlsx"
        elif "xls" in kinds:
            table_kind = "xls"
        else:
            table_kind = "csv"

    columns = bind.get("columns") or staged.get("columns") or contract.get("columns") or []
    if columns and isinstance(columns[0], str):
        columns = [{"name": c} for c in columns]

    findings: list[Any] = []
    for src in (harness.get("findings"), bind.get("findings"), staged.get("findings"), contract.get("findings")):
        if isinstance(src, list):
            findings.extend(src)

    mapping = products.mapping_as_dict(bind.get("mapping"))
    if not mapping:
        mapping = products.mapping_as_dict(staged.get("mapping"))
    domains = products.domains_as_dict(bind.get("domains") if bind.get("domains") is not None else bind.get("value_domains"))
    if not domains:
        domains = products.domains_as_dict(
            staged.get("domains") if staged.get("domains") is not None else staged.get("value_domains")
        )

    doc = {
        "schema": products.INIT_SCHEMA,
        "kind": kind,
        "table_kind": table_kind,
        "entry": bind.get("entry") or staged.get("entry") or contract.get("entry") or "",
        "case_arg": bind.get("case_arg") or staged.get("case_arg") or contract.get("case_arg") or "",
        "modes": harness.get("modes") or staged.get("modes") or contract.get("modes") or {"precision": [], "perf": []},
        "columns": columns,
        "defaults": bind.get("defaults") or staged.get("defaults") or contract.get("defaults") or {},
        "mapping": mapping,
        "domains": domains,
        "golden": harness.get("golden") or staged.get("golden") or {},
        "compare": harness.get("compare") or harness.get("script_compare") or staged.get("compare") or staged.get("script_compare") or {},
        "generate_inputs": harness.get("generate_inputs") or staged.get("generate_inputs") or {},
        "findings": findings,
        "test_script_root": str(scan.get("test_script_root") or _test_script_root(project_root, ctx)),
        "uo_digest": str(ident.get("sha256") or ident.get("digest") or scan.get("uo_digest") or ""),
        "uo_product": str(ident.get("path") or scan.get("uo_product") or ""),
        "declared_key_count": int(scan.get("declared_key_count") or 0),
        "declared_source": "product_uo.legal_key_rows",
        "confirmed": False,
        "project_root": Path(project_root).expanduser().resolve().as_posix(),
        "op_name": str(ctx.get("op_name") or ident.get("op_name") or Path(project_root).name),
        "architecture": str(ctx.get("architecture") or ident.get("architecture") or ""),
        "updated_at": _now(),
    }
    for key in ("precision_cmd", "perf_cmd", "corpus"):
        if harness.get(key) is not None:
            doc[key] = harness[key]
        elif staged.get(key) is not None:
            doc[key] = staged[key]
    errors = products.validate_init(doc)
    if errors:
        receipt = _receipt(project_root, ctx, "bind_promote.yaml", {"ok": False, "errors": errors})
        return {"ok": False, "engine": "bind_promote", "errors": errors, "receipt": receipt.as_posix()}
    path = products.dump_init(tg, doc)
    try:
        from testcase_agent.init_status import mark_init_confirmed

        mark_init_confirmed(tg, notes="Confirmed after Primary bind_review", project_root=project_root)
    except Exception as exc:  # noqa: BLE001
        receipt = _receipt(
            project_root,
            ctx,
            "bind_promote.yaml",
            {"ok": False, "error": str(exc)[:300], "artifact": path.as_posix()},
        )
        return {
            "ok": False,
            "engine": "bind_promote",
            "error": str(exc)[:300],
            "artifact": path.as_posix(),
            "receipt": receipt.as_posix(),
        }
    return {"ok": True, "engine": "bind_promote", "artifact": path.as_posix()}


def run_validate_init(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    try:
        doc = products.load_init(tg)
    except products.ProductError as exc:
        receipt = _receipt(project_root, ctx, "validate_init.yaml", {"ok": False, "error": str(exc)})
        return {"ok": False, "engine": "validate_init", "error": str(exc), "ask": exc.ask, "receipt": receipt.as_posix()}
    errors = products.validate_init(doc)
    ok = not errors
    receipt = _receipt(project_root, ctx, "validate_init.yaml", {"ok": ok, "errors": errors})
    return {"ok": ok, "engine": "validate_init", "errors": errors, "receipt": receipt.as_posix()}


def run_plan_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    from testcase_agent.init_status import require_init_confirmed

    from ascendc_pilot.actions.engines import _resolve_tg_ctx

    tg_ctx = _resolve_tg_ctx(project_root, ctx)
    try:
        doc = require_init_confirmed(project_root, str(tg_ctx.get("op_name") or Path(project_root).name))
    except InitGateError as exc:
        return {"ok": False, "engine": "plan_precheck", "error": str(exc), "ask": exc.ask, "payload": exc.payload}
    declared = _legal_key_count(project_root, ctx)
    intents = products.collect_intent_sources(project_root, architecture=str(tg_ctx.get("architecture") or ""))
    receipt = _receipt(
        project_root,
        ctx,
        "plan_precheck.yaml",
        {
            "ok": True,
            "declared_key_count": declared,
            "declared_source": "product_uo.legal_key_rows",
            "init_confirmed": True,
            "intent_sources": intents,
        },
    )
    return {
        "ok": True,
        "engine": "plan_precheck",
        "declared_key_count": declared,
        "receipt": receipt.as_posix(),
        "init": {"confirmed": True, "uo_digest": doc.get("uo_digest")},
    }


def run_plan_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    text = _collect_staging_text(_action_dir(project_root, ctx, "plan_fuse"))
    if not text.strip():
        return {"ok": False, "engine": "plan_promote", "error": "empty plan staging"}
    path = products.plan_path(tg)
    isolation.assert_tg_write_path(path)
    path.write_text(text, encoding="utf-8")
    try:
        fence = products.parse_plan_fence(text)
    except products.ProductError as exc:
        return {"ok": False, "engine": "plan_promote", "error": str(exc)}
    return {
        "ok": True,
        "engine": "plan_promote",
        "artifact": path.as_posix(),
        "plan_hash": products.plan_hash(text),
        "obligation_count": len(fence.get("obligations") or []),
    }


def run_plan_validate(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    try:
        init_doc = products.load_init(tg)
        text, fence = products.load_plan(tg)
    except products.ProductError as exc:
        return {"ok": False, "engine": "plan_validate", "error": str(exc), "ask": exc.ask}
    errors = products.validate_plan_fence(fence, init_columns=products.column_names(init_doc))
    if not (fence.get("obligations") or []):
        errors.append("obligations empty; default L0 still needs rootable precision/perf rows")
    if str(fence.get("mode") or "").strip() in {"tilingkey_full_coverage", "T=D", "t_equals_d"}:
        errors.append("tilingkey_full_coverage / T=D is not a plan mode")
    ok = not errors
    receipt = _receipt(
        project_root,
        ctx,
        "plan_validate.yaml",
        {
            "ok": ok,
            "errors": errors,
            "plan_hash": products.plan_hash(text),
            "test_harness_gap_pending": products.pending_test_harness_gap(text, fence),
        },
    )
    return {"ok": ok, "engine": "plan_validate", "errors": errors, "receipt": receipt.as_posix()}


def run_solve_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    try:
        text, fence = products.load_plan(tg)
        products.load_init(tg)
    except products.ProductError as exc:
        return {"ok": False, "engine": "solve_precheck", "error": str(exc), "ask": exc.ask}
    if not products.is_plan_approved(fence):
        return {
            "ok": False,
            "engine": "solve_precheck",
            "error": "plan.md is not approved",
            "ask": "plan_required",
            "next": "/tg-plan",
        }
    if products.pending_test_harness_gap(text, fence):
        return {
            "ok": False,
            "engine": "solve_precheck",
            "error": "test_harness_gap is pending; CE-apply the test-script repo then /tg-init",
            "ask": "test_harness_gap_pending",
        }
    receipt = _receipt(project_root, ctx, "solve_precheck.yaml", {"ok": True, "plan_hash": products.plan_hash(text)})
    return {"ok": True, "engine": "solve_precheck", "receipt": receipt.as_posix()}


def run_construct_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    init_doc = products.load_init(tg)
    staged = _collect_staging_mapping(_action_dir(project_root, ctx, "construct_cases"))
    rows = staged.get("rows") or staged.get("cases") or []
    if not isinstance(rows, list):
        return {"ok": False, "engine": "construct_promote", "error": "staging rows is not a list"}
    columns = [c["name"] if isinstance(c, dict) else str(c) for c in (init_doc.get("columns") or [])]
    extra = staged.get("columns") or []
    for col in extra:
        name = col["name"] if isinstance(col, dict) else str(col)
        if name and name not in columns:
            columns.append(name)
    if not columns and rows and isinstance(rows[0], dict):
        columns = [str(k) for k in rows[0].keys()]
    kind = str(init_doc.get("table_kind") or "csv")
    path = products.cases_path(tg, kind)
    products.write_cases_table(path, columns, [r for r in rows if isinstance(r, dict)], table_kind=kind)
    return {
        "ok": True,
        "engine": "construct_promote",
        "artifact": path.as_posix(),
        "rows": len(rows),
        "table_kind": kind,
    }


def _read_cases(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            cols = [str(c) for c in (reader.fieldnames or []) if c]
            rows = [{k: "" if v is None else str(v) for k, v in row.items()} for row in reader]
            return cols, rows
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            return [], []
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(c or "") for c in next(it, ())]
        rows = []
        for raw in it:
            rows.append({header[i]: "" if i >= len(raw) or raw[i] is None else str(raw[i]) for i in range(len(header))})
        return header, rows
    if suffix == ".xls":
        try:
            import xlrd
        except ImportError:
            return [], []
        book = xlrd.open_workbook(str(path))
        sheet = book.sheet_by_index(0)
        header = [str(sheet.cell_value(0, c)) for c in range(sheet.ncols)]
        rows = []
        for r in range(1, sheet.nrows):
            rows.append({header[c]: str(sheet.cell_value(r, c)) for c in range(sheet.ncols)})
        return header, rows
    return [], []


def _live_replay(ctx: dict[str, Any]) -> bool:
    if "live_replay" in ctx:
        return bool(ctx.get("live_replay"))
    if str(os.environ.get("TG_CLOSURE_CI") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    if str(os.environ.get("UO_OPERATOR") or "").startswith("_synthetic"):
        return False
    return True


_REPLAY_FAIL_ZH = {
    "WSL_UNAVAILABLE": "未检测到可用的 WSL 发行版，Host replay 无法启动，不能进入 analyze。",
    "WSL_DISTRO_AMBIGUOUS": "存在多个 WSL 发行版，请设置 UO_REPLAY_DISTRO 后再跑 /tg-solve。",
    "WSL_DISTRO_UNRESOLVED": "指定的 WSL 发行版不在 `wsl -l -q` 列表中。",
    "WSL_BUILD_DEPS_MISSING": "WSL 缺少 g++/cmake，非交互 apt-get 失败。",
    "WSL_PATH_FAILED": "无法把 Windows 路径映射进 WSL（wslpath 失败）。",
    "CANN_ENV_NOT_FOUND": "未找到 UO 解包的 CANN 树（UO_CANN_ROOT / _cann/pkg），Host replay 不能开始。",
    "CANN_ENV_NOT_READY": "CANN 环境未就绪，Host replay 不能开始。",
}


def _replay_bootstrap_failure(exc: BaseException) -> tuple[str, str]:
    text = str(exc or "")
    code = "REPLAY_BOOTSTRAP_FAILED"
    blob = text.replace("\\", "/")
    for token in (
        "WSL_UNAVAILABLE",
        "WSL_DISTRO_AMBIGUOUS",
        "WSL_DISTRO_UNRESOLVED",
        "WSL_BUILD_DEPS_MISSING",
        "WSL_PATH_FAILED",
        "CANN_ENV_NOT_FOUND",
        "CANN_ENV_NOT_READY",
    ):
        if token in blob:
            code = token
            break
    else:
        if blob.startswith("REPLAY_BOOTSTRAP_FAILED:"):
            inner = blob.split(":", 2)[1].strip()
            if inner:
                code = inner.split("/")[0].split(":")[0] or code
    message_zh = _REPLAY_FAIL_ZH.get(code, f"Host replay 环境未就绪（{code}），不能进入 analyze。")
    return code, message_zh


def run_replay_round(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    init_doc = products.load_init(tg)
    path = products.cases_path(tg, str(init_doc.get("table_kind") or "csv"))
    _cols, rows = _read_cases(path)
    verdicts: list[dict[str, Any]] = []
    replayed = False
    error = ""
    message_zh = ""
    if rows and _live_replay(ctx):
        try:
            from testcase_agent.closure.oracle import HostOracle

            class _Row:
                def __init__(self, tag: str, row: dict[str, str]) -> None:
                    self.tag = tag
                    self.row = row

            oracle = HostOracle()
            tagged = [_Row(str(row.get("Testcase_Name") or f"case_{i}"), row) for i, row in enumerate(rows)]
            judged = oracle.judge(tagged, tag="tg_solve")
            replayed = True
            for item in judged:
                verdicts.append(
                    {
                        "case_id": item.case_id,
                        "ok": item.ok,
                        "tiling_key": item.key,
                        "reject": item.reject,
                        "judged": item.judged,
                        "dims": item.dims,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            error, message_zh = _replay_bootstrap_failure(exc)
            doc = {
                "schema": "tg-replay-round/v1",
                "ok": False,
                "replayed": False,
                "error": error,
                "message_zh": message_zh,
                "detail": str(exc)[:400],
                "cases": path.as_posix() if path.is_file() else "",
                "count": len(rows),
                "verdicts": [],
            }
            out = _receipt(project_root, ctx, "replay_round.yaml", doc)
            return {
                "ok": False,
                "engine": "replay_round",
                "error": error,
                "reason_code": error,
                "message_zh": message_zh,
                "artifact": out.as_posix(),
                "replayed": False,
                "count": len(rows),
            }
    if not verdicts:
        for i, row in enumerate(rows):
            verdicts.append(
                {
                    "case_id": str(row.get("Testcase_Name") or f"case_{i}"),
                    "ok": False,
                    "tiling_key": row.get("tiling_key") or row.get("TilingKey") or "",
                    "reject": error or "NOT_RUN",
                    "judged": False,
                    "row": row,
                }
            )
    doc = {
        "schema": "tg-replay-round/v1",
        "ok": True,
        "replayed": replayed,
        "error": error,
        "cases": path.as_posix() if path.is_file() else "",
        "count": len(rows),
        "verdicts": verdicts,
    }
    out = _receipt(project_root, ctx, "replay_round.yaml", doc)
    return {"ok": True, "engine": "replay_round", "artifact": out.as_posix(), "replayed": replayed, "count": len(rows)}


def run_analyze_promote(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    text = _collect_staging_text(_action_dir(project_root, ctx, "analyze_round"), names=("worklog.md", "staging.md"))
    if not text.strip():
        return {"ok": False, "engine": "analyze_promote", "error": "empty worklog staging"}
    if not text.lstrip().startswith("open:"):
        text = "open: []\n\n" + text
    path = products.worklog_path(tg)
    isolation.assert_tg_write_path(path)
    path.write_text(text, encoding="utf-8")
    open_ids = products.worklog_open_ids(text)
    return {"ok": True, "engine": "analyze_promote", "artifact": path.as_posix(), "open": open_ids}


def run_solve_certify(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    tg = _tg(project_root, ctx)
    path = products.worklog_path(tg)
    if not path.is_file():
        return {"ok": False, "engine": "solve_certify", "error": "missing worklog.md"}
    text = path.read_text(encoding="utf-8")
    open_ids = products.worklog_open_ids(text)
    init_doc = products.load_init(tg)
    cases = products.cases_path(tg, str(init_doc.get("table_kind") or "csv"))
    if not cases.is_file():
        return {"ok": False, "engine": "solve_certify", "error": "missing cases table", "path": cases.as_posix()}
    ok = not open_ids
    receipt = _receipt(
        project_root,
        ctx,
        "solve_certify.yaml",
        {"ok": ok, "open": open_ids, "worklog": path.as_posix(), "cases": cases.as_posix()},
    )
    return {"ok": ok, "engine": "solve_certify", "open": open_ids, "receipt": receipt.as_posix()}


def install(registry: dict[tuple[str, str], Any]) -> None:
    registry[("tg-init", "repo_scan")] = run_repo_scan
    registry[("tg-init", "bind_promote")] = run_bind_promote
    registry[("tg-init", "validate_init")] = run_validate_init
    registry[("tg-plan", "plan_precheck")] = run_plan_precheck
    registry[("tg-plan", "plan_promote")] = run_plan_promote
    registry[("tg-plan", "plan_validate")] = run_plan_validate
    registry[("tg-solve", "solve_precheck")] = run_solve_precheck
    registry[("tg-solve", "construct_promote")] = run_construct_promote
    registry[("tg-solve", "replay_round")] = run_replay_round
    registry[("tg-solve", "analyze_promote")] = run_analyze_promote
    registry[("tg-solve", "solve_certify")] = run_solve_certify
