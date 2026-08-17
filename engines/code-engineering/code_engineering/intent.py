# -*- coding: utf-8 -*-
"""Promote staged CE feature drafts to canonical feature_decomposition.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _scope_root(project_root: Path | str, architecture: str) -> Path:
    root = Path(project_root).expanduser().resolve() / ".ascendc-pilot"
    return root / architecture if architecture else root


def _feature_rows(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, dict):
        for key in ("features", "items", "accepted"):
            rows = doc.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    if isinstance(doc, list):
        return [row for row in doc if isinstance(row, dict)]
    return []


def _staging_features(scope: Path, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    roots: list[Path] = []
    if run_id:
        roots.append(scope / "runs" / run_id / "actions" / "feature_decompose")
    else:
        roots.extend(sorted(scope.glob("runs/*/actions/feature_decompose")))
    for root in roots:
        rows.extend(_feature_rows(_load_yaml(root / "staging.yaml")))
        for part in sorted(root.glob("parts/*.yaml")):
            rows.extend(_feature_rows(_load_yaml(part)))
    return rows


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("name") or "").strip()


def promote_feature_decomposition(
    project_root: Path | str,
    *,
    architecture: str,
    run_id: str = "",
) -> dict[str, Any]:
    """Write canonical features from plan_review accepted list (+ staging fallback)."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "feature_promote", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    scope = _scope_root(project_root, arch)
    review = _load_yaml(scope / "ce" / "intent" / "plan_review.yaml")
    status = str(review.get("status") or "").strip().lower()
    if status not in {"pass", "accepted", "ok", "approve"}:
        return {
            "ok": False,
            "engine": "feature_promote",
            "error": "plan_review_not_accepted",
            "status": status or "missing",
        }
    accepted = review.get("accepted")
    if isinstance(accepted, list) and accepted and all(isinstance(row, dict) for row in accepted):
        features = [row for row in accepted if isinstance(row, dict)]
    else:
        wanted = {str(item).strip() for item in (accepted or []) if str(item).strip()}
        staged = _staging_features(scope, run_id)
        if wanted:
            features = [row for row in staged if _row_id(row) in wanted]
        else:
            features = staged
    if not features:
        return {
            "ok": False,
            "engine": "feature_promote",
            "error": "no_accepted_features",
            "status": status,
        }
    doc = {
        "schema": "ce-feature-decomposition/v1",
        "status": "accepted",
        "review_status": status,
        "features": features,
        "source": "plan_review",
    }
    out = scope / "ce" / "intent" / "feature_decomposition.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "ok": True,
        "engine": "feature_promote",
        "artifact": out.as_posix(),
        "feature_count": len(features),
        **doc,
    }


def _grill_rows(doc: Any) -> dict[str, Any]:
    return doc if isinstance(doc, dict) else {}


