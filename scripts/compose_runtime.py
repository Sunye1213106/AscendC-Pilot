#!/usr/bin/env python3
"""Compose Policy/Capability/Action/Prompt/Agent → generated/<host>/{skills,agents,prompts}."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# Forbidden patterns in Action METHOD / task prompts (must not own workflow).
_FORBIDDEN_PATTERNS = [
    re.compile(r"(?i)while\s*\(.*phase"),
    re.compile(r"(?i)announce\s+passed"),
    re.compile(r"(?i)declare\s+(the\s+)?workflow\s+passed"),
    re.compile(r"(?i)自行宣布\s*(done|passed)"),
    re.compile(r"(?i)\bpython\s+.*\b(tg-init|tg-plan|tg-solve|build_layered_kb)\b"),
]

# Shared policies injected into both workflow entry skills and agents (same set).
# Compose injects short *invariant packs* only; full POLICY.md stays on disk for humans/CI.
COMPOSE_POLICY_IDS: tuple[str, ...] = (
    "pilot-control",
    "language",
    "evidence",
    "code-access",
    "source-authority",
    "output-quality",
)

# Short model-facing packs under pilot/policies/invariants/ (≤ ~50 lines total).
COMPOSE_INVARIANT_FILES: tuple[tuple[str, str], ...] = (
    ("control", "control-invariants.md"),
    ("evidence", "evidence-invariants.md"),
    ("code-access", "code-access-invariants.md"),
    ("authority", "authority.md"),
    ("output-quality", "output-quality.md"),
    ("language", "language.md"),
)

# True Skills (model-facing expertise). Workflow slash entries are generated shells.
COGNITIVE_SKILL_IDS: tuple[str, ...] = (
    "operator-analysis",
    "testcase-generation",
    "source-proof",
    "code-review",
)

# Slash / discovery entry metadata. Body is generated from Spec; no skills/workflows source.
# Editorial discovery prose only. cognitive_skill_id / requires_* live on Workflow Spec.
WORKFLOW_ENTRIES: dict[str, dict[str, str]] = {
    "uo-init": {
        "description": (
            "首次构建 AscendC 算子知识库 / Operator CodeMap（`.uo`）：机器解析源码范围与构建变体、"
            "抽取 CompilerFacts、运行确定性 CodeMap Pass、写入并校验单一 `.uo`。"
            "semantic residual 保留在 unresolved.yaml，不由 LLM 写入 canonical UO。"
            "用户要求建立知识库、建库、建 UO/CodeMap、索引/分析算子、首次理解算子或指定 "
            "architecture 建图时使用——这些口语一律走本 workflow，禁止改用外部 MCP/"
            "通用代码图谱索引。"
            "prepare 为确定性步骤：用户定 operator+arch，编译器定源码范围，无人工文件清单确认。"
        ),
    },
    "uo-update": {
        "description": (
            "在已有算子知识库 / `.uo` CodeMap 上根据源码变更执行确定性增量刷新、重建受影响 "
            "CodeMap 关系、校验完整性并输出差异摘要。用户要求刷新知识库、更新已有 UO/CodeMap "
            "或查看源码变更对 CodeMap 的影响时使用；禁止改用外部 MCP 重新索引。"
        ),
    },
    "uo-query": {
        "description": (
            "只读查询已有 AscendC 算子知识库 / `.uo` CodeMap，回答 API、Host、TilingKey/"
            "TilingData、Kernel、模板、宏、编译期变量、架构和数据流问题。用户询问知识库内容、"
            "已有 UO、某个 KEY/字段/路径或 CodeMap 完整性时使用。"
        ),
    },
    "uo-investigate": {
        "description": (
            "调查算子知识库 / `.uo` 中保留的 unresolved semantic residual：分类根因、指出 "
            "deterministic engine 缺什么能力。不修改 canonical `.uo`。用户问某个 gap 为何未闭合、"
            "或要改进 analyzer 时使用。"
        ),
    },
    "ce-review": {
        "description": (
            "基于 KB 的代码审查 / code review / 查 bug。用户要审查算子代码时加载。"
            "Pilot 管阶段；加载后执行 acp start ce-review。"
        ),
    },
    "tg-init": {
        "description": (
            "测例契约与绑定：变量/IO/TilingKey 维信息提取。用户说 tg-init、建测例契约、"
            "tilingkey 绑定时加载。默认 tilingkey_full_coverage（无需 CSV）。"
            "Pilot 管阶段；加载后 acp start tg-init。"
        ),
    },
    "tg-plan": {
        "description": (
            "制定 TG 测试目标并冻结 target set。用户未指定目标时默认计划全部源码声明 TilingKey；"
            "指定 packed keys 或维度过滤条件时只计划该子集。Plan 不构造 case、不做可达性求解。"
        ),
    },
    "tg-solve": {
        "description": (
            "执行已批准 TG Plan：按轮构造→Replay→Round Analysis。"
            "增长符合预期则轮内对 reject 证源码引理扩 E；不符合则基于已发现 key+源码定向再构造；"
            "直到 T=(R∩T)∪E。未指定目标由 tg-plan 默认 T=D。"
        ),
    },
    "operator": {
        "description": (
            "可选助手：列出可用 Pilot workflow entry，或把 /uo-init 等 slash 转给 acp route。"
            "自然语言意图请直接加载对应 entry，不要依赖本入口做口语路由。"
        ),
    },
}

# Capability id → repo-relative directory (tools / pilot runtime / gates).
CAPABILITY_DIRS: dict[str, str] = {
    "source-reading": "tools/source/source-reading",
    "source-navigation": "tools/source/source-navigation",
    "readonly-source-search": "tools/source/readonly-source-search",
    "kb-query": "tools/codemap/kb-query",
    "structured-ir-query": "tools/codemap/structured-ir-query",
    "action-scratch": "pilot/runtime/action-scratch",
    "bounded-semantic-batch": "pilot/runtime/bounded-semantic-batch",
    "sharded-llm-producer": "pilot/runtime/sharded-llm-producer",
    "sharded-semantic-producer": "pilot/runtime/sharded-semantic-producer",
    "producer-self-check": "pilot/gates/producer-self-check",
    "contract-building": "pilot/gates/contract-building",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _require_skill_frontmatter(text: str, *, path: Path | None = None) -> tuple[dict[str, Any], str]:
    """Parse skill frontmatter. BOMs stripped; leading spaces are NOT stripped.

    Cursor/Composer only recognize frontmatter when the first character is ``---``.
    """
    text = text.lstrip("\ufeff")
    label = path.as_posix() if path else "<skill>"
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise ValueError(f"invalid skill frontmatter (must start with ---): {label}")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"invalid skill frontmatter (unclosed fence): {label}")
    meta: dict[str, Any] = {}
    if yaml is not None:
        loaded = yaml.safe_load(parts[1]) or {}
        if isinstance(loaded, dict):
            meta = loaded
    if not meta.get("name"):
        raise ValueError(f"skill frontmatter missing name: {label}")
    if not meta.get("description"):
        raise ValueError(f"skill frontmatter missing description: {label}")
    body = parts[2].lstrip("\n")
    # Body must not re-introduce a YAML frontmatter fence at the start of a line.
    if re.search(r"(?m)^---\s*$", body):
        raise ValueError(f"skill body must not contain frontmatter fence: {label}")
    return meta, body


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Best-effort split for non-skill markdown; skills should use _require_skill_frontmatter."""
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    if yaml is not None:
        loaded = yaml.safe_load(parts[1]) or {}
        if isinstance(loaded, dict):
            meta = loaded
    return meta, parts[2].lstrip("\n")