def promote_intent_grill(
    project_root: Path | str,
    *,
    architecture: str,
    run_id: str = "",
) -> dict[str, Any]:
    """Merge staged grill fields into canonical ce/intent/intent.yaml."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "grill_promote", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    scope = _scope_root(project_root, arch)
    intent_path = scope / "ce" / "intent" / "intent.yaml"
    current = _load_yaml(intent_path)
    staged: dict[str, Any] = {}
    roots: list[Path] = []
    if run_id:
        roots.append(scope / "runs" / run_id / "actions" / "intent_grill")
    else:
        roots.extend(sorted(scope.glob("runs/*/actions/intent_grill")))
    for root in roots:
        staged.update(_grill_rows(_load_yaml(root / "staging.yaml")))
        for part in sorted(root.glob("parts/*.yaml")):
            staged.update(_grill_rows(_load_yaml(part)))
    if not staged:
        return {"ok": False, "engine": "grill_promote", "error": "grill_staging_missing"}
    merged = dict(current)
    merged["schema"] = str(current.get("schema") or "ce-intent/v1")
    for key in ("in_scope", "out_of_scope", "acceptance", "open_questions", "side"):
        if key in staged:
            merged[key] = staged[key]
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    intent_path.write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    open_q = merged.get("open_questions") or []
    return {
        "ok": True,
        "engine": "grill_promote",
        "artifact": intent_path.as_posix(),
        "open_question_count": len(open_q) if isinstance(open_q, list) else 0,
        **merged,
    }


def _md_list(items: Any) -> list[str]:
    if isinstance(items, list):
        rows = [str(x).strip() for x in items if str(x).strip()]
        return [f"- {row}" for row in rows] if rows else ["- （无）"]
    text = str(items or "").strip()
    return [f"- {text}"] if text else ["- （无）"]


def _feature_title(row: dict[str, Any], index: int) -> str:
    return str(row.get("title") or row.get("name") or row.get("id") or f"F{index}").strip()


def render_intent_plan_md(
    *,
    intent: dict[str, Any],
    features: list[dict[str, Any]],
    anchors: list[Any],
    confirmed: bool,
) -> str:
    """Human-readable frozen plan. Apply must align patches to this file."""
    lines = [
        "# 变更计划",
        "",
        "确认后冻结。`/ce-apply` 必须按本文件改码；工作切片在 `ce/apply/todo.md`。",
        "",
        f"- 状态：{'已确认' if confirmed else '草稿'}",
        f"- 意图：{str(intent.get('intent') or intent.get('summary') or '（未写）').strip()}",
        f"- 侧别：{str(intent.get('side') or '（未写）').strip()}",
        "",
        "## 范围",
        *_md_list(intent.get("in_scope")),
        "",
        "## 不做",
        *_md_list(intent.get("out_of_scope")),
        "",
        "## 验收",
        *_md_list(intent.get("acceptance")),
        "",
        "## 特性",
        "",
    ]
    if not features:
        lines.append("（尚未分解特性）")
        lines.append("")
    for i, row in enumerate(features, 1):
        title = _feature_title(row, i)
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"- 目标：{str(row.get('goal') or row.get('intent') or '').strip() or '（未写）'}")
        lines.append(f"- 约束：{str(row.get('constraints') or row.get('constraint') or '').strip() or '（未写）'}")
        blocked = row.get("blocked_by") or row.get("blocking") or row.get("blocked_by_ids") or []
        if isinstance(blocked, list):
            blocked_s = ", ".join(str(x).strip() for x in blocked if str(x).strip()) or "无"
        else:
            blocked_s = str(blocked).strip() or "无"
        lines.append(f"- 阻塞边：{blocked_s}")
        acc = row.get("acceptance") or row.get("verify") or []
        lines.extend(_md_list(acc) if not isinstance(acc, str) else [f"- {acc}"])
        cand = row.get("candidate_anchors") or row.get("anchors") or []
        if cand:
            lines.append("- 候选锚点：")
            if isinstance(cand, list):
                for item in cand:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"  - {cand}")
        lines.append("")
    lines.append("## 锚点")
    lines.append("")
    if not anchors:
        lines.append("- （尚未定位）")
    for row in anchors:
        if isinstance(row, dict):
            loc = str(row.get("file") or row.get("path") or "").strip()
            line = row.get("line") or row.get("start_line")
            name = str(row.get("name") or row.get("id") or "").strip()
            cite = f"{loc}:{line}" if line else loc
            extra = f" `{name}`" if name else ""
            lines.append(f"- `{cite}`{extra}".rstrip())
        else:
            lines.append(f"- {row}")
    lines.append("")
    return "\n".join(lines)


def render_apply_todo_md(features: list[dict[str, Any]], *, intent_text: str = "") -> str:
    """Working TDD checklist. One unchecked slice at a time."""
    lines = [
        "# 改码切片",
        "",
        "对齐 `ce/intent/plan.md`。一次只做一个未勾选项（一个垂直切片）。",
        "",
        "## 待办",
        "",
    ]
    if features:
        for i, row in enumerate(features, 1):
            title = _feature_title(row, i)
            lines.append(f"- [ ] {title}")
        total = len(features)
    else:
        label = str(intent_text or "简单改动").strip() or "简单改动"
        lines.append(f"- [ ] {label}")
        total = 1
    lines.extend(["", "## 进度", "", f"0/{total}", ""])
    return "\n".join(lines)


def write_intent_plan(
    project_root: Path | str,
    *,
    architecture: str,
) -> dict[str, Any]:
    """Write `ce/intent/plan.md` from confirmed intent / features / anchors."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "intent_plan", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    scope = _scope_root(project_root, arch)
    ce = scope / "ce"
    intent = _load_yaml(ce / "intent" / "intent.yaml")
    features_doc = _load_yaml(ce / "intent" / "feature_decomposition.yaml")
    anchors_doc = _load_yaml(ce / "intent" / "anchors.yaml")
    confirm = _load_yaml(ce / "intent" / "confirmation.yaml")
    features = _feature_rows(features_doc)
    anchors = anchors_doc.get("anchors") if isinstance(anchors_doc.get("anchors"), list) else []
    status = str(confirm.get("status") or confirm.get("decision") or "").strip().lower()
    confirmed = status in {"confirmed", "confirm", "ok"}
    text = render_intent_plan_md(
        intent=intent,
        features=features,
        anchors=anchors if isinstance(anchors, list) else [],
        confirmed=confirmed,
    )
    out = ce / "intent" / "plan.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "engine": "intent_plan",
        "artifact": out.as_posix(),
        "feature_count": len(features),
        "anchor_count": len(anchors) if isinstance(anchors, list) else 0,
        "confirmed": confirmed,
    }


def seed_apply_todo(
    project_root: Path | str,
    *,
    architecture: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write `ce/apply/todo.md` from plan features, or a single simple slice."""
    arch = str(architecture or "").strip()
    if not arch:
        return {"ok": False, "engine": "apply_todo", "error": "ARCHITECTURE_MISSING_IN_RUN_STATE"}
    scope = _scope_root(project_root, arch)
    out = scope / "ce" / "apply" / "todo.md"
    if out.is_file() and not overwrite:
        return {"ok": True, "engine": "apply_todo", "artifact": out.as_posix(), "seeded": False}
    features = _feature_rows(_load_yaml(scope / "ce" / "intent" / "feature_decomposition.yaml"))
    intent = _load_yaml(scope / "ce" / "intent" / "intent.yaml")
    text = render_apply_todo_md(
        features,
        intent_text=str(intent.get("intent") or intent.get("summary") or ""),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "engine": "apply_todo",
        "artifact": out.as_posix(),
        "seeded": True,
        "item_count": max(len(features), 1),
    }