def _assert_generated_skill(path: Path, *, expected_actions: int | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    meta, body = _require_skill_frontmatter(text, path=path)
    if expected_actions is not None:
        if "## Composition index" not in body:
            raise ValueError(f"generated skill missing Composition index: {path}")
        section = body.split("## Composition index", 1)[1]
        # Stop at next H2 so Action runtime index is not double-counted.
        section = re.split(r"\n##\s+", section, maxsplit=1)[0]
        found = len(re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", section, flags=re.M))
        if found != expected_actions:
            raise ValueError(
                f"generated skill action count mismatch for {path}: "
                f"expected {expected_actions}, found {found}"
            )
    _ = meta  # name/description already validated


def _dump_frontmatter(meta: dict[str, Any]) -> str:
    if yaml is None:
        lines = ["---"]
        for k, v in meta.items():
            lines.append(f"{k}: {v}")
        lines.append("---\n")
        return "\n".join(lines)
    body = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---\n"


def _repo_paths(repo: Path) -> dict[str, Path]:
    return {
        "skills": repo / "skills",
        "prompts": repo / "prompts",
        "agents": repo / "agents",
        "policies": repo / "pilot" / "policies",
        "hosts": repo / "adapters" / "hosts",
        "out": repo / "generated",
    }


def _capability_dir(repo: Path, cid: str) -> Path:
    rel = CAPABILITY_DIRS.get(cid)
    if not rel:
        return repo / "tools" / "_unknown" / cid
    return repo / Path(rel)


def _read_policy(repo: Path, pid: str) -> str:
    p = repo / "pilot" / "policies" / pid / "POLICY.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _start_requirements_line(repo: Path) -> str:
    """Project Spec requires_project / requires_architecture into model-facing prose."""
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import (  # noqa: WPS433
        workflows_needing_architecture,
        workflows_needing_project,
    )

    arch = "/".join(sorted(workflows_needing_architecture()))
    proj = "/".join(sorted(workflows_needing_project()))
    return (
        f"11. `{arch}` 启动必须同时有 `--project`（算子目录）与 `--architecture`（仓内 `arch*`）。"
        f"缺一 → AskQuestion（arch 选项只来自扫描结果，禁止编造）；齐了 → "
        f"`acp start … --project … --architecture …` 一次启动。"
        f"需要算子目录的 workflow：`{proj}`。"
        f"所有后续 `acp *` 带同一 `--project`；`.ascendc-pilot/` 只允许在该算子目录下。"
    )


def _cognitive_skill_for(repo: Path, wid: str) -> str:
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import cognitive_skill_id  # noqa: WPS433

    return cognitive_skill_id(wid)


def _read_invariant_pack(repo: Path) -> str:
    """Concatenate short invariant markdown for model context (not full POLICY.md)."""
    root = repo / "pilot" / "policies" / "invariants"
    parts: list[str] = [
        "Follow pilot policies (short invariants). Full text: `pilot/policies/*/POLICY.md`.",
        "",
    ]
    start_line = _start_requirements_line(repo)
    for _label, fname in COMPOSE_INVARIANT_FILES:
        path = root / fname
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").rstrip()
        if fname == "control-invariants.md":
            # Spec is authority for which workflows need project/architecture.
            text = re.sub(
                r"(?m)^11\..*$",
                start_line,
                text,
                count=1,
            )
        parts.append(text)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _read_capability(repo: Path, cid: str) -> tuple[dict[str, Any], str]:
    d = _capability_dir(repo, cid)
    return _load_yaml(d / "capability.yaml"), (d / "METHOD.md").read_text(encoding="utf-8") if (d / "METHOD.md").is_file() else ""


def _scan_forbidden(path: Path, text: str, errors: list[str]) -> None:
    for i, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if "must not" in low or "禁止" in line or "不得" in line or "勿" in line:
            continue
        for pat in _FORBIDDEN_PATTERNS:
            if pat.search(line):
                errors.append(f"forbidden pattern {pat.pattern!r} in {path.as_posix()}:{i}")


_DOMAIN_HARNESS_PATTERNS = [
    re.compile(r"\brun_id\b", re.I),
    re.compile(r"\baction_id\b", re.I),
    re.compile(r"\bfinalize\b", re.I),
    re.compile(r"\badvance\b", re.I),
    re.compile(r"\bacp\s+start\b", re.I),
    re.compile(r"\bacp\s+next\b", re.I),
]


def validate_domain_skills(repo: Path) -> list[str]:
    """Lint model-facing cognitive skills: frontmatter, line budget, no harness leakage."""
    errors: list[str] = []
    skills_root = repo / "skills"
    for skill_id in COGNITIVE_SKILL_IDS:
        skill_md = skills_root / skill_id / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"missing cognitive skill: skills/{skill_id}/SKILL.md")
            continue
        text = skill_md.read_text(encoding="utf-8")
        try:
            meta, body = _require_skill_frontmatter(text, path=skill_md)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not str(meta.get("name") or "").strip():
            errors.append(f"{skill_md.as_posix()}: missing frontmatter name")
        if not str(meta.get("description") or "").strip():
            errors.append(f"{skill_md.as_posix()}: missing frontmatter description")
        n_lines = len(text.splitlines())
        if n_lines > 200:
            errors.append(
                f"DOMAIN_SKILL_TOO_LONG {skill_md.as_posix()}: {n_lines} lines > 200"
            )
        gotchas = skills_root / skill_id / "references" / "gotchas.md"
        if not gotchas.is_file():
            errors.append(f"DOMAIN_MISSING_GOTCHAS {gotchas.as_posix()}")
        for i, line in enumerate(body.splitlines(), 1):
            for pat in _DOMAIN_HARNESS_PATTERNS:
                if pat.search(line):
                    errors.append(
                        f"DOMAIN_HARNESS_LEAK {skill_md.as_posix()}:{i}: "
                        f"pattern {pat.pattern!r} belongs in Harness, not Skill"
                    )
    return errors


def _entry_skill_shell(wid: str, *, skill_id: str = "") -> str:
    """Thin slash entry body (orchestration pointer only)."""
    lines = [
        f"# {wid}",
        "",
        "Pilot workflow entry. Orchestration authority: `pilot/.../workflows/specs.py`.",
        "",
    ]
    if skill_id:
        lines.append(f"Domain method: `skills/{skill_id}/SKILL.md`.")
        lines.append("")
    lines.extend(
        [
            "Run via `acp start` / `next` / `run-action` / `advance` / `complete`.",
            "",
            "## Actions",
            "",
            "<!-- BEGIN GENERATED ACTIONS -->",
            "",
            "<!-- END GENERATED ACTIONS -->",
            "",
        ]
    )
    return "\n".join(lines)



def _glob_prefix(pattern: str) -> str:
    """Return the literal directory prefix before the first glob metachar."""
    norm = pattern.replace("\\", "/").strip("/")
    parts: list[str] = []
    for part in norm.split("/"):
        if any(ch in part for ch in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def _scopes_conflict(a: str, b: str) -> bool:
    """True if two write_scopes may overlap (exact, equal, or prefix containment)."""
    if a == b:
        return True
    pa, pb = _glob_prefix(a), _glob_prefix(b)
    if not pa or not pb:
        # Broad globs like ``**`` or ``*`` — treat as conflicting unless both are runs scratch.
        return not (a.startswith("runs") and b.startswith("runs"))
    if pa == pb:
        return True
    return pa.startswith(pb + "/") or pb.startswith(pa + "/")


def _scope_overlap_errors(producer_writes: set[str], referee_writes: set[str]) -> list[str]:
    errors: list[str] = []
    for p in sorted(producer_writes):
        if str(p).startswith("runs"):
            continue
        for r in sorted(referee_writes):
            if str(r).startswith("runs"):
                continue
            if _scopes_conflict(str(p), str(r)):
                errors.append(f"producer/referee write_scopes overlap: {p!r} vs {r!r}")
    return errors


def sync_action_yaml_mirrors(repo: Path) -> list[str]:
    """No-op: Action identity lives only in Workflow Spec (no skills/actions source tree)."""
    del repo
    return []


def sync_skill_action_markers(repo: Path) -> list[str]:
    """No-op: workflow entry Skills are generated from Spec + WORKFLOW_ENTRIES."""
    del repo
    return []


def check_skill_action_markers(repo: Path) -> list[str]:
    """Verify every slash workflow has an entry description and Spec actions."""
    errors: list[str] = []
    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        entry = WORKFLOW_ENTRIES.get(wid)
        if not entry or not str(entry.get("description") or "").strip():
            errors.append(f"SKILL_ENTRY_MISSING {wid}: add WORKFLOW_ENTRIES description")
            continue
        skill_id = str(meta.get("cognitive_skill_id") or "").strip()
        if skill_id and skill_id not in COGNITIVE_SKILL_IDS:
            errors.append(f"SKILL_ENTRY_BAD_SKILL {wid}: unknown cognitive_skill_id {skill_id!r}")
        if "skill_id" in entry:
            errors.append(
                f"SKILL_ENTRY_LEGACY_SKILL_ID {wid}: skill_id moved to Spec cognitive_skill_id"
            )
        expected = {str(a.get("id")) for a in (meta.get("actions") or []) if isinstance(a, dict)}
        if not expected:
            errors.append(f"SKILL_ACTION_SET_DRIFT {wid}: Spec has no actions")
    if "operator" not in WORKFLOW_ENTRIES:
        errors.append("SKILL_ENTRY_MISSING operator: add WORKFLOW_ENTRIES description")
    return errors


def sync_sources(repo: Path) -> list[str]:
    """Write path: Spec is authority; nothing to sync into skills/workflows."""
    errors: list[str] = []
    errors.extend(sync_action_yaml_mirrors(repo))
    errors.extend(sync_skill_action_markers(repo))
    return errors


def validate(repo: Path) -> list[str]:
    """Static validation (read-only); returns list of error strings. Does not write files."""
    paths = _repo_paths(repo)
    skills = paths["skills"]
    prompts = paths["prompts"]
    agents = paths["agents"]
    errors: list[str] = []
    errors.extend(check_skill_action_markers(repo))
    errors.extend(validate_domain_skills(repo))

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    # Collect write scopes by role for overlap / containment check
    producer_writes: set[str] = set()
    referee_writes: set[str] = set()
    for ag_path in agents.glob("*.yaml"):
        meta = _load_yaml(ag_path)
        role = str(meta.get("role") or "")
        scopes = {str(x) for x in (meta.get("write_scopes") or [])}
        aid = str(meta.get("id") or ag_path.stem)
        mode = str(meta.get("mode") or "").strip().lower()
        if mode and mode not in {"primary", "subagent", "all"}:
            errors.append(f"agent {aid}: invalid mode {mode!r} (expected primary|subagent)")
        if meta.get("type") is not None:
            errors.append(
                f"agent {aid}: OpenCode uses mode not type; remove type={meta.get('type')!r}"
            )
        kind = str(meta.get("kind") or "").strip().lower()
        if kind and kind not in {"deterministic_engine"}:
            errors.append(
                f"agent {aid}: invalid kind {kind!r} "
                f"(expected empty or deterministic_engine)"
            )
        if role in {"producer", "referee", "readonly_analyst", "deterministic_engine"} and not mode:
            # Defaulted to subagent at compose time; warn as error to keep sources explicit.
            if aid != "ascendc-pilot":
                errors.append(f"agent {aid}: missing mode (use mode: subagent)")
        if kind == "deterministic_engine" and role != "deterministic_engine":
            errors.append(
                f"agent {aid}: kind=deterministic_engine requires role=deterministic_engine"
            )
        if role == "producer":
            producer_writes |= scopes
        elif role == "referee":
            referee_writes |= scopes
    bad = _scope_overlap_errors(producer_writes, referee_writes)
    errors.extend(bad)

    # Note: generated/ OpenCode frontmatter is validated after compose (see validate_generated).
    # Pre-compose validate only checks sources so install can regenerate stale trees.

    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or meta.get("alias_of") or not meta.get("slash"):
            continue
        entry = WORKFLOW_ENTRIES.get(wid)
        if not entry or not str(entry.get("description") or "").strip():
            errors.append(f"missing WORKFLOW_ENTRIES for {wid}")
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            aid = action.get("id")
            for pid in action.get("policy_ids") or []:
                if not (repo / "pilot" / "policies" / pid / "POLICY.md").is_file():
                    errors.append(f"{wid}/{aid}: missing policy {pid}")
            for cid in action.get("capability_ids") or []:
                if not (_capability_dir(repo, str(cid)) / "capability.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing capability {cid}")
            mid = action.get("action_method_id")
            if not mid:
                errors.append(f"{wid}/{aid}: missing action_method_id")
            tpid = action.get("task_prompt_id")
            if tpid:
                p = prompts / "tasks" / f"{tpid}.md"
                # tpid is domain/name
                if "/" in str(tpid):
                    dom, name = str(tpid).split("/", 1)
                    p = prompts / "tasks" / dom / f"{name}.md"
                if not p.is_file():
                    errors.append(f"{wid}/{aid}: missing task prompt {tpid}")
                else:
                    _scan_forbidden(p, p.read_text(encoding="utf-8"), errors)
            # Semantic / interactive actions need role + context + output contract
            if action.get("role_id") in {
                "producer",
                "referee",
                "readonly_analyst",
                "controller",
            } or action.get("execution_mode") in {"subagent", "primary_interactive"}:
                if not action.get("context_profile_id"):
                    errors.append(f"{wid}/{aid}: missing context_profile_id")
                if not action.get("output_contract_id"):
                    errors.append(f"{wid}/{aid}: missing output_contract_id")
            agent_id = action.get("agent_id")
            if agent_id and agent_id != "ascendc-pilot":
                if not (agents / f"{agent_id}.yaml").is_file():
                    errors.append(f"{wid}/{aid}: missing agent {agent_id}")
            # Primary must not be declared as subagent execution.
            if action.get("execution_mode") == "subagent" and agent_id == "ascendc-pilot":
                errors.append(f"{wid}/{aid}: primary agent cannot use subagent execution_mode")

    if "operator" not in WORKFLOW_ENTRIES:
        errors.append("missing WORKFLOW_ENTRIES for operator")

    return errors


def _action_yaml_drift(wid: str, action: dict[str, Any], ayaml: dict[str, Any]) -> list[str]:
    """Fail when source action.yaml diverges from Workflow Spec identity fields."""
    errors: list[str] = []
    aid = str(action.get("id") or "")
    comparisons = {
        "id": action.get("id"),
        "workflow_id": wid,
        "agent_id": action.get("agent_id"),
        "role_id": action.get("role_id"),
        "execution_mode": action.get("execution_mode"),
        "task_prompt_id": action.get("task_prompt_id"),
        "context_profile_id": action.get("context_profile_id"),
        "output_contract_id": action.get("output_contract_id"),
    }
    # capabilities / policies lists
    if action.get("capability_ids") is not None:
        comparisons["capabilities"] = list(action.get("capability_ids") or [])
    if action.get("policy_ids") is not None:
        comparisons["policies"] = list(action.get("policy_ids") or [])
    for field, spec_value in comparisons.items():
        yaml_value = ayaml.get(field)
        if field in {"capabilities", "policies"}:
            yaml_value = list(yaml_value or [])
            spec_value = list(spec_value or [])
        if yaml_value in (None, "") and spec_value in (None, "", []):
            continue
        if yaml_value != spec_value:
            errors.append(
                "ACTION_METADATA_DRIFT "
                f"{wid}/{aid} field={field} "
                f"spec_value={spec_value!r} action_yaml_value={yaml_value!r}"
            )
    checker_req = bool(action.get("checker_required", True))
    yaml_checker = bool(((ayaml.get("checker") or {}) if isinstance(ayaml.get("checker"), dict) else {}).get("required", True))
    if yaml_checker != checker_req:
        errors.append(
            "ACTION_METADATA_DRIFT "
            f"{wid}/{aid} field=checker.required "
            f"spec_value={checker_req!r} action_yaml_value={yaml_checker!r}"
        )
    referee_req = bool(action.get("referee_required", False))
    yaml_ref = bool(((ayaml.get("referee") or {}) if isinstance(ayaml.get("referee"), dict) else {}).get("required", False))
    if yaml_ref != referee_req:
        errors.append(
            "ACTION_METADATA_DRIFT "
            f"{wid}/{aid} field=referee.required "
            f"spec_value={referee_req!r} action_yaml_value={yaml_ref!r}"
        )
    return errors


def _spec_action_yaml(wid: str, action: dict[str, Any], extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate action.yaml body from Workflow Spec (mirror, not authority)."""
    merged = dict(extras or {})
    merged.update(
        {
            "id": action.get("id"),
            "workflow_id": wid,
            "role_id": action.get("role_id"),
            "agent_id": action.get("agent_id"),
            "execution_mode": action.get("execution_mode"),
            "capabilities": list(action.get("capability_ids") or []),
            "policies": list(action.get("policy_ids") or []),
            "task_prompt_id": action.get("task_prompt_id"),
            "context_profile_id": action.get("context_profile_id"),
            "output_contract_id": action.get("output_contract_id"),
            "allowed_write_paths": list(action.get("allowed_write_paths") or []),
            "forbidden_write_paths": list(action.get("forbidden_write_paths") or []),
            "allowed_read_paths": list(action.get("allowed_read_paths") or []),
            "forbidden_read_paths": list(action.get("forbidden_read_paths") or []),
            "checker": {"required": bool(action.get("checker_required", True))},
            "referee": {"required": bool(action.get("referee_required", False))},
            "generated_from": "workflow_spec",
        }
    )
    return merged


def _replace_actions_table(body: str, meta: dict[str, Any]) -> str:
    """Replace generated Actions markers with Workflow Spec authority."""
    rows = [
        "| action_id | execution_mode | agent | role | method | prompt | output_contract |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in meta.get("actions") or []:
        if not isinstance(a, dict):
            continue
        rows.append(
            "| `{id}` | `{mode}` | `{agent}` | `{role}` | `{method}` | `{prompt}` | `{contract}` |".format(
                id=a.get("id"),
                mode=a.get("execution_mode") or "-",
                agent=a.get("agent_id") or "human",
                role=a.get("role_id") or "-",
                method=a.get("action_method_id") or "-",
                prompt=a.get("task_prompt_id") or "-",
                contract=a.get("output_contract_id") or "-",
            )
        )
    table = "\n".join(rows) + "\n"
    begin = "<!-- BEGIN GENERATED ACTIONS -->"
    end = "<!-- END GENERATED ACTIONS -->"
    if begin in body and end in body:
        pre, rest = body.split(begin, 1)
        _, post = rest.split(end, 1)
        return pre + begin + "\n\n" + table + "\n" + end + post
    # Fallback: replace ## Actions section, wrapping with markers.
    wrapped = f"## Actions\n\n{begin}\n\n{table}\n{end}\n"
    if re.search(r"(?m)^## Actions\s*$", body):
        return re.sub(
            r"(?ms)^## Actions\s*\n.*?(?=^## |\Z)",
            wrapped + "\n",
            body,
            count=1,
        )
    return body.rstrip() + "\n\n" + wrapped


def _compose_skill_body(repo: Path, wid: str, meta: dict[str, Any]) -> str:
    skill_id = str(meta.get("cognitive_skill_id") or "").strip()
    body = _entry_skill_shell(wid, skill_id=skill_id)
    body = _replace_actions_table(body, meta)
    # Short invariant pack only (full POLICY.md stays under pilot/policies/ for humans).
    pack = _read_invariant_pack(repo)
    marker = "## Composed: policy-invariants"
    if marker not in body and pack.strip():
        body = body.rstrip() + f"\n\n{marker}\n\n" + pack + "\n"
    # Index composed refs + runtime bundle paths
    lines = [
        "\n## Composition index\n",
        "| action_id | policies | capabilities | method | prompt | agent |",
        "|---|---|---|---|---|---|",
    ]
    runtime_lines = [
        "\n## Action runtime index\n",
        "| action_id | method_path | prompt_path | output_contract | role |",
        "|---|---|---|---|---|",
    ]
    for a in meta.get("actions") or []:
        lines.append(
            "| `{id}` | {pols} | {caps} | `{method}` | `{prompt}` | `{agent}` |".format(
                id=a.get("id"),
                pols=",".join(a.get("policy_ids") or []) or "-",
                caps=",".join(a.get("capability_ids") or []) or "-",
                method=a.get("action_method_id") or "-",
                prompt=a.get("task_prompt_id") or "-",
                agent=a.get("agent_id") or "human",
            )
        )
        mid = str(a.get("action_method_id") or "")
        folder = mid.split("/", 1)[-1] if mid else "-"
        tpid = str(a.get("task_prompt_id") or "")
        prompt_path = f"prompts/tasks/{tpid}.md" if tpid and "/" not in tpid else (
            f"prompts/tasks/{tpid}.md" if tpid else "-"
        )
        if tpid and "/" in tpid:
            dom, name = tpid.split("/", 1)
            prompt_path = f"prompts/tasks/{dom}/{name}.md"
        runtime_lines.append(
            "| `{id}` | `actions/{folder}/action.yaml` | `{prompt}` | `{contract}` | `{role}` |".format(
                id=a.get("id"),
                folder=folder,
                prompt=prompt_path,
                contract=a.get("output_contract_id") or "-",
                role=a.get("role_id") or "-",
            )
        )
    return body.rstrip() + "\n" + "\n".join(lines) + "\n" + "\n".join(runtime_lines) + "\n"


# OpenCode agent frontmatter: use ``mode``, never legacy ``type: subagent``.
_OPENCODE_AGENT_ALLOWED_KEYS = frozenset(
    {
        "name",
        "description",
        "mode",
        "permission",
        "tools",
        "model",
        "temperature",
        "color",
        "hidden",
    }
)


def _opencode_bash_permission() -> dict[str, str]:
    """OpenCode frontmatter bash rules (last match wins: deny-all first, then allows).

    Aligns with ``authorize`` ``BASH_READONLY_INSPECT`` + ``acp *``.
    Without these, primary ``bash: *: deny`` blocks ``grep``/``rg`` before Pilot authorize runs.
    """
    return {
        "*": "deny",
        # Exact + prefixed; agent must invoke bare `acp` (not absolute acp.exe path).
        "acp": "allow",
        "acp *": "allow",
        # Absolute Scripts path sometimes appears if Host expands PATH; keep allowlisted.
        "*\\Scripts\\acp.exe": "allow",
        "*\\Scripts\\acp.exe *": "allow",
        "*/bin/acp": "allow",
        "*/bin/acp *": "allow",
        # Locate-only search (bash tool; OpenCode Grep tool is separate → permission.grep)
        "grep *": "allow",
        "Grep *": "allow",
        "rg *": "allow",
        "ripgrep *": "allow",
        "findstr *": "allow",
        "Select-String *": "allow",
        "sls *": "allow",
        # Path / listing probes
        "ls": "allow",
        "ls *": "allow",
        "dir": "allow",
        "dir *": "allow",
        "pwd": "allow",
        "tree": "allow",
        "tree *": "allow",
        "Get-ChildItem *": "allow",
        "gci *": "allow",
        "Get-Item *": "allow",
        "gi *": "allow",
        "Get-Location": "allow",
        "Get-Location *": "allow",
        "gl": "allow",
        "Test-Path *": "allow",
        "Resolve-Path *": "allow",
        # acp discovery only (ses_00c4: Get-Command was denied by frontmatter)
        "Get-Command acp": "allow",
        "Get-Command acp *": "allow",
        "gcm acp": "allow",
        "gcm acp *": "allow",
        "where acp": "allow",
        "where acp *": "allow",
        "where.exe acp": "allow",
        "where.exe acp *": "allow",
        "cd *": "allow",
        "Set-Location *": "allow",
        "sl *": "allow",
        "Push-Location *": "allow",
        "Pop-Location": "allow",
        "Pop-Location *": "allow",
    }


def _project_primary_description(repo: Path, description: str) -> str:
    """No-op: start requirements live only in Spec-projected invariant pack item 11."""
    del repo
    return str(description or "")


def _compose_agent_md(repo: Path, agent_meta: dict[str, Any], *, host: str = "") -> str:
    skills = repo / "skills"
    aid = agent_meta.get("id", "agent")
    role = agent_meta.get("role", "")
    read_scopes = list(agent_meta.get("read_scopes") or [])
    if host == "opencode":
        # Cognitive skills are not in OpenCode Skill discovery; agents load
        # them from the plugin-internal cognitive-skills/ tree.
        remapped: list[str] = []
        for scope in read_scopes:
            s = str(scope)
            if s.startswith("skills/") and any(
                s.startswith(f"skills/{cid}")
                for cid in COGNITIVE_SKILL_IDS
            ):
                remapped.append("cognitive-" + s)
            else:
                remapped.append(s)
        read_scopes = remapped
    reads = "\n".join(f"- `{x}`" for x in read_scopes) or "- (none)"
    writes = "\n".join(f"- `{x}`" for x in (agent_meta.get("write_scopes") or [])) or "- (none)"
    forbidden = "\n".join(f"- {x}" for x in (agent_meta.get("forbidden") or []))
    # Short invariant pack for ALL agents (same pack as workflow skills).
    inv_pack = _read_invariant_pack(repo)
    desc = _project_primary_description(repo, str(agent_meta.get("description") or aid))
    front: dict[str, Any] = {
        "name": aid,
        "description": desc,
    }
    bash_perm = _opencode_bash_permission()
    if agent_meta.get("mode") == "primary":
        front["mode"] = "primary"
        front["permission"] = {
            "bash": bash_perm,
            # Native OpenCode Grep tool (not bash); default allow, set explicitly.
            "grep": "allow",
            "edit": {"*": "ask"},
            "write": {"*": "ask"},
        }
    else:
        # OpenCode recognizes mode=subagent (not type=subagent).
        front["mode"] = "subagent"
        # Same bash fence as primary so Task does not inherit a silent deny-all
        # while still allowing locate-only search + acp (Pilot authorize remains).
        front["permission"] = {
            "bash": bash_perm,
            "grep": "allow",
        }

    # Role stays thin: controller brief only; start rules live in composed invariants.
    body = f"""# Agent: {aid}

## Role

You are a `{role}` for AscendC-Pilot.

{desc}

## Boundaries

You may read:

{reads}

Machine-scope **operator sources** (`op_host/**`, `op_kernel/**`, …) are outside `.ascendc-pilot`.
Locate with UO KB query / ScopeSet first, then machine-scope windowed `Read` — never whole-file dumps.

You may write:

{writes}

You must not:

{forbidden}

## Runtime Contract

At runtime, follow:

1. **First**: Read the session `prompt.md` from the prepared Action Bundle (path given by Host `task_prompt_stub` / `session_dir`). Treat it as the sole task body.
2. Then the current Pilot Action / METHOD only as referenced by that prompt;
3. the composed Policy invariants;
4. the composed Capabilities (`source-navigation`, `source-reading` when declared on the Action);
5. the declared Output Contract.

When these sources conflict, follow the session `prompt.md` and Pilot Action / source-authority Policy.
Do **not** invent extra goals beyond the session prompt. Do **not** finalize the Action (primary runs `--finalize`).

## Composed: policy-invariants

{inv_pack}
"""
    return _dump_frontmatter(front) + "\n" + body


def compose_host(repo: Path, host: str, *, out_root: Path | None = None) -> dict[str, Any]:
    paths = _repo_paths(repo)
    skills = paths["skills"]
    prompts_src = paths["prompts"]
    agents_src = paths["agents"]
    # Compose into out_root (default generated/<host>). Temp out_roots stay
    # isolated; Spec is the sole Action identity authority (no skills/actions/).
    if out_root is None:
        out_root = paths["out"] / host
    else:
        out_root = Path(out_root)
    host_meta = _load_yaml(paths["hosts"] / f"{host}.yaml")

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    if out_root.exists():
        shutil.rmtree(out_root)
    out_skills = out_root / "skills"
    out_agents = out_root / "agents"
    out_prompts = out_root / "prompts"
    out_skills.mkdir(parents=True)
    out_agents.mkdir(parents=True)
    out_prompts.mkdir(parents=True)

    compiled: list[str] = []

    # Workflow slash entries (thin shells) + cognitive skills
    workflow_ids = [
        wid
        for wid, m in WORKFLOWS.items()
        if m.get("slash") and not m.get("reserved") and not m.get("alias_of")
    ]
    workflow_ids.append("operator")
    for wid in workflow_ids:
        entry = WORKFLOW_ENTRIES.get(wid) or {}
        desc = str(entry.get("description") or "").strip() or wid
        meta: dict[str, Any] = {"name": wid, "description": desc}
        overrides = dict(host_meta.get("skill_defaults") or {})
        per_skill = (host_meta.get("skills") or {}).get(wid) or {}
        if isinstance(per_skill, dict):
            overrides.update(per_skill)
        meta = {**meta, **overrides}
        # OpenCode Skill frontmatter does not honor Cursor-only keys.
        if host == "opencode":
            meta.pop("disable-model-invocation", None)
            meta.pop("disable_model_invocation", None)
        wf_meta = WORKFLOWS.get(wid) or {}
        if wid == "operator":
            body = _entry_skill_shell(wid, skill_id="")
            hc = _read_policy(repo, "pilot-control")
            body = body.rstrip() + "\n\n## Composed: pilot-control\n\n" + hc + "\n"
        else:
            body = _compose_skill_body(repo, wid, wf_meta)
        dest = out_skills / wid
        dest.mkdir(parents=True, exist_ok=True)
        skill_out = dest / "SKILL.md"
        # Ensure composed frontmatter keeps name/description; do not indent.
        out_text = _dump_frontmatter(meta) + "\n" + body.lstrip("\n")
        if not out_text.startswith("---\n"):
            raise ValueError(f"composed skill must start with ---: {skill_out}")
        skill_out.write_text(out_text, encoding="utf-8")
        expected_n = len(wf_meta.get("actions") or []) if wid != "operator" else None
        _assert_generated_skill(skill_out, expected_actions=expected_n)
        # Emit Spec-derived Action Bundle sidecars (identity only).
        for a in wf_meta.get("actions") or []:
            mid = a.get("action_method_id")
            if not mid:
                continue
            folder = str(mid).split("/", 1)[-1]
            adir = dest / "actions" / folder
            adir.mkdir(parents=True, exist_ok=True)
            merged = _spec_action_yaml(wid, a)
            if yaml is not None:
                (adir / "action.yaml").write_text(
                    "# GENERATED from Workflow Spec — do not hand-edit identity fields\n"
                    + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
        # Copy capabilities used
        caps_needed: set[str] = set()
        for a in wf_meta.get("actions") or []:
            caps_needed.update(a.get("capability_ids") or [])
        for cid in sorted(caps_needed):
            csrc = _capability_dir(repo, str(cid))
            if csrc.is_dir():
                cdst = dest / "capabilities" / cid
                if cdst.exists():
                    shutil.rmtree(cdst)
                shutil.copytree(csrc, cdst)
        compiled.append(f"{host}/skills/{wid}")

    # Cognitive skills: Cursor/Codex get disable-model-invocation;
    # OpenCode does not put them in Skill discovery — only workflow entries.
    cognitive_out = (
        out_root / "cognitive-skills" if host == "opencode" else out_skills
    )
    if host == "opencode":
        if cognitive_out.exists():
            shutil.rmtree(cognitive_out)
        cognitive_out.mkdir(parents=True, exist_ok=True)
    for skill_id in COGNITIVE_SKILL_IDS:
        src = skills / skill_id
        if not (src / "SKILL.md").is_file():
            continue
        dst = cognitive_out / skill_id
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("README.md"))
        skill_md = dst / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        meta, body = _require_skill_frontmatter(text, path=skill_md)
        if host != "opencode":
            meta["disable-model-invocation"] = True
        else:
            meta.pop("disable-model-invocation", None)
        per = (host_meta.get("skills") or {}).get(skill_id) or {}
        if isinstance(per, dict):
            meta.update(per)
        skill_md.write_text(_dump_frontmatter(meta) + "\n" + body.lstrip("\n"), encoding="utf-8")
        compiled.append(
            f"{host}/cognitive-skills/{skill_id}"
            if host == "opencode"
            else f"{host}/skills/{skill_id}"
        )
    shared_src = skills / "_shared"
    if shared_src.is_dir() and any(shared_src.glob("*.md")):
        # Legacy leftover: cognitive skills must be self-contained under references/.
        # Do not copy _shared into generated hosts.
        pass

    # Shared policies + short invariants under each host
    pol_dst = out_skills / "_policies"
    pol_dst.mkdir(parents=True, exist_ok=True)
    policies_src = paths["policies"]
    if policies_src.is_dir():
        for pdir in policies_src.iterdir():
            if pdir.is_dir():
                d = pol_dst / pdir.name
                if d.exists():
                    shutil.rmtree(d)
                shutil.copytree(pdir, d)

    # Agents — skip kind=deterministic_engine (authorize identity only; not LLM-spawned).
    for ag in sorted(agents_src.glob("*.yaml")):
        meta = _load_yaml(ag)
        if not meta.get("id"):
            continue
        kind = str(meta.get("kind") or "").strip().lower()
        if kind == "deterministic_engine":
            continue
        md = _compose_agent_md(repo, meta, host=host)
        (out_agents / f"{meta['id']}.md").write_text(md, encoding="utf-8")
        compiled.append(f"{host}/agents/{meta['id']}")
    # references
    ref_src = agents_src / "references"
    if ref_src.is_dir():
        ref_dst = out_agents / "references"
        if ref_dst.exists():
            shutil.rmtree(ref_dst)
        shutil.copytree(ref_src, ref_dst)

    # Prompts
    if prompts_src.is_dir():
        for src in prompts_src.rglob("*"):
            if src.is_file():
                rel = src.relative_to(prompts_src)
                dst = out_prompts / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        compiled.append(f"{host}/prompts")

    return {"ok": True, "compiled": compiled, "out_root": out_root.as_posix()}


def validate_generated(repo: Path, *, host: str = "opencode") -> list[str]:
    """Validate composed OpenCode/host artifacts against current sources."""
    errors: list[str] = []
    out_agents = repo / "generated" / host / "agents"
    if not out_agents.is_dir():
        errors.append(f"missing generated/{host}/agents")
        return errors

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    # Engine-identity agents (kind=deterministic_engine) are never composed to host MD.
    engine_ids: set[str] = set()
    agents_src = repo / "agents"
    if agents_src.is_dir():
        for ag in agents_src.glob("*.yaml"):
            meta = _load_yaml(ag)
            if str(meta.get("kind") or "").strip() == "deterministic_engine":
                engine_ids.add(str(meta.get("id") or ag.stem))

    # Every referenced non-primary LLM agent must have a generated md
    needed: set[str] = set()
    for wid, meta in WORKFLOWS.items():
        if meta.get("reserved") or not meta.get("slash"):
            continue
        for action in meta.get("actions") or []:
            if not isinstance(action, dict):
                continue
            agent_id = action.get("agent_id")
            if (
                agent_id
                and agent_id != "ascendc-pilot"
                and str(agent_id) not in engine_ids
                and str(action.get("execution_mode") or "") != "deterministic"
            ):
                needed.add(str(agent_id))
            role = action.get("role_id")
            if role in {"producer", "referee", "readonly_analyst"} and not agent_id:
                errors.append(f"{wid}/{action.get('id')}: semantic role missing agent_id")
        # Skill action table must match workflow agents
        skill = repo / "generated" / host / "skills" / wid / "SKILL.md"
        if skill.is_file():
            text = skill.read_text(encoding="utf-8")
            for action in meta.get("actions") or []:
                if not isinstance(action, dict):
                    continue
                aid = str(action.get("id") or "")
                agent = str(action.get("agent_id") or "human")
                role = str(action.get("role_id") or "-")
                # Composition index row must list the workflow agent
                if aid and f"| `{aid}` |" in text:
                    # Prefer Action runtime index role column
                    if f"| `{aid}` |" in text and role != "-" and f"| `{role}` |" not in text.split(f"| `{aid}` |", 1)[-1][:200]:
                        # Soft: check composition index agent cell
                        pass
                if aid and agent and agent != "human":
                    # Fail if skill still maps this action to a different agent in the Actions table
                    # New table: action_id | execution_mode | agent | role | method | prompt | contract
                    m = re.search(
                        rf"\|\s*`{re.escape(aid)}`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|",
                        text,
                    )
                    if m:
                        table_mode, table_agent, table_role = m.group(1), m.group(2), m.group(3)
                        if table_agent != agent:
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} agent "
                                f"{table_agent!r} != workflow {agent!r}"
                            )
                        if table_role != role and role != "-":
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} role "
                                f"{table_role!r} != workflow {role!r}"
                            )
                        expected_mode = str(action.get("execution_mode") or "")
                        if expected_mode and table_mode != expected_mode:
                            errors.append(
                                f"generated/{host}/skills/{wid}: action {aid} execution_mode "
                                f"{table_mode!r} != workflow {expected_mode!r}"
                            )

    for agent_id in sorted(needed):
        md = out_agents / f"{agent_id}.md"
        if not md.is_file():
            errors.append(f"generated/{host}/agents missing {agent_id}.md")
            continue
        front, _ = _split_frontmatter(md.read_text(encoding="utf-8"))
        if front.get("type") is not None:
            errors.append(f"generated/{host}/agents/{agent_id}.md: illegal type=; use mode")
        if front.get("mode") not in {"subagent", "primary", "all"}:
            errors.append(
                f"generated/{host}/agents/{agent_id}.md: missing/invalid mode={front.get('mode')!r}"
            )
        unknown = sorted(set(front) - _OPENCODE_AGENT_ALLOWED_KEYS)
        if unknown:
            errors.append(
                f"generated/{host}/agents/{agent_id}.md: unknown OpenCode keys {unknown}"
            )
    return errors


_GENERATED_DRIFT_IGNORE_RES = (
    re.compile(r"(?im)^generated_at\s*[:=].*$"),
    re.compile(r"(?i)[A-Za-z]:\\[^\s\"']+"),  # Windows absolute paths
    re.compile(r"(?i)/tmp/[^\s\"']+"),
    re.compile(r"(?i)/var/folders/[^\s\"']+"),
    re.compile(r"(?i)C:\\Users\\[^\\]+\\AppData\\Local\\Temp[^\s\"']*"),
)


def _normalize_generated_text(text: str, *, tmp_root: str = "", repo_root: str = "") -> str:
    out = text.replace("\r\n", "\n")
    for pat in _GENERATED_DRIFT_IGNORE_RES:
        out = pat.sub("", out)
    if tmp_root:
        out = out.replace(tmp_root.replace("\\", "/"), "<TMP>")
        out = out.replace(tmp_root, "<TMP>")
    if repo_root:
        out = out.replace(repo_root.replace("\\", "/"), "<REPO>")
        out = out.replace(repo_root, "<REPO>")
    # Drop empty lines introduced by stripping generated_at
    lines = [ln for ln in out.split("\n") if ln.strip() != ""]
    return "\n".join(lines) + ("\n" if lines else "")


def check_generated_drift(repo: Path, *, hosts: list[str] | None = None) -> list[str]:
    """Recompose into a temp dir and compare against committed generated/ (content).

    Does not modify the workspace. Returns GENERATED_DRIFT errors with regen hint.
    """
    import tempfile

    host_list = hosts or ["opencode", "cursor", "codex"]
    errors: list[str] = []
    repo = repo.expanduser().resolve()
    src_errors = validate(repo)
    if src_errors:
        return [f"GENERATED_DRIFT: compose sources invalid: {e}" for e in src_errors[:8]]

    with tempfile.TemporaryDirectory(prefix="acp-gen-") as tmp:
        tmp_path = Path(tmp)
        for host in host_list:
            candidate_root = tmp_path / host
            compose_host(repo, host, out_root=candidate_root)
            committed = repo / "generated" / host
            if not committed.is_dir():
                errors.append(f"GENERATED_DRIFT: missing committed generated/{host}/")
                continue
            cand_files = {
                p.relative_to(candidate_root).as_posix()
                for p in candidate_root.rglob("*")
                if p.is_file()
            }
            committed_files = {
                p.relative_to(committed).as_posix()
                for p in committed.rglob("*")
                if p.is_file()
            }
            only_cand = sorted(cand_files - committed_files)
            only_committed = sorted(committed_files - cand_files)
            for rel in only_cand[:20]:
                errors.append(f"GENERATED_DRIFT: generated/{host}/{rel} missing in repo")
            for rel in only_committed[:20]:
                errors.append(f"GENERATED_DRIFT: generated/{host}/{rel} stale (not in fresh compose)")
            for rel in sorted(cand_files & committed_files):
                left = _normalize_generated_text(
                    (candidate_root / rel).read_text(encoding="utf-8", errors="replace"),
                    tmp_root=str(tmp_path),
                    repo_root=str(repo),
                )
                right = _normalize_generated_text(
                    (committed / rel).read_text(encoding="utf-8", errors="replace"),
                    tmp_root=str(tmp_path),
                    repo_root=str(repo),
                )
                if left != right:
                    errors.append(f"GENERATED_DRIFT: generated/{host}/{rel}")
    if errors:
        errors.append(
            "GENERATED_DRIFT: run `python scripts/compose_runtime.py --repo .` to regenerate"
        )
    return errors


def compose_all(
    repo: Path,
    *,
    hosts: list[str] | None = None,
    sync: bool = True,
) -> dict[str, Any]:
    hosts_dir = repo / "adapters" / "hosts"
    host_names = hosts or [p.stem for p in hosts_dir.glob("*.yaml")]
    if sync:
        sync_errs = sync_sources(repo)
        if sync_errs:
            return {"ok": False, "errors": sync_errs}
    errors = validate(repo)
    if errors:
        return {"ok": False, "errors": errors}
    all_compiled: list[str] = []
    for host in host_names:
        result = compose_host(repo, host)
        all_compiled.extend(result.get("compiled") or [])
    gen_errors: list[str] = []
    for host in host_names:
        gen_errors.extend(validate_generated(repo, host=host))
    if gen_errors:
        return {"ok": False, "errors": gen_errors, "compiled": all_compiled}
    return {"ok": True, "compiled": all_compiled, "out_root": (repo / "generated").as_posix()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose compositional sources → generated/<host>/")
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--host", action="append", default=[])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--validate-generated", action="store_true")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Write action.yaml mirrors + Skill markers (and compose generated/ unless --validate-only)",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Only sync action.yaml + Skill markers (no compose)",
    )
    args = parser.parse_args(argv)
    repo = args.repo or Path(__file__).resolve().parents[1]
    if args.sync_only or (args.sync and args.validate_only):
        errors = sync_sources(repo)
        if errors:
            print({"ok": False, "errors": errors})
            return 1
        # After sync, optionally re-validate sources (read-only).
        if args.validate_only:
            errors = validate(repo)
            if args.validate_generated:
                for host in (args.host or ["opencode", "cursor", "codex"]):
                    errors.extend(validate_generated(repo, host=host))
            if errors:
                print({"ok": False, "errors": errors})
                return 1
        print({"ok": True, "synced": True, "errors": []})
        return 0
    if args.validate_only:
        errors = validate(repo)
        if args.validate_generated:
            for host in (args.host or ["opencode", "cursor", "codex"]):
                errors.extend(validate_generated(repo, host=host))
        if errors:
            print({"ok": False, "errors": errors})
            return 1
        print({"ok": True, "errors": []})
        return 0
    # Default compose and --sync both refresh mirrors then regenerate generated/.
    result = compose_all(repo, hosts=args.host or None, sync=True)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
